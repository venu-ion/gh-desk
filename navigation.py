# SPDX-License-Identifier: Apache-2.0
"""Navigation component; dependencies are explicit through its application context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from clipboard import item_permalink
from text_utils import label_names

if TYPE_CHECKING:
    from application import App


class Navigation:
    def __init__(self, app: App):
        self.app = app

    def project_items(self):
        return self.app.state.tab == 4 and self.app.state.project is not None

    def board_active(self):
        return self.project_items() and self.app.state.board_enabled

    @staticmethod
    def item_status(row):
        return str(row.get("status") or "Unassigned")

    def visible(self):
        rows = self.app.state.rows
        status = self.app.state.status_filter
        if self.project_items() and status is not None:
            rows = [row for row in rows if self.item_status(row) == status]
        terms = self.app.state.query.casefold().split()
        return (
            [r for r in rows if all(t in self.row_text(r).casefold() for t in terms)]
            if terms
            else rows
        )

    def status_names(self):
        names = []
        if self.project_items() and self.app.store:
            fields, _ = self.app.store.get("fields:" + self.app.state.project["id"])
            for field in (fields or {}).get("fields", []):
                if field.get("name") == "Status":
                    names.extend(option["name"] for option in field.get("options", []))
        for row in self.app.state.rows:
            status = self.item_status(row)
            if status not in names:
                names.append(status)
        if "Unassigned" not in names:
            names.append("Unassigned")
        return list(dict.fromkeys(names))

    def board_groups(self):
        rows = self.visible()
        names = (
            [self.app.state.status_filter]
            if self.app.state.status_filter is not None
            else self.status_names()
        )
        return [
            (name, [(i, row) for i, row in enumerate(rows) if self.item_status(row) == name])
            for name in names
        ]

    def current(self):
        rows = self.visible()
        self.app.state.selected = max(0, min(self.app.state.selected, len(rows) - 1))
        if not rows:
            return None
        if self.board_active():
            groups = self.board_groups()
            names = [name for name, _ in groups]
            if self.app.state.board_status not in names:
                self.app.state.board_status = (
                    self.item_status(rows[self.app.state.selected]) if rows else names[0]
                )
            positions = [
                i for name, items in groups if name == self.app.state.board_status for i, _ in items
            ]
            if not positions:
                return None
            if self.app.state.selected not in positions:
                self.app.state.selected = positions[0]
        return rows[self.app.state.selected] if rows else None

    def filter_status(self):
        if not self.project_items():
            return
        names = self.status_names()
        counts = {
            name: sum(self.item_status(row) == name for row in self.app.state.rows)
            for name in names
        }

        def choose(value):
            self.app.state.status_filter, self.app.state.board_status = (value, value)
            self.app.state.selected, self.app.state.top, self.app.state.scroll = (0, 0, 0)
            self.app.workspace.request_detail()

        entries = [(f"All statuses ({len(self.app.state.rows)})", lambda: choose(None))]
        entries += [(f"{name} ({counts[name]})", lambda name=name: choose(name)) for name in names]
        self.app.state.modal, self.app.state.modal_index = (
            ("menu", "Filter by status", entries),
            0,
        )

    def move_column(self, delta):
        self.current()
        names = [name for name, _ in self.board_groups()]
        index = (
            names.index(self.app.state.board_status) if self.app.state.board_status in names else 0
        )
        self.app.state.board_status = names[max(0, min(index + delta, len(names) - 1))]
        self.current()
        self.app.state.scroll = 0

    @staticmethod
    def identity(row):
        if not row:
            return None
        return (
            row.get("id") or row.get("nameWithOwner") or row.get("databaseId") or row.get("number")
        )

    def row_text(self, row):
        if self.app.state.tab == 0:
            return f"{row.get('nameWithOwner', '')} {row.get('description', '')}"
        if self.app.state.tab == 3:
            return f"{row.get('conclusion') or row.get('status', '')} {row.get('displayTitle', '')} {row.get('headBranch', '')}"
        status = row.get("status", row.get("state", ""))
        number = row.get("number", (row.get("content") or {}).get("number", ""))
        return (
            f"{('#' + str(number) if number else '')} {row.get('title', '')} {status} "
            + " ".join(label_names(row.get("labels")))
        )

    def move(self, delta):
        if self.board_active():
            self.current()
            positions = [
                i
                for name, items in self.board_groups()
                if name == self.app.state.board_status
                for i, _ in items
            ]
            if positions:
                index = positions.index(self.app.state.selected)
                self.app.state.selected = positions[max(0, min(index + delta, len(positions) - 1))]
            return
        old = self.app.state.selected
        self.app.state.selected = max(
            0, min(self.app.state.selected + delta, len(self.visible()) - 1)
        )
        if old != self.app.state.selected:
            self.app.workspace.request_detail()

    def toggle_board(self):
        if self.project_items():
            row = self.current()
            self.app.state.board_enabled = not self.app.state.board_enabled
            if self.app.state.board_enabled and row:
                self.app.state.board_status = self.item_status(row)
            self.app.state.focus, self.app.state.top, self.app.state.scroll = ("list", 0, 0)

    def enter(self):
        row = self.current()
        if not row:
            return
        if self.app.state.tab == 0:
            self.app.state.repo = row["nameWithOwner"]
            self.switch(1)
        elif self.app.state.tab == 4 and (not self.app.state.project):
            self.app.state.project = dict(row)
            (
                self.app.state.status_filter,
                self.app.state.board_status,
                self.app.state.board_offsets,
            ) = (None, None, {})
            (
                self.app.state.rows,
                self.app.state.selected,
                self.app.state.top,
                self.app.state.query,
            ) = ([], 0, 0, "")
            self.app.workspace.load()
        elif self.board_active():
            self.app.state.item_detail_id = self.identity(row)
            self.app.state.item_detail_permalink = item_permalink(
                self.app.state.tab, row, self.app.state.repo
            )
            self.app.state.modal, self.app.state.modal_index = (
                (
                    "detail",
                    "Project item · a actions · n new issue",
                    self.app.renderer.detail_text(),
                ),
                0,
            )
        else:
            self.app.state.focus = "detail"

    def switch(self, tab):
        if tab == self.app.state.tab:
            return
        self.app.state.tab, self.app.state.selected, self.app.state.top, self.app.state.scroll = (
            tab,
            0,
            0,
            0,
        )
        self.app.state.focus = "list"
        self.app.state.rows, self.app.state.query, self.app.state.project = ([], "", None)
        self.app.state.status_filter, self.app.state.board_status, self.app.state.board_offsets = (
            None,
            None,
            {},
        )
        self.app.workspace.load()
