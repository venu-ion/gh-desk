# SPDX-License-Identifier: Apache-2.0
"""Workspace component; dependencies are explicit through its application context."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from demo import demo_rows
from sync import Sync

if TYPE_CHECKING:
    from application import App


class Workspace:
    def __init__(self, app: App):
        self.app = app

    def cache_key(self):
        return json.dumps(
            dict(
                tab=self.app.state.tab,
                owner=self.app.args.owner,
                repo=self.app.state.repo if self.app.state.tab in (1, 2, 3) else None,
                state=self.app.state.issue_state,
                limit=self.app.args.limit,
                project=self.app.state.project["id"] if self.app.state.project else None,
            ),
            sort_keys=True,
        )

    def apply_local(self, rows):
        return self.app.store.overlay(self.app.state.view_key, rows) if self.app.store else rows

    def load(self, force=False):
        self.app.state.generation += 1
        self.app.state.detail_generation += 1
        self.app.state.loading, self.app.state.error, self.app.state.detail = (True, "", "")
        self.app.state.snapshot = self.app.navigation.identity(self.app.navigation.current())
        self.app.state.modal = None
        self.app.state.view_key = self.cache_key()
        tab, repo, state, key = (
            self.app.state.tab,
            self.app.state.repo,
            self.app.state.issue_state,
            self.app.state.view_key,
        )
        project = dict(self.app.state.project) if self.app.state.project else None
        cached, fetched = self.app.store.get(key) if self.app.store else (None, 0)
        if self.app.store:
            self.app.state.rows = self.apply_local(cached or [])
        if cached is not None:
            identities = [
                self.app.navigation.identity(row) for row in self.app.navigation.visible()
            ]
            if self.app.state.snapshot in identities:
                self.app.state.selected = identities.index(self.app.state.snapshot)
                if self.app.navigation.board_active():
                    self.app.state.board_status = self.app.navigation.item_status(
                        self.app.navigation.visible()[self.app.state.selected]
                    )
            self.app.state.loading = False
            self.app.state.message = (
                "Local snapshot · "
                + time.strftime("%H:%M", time.localtime(fetched))
                + " · r refresh · S sync · o outbox"
            )
            self.request_detail()
        if not self.app.args.demo and self.app.args.offline:
            self.app.state.loading = False
            self.app.state.message = "Offline · local data · edits saved to outbox · S when online"
            return
        if cached is not None and (not force) and (time.time() - fetched < 60):
            return
        self.app.state.loading = cached is None and (not self.app.state.rows)

        def fetch():
            rows = (
                demo_rows(tab, project)
                if self.app.args.demo
                else self.app.gh.listing(
                    tab, self.app.args.owner, repo, state, self.app.args.limit, project
                )
            )
            if self.app.store:
                self.app.store.put(key, rows)
                if tab == 4 and (not project):
                    self.app.store.put("project-catalog:" + (self.app.args.owner or "@me"), rows)
                if project:
                    self.app.launch("prefetch", lambda: self.app.metadata.project_fields(project))
            return rows

        self.app.launch("list", fetch, self.app.state.generation)

    def start_sync(self):
        if self.app.args.demo or self.app.state.syncing:
            return
        if self.app.args.offline:
            self.app.state.message = (
                "Offline mode: restart without --offline to sync. Your edits are saved."
            )
            return
        self.app.state.syncing = True
        self.app.state.next_sync = time.monotonic() + 30
        self.app.launch("sync", lambda: Sync(self.app.store, self.app.gh).run())

    def request_detail(self):
        self.app.state.detail_generation += 1
        self.app.state.detail, self.app.state.scroll, self.app.state.readme_due = ("", 0, None)
        row = self.app.navigation.current()
        if not row or self.app.state.tab != 0 or self.app.args.demo:
            return
        repo = row["nameWithOwner"]
        data, fetched = self.app.store.get("readme:" + repo)
        self.app.state.detail = data or (
            "README not cached. Connect to fetch it." if self.app.args.offline else ""
        )
        if not self.app.args.offline and (data is None or time.time() - fetched > 300):
            self.app.state.readme_due = (
                time.monotonic() + 0.2,
                repo,
                self.app.state.detail_generation,
            )

    def fetch_readme_if_due(self):
        if not self.app.state.readme_due or time.monotonic() < self.app.state.readme_due[0]:
            return
        _, repo, generation = self.app.state.readme_due
        self.app.state.readme_due = None

        def readme():
            data = self.app.gh.run(
                [
                    "api",
                    f"repos/{repo}/readme",
                    "--header",
                    "Accept: application/vnd.github.raw+json",
                ]
            )
            self.app.store.put("readme:" + repo, data)
            return data

        self.app.launch("detail", readme, generation)
