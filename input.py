# SPDX-License-Identifier: Apache-2.0
"""InputController component; dependencies are explicit through its application context."""

from __future__ import annotations

import curses
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from help_text import HELP_TEXT
from terminal_input import WHEEL_DOWN, MouseEvent
from text_utils import cell_width

if TYPE_CHECKING:
    from application import App


class InputController:
    def __init__(self, app: App):
        self.app = app

    def prompt(self, title, initial=""):
        value, pos = (initial, len(initial))
        while True:
            self.app.renderer.draw()
            h, w = self.app.screen.getmaxyx()
            self.app.renderer.put(h - 3, 1, " " * (w - 2))
            prefix = title + ": "
            capacity = max(1, w - len(prefix) - 4)
            start = max(0, pos - capacity + 1)
            self.app.renderer.put(
                h - 3, 2, prefix + value[start : start + capacity], self.app.renderer.color(1)
            )
            try:
                curses.curs_set(1)
                self.app.screen.move(
                    h - 3, min(w - 2, 2 + len(prefix) + cell_width(value[start:pos]))
                )
                key = self.read_key()
                if key is None or isinstance(key, MouseEvent):
                    continue
            except curses.error:
                continue
            finally:
                try:
                    curses.curs_set(0)
                except curses.error:
                    pass
            if key == "\x1b":
                return None
            if key in ("\n", "\r", curses.KEY_ENTER):
                return value
            if key in (curses.KEY_BACKSPACE, "\x7f", "\x08"):
                if pos:
                    value, pos = (value[: pos - 1] + value[pos:], pos - 1)
            elif key == curses.KEY_DC:
                value = value[:pos] + value[pos + 1 :]
            elif key == curses.KEY_LEFT:
                pos = max(0, pos - 1)
            elif key == curses.KEY_RIGHT:
                pos = min(len(value), pos + 1)
            elif key in (curses.KEY_HOME, "\x01"):
                pos = 0
            elif key in (curses.KEY_END, "\x05"):
                pos = len(value)
            elif key == "\x15":
                value, pos = ("", 0)
            elif isinstance(key, str) and key.isprintable():
                value, pos = (value[:pos] + key + value[pos:], pos + len(key))

    def draft_directory(self):
        from contextlib import nullcontext

        root = (
            self.app.store.path.parent / "drafts" if self.app.store else Path(tempfile.gettempdir())
        )
        root.mkdir(parents=True, exist_ok=True, mode=448)
        return nullcontext(tempfile.mkdtemp(prefix="draft-", dir=root))

    def editor(self, title, initial=""):
        command = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi")
        with self.draft_directory() as tmp:
            path = Path(tmp) / "message.md"
            path.write_text(initial, encoding="utf-8")
            curses.def_prog_mode()
            curses.endwin()
            try:
                result = subprocess.run([*command, str(path)], check=False)
                if result.returncode:
                    self.app.state.message = (
                        f"{title} cancelled: editor exited {result.returncode}."
                    )
                    return None
                return path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                self.app.state.message = str(exc)
                return None
            finally:
                curses.reset_prog_mode()
                self.app.screen.keypad(True)
                self.app.screen.timeout(80)
                self.app.screen.clear()
                self.app.state.mouse_protocol_enabled = False

    def mouse(self, event=None):
        h, w = self.app.screen.getmaxyx()
        if h < 14 or w < 55:
            return
        try:
            if event is None:
                _, x, y, _, state = curses.getmouse()
            else:
                x, y, state = (event.x, event.y, event.state)
        except curses.error:
            return
        if self.app.viewer.text_mouse(x, y, state):
            return
        up = bool(state & curses.BUTTON4_PRESSED)
        down = bool(state & WHEEL_DOWN)
        if self.app.state.modal:
            kind, _, content = self.app.state.modal
            if up or down:
                self.app.state.modal_index = max(
                    0, min(self.app.state.modal_index + (-3 if up else 3), self.app.state.modal_max)
                )
                return
            mx, my, mw, mh = self.app.state.modal_box
            if state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                index = y - my - 2 + max(0, self.app.state.modal_index - (mh - 4) + 1)
                if (
                    kind in ("menu", "confirm")
                    and mx <= x < mx + mw
                    and (my + 2 <= y < my + mh - 2)
                    and (0 <= index < len(content))
                ):
                    self.app.state.modal_index = index
                    self.app.actions.choose()
            return
        if self.app.navigation.board_active():
            for bx, by, bw, bh, name, position in self.app.state.board_hits:
                if bx <= x < bx + bw and ((up or down) or by <= y < by + bh):
                    self.app.state.board_status = name
                    self.app.navigation.current()
                    if up or down:
                        self.app.navigation.move(-1 if up else 1)
                    elif state & (
                        curses.BUTTON1_CLICKED
                        | curses.BUTTON1_PRESSED
                        | curses.BUTTON1_DOUBLE_CLICKED
                    ):
                        if position is not None:
                            self.app.state.selected = position
                        if state & curses.BUTTON1_DOUBLE_CLICKED:
                            self.app.navigation.enter()
                    return
            return
        if up or down:
            if x > self.app.state.split:
                self.app.state.scroll = max(0, self.app.state.scroll + (-3 if up else 3))
            else:
                self.app.navigation.move(-3 if up else 3)
            return
        if state & (
            curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED
        ):
            if y == 2:
                for left, right, (_, tab) in self.app.state.hitboxes:
                    if left <= x < right:
                        self.app.navigation.switch(tab)
                        return
            if 6 <= y < 6 + self.app.state.height:
                self.app.state.focus = "list" if x < self.app.state.split else "detail"
                if x < self.app.state.split:
                    self.app.navigation.move(
                        self.app.state.top
                        + (y - 6) // self.app.state.list_stride
                        - self.app.state.selected
                    )
                    if state & curses.BUTTON1_DOUBLE_CLICKED:
                        self.app.navigation.enter()

    def help(self):
        self.app.state.modal = ("text", "Keyboard & mouse", HELP_TEXT)
        self.app.state.modal_index = 0

    def handle(self, key):
        self.app.state.copy_notice = ""
        if isinstance(key, MouseEvent):
            self.mouse(key)
            return
        if key == curses.KEY_MOUSE:
            self.mouse()
            return
        if self.app.viewer.text_key(key):
            return
        if key == "\x03":
            self.app.state.running = False
            return
        if self.app.state.modal:
            kind, title, content = self.app.state.modal
            if kind == "detail" and key == "y":
                if self.app.state.item_detail_permalink:
                    self.app.actions.copy_permalink(self.app.state.item_detail_permalink)
                else:
                    self.app.state.modal, self.app.state.modal_index = (
                        (
                            "text",
                            "No permalink yet",
                            "This item has no remote URL yet. Sync it first, or copy the Project URL with Y.",
                        ),
                        0,
                    )
            elif (
                (kind == "detail" or (kind == "menu" and title == "Actions"))
                and key == "Y"
                and self.app.navigation.project_items()
            ):
                self.app.actions.copy_permalink(project=True)
            elif kind == "menu" and title == "Actions" and (key == "y"):
                if self.app.state.actions_permalink:
                    self.app.actions.copy_permalink(self.app.state.actions_permalink)
                else:
                    self.app.state.modal, self.app.state.modal_index = (
                        ("text", "No permalink yet", "This item has no remote URL yet."),
                        0,
                    )
            elif (
                kind == "menu"
                and title == "Actions"
                and (key == "n")
                and self.app.navigation.project_items()
                and (not self.app.state.busy)
            ):
                self.app.state.modal = None
                self.app.actions.new_issue()
            elif kind == "detail" and key in (":", "a", "n"):
                rows = self.app.navigation.visible()
                index = next(
                    (
                        i
                        for i, row in enumerate(rows)
                        if self.app.navigation.identity(row) == self.app.state.item_detail_id
                    ),
                    None,
                )
                if index is None:
                    self.app.state.modal = (
                        "text",
                        "Item changed",
                        "This item is no longer in the current view. Close this popup and select it again before taking an action.",
                    )
                    self.app.state.modal_index = 0
                else:
                    self.app.state.selected = index
                    self.app.state.board_status = self.app.navigation.item_status(rows[index])
                    if key == "n" and (not self.app.state.busy):
                        self.app.state.modal = None
                        self.app.actions.new_issue()
                    else:
                        self.app.actions.show_menu()
            elif key in ("\x1b", "q"):
                self.app.state.modal = None
            elif key in ("j", curses.KEY_DOWN, curses.KEY_NPAGE):
                self.app.state.modal_index = min(
                    self.app.state.modal_index + (10 if key == curses.KEY_NPAGE else 1),
                    self.app.state.modal_max,
                )
            elif key in ("k", curses.KEY_UP, curses.KEY_PPAGE):
                self.app.state.modal_index = max(
                    0, self.app.state.modal_index - (10 if key == curses.KEY_PPAGE else 1)
                )
            elif key in ("\n", "\r", curses.KEY_ENTER):
                self.app.actions.choose()
            return
        if key == "q":
            self.app.state.running = False
        elif isinstance(key, str) and key in "12345":
            self.app.navigation.switch(int(key) - 1)
        elif key in ("f", "s") and self.app.navigation.project_items():
            self.app.navigation.filter_status()
        elif key == "b" and self.app.navigation.project_items():
            self.app.navigation.toggle_board()
        elif self.app.navigation.board_active() and key in (
            "h",
            "l",
            curses.KEY_LEFT,
            curses.KEY_RIGHT,
        ):
            self.app.navigation.move_column(-1 if key in ("h", curses.KEY_LEFT) else 1)
        elif key == "\t" and self.app.navigation.board_active():
            self.app.navigation.move_column(1)
        elif key == "\t":
            self.app.state.focus = "detail" if self.app.state.focus == "list" else "list"
        elif key in ("j", "k", curses.KEY_DOWN, curses.KEY_UP, curses.KEY_NPAGE, curses.KEY_PPAGE):
            delta = (-1 if key in ("k", curses.KEY_UP, curses.KEY_PPAGE) else 1) * (
                self.app.state.height if key in (curses.KEY_NPAGE, curses.KEY_PPAGE) else 1
            )
            if self.app.state.focus == "detail" and (not self.app.navigation.board_active()):
                self.app.state.scroll = max(0, self.app.state.scroll + delta)
            else:
                self.app.navigation.move(delta)
        elif key in (curses.KEY_HOME, curses.KEY_END):
            if self.app.state.focus == "list" or self.app.navigation.board_active():
                self.app.navigation.move(
                    -len(self.app.state.rows)
                    if key == curses.KEY_HOME
                    else len(self.app.state.rows)
                )
            else:
                self.app.state.scroll = 0 if key == curses.KEY_HOME else 1000000
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.app.navigation.enter()
        elif key == "y":
            self.app.actions.copy_permalink()
        elif key == "Y" and self.app.navigation.project_items():
            self.app.actions.copy_permalink(project=True)
        elif key == "r":
            self.app.workspace.load(force=True)
        elif key == "S":
            self.app.workspace.start_sync()
        elif key == "o":
            self.app.actions.outbox()
        elif key == "/":
            result = self.prompt("Filter", self.app.state.query)
            if result is not None:
                self.app.state.query, self.app.state.selected, self.app.state.top = (result, 0, 0)
                self.app.state.board_status = None
                self.app.workspace.request_detail()
        elif key in (":", "a"):
            self.app.actions.show_menu()
        elif (
            key == "n"
            and (
                self.app.state.tab == 1
                and self.app.state.repo
                or self.app.navigation.project_items()
            )
            and (not self.app.state.busy)
        ):
            self.app.actions.new_issue()
        elif key == "s" and self.app.state.tab in (1, 2):
            self.app.state.issue_state = {"open": "closed", "closed": "all", "all": "open"}[
                self.app.state.issue_state
            ]
            self.app.state.rows, self.app.state.selected, self.app.state.top = ([], 0, 0)
            self.app.workspace.load()
        elif key == "?":
            self.help()
        elif key == "\x1b":
            if self.app.state.query:
                self.app.state.query, self.app.state.selected = ("", 0)
                self.app.workspace.request_detail()
            elif self.app.navigation.project_items() and self.app.state.status_filter is not None:
                self.app.state.status_filter, self.app.state.board_status = (None, None)
                self.app.state.selected = 0
            elif self.app.state.project:
                self.app.state.status_filter, self.app.state.board_status = (None, None)
                (
                    self.app.state.project,
                    self.app.state.rows,
                    self.app.state.selected,
                    self.app.state.top,
                ) = (None, [], 0, 0)
                self.app.workspace.load()
            else:
                self.app.state.focus = "list"

    def read_key(self):
        return self.app.state.terminal_input.read(self.app.screen)

    def enable_mouse_protocol(self):
        os.write(1, b"\x1b[?1002h\x1b[?1006h")
        self.app.state.mouse_protocol_enabled = True
