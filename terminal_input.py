# SPDX-License-Identifier: Apache-2.0
"""Decode modern SGR mouse reports even with macOS's legacy ncurses build."""

import curses
import re
import time
from collections import deque
from dataclasses import dataclass

WHEEL_DOWN = getattr(curses, "BUTTON5_PRESSED", 1 << 40)


@dataclass
class MouseEvent:
    x: int
    y: int
    state: int


class TerminalInput:
    def __init__(self):
        self.pending = deque()
        self.escape = ""
        self.started = 0
        self.press = None
        self.last_click = None

    def mouse_event(self, button, x, y, release):
        x, y = x - 1, y - 1
        if button & 64:
            return MouseEvent(x, y, WHEEL_DOWN if button & 1 else curses.BUTTON4_PRESSED)
        number = button & 3
        pressed = (curses.BUTTON1_PRESSED, curses.BUTTON2_PRESSED, curses.BUTTON3_PRESSED, 0)
        released = (
            curses.BUTTON1_RELEASED,
            curses.BUTTON2_RELEASED,
            curses.BUTTON3_RELEASED,
            curses.BUTTON1_RELEASED,
        )
        if release:
            state = released[number]
            if number == 0 and self.press == (x, y):
                now = time.monotonic()
                if (
                    self.last_click
                    and self.last_click[:2] == (x, y)
                    and now - self.last_click[2] < 0.3
                ):
                    state |= curses.BUTTON1_DOUBLE_CLICKED
                    self.last_click = None
                else:
                    self.last_click = (x, y, now)
            self.press = None
        else:
            state = pressed[number]
            if button & 32:
                state |= curses.REPORT_MOUSE_POSITION
                if self.press != (x, y):
                    self.press = None
            elif number == 0:
                self.press = (x, y)
        return MouseEvent(x, y, state)

    def read(self, screen):
        if self.pending:
            return self.pending.popleft()
        try:
            key = screen.get_wch()
        except curses.error:
            if self.escape and time.monotonic() - self.started > 0.08:
                text = self.escape
                self.escape = ""
                if text.startswith("\x1b[<"):
                    return None
                self.pending.extend(text[1:])
                return "\x1b"
            raise
        if not self.escape:
            if key == "\x1b":
                self.escape = key
                self.started = time.monotonic()
                return None
            return key
        if not isinstance(key, str):
            self.pending.append(key)
            self.escape = ""
            return "\x1b"
        self.escape += key
        if self.escape in ("\x1b[", "\x1b[<"):
            return None
        if self.escape.startswith("\x1b[<"):
            match = re.fullmatch(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])", self.escape)
            if match:
                self.escape = ""
                return self.mouse_event(
                    int(match[1]), int(match[2]), int(match[3]), match[4] == "m"
                )
            if len(self.escape) < 64 and re.fullmatch(r"\x1b\[<[0-9;]*", self.escape):
                return None
        self.pending.extend(self.escape[1:])
        self.escape = ""
        return "\x1b"
