# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from support import make_app

from identity import auth_namespace
from local_store import Store
from sync import Sync


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, auth_namespace())
        self.app = app = make_app()
        app.store = self.store
        app.args = argparse.Namespace(demo=False, offline=True, owner=None, limit=100)
        app.state.repo, app.state.tab, app.state.project = ("me/repo", 1, None)
        app.state.query, app.state.selected, app.state.busy = ("", 0, False)
        app.state.rows = [
            dict(
                number=7,
                title="Task",
                state="OPEN",
                labels=[{"name": "bug"}],
                assignees=[{"login": "alice"}],
            )
        ]
        app.gh = Mock()
        self.target = app.actions.comment_target(app.state.rows[0])
        self.project = dict(id="P", number=3, title="First", owner={"login": "me"})
        self.field = dict(id="F", name="Due date", dataType="DATE")
        self.item = dict(id="ITEM", **{"due date": "2026-12-01"})
        self.meta = dict(id="ISSUE", labels=[{"name": "bug"}], assignees=[{"login": "alice"}])
        self.store.put(app.metadata.metadata_key(self.target), self.meta)

    def tearDown(self):
        self.tmp.cleanup()

    def action_from_menu(self, prefix):
        app = self.app
        index = next((i for i, e in enumerate(app.state.modal[2]) if e[0].startswith(prefix)))
        app.state.modal_index = index
        with patch.object(app.actions, "review") as review:
            app.actions.choose()
        return review.call_args.args[0]

    def test_issue_and_card_menus_expose_all_requested_actions(self):
        app = self.app
        app.actions.show_menu()
        labels = [e[0] for e in app.state.modal[2] if isinstance(e, tuple)]
        for label in ("Assignees…", "Labels…", "Projects…", "Due date in Project…"):
            self.assertIn(label, labels)
        app.state.tab, app.state.project = (4, self.project)
        app.state.rows = [
            dict(id="ITEM", status="Todo", content={"url": "https://github.com/me/repo/issues/7"})
        ]
        app.store.put("fields:P", {"fields": []})
        app.actions.show_menu()
        labels = [e[0] for e in app.state.modal[2] if isinstance(e, tuple)]
        for label in ("Assignees…", "Labels…", "Projects…", "Due date…"):
            self.assertIn(label, labels)

    def test_add_label_uses_delta_and_preserves_other_remote_labels(self):
        app = self.app
        app.issue_actions.people_labels_menu(self.target, "labels", self.meta, ["bug", "urgent"])
        action = self.action_from_menu("[ ] urgent")
        self.assertEqual(action.args[-2:], ["--add-label", "urgent"])
        self.assertFalse(action.operation.base)
        self.store.enqueue(action.label, app.actions.write_payload(action))
        app.gh.run.side_effect = [
            {"labels": [{"name": "bug"}, {"name": "added-remotely"}]},
            "Updated",
        ]
        Sync(self.store, app.gh).run()
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(
            app.gh.run.call_args.args[0],
            ["issue", "edit", "7", "--repo", "me/repo", "--add-label", "urgent"],
        )
        cached, _ = self.store.get(app.metadata.metadata_key(self.target))
        self.assertEqual({v["name"] for v in cached["labels"]}, {"bug", "urgent", "added-remotely"})
        self.assertNotIn("--body", action.args)

    def test_remove_assignee_only_removes_selected_login(self):
        app = self.app
        app.issue_actions.people_labels_menu(self.target, "assignees", self.meta, ["alice"])
        action = self.action_from_menu("[x] alice")
        self.assertEqual(action.args[-2:], ["--remove-assignee", "alice"])
        self.assertTrue(action.operation.base)
        self.store.enqueue(action.label, app.actions.write_payload(action))
        app.gh.run.side_effect = [{"assignees": [{"login": "alice"}, {"login": "bob"}]}, "Updated"]
        Sync(self.store, app.gh).run()
        self.assertEqual(app.gh.run.call_args.args[0][-2:], ["--remove-assignee", "alice"])
        self.assertEqual(self.store.jobs(), [])

    def test_date_set_and_clear_have_baselines_and_validate_calendar(self):
        app = self.app
        for value, expected in [("2026-12-25", ["--date", "2026-12-25"]), ("", ["--clear"])]:
            with (
                patch.object(app.input, "prompt", return_value=value),
                patch.object(app.actions, "review") as review,
            ):
                app.issue_actions.due_date_menu(self.project, self.item, [self.field])
            action = review.call_args.args[0]
            self.assertEqual(action.args[-len(expected) :], expected)
            self.assertEqual(action.operation.base, "2026-12-01")
            self.assertEqual(action.operation.desired, value)
        with (
            patch.object(app.input, "prompt", return_value="2026-02-30"),
            patch.object(app.actions, "review") as review,
        ):
            app.issue_actions.due_date_menu(self.project, self.item, [self.field])
            review.assert_not_called()
        self.assertEqual(app.state.modal[:2], ("text", "Invalid date"))

    def date_payload(self):
        return dict(
            kind="date",
            args=[
                "project",
                "item-edit",
                "--id",
                "ITEM",
                "--project-id",
                "P",
                "--field-id",
                "F",
                "--date",
                "2026-12-25",
            ],
            project=self.project,
            identity="ITEM",
            field_id="F",
            field_name="Due date",
            base="2026-12-01",
            desired="2026-12-25",
            target="P:ITEM:F",
        )

    def date_response(self, value):
        return [
            {"data": {"node": {"fieldValues": {"nodes": [{"date": value, "field": {"id": "F"}}]}}}}
        ]

    def test_remote_date_conflict_retains_both_values_and_sends_no_write(self):
        self.store.enqueue("Set date", self.date_payload())
        self.app.gh.run.return_value = self.date_response("2026-12-10")
        Sync(self.store, self.app.gh).run()
        job = self.store.jobs()[0]
        self.assertEqual(job["status"], "conflict")
        self.assertIn("2026-12-10", job["note"])
        self.assertEqual(job["payload"]["desired"], "2026-12-25")
        self.assertEqual(self.app.gh.run.call_count, 1)

    def test_date_success_updates_local_value_and_does_not_replay(self):
        self.store.enqueue("Set date", self.date_payload())
        self.app.gh.run.side_effect = [self.date_response("2026-12-01"), "Updated"]
        sync = Sync(self.store, self.app.gh)
        sync.run()
        sync.run()
        self.assertEqual(self.app.gh.run.call_count, 2)
        self.assertEqual(self.store.get("item-date:P:ITEM:F")[0], "2026-12-25")

    def test_local_overlay_shows_labels_assignees_and_date_without_mutating_snapshot(self):
        for field, value in [("labels", "urgent"), ("assignees", "bob")]:
            self.store.enqueue(
                "Add " + value,
                dict(
                    kind="membership",
                    args=["issue", "edit", "7"],
                    repo="me/repo",
                    tab=1,
                    identity=7,
                    field=field,
                    value=value,
                    base=False,
                    desired=True,
                    target=field + value,
                ),
            )
        self.store.enqueue("Date", self.date_payload())
        rows = [
            dict(
                id="ITEM",
                labels=["bug"],
                assignees=["alice"],
                content={"url": "https://github.com/me/repo/issues/7"},
                **{"due date": "2026-12-01"},
            )
        ]
        key = json.dumps(dict(tab=4, project="P", repo=None, state="open"))
        result = self.store.overlay(key, rows)[0]
        self.assertEqual({v["name"] for v in result["labels"]}, {"bug", "urgent"})
        self.assertEqual({v["login"] for v in result["assignees"]}, {"alice", "bob"})
        self.assertEqual(result["due date"], "2026-12-25")
        self.assertEqual(rows[0]["labels"], ["bug"])
        self.assertEqual(rows[0]["due date"], "2026-12-01")

    def test_add_second_project_does_not_remove_first_and_can_remove_membership(self):
        app = self.app
        second = dict(id="P2", number=4, title="Second", owner={"login": "me"})
        memberships = [dict(id="PI", project=self.project)]
        app.issue_actions.projects_menu(self.target, memberships, [self.project, second])
        action = self.action_from_menu("[ ] Second")
        self.assertEqual(action.operation.kind, "add")
        self.assertEqual(action.operation.project["id"], "P2")
        self.assertEqual(
            action.args,
            [
                "project",
                "item-add",
                "4",
                "--owner",
                "me",
                "--url",
                "https://github.com/me/repo/issues/7",
            ],
        )
        app.issue_actions.projects_menu(self.target, memberships, [self.project, second])
        action = self.action_from_menu("[x] First")
        self.assertEqual(action.operation.kind, "project_remove")
        self.assertEqual(
            action.args, ["project", "item-delete", "3", "--owner", "me", "--id", "PI"]
        )

    def test_project_removal_preflight_and_cache_invalidation(self):
        app = self.app
        app.issue_actions.projects_menu(self.target, [dict(id="PI", project=self.project)], [])
        action = self.action_from_menu("[x] First")
        self.store.enqueue(action.label, app.actions.write_payload(action))
        key = "memberships:" + app.metadata.metadata_key(self.target)
        self.store.put(key, [dict(id="PI", project=self.project)])
        app.gh.run.side_effect = [
            [
                {
                    "data": {
                        "node": {
                            "items": {
                                "nodes": [
                                    {"content": {"url": "https://github.com/me/repo/issues/7"}}
                                ]
                            }
                        }
                    }
                }
            ],
            "Removed",
        ]
        Sync(self.store, app.gh).run()
        self.assertEqual(app.gh.run.call_args.args[0][1], "item-delete")
        self.assertEqual(self.store.get(key)[1], 0)
        key = json.dumps(dict(tab=4, project="P", repo=None, state="open"))
        self.assertEqual(
            self.store.overlay(key, [dict(content={"url": "https://github.com/me/repo/issues/7"})]),
            [],
        )

    def test_ambiguous_membership_write_is_verified_without_replay(self):
        app = self.app
        p = dict(
            kind="membership",
            args=["issue", "edit", "7", "--repo", "me/repo", "--add-label", "urgent"],
            repo="me/repo",
            tab=1,
            identity=7,
            field="labels",
            value="urgent",
            base=False,
            desired=True,
            target="label:urgent",
        )
        identifier = self.store.enqueue("Label", p)
        self.store.update(identifier, "uncertain", "timeout")
        app.gh.run.return_value = {"labels": [{"name": "urgent"}]}
        Sync(self.store, app.gh).run()
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(app.gh.run.call_count, 1)
        self.assertEqual(app.gh.run.call_args.args[0][1], "view")

    def test_date_fields_and_issue_metadata_work_offline_after_caching(self):
        self.store.put("date-fields:P", [self.field])
        self.assertEqual(self.app.metadata.date_fields(self.project), [self.field])
        self.assertEqual(self.app.metadata.issue_metadata(self.target)["id"], "ISSUE")
        self.app.gh.run.assert_not_called()

    def test_real_offline_terminal_metadata_menus_queue_all_four_actions(self):
        import errno
        import fcntl
        import os
        import pty
        import select
        import struct
        import subprocess
        import termios
        import time

        app = self.app
        second = dict(id="P2", number=4, title="Second", owner={"login": "me"})
        row = dict(
            id="ITEM",
            title="Terminal metadata task",
            status="Todo",
            labels=["bug"],
            assignees=["alice"],
            content={"url": "https://github.com/me/repo/issues/7"},
            **{"due date": "2026-12-01"},
        )
        app.state.tab, app.state.project, app.state.repo, app.state.rows = (
            4,
            self.project,
            None,
            [row],
        )
        app.args.offline = True
        self.store.put("date-fields:P", [self.field])
        self.store.put("project-catalog:@me", [self.project, second])
        self.store.put(
            "memberships:" + app.metadata.metadata_key(self.target),
            [dict(id="ITEM", project=self.project)],
        )

        def key(project=None):
            return json.dumps(
                dict(tab=4, owner=None, repo=None, state="open", limit=100, project=project),
                sort_keys=True,
            )

        self.store.put(key(), [self.project])
        self.store.put(key("P"), [row])
        app.actions.show_menu()
        menu = app.state.modal[2]
        indices = {
            name: next((i for i, e in enumerate(menu) if isinstance(e, tuple) and e[0] == name))
            for name in ("Assignees…", "Labels…", "Due date…", "Projects…")
        }
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.Popen(
            [
                sys.executable,
                str(root / "gh_desk.py"),
                "--no-config",
                "--offline",
                "--data-dir",
                self.tmp.name,
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=dict(os.environ, TERM="xterm-256color"),
            start_new_session=True,
        )
        os.close(slave)
        transcript = bytearray()

        def pump(seconds=0.18):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.02)[0]:
                    try:
                        transcript.extend(os.read(master, 65536))
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise

        def send(data):
            os.write(master, data)
            pump()

        def expect(text):
            deadline = time.monotonic() + 4
            while text not in transcript and time.monotonic() < deadline:
                pump(0.1)
            self.assertIn(text, transcript)

        def open_action(name):
            send(b"a")
            send(b"j" * indices[name] + b"\n")

        try:
            expect(b"GH DESK")
            send(b"5")
            send(b"\n")
            expect(b"Terminal metadata task")
            open_action("Labels…")
            expect(b"Labels")
            send(b"j\n")
            send(b"j\n")
            open_action("Assignees…")
            send(b"\n")
            expect(b"GitHub login")
            send(b"bob\n")
            send(b"j\n")
            open_action("Due date…")
            expect(b"YYYY-MM-DD")
            send(b"\x152026-12-25\n")
            send(b"j\n")
            open_action("Projects…")
            expect(b"Second")
            send(b"j\n")
            send(b"j\n")
            send(b"q")
            proc.wait(timeout=2)
            self.assertEqual(proc.returncode, 0, transcript.decode(errors="replace"))
            self.assertNotIn(b"Traceback", transcript)
            jobs = self.store.jobs()
            self.assertEqual(len(jobs), 4)
            self.assertEqual(
                [j["payload"]["kind"] for j in jobs], ["membership", "membership", "date", "add"]
            )
            self.assertFalse(jobs[0]["payload"]["desired"])
            self.assertEqual(jobs[1]["payload"]["value"], "bob")
            self.assertEqual(jobs[2]["payload"]["desired"], "2026-12-25")
            self.assertEqual(jobs[3]["payload"]["project"]["id"], "P2")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)

    def test_pending_project_add_cannot_be_toggled_twice(self):
        app = self.app
        app.issue_actions.projects_menu(self.target, [], [self.project])
        action = self.action_from_menu("[ ] First")
        self.store.enqueue(action.label, app.actions.write_payload(action))
        app.issue_actions.projects_menu(self.target, [], [self.project])
        app.state.modal_index = 0
        app.actions.choose()
        self.assertEqual(app.state.modal[:2], ("text", "Project edit pending"))


if __name__ == "__main__":
    unittest.main()
