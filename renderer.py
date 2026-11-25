# SPDX-License-Identifier: Apache-2.0
"""Renderer component; dependencies are explicit through its application context."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

from constants import TABS
from models import Action
from text_utils import cell_width, clean, clip, label_names, names

if TYPE_CHECKING:
    from application import App


class Renderer:
    def __init__(self, app: App):
        self.app = app

    def color(self, n):
        return curses.color_pair(n) if self.app.state.colors else curses.A_REVERSE if n == 2 else 0

    def put(self, y, x, text, style=0, width=None):
        h, w = self.app.screen.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.app.screen.addstr(
                    y, x, clip(text, min(w - x - 1, width if width is not None else w)), style
                )
            except curses.error:
                pass

    def detail_text(self):
        row = self.app.navigation.current()
        if not row:
            if self.app.state.error:
                return (
                    "Could not load GitHub data\n\n"
                    + self.app.state.error
                    + "\n\nTry: gh auth status\nSign in: gh auth login\nProjects scopes: gh auth refresh -s project\n\nPress r to retry, or q to quit."
                )
            return "Your workspace\n\nSelect a repository to browse issues, pull requests, and workflow runs.\n\nProjects opens your GitHub Projects and their items.\n\n/ filter   : actions   ? help"
        if self.app.state.tab == 0:
            lang = (row.get("primaryLanguage") or {}).get("name", "—")
            return f"{row['nameWithOwner']}\n\n{row.get('description') or 'No description.'}\n\n{lang}  ·  {('private' if row.get('isPrivate') else 'public')}  ·  {('archived' if row.get('isArchived') else 'active')}\n\nEnter to use this repository\n\n── README ──\n\n{self.app.state.detail or ('Demo README: build small, ship often.' if self.app.args.demo else 'Loading README…')}"
        if self.app.state.tab in (1, 2):
            author = (row.get("author") or {}).get("login", "unknown")
            meta = f"{row.get('state')}  ·  @{author}"
            if self.app.state.tab == 2:
                meta += f"\n{row.get('headRefName')} → {row.get('baseRefName')}  ·  {('draft' if row.get('isDraft') else row.get('mergeable', ''))}"
            labels = ", ".join(label_names(row.get("labels"))) or "none"
            return f"#{row['number']} {row['title']}\n\n{meta}\nLabels: {labels}\nAssignees: {', '.join(names(row.get('assignees'), 'login')) or 'none'}\n\n{row.get('body') or 'No description.'}\n\n{row.get('url', '')}"
        if self.app.state.tab == 3:
            return "\n\n".join(
                str(row.get(k, ""))
                for k in [
                    "displayTitle",
                    "workflowName",
                    "status",
                    "conclusion",
                    "headBranch",
                    "createdAt",
                    "url",
                ]
            )
        if self.app.state.project:
            content = row.get("content") or {}
            return f"{row.get('title', '')}\n\nStatus: {row.get('status', 'Unassigned')}\nRepository: {row.get('repository', '—')}\nLabels: {', '.join(label_names(row.get('labels'))) or 'none'}\nAssignees: {', '.join(names(row.get('assignees'), 'login')) or 'none'}{self.app.issue_actions.cached_date_summary(row)}\n\n{content.get('body', '')}\n\n{content.get('url', '')}\n\n: actions to change status"
        return f"{row.get('title', '')}\n\n{row.get('shortDescription', '')}\n\n{row.get('items', {}).get('totalCount', 0)} items\n\n{row.get('url', '')}\n\nEnter to view items"

    def wrapped(self, text, width):
        lines = []
        for line in clean(text).splitlines():
            if not line:
                lines.append("")
            while line:
                part = clip(line, max(1, width))
                if not part:
                    break
                lines.append(part)
                line = line[len(part) :]
        return lines

    def draw(self):
        self.app.state.text_surfaces = {}
        self.app.screen.erase()
        h, w = self.app.screen.getmaxyx()
        self.app.state.hitboxes = []
        if h < 14 or w < 55:
            self.put(0, 0, "gh-desk · resize to at least 55 × 14 · q quit")
            self.app.screen.refresh()
            return
        self.put(0, 2, "GH DESK", self.color(1) | curses.A_BOLD)
        self.put(
            0,
            12,
            " / " + (self.app.state.repo or self.app.args.owner or "personal workspace"),
            curses.A_DIM,
        )
        if self.app.args.demo:
            self.put(0, w - 10, " DEMO ", self.color(6))
        x = 2
        for i, name in enumerate(TABS):
            label = f" {i + 1} {name} "
            self.put(
                2,
                x,
                label,
                self.color(2) | curses.A_BOLD if self.app.state.tab == i else curses.A_DIM,
            )
            self.app.state.hitboxes.append((x, x + cell_width(label), ("tab", i)))
            x += cell_width(label) + 1
        self.put(
            4,
            2,
            (
                f"Project: {self.app.state.project['title']} · Esc back"
                if self.app.state.project
                else f"{TABS[self.app.state.tab]} · {(self.app.state.issue_state if self.app.state.tab in (1, 2) else 'recent')}"
            )
            + (f"  /{self.app.state.query}" if self.app.state.query else ""),
            self.color(1),
        )
        if self.app.navigation.project_items():
            self.put(
                4,
                2,
                f"{self.app.state.project['title']} · {('Board' if self.app.navigation.board_active() else 'List')} · Status: {self.app.state.status_filter or 'All'}"
                + (f" · /{self.app.state.query}" if self.app.state.query else ""),
                self.color(1),
            )
        if self.app.navigation.board_active():
            self.draw_board()
            if self.app.state.modal:
                self.draw_modal()
            self.app.screen.refresh()
            return
        self.app.state.split = max(24, min(48, w * 2 // 5))
        self.app.state.height = h - 9
        self.app.state.list_stride = 6 if self.app.navigation.project_items() else 1
        list_slots = max(1, self.app.state.height // self.app.state.list_stride)
        date_context = (
            self.app.issue_actions.date_display_context()
            if self.app.navigation.project_items()
            else None
        )
        for y in range(5, h - 3):
            self.put(y, self.app.state.split, "│", curses.A_DIM)
        rows = self.app.navigation.visible()
        self.app.navigation.current()
        self.app.state.top = min(self.app.state.top, self.app.state.selected)
        if self.app.state.selected >= self.app.state.top + list_slots:
            self.app.state.top = self.app.state.selected - list_slots + 1
        for i, row in enumerate(rows[self.app.state.top : self.app.state.top + list_slots]):
            y, idx = (6 + i * self.app.state.list_stride, self.app.state.top + i)
            selected = idx == self.app.state.selected
            style = self.color(2) if selected else self.color(3)
            label = (
                "[local] " if row.get("_pending") or row.get("_local") else ""
            ) + self.app.navigation.row_text(row).strip()
            if self.app.state.tab == 0:
                label = row["nameWithOwner"].split("/", 1)[-1] + (
                    "  [private]" if row.get("isPrivate") else ""
                )
            self.put(
                y,
                1,
                (" › " if selected else "   ") + clip(label, self.app.state.split - 5),
                style,
                self.app.state.split - 1,
            )
            if self.app.navigation.project_items():
                for line, value in enumerate(
                    self.app.issue_actions.display_metadata(row, date_context), start=1
                ):
                    self.put(y + line, 4, value, curses.A_DIM, self.app.state.split - 5)
        if not rows:
            self.put(
                6,
                3,
                "Loading…"
                if self.app.state.loading
                else "No matching items."
                if self.app.state.query
                else "No items.",
                curses.A_DIM,
                self.app.state.split - 4,
            )
            if self.app.state.error:
                self.put(8, 3, "Load failed · r retry", self.color(5), self.app.state.split - 4)
        content = self.detail_text()
        document = self.app.viewer.text_document("pane", content, w - self.app.state.split - 5)
        self.app.state.scroll = max(
            0, min(self.app.state.scroll, max(0, len(document.lines) - self.app.state.height))
        )
        self.app.viewer.render_text_surface(
            "pane",
            content,
            self.app.state.split + 3,
            6,
            w - self.app.state.split - 5,
            self.app.state.height,
            self.app.state.scroll,
        )
        status = (
            "Syncing…"
            if self.app.state.syncing
            else "Working…"
            if self.app.state.busy
            else "Loading…"
            if self.app.state.loading
            else self.app.state.error.split("\n")[0]
            if self.app.state.error
            else self.app.state.message
        )
        self.put(h - 3, 2, status, self.color(5) if self.app.state.error else curses.A_DIM)
        self.put(
            h - 2,
            2,
            "f/s status   b board   / search   : actions   Enter detail   q quit"
            if self.app.navigation.project_items()
            else "↑↓/jk move   Enter select   / filter   : actions   Tab pane   ? help   q quit",
            self.color(1),
        )
        self.put(
            h - 1,
            2,
            f"{len(rows)} / {len(self.app.state.rows)} loaded · limit {self.app.args.limit} · {self.app.state.focus} focus · r refresh · S sync · o outbox",
            curses.A_DIM,
        )
        if self.app.state.modal:
            self.draw_modal()
        self.app.screen.refresh()

    def draw_board(self):
        h, w = self.app.screen.getmaxyx()
        available = max(1, h - 13)
        self.app.state.card_lines = min(7, available)
        self.app.state.card_stride = self.app.state.card_lines + 1
        self.app.state.height = max(1, available // self.app.state.card_stride)
        date_context = self.app.issue_actions.date_display_context()
        self.app.navigation.current()
        groups = self.app.navigation.board_groups()
        names = [name for name, _ in groups]
        active = (
            names.index(self.app.state.board_status) if self.app.state.board_status in names else 0
        )
        count = min(len(groups), max(1, (w - 2) // 26))
        start = max(0, min(active - count + 1, len(groups) - count))
        width = (w - 2) // count
        self.app.state.board_hits = []
        for col, (name, items) in enumerate(groups[start : start + count]):
            x = 1 + col * width
            focused = name == self.app.state.board_status or (
                self.app.state.board_status is None and col == 0
            )
            self.put(
                6,
                x + 1,
                f"{name} ({len(items)})",
                self.color(2) if focused else self.color(1),
                width - 3,
            )
            self.app.state.board_hits.append((x, 6, width, 1, name, None))
            top = self.app.state.board_offsets.get(name, 0)
            if focused and items:
                index = next(
                    (
                        i
                        for i, (position, _) in enumerate(items)
                        if position == self.app.state.selected
                    )
                )
                top = max(0, min(top, index))
                if index >= top + self.app.state.height:
                    top = index - self.app.state.height + 1
            top = min(top, max(0, len(items) - self.app.state.height))
            self.app.state.board_offsets[name] = top
            if not items:
                self.put(8, x + 2, "No items", curses.A_DIM, width - 4)
            for n, (position, row) in enumerate(items[top : top + self.app.state.height]):
                y = 8 + n * self.app.state.card_stride
                selected = focused and position == self.app.state.selected
                style = self.color(2) if selected else self.color(3)
                title = self.wrapped(row.get("title") or "Untitled", width - 5)[:2] or ["Untitled"]
                title += [""] * (2 - len(title))
                content = row.get("content") or {}
                number = content.get("number", "")
                repo = row.get("repository") or content.get("repository") or ""
                if isinstance(repo, dict):
                    repo = repo.get("nameWithOwner") or repo.get("name", "")
                meta = (
                    ("[local] " if row.get("_pending") else "")
                    + (f"#{number} " if number else "")
                    + str(repo)
                )
                lines = [*title, meta, *self.app.issue_actions.display_metadata(row, date_context)]
                for line, value in enumerate(lines[: self.app.state.card_lines]):
                    self.put(
                        y + line,
                        x + 1 if line == 0 else x + 3,
                        ("› " if selected else "  ") + value if line == 0 else value,
                        style if line < 2 else curses.A_DIM,
                        width - 3 if line == 0 else width - 5,
                    )
                self.app.state.board_hits.append(
                    (x, y, width, self.app.state.card_lines, name, position)
                )
            if top or len(items) > self.app.state.height:
                self.put(
                    h - 5,
                    x + 2,
                    f"{top + 1}–{min(top + self.app.state.height, len(items))} / {len(items)}",
                    curses.A_DIM,
                    width - 4,
                )
            if col < count - 1:
                for y in range(6, h - 5):
                    self.put(y, x + width - 1, "│", curses.A_DIM)
        row = self.app.navigation.current()
        self.put(
            h - 4,
            2,
            self.app.navigation.row_text(row).strip()
            if row
            else "No items in this column. ←/→ choose another status.",
            curses.A_DIM,
        )
        status = (
            "Syncing…"
            if self.app.state.syncing
            else "Loading…"
            if self.app.state.loading
            else self.app.state.error or self.app.state.message
        )
        self.put(h - 3, 2, status, self.color(5) if self.app.state.error else curses.A_DIM)
        self.put(
            h - 2,
            2,
            "←→/hl column  ↑↓/jk card  f/s status  / search  Enter detail  : actions  b list",
            self.color(1),
        )
        self.put(
            h - 1,
            2,
            f"Columns {start + 1}–{start + count}/{len(groups)} · {len(self.app.navigation.visible())}/{len(self.app.state.rows)} loaded · r refresh · S sync · o outbox · q quit",
            curses.A_DIM,
        )

    def draw_modal(self):
        h, w = self.app.screen.getmaxyx()
        kind, title, content = self.app.state.modal
        mw = min(90, w - 6)
        if kind in ("menu", "confirm"):
            lines = [a.label if isinstance(a, Action) else a[0] for a in content]
        else:
            lines = [
                line.text for line in self.app.viewer.text_document("modal", content, mw - 6).lines
            ]
        mh = min(h - 6, max(7, len(lines) + 5))
        x, y = ((w - mw) // 2, (h - mh) // 2)
        self.app.state.modal_box = (x, y, mw, mh)
        for dy in range(mh):
            self.put(y + dy, x, " " * mw, curses.A_REVERSE)
        self.put(y, x + 2, " " + title + " ", self.color(2) | curses.A_BOLD, mw - 4)
        page = mh - 4
        self.app.state.modal_max = (
            max(0, len(lines) - 1) if kind in ("menu", "confirm") else max(0, len(lines) - page)
        )
        self.app.state.modal_index = min(self.app.state.modal_index, self.app.state.modal_max)
        offset = (
            max(0, self.app.state.modal_index - page + 1)
            if kind in ("menu", "confirm")
            else self.app.state.modal_index
        )
        if kind in ("menu", "confirm"):
            for i, line in enumerate(lines[offset : offset + page]):
                idx = i + offset
                style = self.color(2) if idx == self.app.state.modal_index else curses.A_REVERSE
                self.put(
                    y + 2 + i,
                    x + 2,
                    ("› " if idx == self.app.state.modal_index else "  ") + line,
                    style,
                    mw - 4,
                )
        else:
            self.app.viewer.render_text_surface(
                "modal", content, x + 4, y + 2, mw - 6, page, offset, curses.A_REVERSE
            )
        footer = (
            "↑↓ scroll · Enter choose · Esc close"
            if kind in ("menu", "confirm")
            else "Drag select · c copy · C copy all · L links · ↑↓ scroll · Esc close"
        )
        if kind == "detail":
            footer = "Drag select · c copy · C all · L links · a actions · y permalink · Esc"
        if self.app.state.copy_notice:
            footer = self.app.state.copy_notice
        self.put(y + mh - 1, x + 2, footer, self.color(2), mw - 4)
