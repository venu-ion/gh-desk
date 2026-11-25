# SPDX-License-Identifier: Apache-2.0
import curses
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from support import make_app

from text_view import TextDocument, browser_url, find_links


class Screen:
    def __init__(self):
        self.output = []

    def getmaxyx(self):
        return (32, 120)

    def addstr(self, y, x, text, style):
        self.output.append((y, x, text, style))


class TextTests(unittest.TestCase):
    def app(self, text="Hello world\nSecond line\nhttps://example.com/path"):
        app = make_app()
        app.screen, app.state.colors = (Screen(), False)
        app.state.tab, app.state.project, app.state.repo = (1, None, "me/repo")
        app.state.focus, app.state.modal = ("detail", ("text", "Conversation", text))
        app.state.modal_index, app.state.copy_notice = (0, "")
        app.events, app.state.text_surfaces = (queue.Queue(), {})
        app.viewer.render_text_surface("modal", text, 4, 6, 50, 15, 0, curses.A_REVERSE)
        return app

    def test_links_include_markdown_nested_parentheses_and_bare_urls(self):
        source = "See [guide](https://example.com/a_(b)#part) and https://example.org/test.\n[bad](javascript:alert(1))"
        links = find_links(source)
        self.assertEqual(
            [item.url for item in links],
            ["https://example.com/a_(b)#part", "https://example.org/test"],
        )
        self.assertEqual(links[0].label, "guide")
        self.assertIsNone(browser_url("file:///etc/passwd"))
        self.assertIsNone(browser_url("javascript:alert(1)"))
        self.assertIsNone(browser_url("https://user:password@example.com"))
        self.assertIsNone(browser_url("https://example.com/\x1b"))

    def test_wrap_maps_source_offsets_and_does_not_copy_soft_wrap_newlines(self):
        doc = TextDocument("abcdefghij\nSecond line", 4)
        self.assertEqual(
            [item.text for item in doc.lines], ["abcd", "efgh", "ij", "Seco", "nd l", "ine"]
        )
        self.assertEqual(doc.index_at(1, 2), 6)
        lo, hi = doc.selection(2, 8)
        self.assertEqual(doc.text[lo:hi], "cdefghi")
        lo, hi = doc.selection(8, 13)
        self.assertEqual(doc.text[lo:hi], "ij\nSec")

    def test_unicode_wide_and_combining_characters_keep_correct_selection(self):
        doc = TextDocument("你好 café", 8)
        self.assertEqual(doc.index_at(0, 1), 0)
        self.assertEqual(doc.index_at(0, 2), 1)
        lo, hi = doc.selection(3, 6)
        self.assertEqual(doc.text[lo:hi], "café")

    def test_drag_select_copy_and_ctrl_c_keep_app_running(self):
        app = self.app()
        app.state.running = True
        app.viewer.text_mouse(4, 6, curses.BUTTON1_PRESSED)
        app.viewer.text_mouse(8, 6, curses.REPORT_MOUSE_POSITION)
        app.viewer.text_mouse(8, 6, curses.BUTTON1_RELEASED)
        self.assertEqual(app.state.text_selection, ("modal", 0, 5))
        with patch.object(app, "launch") as launch:
            app.input.handle("c")
            self.assertEqual(launch.call_args.args[0], "text_clipboard")
            self.assertEqual(launch.call_args.args[2], "Hello")
            app.input.handle("\x03")
            self.assertTrue(app.state.running)
        app.input.handle("\x1b")
        self.assertIsNone(app.state.text_selection)
        app.input.handle("\x03")
        self.assertFalse(app.state.running)

    def test_wrapped_link_click_opens_exact_url_and_drag_does_not(self):
        url = "https://example.com/a/very/long/url"
        app = self.app(url)
        app.state.text_surfaces = {}
        app.viewer.render_text_surface("modal", url, 4, 6, 12, 10, 0, curses.A_REVERSE)
        with patch.object(app.viewer, "open_text_link") as opened:
            app.viewer.text_mouse(6, 7, curses.BUTTON1_CLICKED)
            opened.assert_called_once_with(url)
        with patch.object(app.viewer, "open_text_link") as opened:
            app.viewer.text_mouse(4, 6, curses.BUTTON1_PRESSED)
            app.viewer.text_mouse(8, 7, curses.REPORT_MOUSE_POSITION)
            app.viewer.text_mouse(8, 7, curses.BUTTON1_RELEASED)
            opened.assert_not_called()
        self.assertEqual(app.state.text_selection, ("modal", 0, 17))

    def test_select_all_copy_all_and_keyboard_link_picker(self):
        app = self.app()
        app.input.handle("\x01")
        self.assertEqual(app.state.text_selection, ("modal", 0, len(app.state.modal[2])))
        with patch.object(app, "launch") as launch:
            app.input.handle("C")
            self.assertEqual(launch.call_args.args[2], app.state.modal[2])
        app.input.handle("L")
        self.assertEqual(app.state.modal[:2], ("menu", "Links · choose to open or copy"))
        app.state.modal_index = 0
        app.actions.choose()
        self.assertEqual(app.state.modal[0], "menu")
        self.assertEqual(app.state.modal[1], "https://example.com/path")
        app.state.modal_index = 1
        with patch.object(app, "launch") as launch:
            app.actions.choose()
            self.assertEqual(launch.call_args.args[2], "https://example.com/path")

    def test_right_click_offers_copy_selection_and_link_actions(self):
        app = self.app()
        app.state.text_selection = ("modal", 0, 5)
        app.viewer.text_mouse(5, 8, curses.BUTTON3_CLICKED)
        self.assertEqual(app.state.modal[1], "Text actions")
        self.assertEqual(
            [e[0] for e in app.state.modal[2]],
            ["Copy selection", "Open link", "Copy link URL", "Copy all text"],
        )

    def test_refresh_clears_selection_but_resize_preserves_it(self):
        app = self.app("Original text")
        app.state.text_selection = ("modal", 0, 8)
        app.viewer.text_document("modal", "Original text", 10)
        self.assertEqual(app.state.text_selection, ("modal", 0, 8))
        app.viewer.text_document("modal", "New description", 10)
        self.assertIsNone(app.state.text_selection)

    def test_menus_do_not_allow_click_through_to_text(self):
        app = self.app("https://example.com")
        app.state.modal = ("menu", "Actions", [("Copy", lambda: None)])
        with patch.object(app.viewer, "open_text_link") as opened:
            self.assertFalse(app.viewer.text_mouse(5, 6, curses.BUTTON1_CLICKED))
            opened.assert_not_called()

    def test_reverse_selection_and_double_click_word(self):
        app = self.app()
        app.viewer.text_mouse(8, 6, curses.BUTTON1_PRESSED)
        app.viewer.text_mouse(4, 6, curses.BUTTON1_RELEASED)
        self.assertEqual(app.state.text_selection, ("modal", 0, 5))
        app.viewer.text_mouse(11, 6, curses.BUTTON1_DOUBLE_CLICKED)
        self.assertEqual(app.state.text_selection, ("modal", 6, 11))

    def test_browser_launch_is_async_and_never_runs_for_non_http_scheme(self):
        app = self.app()
        with patch.object(app, "launch") as launch:
            app.viewer.open_text_link("javascript:alert(1)")
            launch.assert_not_called()
            app.viewer.open_text_link("https://example.com")
            self.assertEqual(launch.call_args.args[0], "browser")
            worker = launch.call_args.args[1]
            with patch("text_view.webbrowser.open", return_value=True) as opened:
                worker()
                opened.assert_called_once_with("https://example.com", new=2)

    @unittest.skipUnless(sys.platform == "darwin", "Native pbcopy shim test targets macOS")
    def test_real_terminal_mouse_drag_copies_exact_description_text(self):
        import errno
        import fcntl
        import os
        import pty
        import select
        import struct
        import subprocess
        import tempfile
        import termios
        import time

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            clipboard = Path(directory) / "copied.txt"
            tool = Path(directory) / "pbcopy"
            tool.write_text('#!/bin/sh\n/bin/cat > "' + str(clipboard) + '"\n')
            tool.chmod(448)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 120, 0, 0))
            proc = subprocess.Popen(
                [sys.executable, str(root / "gh_desk.py"), "--no-config", "--demo"],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=dict(os.environ, TERM="xterm-256color", PATH=directory),
                start_new_session=True,
            )
            os.close(slave)
            transcript = bytearray()

            def pump(seconds=0.22):
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

            try:
                deadline = time.monotonic() + 4
                while b"GH DESK" not in transcript and time.monotonic() < deadline:
                    pump(0.1)
                send(b"\n")
                send(b"\n")
                send(b"\x1b[<0;52;7M")
                send(b"\x1b[<32;55;7M")
                send(b"\x1b[<0;55;7m")
                send(b"c")
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if clipboard.exists() and clipboard.read_text() == "#42 ":
                        break
                    pump(0.05)
                self.assertTrue(clipboard.exists(), transcript.decode(errors="replace"))
                self.assertEqual(clipboard.read_text(), "#42 ")
                send(b"q")
                proc.wait(timeout=2)
                self.assertEqual(proc.returncode, 0)
                self.assertIn(b"\x1b[?1002h", transcript)
                self.assertIn(b"\x1b[?1006l", transcript)
                self.assertNotIn(b"Traceback", transcript)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                os.close(master)

    def test_description_pane_supports_same_controls_as_comment_popup(self):
        app = self.app()
        app.state.modal = None
        app.viewer.render_text_surface("pane", "Description https://example.org", 50, 6, 50, 10, 0)
        with patch.object(app, "launch") as launch:
            app.input.handle("C")
            self.assertEqual(launch.call_args.args[2], "Description https://example.org")
        with patch.object(app.viewer, "open_text_link") as opened:
            app.viewer.text_mouse(64, 6, curses.BUTTON1_CLICKED)
            opened.assert_called_once_with("https://example.org")


if __name__ == "__main__":
    unittest.main()
