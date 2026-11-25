# SPDX-License-Identifier: Apache-2.0
import curses
import unittest

from terminal_input import WHEEL_DOWN, MouseEvent, TerminalInput


class InputTests(unittest.TestCase):
    def test_split_sgr_report_becomes_one_mouse_event_not_shortcut_keys(self):

        class Screen:
            def __init__(self):
                self.keys = iter("\x1b[<0;52;7M")

            def get_wch(self):
                return next(self.keys)

        parser = TerminalInput()
        screen = Screen()
        events = [parser.read(screen) for _ in range(len("\x1b[<0;52;7M"))]
        self.assertTrue(all(event is None for event in events[:-1]))
        self.assertEqual(events[-1], MouseEvent(51, 6, curses.BUTTON1_PRESSED))

    def test_drag_release_and_wheel_works_with_legacy_curses(self):
        parser = TerminalInput()
        self.assertTrue(parser.mouse_event(32, 5, 6, False).state & curses.REPORT_MOUSE_POSITION)
        self.assertTrue(parser.mouse_event(0, 5, 6, True).state & curses.BUTTON1_RELEASED)
        self.assertEqual(parser.mouse_event(65, 5, 6, False).state, WHEEL_DOWN)
        self.assertEqual(parser.mouse_event(64, 5, 6, False).state, curses.BUTTON4_PRESSED)

    def test_escape_and_next_key_are_preserved(self):

        class Screen:
            def __init__(self):
                self.keys = iter(["\x1b", "j"])

            def get_wch(self):
                return next(self.keys)

        parser = TerminalInput()
        screen = Screen()
        self.assertIsNone(parser.read(screen))
        self.assertEqual(parser.read(screen), "\x1b")
        self.assertEqual(parser.read(screen), "j")

    def test_incomplete_mouse_report_cannot_execute_number_shortcuts(self):

        class Screen:
            def get_wch(self):
                raise curses.error()

        parser = TerminalInput()
        parser.escape = "\x1b[<0;52;"
        parser.started = 0
        self.assertIsNone(parser.read(Screen()))
        self.assertEqual(list(parser.pending), [])


if __name__ == "__main__":
    unittest.main()
