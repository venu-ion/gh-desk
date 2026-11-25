# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from support import make_app

from github import GhError
from identity import auth_namespace
from local_store import Store
from sync import Sync


class ProjectCreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, auth_namespace())
        self.gh = Mock()
        self.sync = Sync(self.store, self.gh)
        self.project = dict(id="P", number=7, title="Personal")
        self.payload = dict(
            kind="create",
            args=[
                "issue",
                "create",
                "--repo",
                "me/repo",
                "--title",
                "New work",
                "--body",
                "Details",
            ],
            repo="me/repo",
            tab=1,
            title="New work",
            body="Details",
            project=self.project,
            project_owner="me",
        )
        self.url = "https://github.com/me/repo/issues/43"
        self.empty = [{"data": {"node": {"items": {"nodes": []}}}}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_creation_and_project_add_run_in_one_sync(self):
        self.store.enqueue("Create in Project", self.payload)
        self.gh.run.side_effect = [self.url, self.empty, "Added"]
        self.sync.run()
        self.assertEqual(
            [c.args[0][:2] for c in self.gh.run.call_args_list],
            [["issue", "create"], ["api", "graphql"], ["project", "item-add"]],
        )
        self.assertEqual(
            self.gh.run.call_args_list[-1].args[0],
            ["project", "item-add", "7", "--owner", "me", "--url", self.url],
        )
        self.assertEqual(self.store.jobs(), [])
        self.assertEqual(len(self.store.jobs(active=False)), 2)

    def test_parent_completion_and_child_queue_are_durable_and_unique(self):
        identifier = self.store.enqueue("Create", self.payload)
        self.store.finish_create(identifier, self.url, "Created")
        self.store.finish_create(identifier, self.url, "Verified again")
        reopened = Store(self.tmp.name, self.store.namespace)
        self.assertEqual(len(reopened.jobs()), 1)
        self.assertEqual(reopened.jobs()[0]["payload"]["parent"], identifier)
        self.assertEqual(reopened.jobs()[0]["payload"]["url"], self.url)
        self.assertEqual(
            next(j for j in reopened.jobs(active=False) if j["id"] == identifier)["payload"][
                "result_url"
            ],
            self.url,
        )

    def test_failed_project_add_never_recreates_issue(self):
        self.store.enqueue("Create", self.payload)
        self.gh.run.side_effect = [self.url, self.empty, GhError("Missing project scope")]
        self.sync.run()
        self.assertEqual(self.store.jobs()[0]["status"], "uncertain")
        self.assertEqual(self.store.jobs()[0]["payload"]["kind"], "add")
        self.gh.run.side_effect = [self.empty]
        self.sync.run()
        self.assertEqual(self.store.jobs()[0]["status"], "uncertain")
        self.assertEqual(
            sum(c.args[0][:2] == ["issue", "create"] for c in self.gh.run.call_args_list), 1
        )
        key = json.dumps(dict(tab=4, project="P", repo=None, state="open"))
        rows = self.store.overlay(key, [])
        self.assertEqual(rows[0]["title"], "New work")
        self.assertEqual(rows[0]["content"]["url"], self.url)
        self.assertEqual(rows[0]["_pending"], "link pending")

    def test_uncertain_creation_recovered_by_marker_then_links_without_recreate(self):
        identifier = self.store.enqueue("Create", self.payload)
        self.store.update(identifier, "uncertain", "timeout")
        marker = self.store.jobs()[0]["payload"]["marker"]
        self.gh.run.side_effect = [
            [[dict(html_url=self.url, body="Details " + marker)]],
            self.empty,
            "Added",
        ]
        self.sync.run()
        self.assertFalse(
            any(c.args[0][:2] == ["issue", "create"] for c in self.gh.run.call_args_list)
        )
        self.assertEqual(self.gh.run.call_args_list[-1].args[0][:2], ["project", "item-add"])
        self.assertEqual(self.store.jobs(), [])

    def test_existing_project_membership_skips_add(self):
        identifier = self.store.enqueue("Create", self.payload)
        self.store.finish_create(identifier, self.url, "Created")
        self.gh.run.return_value = [
            {"data": {"node": {"items": {"nodes": [{"content": {"url": self.url}}]}}}}
        ]
        self.sync.run()
        self.assertEqual(self.gh.run.call_count, 1)
        self.assertEqual(self.store.jobs(), [])

    def test_inaccessible_project_is_a_pending_read_failure(self):
        identifier = self.store.enqueue("Create", self.payload)
        self.store.finish_create(identifier, self.url, "Created")
        self.gh.run.return_value = [{"data": {"node": None}}]
        self.sync.run()
        job = self.store.jobs()[0]
        self.assertEqual(job["status"], "pending")
        self.assertIn("Project access", job["note"])
        self.assertEqual(self.gh.run.call_count, 1)

    def test_new_issue_from_project_prompts_repo_and_confirms_both_steps(self):
        app = make_app()
        app.store = self.store
        app.state.tab, app.state.project, app.state.repo = (4, self.project, "unrelated/repo")
        app.args = argparse.Namespace(demo=False, owner="me")
        row = dict(id="I", content=dict(url="https://github.com/me/repo/issues/2"))
        with (
            patch.object(app.navigation, "current", return_value=row),
            patch.object(app.input, "prompt", side_effect=["me/repo", "New work"]) as prompt,
            patch.object(app.input, "editor", return_value="Details"),
        ):
            app.actions.new_issue()
            self.assertEqual(prompt.call_args_list[0].args, ("Repository OWNER/REPO", "me/repo"))
        self.assertIn("Create issue and add to Personal", app.state.modal[1])
        self.assertEqual(app.state.modal_index, 0)
        app.state.modal_index = 1
        with patch.object(app.actions, "execute") as execute:
            app.actions.choose()
            action = execute.call_args.args[0]
        self.assertEqual(action.operation.project["id"], "P")
        self.assertEqual(action.operation.repo, "me/repo")
        self.assertEqual(action.operation.tab, 1)

    def test_actual_terminal_creates_local_project_issue_via_editor_and_confirmation(self):
        import errno
        import fcntl
        import os
        import pty
        import select
        import shlex
        import struct
        import subprocess
        import termios
        import time

        root = Path(__file__).resolve().parents[1]

        def key(project=None):
            return json.dumps(
                dict(tab=4, owner=None, repo=None, state="open", limit=100, project=project),
                sort_keys=True,
            )

        self.store.put(key(), [self.project])
        self.store.put(key("P"), [])
        editor = Path(self.tmp.name) / "editor.py"
        editor.write_text(
            'import sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text("Terminal body")\n'
        )
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
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
            env=dict(
                os.environ, TERM="xterm-256color", VISUAL=shlex.join([sys.executable, str(editor)])
            ),
            start_new_session=True,
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

        def expect(needle):
            deadline = time.monotonic() + 4
            while needle not in transcript and time.monotonic() < deadline:
                pump(0.1)
            self.assertIn(needle, transcript)

        def send(data):
            os.write(master, data)
            pump()

        try:
            expect(b"GH DESK")
            send(b"5")
            expect(b"Personal")
            send(b"\n")
            send(b"n")
            expect(b"Repository OWNER/REPO")
            send(b"me/repo\n")
            expect(b"Issue title")
            send(b"New terminal issue\n")
            expect(b"Create issue and add to Personal")
            send(b"j\n")
            expect(b"New terminal issue")
            send(b"q")
            proc.wait(timeout=2)
            self.assertEqual(proc.returncode, 0, transcript.decode(errors="replace"))
            self.assertNotIn(b"Traceback", transcript)
            job = self.store.jobs()[0]
            self.assertEqual(job["status"], "pending")
            self.assertEqual(job["payload"]["project"]["id"], "P")
            self.assertEqual(job["payload"]["body"], "Terminal body")
            rows = self.store.overlay(key("P"), [])
            self.assertEqual(rows[0]["title"], "New terminal issue")
            self.assertTrue(rows[0]["_local"])
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)

    def test_plain_issue_draft_does_not_appear_as_project(self):
        plain = dict(self.payload)
        del plain["project"]
        self.store.enqueue("Create", plain)
        key = json.dumps(dict(tab=4, project=None, repo=None, state="open"))
        self.assertEqual(self.store.overlay(key, []), [])

    def test_existing_issue_url_is_trimmed_and_project_context_is_saved(self):
        app = make_app()
        app.state.project, app.args = (self.project, argparse.Namespace(owner="me"))
        with (
            patch.object(app.input, "prompt", return_value="  " + self.url + "/#comment  "),
            patch.object(app.actions, "review") as review,
        ):
            app.actions.add_item()
        action = review.call_args.args[0]
        self.assertEqual(action.args[-1], self.url)
        self.assertEqual(action.operation.project["id"], "P")


if __name__ == "__main__":
    unittest.main()
