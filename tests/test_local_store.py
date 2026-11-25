# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from support import make_app

from demo import demo_rows
from github import GhError
from identity import auth_namespace
from local_store import Store
from models import Action
from sync import Sync
from text_utils import label_names


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, auth_namespace())
        self.gh = Mock()
        self.sync = Sync(self.store, self.gh)
        self.key = json.dumps(dict(tab=1, repo="me/repo", state="all", project=None))

    def tearDown(self):
        self.tmp.cleanup()

    def state_payload(self):
        return dict(
            kind="state",
            args=["issue", "close", "1", "--repo", "me/repo"],
            repo="me/repo",
            tab=1,
            identity=1,
            base="OPEN",
            desired="CLOSED",
            target="me/repo:1",
            row=dict(number=1, title="Keep this", body="remote body", state="OPEN"),
        )

    def test_project_label_variants_regression(self):
        app = make_app()
        app.state.tab = 4
        for labels in (
            ["bug", "personal"],
            [{"name": "bug"}],
            ["bug", {"name": "personal"}],
            None,
            "bug",
        ):
            row = dict(title="Task", content=None, labels=labels)
            self.assertIn("Task", app.navigation.row_text(row))
        self.assertEqual(label_names(["bug", {"name": "personal"}]), ["bug", "personal"])

    def test_snapshots_survive_restart_and_keep_history(self):
        self.store.put("view", [{"body": "original"}])
        self.store.put("view", [{"body": "remote changed"}])
        reopened = Store(self.tmp.name, self.store.namespace)
        self.assertEqual(reopened.get("view")[0], [{"body": "remote changed"}])
        with reopened.connection() as db:
            rows = db.execute(
                "SELECT value FROM history WHERE key=? ORDER BY updated", ("view",)
            ).fetchall()
        self.assertIn("original", rows[0]["value"])
        self.assertEqual(self.store.path.stat().st_mode & 511, 384)

    def test_queue_survives_restart_and_overlay_preserves_remote_body(self):
        self.store.put(self.key, [dict(number=1, title="Keep", body="remote text", state="OPEN")])
        identifier = self.store.enqueue("Close", self.state_payload())
        reopened = Store(self.tmp.name, self.store.namespace)
        self.assertEqual(reopened.jobs()[0]["id"], identifier)
        rows = reopened.overlay(self.key, self.store.get(self.key)[0])
        self.assertEqual(rows[0]["state"], "CLOSED")
        self.assertEqual(rows[0]["body"], "remote text")
        self.assertEqual(self.store.get(self.key)[0][0]["state"], "OPEN")
        self.assertEqual(reopened.overlay(self.key, [])[0]["number"], 1)

    def test_namespace_separation_and_account_switch_block(self):
        self.store.put("private", ["secret"])
        self.store.enqueue("Close", self.state_payload())
        other = Store(self.tmp.name, "other-account")
        self.assertEqual(other.get("private"), (None, 0))
        self.assertEqual(other.jobs(), [])
        with patch("sync.auth_namespace", return_value="other-account"):
            with self.assertRaisesRegex(RuntimeError, "account/config changed"):
                self.sync.run()
        self.gh.run.assert_not_called()

    def test_conflict_preserves_local_and_remote_without_write(self):
        payload = self.state_payload()
        payload.update(base="CLOSED", desired="OPEN")
        identifier = self.store.enqueue("Reopen", payload)
        self.gh.run.return_value = {"state": "MERGED"}
        self.sync.run()
        job = self.store.jobs()[0]
        self.assertEqual(job["status"], "conflict")
        self.assertEqual(job["payload"]["desired"], "OPEN")
        self.assertEqual(
            self.store.get("remote-before-write:" + identifier)[0], {"value": "MERGED"}
        )
        self.assertEqual(self.gh.run.call_count, 1)
        self.assertEqual(self.gh.run.call_args.args[0][1], "view")

    def test_success_is_not_replayed(self):
        self.store.enqueue("Close", self.state_payload())
        self.gh.run.side_effect = [{"state": "OPEN"}, "Closed"]
        self.sync.run()
        self.sync.run()
        self.assertEqual(self.gh.run.call_count, 2)
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.jobs(active=False)[0]["status"], "done")

    def test_read_failure_can_retry_but_ambiguous_write_never_replays(self):
        self.store.enqueue("Close", self.state_payload())
        self.gh.run.side_effect = GhError("offline")
        self.sync.run()
        self.assertEqual(self.store.jobs()[0]["status"], "pending")
        self.gh.run.side_effect = [{"state": "OPEN"}, GhError("lost acknowledgement")]
        self.sync.run()
        self.assertEqual(self.store.jobs()[0]["status"], "uncertain")
        calls = self.gh.run.call_count
        self.gh.run.side_effect = [{"state": "OPEN"}]
        self.sync.run()
        self.assertEqual(self.gh.run.call_count, calls + 1)
        self.assertEqual(self.gh.run.call_args.args[0][1], "view")
        self.assertEqual(self.store.jobs()[0]["status"], "uncertain")

    def test_crash_after_claim_never_replays(self):
        identifier = self.store.enqueue("Close", self.state_payload())
        self.assertTrue(self.store.claim(identifier))
        self.assertFalse(self.store.claim(identifier))
        reopened = Store(self.tmp.name, self.store.namespace)
        self.gh.run.return_value = {"state": "OPEN"}
        Sync(reopened, self.gh).run()
        self.assertEqual(self.gh.run.call_count, 1)
        self.assertEqual(self.gh.run.call_args.args[0][1], "view")
        self.assertEqual(reopened.jobs()[0]["status"], "sending")

    def test_comment_marker_reconciles_unknown_outcome_without_duplicate(self):
        p = dict(
            kind="comment",
            args=["issue", "comment", "1", "--repo", "me/repo", "--body", "my words"],
            repo="me/repo",
            tab=1,
            identity=1,
            body="my words",
        )
        identifier = self.store.enqueue("Comment", p)
        job = self.store.jobs()[0]
        self.assertIn("gh-desk:" + identifier, job["payload"]["args"][-1])
        self.store.update(identifier, "uncertain", "timeout")
        self.gh.run.return_value = [[{"body": "my words\n" + job["payload"]["marker"]}]]
        self.sync.run()
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.gh.run.call_count, 1)
        self.assertEqual(self.gh.run.call_args.args[0][0], "api")

    def test_unfound_marker_does_not_authorize_replay(self):
        p = dict(
            kind="create",
            args=["issue", "create", "--repo", "me/repo", "--title", "new", "--body", "draft"],
            repo="me/repo",
            tab=1,
            title="new",
            body="draft",
        )
        identifier = self.store.enqueue("Create", p)
        self.store.update(identifier, "uncertain", "disconnected")
        self.gh.run.return_value = [[]]
        self.sync.run()
        self.assertEqual(self.store.jobs()[0]["status"], "uncertain")
        self.assertEqual(self.gh.run.call_count, 1)

    def test_multiple_edits_to_unresolved_target_are_blocked(self):
        self.store.enqueue("Close", self.state_payload())
        with self.assertRaisesRegex(ValueError, "unsynced edit"):
            self.store.enqueue("Close again", self.state_payload())

    def test_online_commands_are_not_automatically_replayed(self):
        self.store.enqueue("Merge", dict(kind="online", args=["pr", "merge", "1", "--squash"]))
        self.sync.run()
        self.gh.run.assert_not_called()

    def test_project_status_reads_paginated_remote_value(self):
        p = dict(
            kind="status",
            args=["project", "item-edit"],
            project={"id": "PROJECT"},
            identity="ITEM",
            base="Todo",
            desired="Done",
            target="PROJECT:ITEM",
        )
        self.store.enqueue("Done", p)
        self.gh.run.side_effect = [
            [
                {"data": {"node": {"items": {"nodes": []}}}},
                {
                    "data": {
                        "node": {
                            "items": {
                                "nodes": [
                                    {"id": "ITEM", "fieldValueByName": {"name": "In progress"}}
                                ]
                            }
                        }
                    }
                },
            ]
        ]
        self.sync.run()
        self.assertEqual(self.store.jobs()[0]["status"], "conflict")
        self.assertIn("--paginate", self.gh.run.call_args.args[0])
        self.assertEqual(self.gh.run.call_count, 1)

    def test_archive_and_rebase_keep_original_audit_payload(self):
        identifier = self.store.enqueue("Close", self.state_payload())
        p = self.state_payload()
        p["base"] = "updated base"
        self.store.update(identifier, "pending", "rebase", p)
        self.store.update(identifier, "archived", "kept in journal")
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(self.store.audit(identifier)[0]["payload"]["base"], "OPEN")
        self.assertEqual(self.store.audit(identifier)[1]["payload"]["base"], "updated base")
        self.assertEqual(self.store.jobs(active=False)[0]["payload"]["row"]["body"], "remote body")

    def test_confirmed_action_keeps_original_target_during_remote_refresh(self):
        app = make_app()
        app.state.tab, app.state.repo, app.state.project = (1, "me/repo", None)
        app.state.rows, app.state.query, app.state.selected = (demo_rows(1), "", 0)
        app.state.busy, app.state.loading = (False, False)
        app.actions.show_menu()
        action = next(
            a for a in app.state.modal[2] if isinstance(a, Action) and a.args[1] == "close"
        )
        original = app.state.rows[0]["number"]
        app.state.rows = app.state.rows[1:]
        payload = app.actions.write_payload(action)
        self.assertEqual(payload["identity"], original)
        self.assertEqual(payload["args"][2], str(original))
        self.assertEqual(payload["base"], "OPEN")

    def test_offline_create_appears_without_any_remote_snapshot(self):
        app = make_app()
        app.args = argparse.Namespace(owner=None, limit=100, demo=False, offline=True)
        app.store, app.state.tab, app.state.repo, app.state.project, app.state.issue_state = (
            self.store,
            1,
            "me/repo",
            None,
            "open",
        )
        app.state.generation = app.state.detail_generation = 0
        app.state.rows, app.state.query, app.state.selected = ([], "", 0)
        self.store.enqueue(
            "New issue",
            dict(
                kind="create",
                args=["issue", "create", "--body", "draft"],
                repo="me/repo",
                tab=1,
                title="Offline draft",
                body="draft",
            ),
        )
        with patch.object(app, "launch") as launch:
            app.workspace.load()
            launch.assert_not_called()
        self.assertEqual(app.navigation.current()["title"], "Offline draft")
        self.assertTrue(app.navigation.current()["_local"])

    def test_real_offline_terminal_edit_survives_restart_without_gh_calls(self):
        import errno
        import fcntl
        import os
        import pty
        import select
        import struct
        import subprocess
        import termios

        root = Path(__file__).resolve().parents[1]
        key = json.dumps(
            dict(tab=1, owner=None, repo="me/repo", state="open", limit=100, project=None),
            sort_keys=True,
        )
        self.store.put(
            key,
            [
                dict(
                    number=1,
                    title="Offline terminal task",
                    body="Preserve remote text",
                    state="OPEN",
                    author={},
                    labels=[],
                )
            ],
        )
        bindir = Path(self.tmp.name) / "bin"
        bindir.mkdir()
        log = Path(self.tmp.name) / "gh-calls"
        stub = bindir / "gh"
        stub.write_text('#!/bin/sh\necho called >> "' + str(log) + '"\nexit 1\n')
        stub.chmod(448)

        def session(edit):
            ready = Path(self.tmp.name) / "ui-ready.json"
            ready.unlink(missing_ok=True)
            # Observe completed real curses frames rather than guessing when the
            # app has handled input. The launcher and all actions remain real.
            harness = """
import json, os, sys
from pathlib import Path
from renderer import Renderer
import gh_desk
ready = Path(sys.argv.pop(1))
original = Renderer.draw
def observed_draw(renderer):
    original(renderer)
    state = renderer.app.state
    frame = dict(modal=state.modal[1] if state.modal else None,
                 message=state.message, rows=len(state.rows))
    temporary = ready.with_suffix('.tmp')
    temporary.write_text(json.dumps(frame))
    os.replace(temporary, ready)
Renderer.draw = observed_draw
gh_desk.main()
"""
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    harness,
                    str(ready),
                    "--no-config",
                    "--offline",
                    "--repo",
                    "me/repo",
                    "--data-dir",
                    self.tmp.name,
                ],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=dict(os.environ, TERM="xterm-256color", PATH=str(bindir)),
                start_new_session=True,
                cwd=root,
            )
            os.close(slave)
            transcript = bytearray()

            def pump(seconds=0.2):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.02)[0]:
                        try:
                            transcript.extend(os.read(master, 65536))
                        except OSError as exc:
                            if exc.errno == errno.EIO:
                                break
                            raise

            def wait_for(predicate, timeout=5):
                deadline = time.monotonic() + timeout
                frame = None
                while time.monotonic() < deadline:
                    pump(0.02)
                    if ready.exists():
                        frame = json.loads(ready.read_text())
                        if predicate(frame):
                            return
                    if proc.poll() is not None:
                        break
                self.fail(
                    f"UI state did not arrive: {frame!r}\n" + transcript.decode(errors="replace")
                )

            def send(data, predicate):
                ready.unlink(missing_ok=True)
                os.write(master, data)
                wait_for(predicate)

            try:
                wait_for(
                    lambda frame: frame["modal"] is None and frame["rows"] == (1 if edit else 0)
                )
                if edit:
                    send(b"a", lambda frame: frame["modal"] == "Actions")
                    send(b"j\n", lambda frame: frame["modal"] == "Confirm: Close #1")
                    send(b"j\n", lambda frame: frame["modal"] is None and frame["rows"] == 0)
                    self.assertEqual(self.store.jobs()[0]["status"], "pending")
                send(b"o", lambda frame: frame["modal"] == "Outbox · 1 unresolved")
                self.assertIn(b"pending", transcript)
                send(b"\x1b", lambda frame: frame["modal"] is None)
                os.write(master, b"q")
                deadline = time.monotonic() + 5
                while proc.poll() is None and time.monotonic() < deadline:
                    pump(0.02)
                self.assertIsNotNone(proc.poll(), transcript.decode(errors="replace"))
                proc.wait(timeout=1)
                pump(0.05)
                self.assertEqual(proc.returncode, 0, transcript.decode(errors="replace"))
                self.assertNotIn(b"Traceback", transcript)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                os.close(master)

        session(True)
        session(False)
        self.assertFalse(log.exists(), "Offline mode invoked gh")
        self.assertEqual(self.store.jobs()[0]["status"], "pending")
        self.assertEqual(self.store.jobs()[0]["payload"]["row"]["body"], "Preserve remote text")

    def test_cached_load_offline_and_fresh_load_make_no_network_calls(self):
        app = make_app()
        app.args = argparse.Namespace(owner=None, limit=100, demo=False, offline=True)
        app.store, app.state.tab, app.state.repo, app.state.project, app.state.issue_state = (
            self.store,
            4,
            None,
            {"id": "P", "number": 1},
            "open",
        )
        app.state.generation = app.state.detail_generation = 0
        app.state.rows, app.state.query, app.state.selected = ([], "", 0)
        key = app.workspace.cache_key()
        self.store.put(key, [dict(id="I", title="Cached task", labels=["bug"], status="Todo")])
        with patch.object(app, "launch") as launch:
            app.workspace.load()
            self.assertEqual(app.navigation.current()["title"], "Cached task")
            self.assertFalse(app.state.loading)
            launch.assert_not_called()
            app.args.offline = False
            app.workspace.load()
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
