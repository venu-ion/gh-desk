# SPDX-License-Identifier: Apache-2.0
import argparse
import errno
import fcntl
import os
import pty
import queue
import select
import struct
import subprocess
import sys
import termios
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from support import make_app

from demo import demo_rows
from github import GhError, GitHub
from models import Action
from text_utils import clean, clip

ROOT = Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def test_arguments_are_literal_and_prompting_is_disabled(self):
        with patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")
        ) as run:
            result = GitHub().run(
                ["issue", "comment", "1", "--body", "$(touch /tmp/no); `echo danger`"]
            )
        self.assertEqual(result, "ok")
        self.assertEqual(run.call_args.args[0][-1], "$(touch /tmp/no); `echo danger`")
        self.assertEqual(run.call_args.kwargs["env"]["GH_PROMPT_DISABLED"], "1")
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_project_and_issue_queries(self):
        api = GitHub()
        with patch.object(api, "run", return_value={"items": [{"id": "x"}]}) as run:
            self.assertEqual(api.listing(4, "me", "", "open", 100, {"number": 7}), [{"id": "x"}])
            self.assertEqual(
                run.call_args.args[0],
                ["project", "item-list", 7, "--owner", "me", "--limit", 100, "--format", "json"],
            )
        with patch.object(api, "run", return_value=[]) as run:
            api.listing(1, None, "owner/repo", "closed", 50)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("--state") + 1], "closed")
            self.assertEqual(args[args.index("--repo") + 1], "owner/repo")

    def test_failures(self):
        for result, expected in [
            (subprocess.CompletedProcess([], 1, "", "missing scope"), "missing scope"),
            (subprocess.CompletedProcess([], 0, "not-json", ""), "invalid JSON"),
        ]:
            with patch("subprocess.run", return_value=result):
                with self.assertRaisesRegex(GhError, expected):
                    GitHub().run(["api", "user"], parse=True)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 35)):
            with self.assertRaisesRegex(GhError, "write may have completed"):
                GitHub().run(["issue", "close", "1"])


class ModelTests(unittest.TestCase):
    def app(self, tab=1):
        app = make_app()
        app.store = None
        app.state.tab, app.state.rows, app.state.query, app.state.selected = (
            tab,
            demo_rows(tab),
            "",
            0,
        )
        app.args = argparse.Namespace(demo=True, owner=None)
        app.state.repo, app.state.project, app.state.issue_state = (
            "octocat/launchpad",
            None,
            "open",
        )
        app.state.loading = app.state.busy = False
        app.state.modal = None
        app.state.modal_index = 0
        app.state.generation = 2
        app.state.detail_generation = 2
        app.events = queue.Queue()
        return app

    def test_filter_empty_unicode_and_all_terms(self):
        app = self.app()
        app.state.query = "SEARCH INSTANT"
        self.assertEqual(len(app.navigation.visible()), 1)
        app.state.query = "does not exist"
        self.assertIsNone(app.navigation.current())
        self.assertEqual(clip("你好abc", 5), "你好a")
        self.assertNotIn("\x1b", clean("\x1b[31mhello"))

    def test_merge_pins_head_and_requires_confirmation(self):
        app = self.app(2)
        app.actions.show_menu()
        action = next(a for a in app.state.modal[2] if isinstance(a, Action) and "merge" in a.label)
        self.assertTrue(action.confirm)
        self.assertIn("--match-head-commit", action.args)
        app.state.modal_index = app.state.modal[2].index(action)
        app.actions.choose()
        self.assertEqual(app.state.modal[0], "confirm")
        self.assertEqual(app.state.modal_index, 0)
        self.assertEqual(app.state.modal[2][0][0], "Cancel")

    def test_demo_never_launches_writes(self):
        app = self.app()
        with patch.object(app, "launch") as launch:
            app.actions.execute(Action("Close issue", ["issue", "close", "42"]))
            launch.assert_not_called()
        self.assertEqual(app.state.modal[1], "Demo mode")

    def test_stale_requests_cannot_overwrite_current_view(self):
        app = self.app()
        before = app.state.rows
        app.events.put(("list", 1, [{"title": "wrong view"}], None))
        app.events.put(("detail", 1, "wrong readme", None))
        app.state.detail = "current"
        app.drain()
        self.assertIs(app.state.rows, before)
        self.assertEqual(app.state.detail, "current")

    def test_refresh_preserves_identity_when_order_and_fields_change(self):
        app = self.app()
        app.state.snapshot = app.navigation.identity(app.state.rows[0])
        changed = dict(app.state.rows[0], title="Updated remotely")
        app.events.put(("list", 2, [app.state.rows[1], changed], None))
        with patch.object(app.workspace, "request_detail"):
            app.drain()
        self.assertEqual(app.state.selected, 1)
        self.assertEqual(app.navigation.current()["title"], "Updated remotely")

    def test_project_status_uses_field_option_ids(self):
        app = self.app(4)
        app.actions.status_menu(
            {
                "fields": [
                    {"name": "Status", "id": "FIELD", "options": [{"id": "OPTION", "name": "Done"}]}
                ]
            },
            ({"id": "PROJECT"}, {"id": "ITEM", "title": "Task"}),
        )
        action = app.state.modal[2][0]
        self.assertEqual(
            action.args,
            [
                "project",
                "item-edit",
                "--id",
                "ITEM",
                "--project-id",
                "PROJECT",
                "--field-id",
                "FIELD",
                "--single-select-option-id",
                "OPTION",
            ],
        )


class TerminalTests(unittest.TestCase):
    def test_real_terminal_navigation_mouse_popups_and_resize(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "gh_desk.py"), "--no-config", "--demo"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=dict(os.environ, TERM="xterm-256color"),
            start_new_session=True,
        )
        os.close(slave)
        transcript = bytearray()

        def drain(seconds=0.25):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if select.select([master], [], [], 0.03)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    transcript.extend(chunk)

        def send(data):
            os.write(master, data)
            drain()

        try:
            deadline = time.monotonic() + 4
            while b"GH DESK" not in transcript and time.monotonic() < deadline:
                drain(0.1)
            self.assertIn(b"GH DESK", transcript)
            send(b"\n")
            send(b"/instant\n")
            send(b"\x1b")
            send(b"3")
            send(b":")
            send(b"jjjjj\n")
            send(b"\x1b")
            send(b"5\n")
            send(b"l")
            send(b"\n")
            send(b":")
            self.assertIn(b"Change status", transcript)
            send(b"\x1b")
            send(b"\n")
            send(b"a")
            send(b"\x1b")
            send(b"f")
            send(b"j\n")
            send(b"b")
            send(b"\x1b")
            send(b"b")
            send(b":")
            send(b"\x1b")
            send(b"?")
            send(b"jjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj")
            send(b"\x1b")
            send(b"1")
            send(b"\x1b[<0;8;8M\x1b[<0;8;8m")
            send(b"\tjj\t")
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 10, 40, 0, 0))
            os.kill(proc.pid, __import__("signal").SIGWINCH)
            send(b"j")
            send(b"q")
            proc.wait(timeout=3)
            drain()
            self.assertEqual(proc.returncode, 0, transcript.decode(errors="replace"))
            self.assertNotIn(b"Traceback", transcript)
            self.assertIn(b"Personal roadmap", transcript)
            self.assertIn(b"resize to at least", transcript)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)


if __name__ == "__main__":
    unittest.main()
