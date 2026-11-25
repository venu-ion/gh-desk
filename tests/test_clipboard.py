# SPDX-License-Identifier: Apache-2.0
import argparse
import queue
import subprocess
import unittest
from unittest.mock import patch

from support import make_app

from clipboard import ClipboardError, copy_text, https_url, item_permalink


class ClipboardTests(unittest.TestCase):
    def app(self):
        app = make_app()
        app.state.tab, app.state.repo, app.state.project = (
            4,
            None,
            dict(id="P", title="Roadmap", url="https://github.com/users/me/projects/3"),
        )
        app.state.rows = [
            dict(
                id="ITEM",
                status="Todo",
                title="Task",
                content={"url": "https://github.com/me/repo/issues/7"},
            )
        ]
        app.state.selected, app.state.query, app.state.busy, app.store = (0, "", False, None)
        app.args = argparse.Namespace(demo=False)
        app.state.focus, app.state.modal = ("list", None)
        app.state.board_enabled, app.state.board_status = (True, None)
        app.events = queue.Queue()
        return app

    def test_cached_urls_cover_all_views_and_local_pending_link(self):
        cases = [
            (0, dict(url="https://github.com/me/repo")),
            (1, dict(url="https://github.com/me/repo/issues/7")),
            (2, dict(url="https://github.com/me/repo/pull/9")),
            (3, dict(url="https://github.com/me/repo/actions/runs/12")),
            (4, dict(url="https://github.com/users/me/projects/3")),
        ]
        for tab, row in cases:
            self.assertEqual(item_permalink(tab, row), row["url"])
        row = dict(_local=True, content={"url": "https://github.com/me/repo/issues/7"})
        self.assertEqual(item_permalink(4, row), row["content"]["url"])
        self.assertIsNone(item_permalink(4, dict(_local=True, title="Unsynced")))

    def test_bad_urls_are_not_copied_and_issue_fallback_is_canonical(self):
        for value in (
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://example.com/\x1b[31m",
            "https://example.com/path with space",
            "https://user:password@example.com",
        ):
            self.assertIsNone(https_url(value))
        self.assertEqual(
            item_permalink(1, dict(number=7), "me/repo"), "https://github.com/me/repo/issues/7"
        )

    def test_native_pbcopy_uses_literal_stdin_without_shell(self):
        with (
            patch("clipboard.sys.platform", "darwin"),
            patch("clipboard.shutil.which", return_value="/usr/bin/pbcopy"),
            patch(
                "clipboard.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run,
        ):
            copy_text("https://github.com/me/repo/issues/7")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/pbcopy"])
        self.assertEqual(run.call_args.kwargs["input"], "https://github.com/me/repo/issues/7")
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_wayland_and_x11_clipboards(self):
        for env, expected in [
            ({"WAYLAND_DISPLAY": "wayland-0"}, ["/bin/wl-copy"]),
            ({"DISPLAY": ":0"}, ["/bin/xclip", "-selection", "clipboard"]),
        ]:
            with (
                patch("clipboard.sys.platform", "linux"),
                patch.dict("os.environ", env, clear=True),
                patch("clipboard.shutil.which", side_effect=lambda name: "/bin/" + name),
                patch(
                    "clipboard.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, "", ""),
                ) as run,
            ):
                copy_text("https://github.com/me/repo")
            self.assertEqual(run.call_args.args[0], expected)

    def test_failure_and_missing_clipboard_are_reported(self):
        with patch("clipboard.shutil.which", return_value=None):
            with self.assertRaises(ClipboardError):
                copy_text("https://github.com")
        with (
            patch("clipboard.sys.platform", "darwin"),
            patch.dict("os.environ", {}, clear=True),
            patch("clipboard.shutil.which", return_value="/usr/bin/pbcopy"),
            patch("clipboard.subprocess.run", side_effect=subprocess.TimeoutExpired("pbcopy", 2)),
        ):
            with self.assertRaises(ClipboardError):
                copy_text("https://github.com")

    def test_shortcuts_copy_item_or_project_without_network(self):
        app = self.app()
        with patch.object(app, "launch") as launch:
            app.input.handle("y")
            self.assertEqual(launch.call_args.args[0], "clipboard")
            self.assertEqual(launch.call_args.args[2], "https://github.com/me/repo/issues/7")
            app.input.handle("Y")
            self.assertEqual(launch.call_args.args[2], app.state.project["url"])
        app.actions.show_menu()
        labels = [e[0] for e in app.state.modal[2] if isinstance(e, tuple)]
        self.assertIn("Copy permalink (y)", labels)
        self.assertIn("Copy Project permalink (Y)", labels)

    def test_detail_and_actions_keep_original_link_if_selection_changes(self):
        app = self.app()
        for kind in ("detail", "actions"):
            app.state.rows = [
                dict(
                    id="ITEM", status="Todo", content={"url": "https://github.com/me/repo/issues/7"}
                )
            ]
            if kind == "detail":
                app.navigation.enter()
            else:
                app.actions.show_menu()
            app.state.rows = [
                dict(
                    id="OTHER",
                    status="Todo",
                    content={"url": "https://github.com/other/repo/issues/8"},
                )
            ]
            with patch.object(app, "launch") as launch:
                app.input.handle("y")
                self.assertEqual(launch.call_args.args[2], "https://github.com/me/repo/issues/7")

    def test_clipboard_result_is_visible_in_popup_or_falls_back_to_url(self):
        app = self.app()
        app.state.modal = ("detail", "Item", "Description")
        app.events.put(("clipboard", "https://github.com/me/repo/issues/7", None, None))
        app.drain()
        self.assertIn("Copied permalink", app.state.copy_notice)
        self.assertEqual(app.state.modal[0], "detail")
        app.events.put(
            ("clipboard", "https://github.com/me/repo/issues/7", None, "pbcopy unavailable")
        )
        app.drain()
        self.assertEqual(app.state.modal[:2], ("text", "Copy permalink manually"))
        self.assertIn("https://github.com/me/repo/issues/7", app.state.modal[2])


if __name__ == "__main__":
    unittest.main()
