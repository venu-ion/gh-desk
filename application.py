# SPDX-License-Identifier: Apache-2.0
"""Composition root and asynchronous event loop for gh-desk."""

from __future__ import annotations

import curses
import queue
import threading
import time

from actions import ActionController
from app_state import Options, UIState
from github import GitHub
from identity import auth_namespace, bind_workspace
from input import InputController
from issue_actions import IssueActions
from local_store import Store
from metadata import Metadata
from navigation import Navigation
from renderer import Renderer
from text_view import TextViewer
from workspace import Workspace


class App:
    def __init__(
        self, screen, args: Options, *, store=None, github=None, interactive=True, autoload=True
    ):
        self.screen, self.args = screen, args
        self.state = UIState(tab=1 if args.repo else 0, repo=args.repo)
        self.gh = github if github is not None else GitHub()
        self.events = queue.Queue()
        self.store = (
            store
            if store is not None
            else (None if args.demo else Store(args.data_dir, auth_namespace()))
        )
        if self.store:
            self.gh.namespace = self.store.credential_namespace
            if store is None:
                bind_workspace(self.store, self.gh, offline=args.offline)
                if args.offline and self.store.namespace == self.store.credential_namespace:
                    self.state.message = (
                        "Offline · credentials not verified. Start online once after changing "
                        "credentials to reconnect previous work; all workspaces are preserved."
                    )
        self.navigation = Navigation(self)
        self.workspace = Workspace(self)
        self.renderer = Renderer(self)
        self.actions = ActionController(self)
        self.input = InputController(self)
        self.issue_actions = IssueActions(self)
        self.viewer = TextViewer(self)
        if interactive:
            self._initialize_terminal()
        if args.demo:
            self.state.message = "DEMO · sample data · all writes disabled"
        if autoload:
            self.workspace.load()

    @property
    def metadata(self) -> Metadata:
        if self.store is None:
            raise RuntimeError("Account metadata is unavailable in demo mode.")
        return Metadata(self.store, self.gh, self.args)

    def _initialize_terminal(self):
        self.screen.timeout(80)
        curses.set_escdelay(25)
        try:
            curses.curs_set(0)
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
            curses.mouseinterval(180)
        except curses.error:
            self.state.message = (
                "Terminal mouse support unavailable; keyboard navigation remains available."
            )
        self.state.colors = curses.has_colors()
        if self.state.colors:
            curses.start_color()
            curses.use_default_colors()
            for number, fg, bg in [
                (1, curses.COLOR_CYAN, -1),
                (2, curses.COLOR_BLACK, curses.COLOR_CYAN),
                (3, curses.COLOR_WHITE, -1),
                (4, curses.COLOR_GREEN, -1),
                (5, curses.COLOR_RED, -1),
                (6, curses.COLOR_YELLOW, -1),
            ]:
                curses.init_pair(number, fg, bg)

    def launch(self, kind, fn, token=None):

        def work():

            try:
                self.events.put((kind, token, fn(), None))

            except Exception as exc:
                # The thread boundary must return unexpected errors to the UI;
                # individual domain operations catch only expected failures.
                self.events.put((kind, token, None, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def drain(self):

        while True:
            try:
                kind, token, result, error = self.events.get_nowait()

            except queue.Empty:
                break

            if kind == "list" and token == self.state.generation:
                self.state.loading = False

                if error:
                    self.state.error = error

                    continue

                self.state.rows = self.workspace.apply_local(result)

                identities = [self.navigation.identity(row) for row in self.navigation.visible()]

                if self.state.snapshot in identities:
                    self.state.selected = identities.index(self.state.snapshot)

                    if self.navigation.board_active():
                        self.state.board_status = self.navigation.item_status(
                            self.navigation.visible()[self.state.selected]
                        )

                self.navigation.current()

                self.workspace.request_detail()

            elif kind == "detail" and token == self.state.detail_generation:
                self.state.detail = error or result

                row = self.navigation.current()

                if not error and row and (self.state.tab == 0):
                    self.state.detail_cache[row["nameWithOwner"]] = result

            elif kind == "sync":
                self.state.syncing = False

                saved_modal = self.state.modal

                self.workspace.load(force=True)

                self.state.modal = saved_modal

                self.state.message = error or result

            elif kind == "write":
                self.state.busy = False

                if error:
                    self.state.modal = ("text", "Action failed", error)

                else:
                    self.state.message = result.strip() or "Done."

                    self.workspace.load()

            elif kind == "view":
                self.state.busy = False

                self.state.modal = ("text", "Output", error or result or "No output.")

                self.state.modal_index = 0

            elif kind == "text_clipboard":
                if error:
                    self.state.modal, self.state.modal_index = (
                        (
                            "text",
                            "Copy text manually",
                            token + "\n\nClipboard unavailable: " + error,
                        ),
                        0,
                    )

                else:
                    self.state.message = "Copied " + str(len(token)) + " characters"

                    self.state.copy_notice = self.state.message

            elif kind == "browser":
                if error:
                    self.state.modal, self.state.modal_index = (
                        ("text", "Could not open link", token + "\n\n" + error),
                        0,
                    )

                else:
                    self.state.message = "Opened link: " + token

                    self.state.copy_notice = self.state.message

            elif kind == "clipboard":
                if error:
                    self.state.modal, self.state.modal_index = (
                        ("text", "Copy permalink manually", token + "\n\n" + error),
                        0,
                    )

                else:
                    self.state.message = "Copied permalink: " + token

                    self.state.copy_notice = "Copied permalink · " + token

            elif kind == "menu_data":
                self.state.busy = False

                if error:
                    self.state.modal, self.state.modal_index = (
                        ("text", "Could not load actions", error),
                        0,
                    )

                else:
                    token(result)

            elif kind == "fields":
                self.state.busy = False

                if error:
                    self.state.modal = ("text", "Could not load project fields", error)

                else:
                    self.actions.status_menu(result, token)

    def run(self):

        dirty = True

        while self.state.running:
            if not self.events.empty():
                self.drain()

                dirty = True

            self.workspace.fetch_readme_if_due()

            if (
                self.store
                and (not self.args.offline)
                and (not self.state.syncing)
                and (time.monotonic() >= self.state.next_sync)
            ):
                self.state.next_sync = time.monotonic() + 30

                if self.store.jobs():
                    self.workspace.start_sync()

                    dirty = True

            if dirty:
                self.renderer.draw()

                if not self.state.mouse_protocol_enabled:
                    self.input.enable_mouse_protocol()

                dirty = False

            try:
                key = self.input.read_key()

            except curses.error:
                continue

            if key is None:
                continue

            self.input.handle(key)

            dirty = True
