# SPDX-License-Identifier: Apache-2.0
"""ActionController component; dependencies are explicit through its application context."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from clipboard import copy_text, https_url, item_permalink
from models import Action
from sync import Sync

if TYPE_CHECKING:
    from application import App


class ActionController:
    def __init__(self, app: App):
        self.app = app

    def comment_target(self, row):
        if not row or row.get("_local"):
            return None
        if self.app.state.tab in (1, 2):
            return dict(
                command="issue" if self.app.state.tab == 1 else "pr",
                number=row["number"],
                repo=self.app.state.repo,
                cli_repo=self.app.state.repo,
                tab=self.app.state.tab,
                snapshot=dict(row),
            )
        if self.app.navigation.project_items():
            content = row.get("content") or {}
            match = re.fullmatch(
                "https://([^/]+)/([\\w.-]+)/([\\w.-]+)/(issues|pull)/(\\d+)/?(?:[?#].*)?",
                content.get("url") or "",
            )
            if match:
                host, owner, repo, kind, number = match.groups()
                repo = owner + "/" + repo
                return dict(
                    command="issue" if kind == "issues" else "pr",
                    number=int(number),
                    repo=repo,
                    cli_repo=repo if host == "github.com" else host + "/" + repo,
                    hostname=host,
                    tab=1 if kind == "issues" else 2,
                    snapshot=dict(row),
                )
        return None

    def copy_permalink(self, url=None, project=False):
        if url is None:
            if project:
                url = https_url((self.app.state.project or {}).get("url"))
            else:
                row = self.app.navigation.current()
                url = item_permalink(self.app.state.tab, row, self.app.state.repo)
        url = https_url(url)
        if not url:
            self.app.state.modal, self.app.state.modal_index = (
                (
                    "text",
                    "No permalink yet",
                    "This item has no remote URL yet. Sync a new issue first. To copy the containing Project URL, press Y from the Project board.",
                ),
                0,
            )
            return
        self.app.launch("clipboard", lambda: copy_text(url), url)

    def show_menu(self):
        if self.app.state.busy:
            self.app.state.message = "Wait for the current request to finish."
            return
        row = self.app.navigation.current()
        entries = []
        if self.app.state.tab == 1 and self.app.state.repo:
            entries.append(("New issue…", self.new_issue))
        if self.app.state.tab == 4 and self.app.state.project:
            entries.append(("Filter by status…", self.app.navigation.filter_status))
            entries.append(("Switch board / list", self.app.navigation.toggle_board))
            entries.append(("New issue in this project…", self.new_issue))
            entries.append(("Add issue or pull request by URL…", self.add_item))
        if row and (not row.get("_local")):
            if self.app.state.tab == 0:
                entries.append(("Use repository", self.app.navigation.enter))
            elif self.app.state.tab in (1, 2):
                kind, number = ("issue" if self.app.state.tab == 1 else "pr", str(row["number"]))
                base = [kind]
                if row["state"] in ("OPEN", "CLOSED"):
                    verb = "close" if row["state"] == "OPEN" else "reopen"
                    entries.append(
                        Action(
                            f"{verb.title()} #{number}",
                            base + [verb, number, "--repo", self.app.state.repo],
                            True,
                            context=dict(
                                kind="state",
                                row=dict(row),
                                repo=self.app.state.repo,
                                tab=self.app.state.tab,
                                identity=row["number"],
                                base=row["state"],
                                desired="CLOSED" if verb == "close" else "OPEN",
                                target=self.app.state.repo + ":" + number,
                            ),
                        )
                    )
                target = self.comment_target(row)
                entries.append(("Write a comment…", lambda target=target: self.comment(target)))
                entries.append(
                    Action(
                        "Read conversation",
                        base + ["view", number, "--repo", self.app.state.repo, "--comments"],
                        viewer=True,
                    )
                )
                if self.app.state.tab == 2:
                    entries.append(
                        Action(
                            "Read diff",
                            ["pr", "diff", number, "--repo", self.app.state.repo],
                            viewer=True,
                        )
                    )
                    entries.append(
                        Action(
                            "Check CI status",
                            ["pr", "checks", number, "--repo", self.app.state.repo],
                            viewer=True,
                        )
                    )
                    if row["state"] == "OPEN":
                        entries.append(
                            Action(
                                f"Squash merge #{number}",
                                [
                                    "pr",
                                    "merge",
                                    number,
                                    "--repo",
                                    self.app.state.repo,
                                    "--squash",
                                    "--match-head-commit",
                                    row["headRefOid"],
                                ],
                                True,
                            )
                        )
            elif self.app.state.tab == 3:
                number = str(row["databaseId"])
                entries += [
                    Action(
                        "Read failed logs",
                        ["run", "view", number, "--repo", self.app.state.repo, "--log-failed"],
                        viewer=True,
                    ),
                    Action(
                        "Rerun failed jobs",
                        ["run", "rerun", number, "--repo", self.app.state.repo, "--failed"],
                        True,
                    ),
                ]
                if row.get("status") != "completed":
                    entries.append(
                        Action(
                            "Cancel workflow run",
                            ["run", "cancel", number, "--repo", self.app.state.repo],
                            True,
                        )
                    )
            elif self.app.state.tab == 4:
                target = self.comment_target(row)
                if target:
                    entries.append(("Write a comment…", lambda target=target: self.comment(target)))
                    entries.append(
                        Action(
                            "Read conversation",
                            [
                                target["command"],
                                "view",
                                str(target["number"]),
                                "--repo",
                                target["cli_repo"],
                                "--comments",
                            ],
                            viewer=True,
                        )
                    )
                entries.append(
                    ("Change status…", self.change_status)
                    if self.app.state.project
                    else ("View project items", self.app.navigation.enter)
                )
        target = self.comment_target(row)
        if target:
            entries.append(
                (
                    "Assignees…",
                    lambda target=target: self.app.issue_actions.edit_people_or_labels(
                        target, "assignees"
                    ),
                )
            )
            entries.append(
                (
                    "Labels…",
                    lambda target=target: self.app.issue_actions.edit_people_or_labels(
                        target, "labels"
                    ),
                )
            )
            entries.append(
                ("Projects…", lambda target=target: self.app.issue_actions.edit_projects(target))
            )
            if not self.app.navigation.project_items():
                entries.append(
                    (
                        "Due date in Project…",
                        lambda target=target: self.app.issue_actions.edit_projects(
                            target, dates=True
                        ),
                    )
                )
        if self.app.navigation.project_items() and row and (not row.get("_local")):
            project, item = (dict(self.app.state.project), dict(row))
            entries.append(
                (
                    "Due date…",
                    lambda project=project, item=item: self.app.issue_actions.edit_due_date(
                        project, item
                    ),
                )
            )
        url = item_permalink(self.app.state.tab, row, self.app.state.repo)
        self.app.state.actions_permalink = url
        if url:
            entries.append(("Copy permalink (y)", lambda url=url: self.copy_permalink(url)))
        project_url = https_url((self.app.state.project or {}).get("url"))
        if self.app.navigation.project_items() and project_url:
            entries.append(
                ("Copy Project permalink (Y)", lambda url=project_url: self.copy_permalink(url))
            )
        entries.append(("Refresh from GitHub", lambda: self.app.workspace.load(force=True)))
        entries.append(("Sync local edits", self.app.workspace.start_sync))
        entries.append(("Open outbox", self.outbox))
        self.app.state.modal, self.app.state.modal_index = (("menu", "Actions", entries), 0)

    def execute(self, action):
        if self.app.args.demo:
            self.app.state.modal = (
                "text",
                "Demo mode",
                "This is sample data. No commands that change GitHub are executed.\n\nRun without --demo to use your gh account.",
            )
            return
        if self.app.state.busy:
            return
        self.app.state.modal = None
        if action.viewer:
            key = "output:" + json.dumps(action.args)
            cached, _ = self.app.store.get(key)
            if self.app.args.offline:
                self.app.state.modal = (
                    "text",
                    "Cached output",
                    cached or "This output is not cached yet.",
                )
                return
            self.app.state.busy = True

            def fetch():
                output = self.app.gh.run(action.args)
                self.app.store.put(key, output)
                return output

            self.app.launch("view", fetch)
            return
        payload = self.write_payload(action)
        if payload["kind"] == "online" and self.app.args.offline:
            self.app.state.modal = (
                "text",
                "Online action",
                "Merging and workflow commands need a connection and a fresh confirmation. They are not queued offline.",
            )
            return
        try:
            identifier = self.app.store.enqueue(action.label, payload)
        except (ValueError, OSError) as exc:
            self.app.state.modal = ("text", "Not queued", str(exc))
            return
        self.app.state.message = "Saved locally · o outbox · S sync"
        if (
            payload["kind"] == "create"
            and payload.get("project")
            and self.app.navigation.project_items()
        ):
            self.app.state.status_filter, self.app.state.query, self.app.state.board_status = (
                None,
                "",
                "Unassigned",
            )
        if payload["kind"] == "online":
            self.app.state.syncing = True
            self.app.launch(
                "sync", lambda: Sync(self.app.store, self.app.gh).send_online(identifier)
            )
        else:
            self.app.workspace.load()
            self.app.workspace.start_sync()

    def write_payload(self, action: Action):
        if action.operation is None:
            raise ValueError("Write actions require a validated operation.")
        payload = dict(repo=self.app.state.repo, tab=self.app.state.tab)
        payload.update(action.operation.to_payload())
        return payload

    def outbox(self):
        if not self.app.store:
            return
        jobs = self.app.store.jobs()
        entries = [
            (f"[{job['status']}] {job['label']}", lambda job=job: self.outbox_item(job))
            for job in jobs
        ]
        entries.append(
            ("Sync now (verify uncertain writes; never replay them)", self.app.workspace.start_sync)
        )
        self.app.state.modal, self.app.state.modal_index = (
            ("menu", f"Outbox · {len(jobs)} unresolved", entries),
            0,
        )

    def outbox_item(self, job):

        def inspect():
            self.app.state.modal, self.app.state.modal_index = (
                (
                    "text",
                    "Local edit / remote result",
                    json.dumps(
                        dict(job, history=self.app.store.audit(job["id"])),
                        indent=2,
                        ensure_ascii=False,
                    ),
                ),
                0,
            )

        def archive():
            self.app.store.update(
                job["id"], "archived", job["note"] + "\nArchived by user; local payload retained."
            )
            self.app.workspace.load()

        def retry():
            payload = job["payload"]
            remote, _ = self.app.store.get("remote-before-write:" + job["id"])
            if not remote:
                return
            payload["base"] = remote["value"]
            self.app.store.update(
                job["id"], "pending", "User reviewed conflict and chose local value.", payload
            )
            self.app.workspace.start_sync()

        entries = [
            ("Inspect local edit and sync result", inspect),
            (
                "Archive local edit (retain journal)",
                lambda: self.review_callback("Archive this local edit?", archive),
            ),
        ]
        if job["payload"]["kind"] == "add" and job["status"] in ("uncertain", "pending"):

            def retry_link():
                self.app.store.update(
                    job["id"],
                    "pending",
                    "User requested retry of Project link only; issue is not recreated.",
                )
                self.app.workspace.start_sync()

            entries.append(
                (
                    "Retry adding this existing issue to the Project…",
                    lambda: self.review_callback("Retry Project addition only?", retry_link),
                )
            )
        if job["status"] == "conflict" and job["payload"]["kind"] in (
            "state",
            "status",
            "date",
            "membership",
            "project_remove",
        ):
            entries.append(
                (
                    "Apply local value after reviewing conflict…",
                    lambda: self.review_callback(
                        "Apply local value? Inspect remote value first.", retry
                    ),
                )
            )
        self.app.state.modal, self.app.state.modal_index = (
            ("menu", job["status"] + " · " + job["label"], entries),
            0,
        )

    def review_callback(self, title, callback):
        self.app.state.modal, self.app.state.modal_index = (
            ("confirm", title, [("Cancel", lambda: None), ("Confirm", callback)]),
            0,
        )

    def choose(self):
        kind, title, entries = self.app.state.modal
        if kind in ("text", "detail"):
            self.app.state.modal = None
            return
        entry = entries[self.app.state.modal_index]
        self.app.state.modal = None
        if isinstance(entry, Action):
            if entry.confirm:
                self.app.state.modal = (
                    "confirm",
                    "Confirm: " + entry.label,
                    [("Cancel", lambda: None), (entry.label, lambda: self.execute(entry))],
                )
                self.app.state.modal_index = 0
            else:
                self.execute(entry)
        else:
            entry[1]()

    def new_issue(self):
        if self.app.args.demo:
            self.execute(Action("", []))
            return
        project = dict(self.app.state.project) if self.app.navigation.project_items() else None
        repo = self.app.state.repo
        if project:
            target = self.comment_target(self.app.navigation.current())
            repo = self.app.input.prompt(
                "Repository OWNER/REPO", (target or {}).get("repo") or repo or ""
            )
            if repo is None:
                return
            repo = repo.strip()
        if not repo or not re.fullmatch("[\\w.-]+/[\\w.-]+", repo):
            self.app.state.modal = (
                "text",
                "Repository needed",
                "Enter a repository as OWNER/REPO, for example example-owner/example-repo.",
            )
            return
        title = self.app.input.prompt("Issue title")
        if title and title.strip():
            body = self.app.input.editor("New issue")
            if body is not None:
                context = dict(kind="create", repo=repo, tab=1, title=title.strip(), body=body)
                if project:
                    context.update(project=project, project_owner=self.app.args.owner or "@me")
                label = (
                    "Create issue and add to " + project.get("title", "Project")
                    if project
                    else "Create issue"
                )
                self.review(
                    Action(
                        label,
                        [
                            "issue",
                            "create",
                            "--repo",
                            repo,
                            "--title",
                            title.strip(),
                            "--body",
                            body,
                        ],
                        context=context,
                    )
                )

    def comment(self, target=None):
        if self.app.args.demo:
            self.execute(Action("", []))
            return
        target = target or self.comment_target(self.app.navigation.current())
        if not target:
            return
        body = self.app.input.editor("Comment")
        if body:
            context = dict(
                kind="comment",
                identity=target["number"],
                repo=target["repo"],
                tab=target["tab"],
                body=body,
            )
            if target.get("hostname"):
                context["hostname"] = target["hostname"]
            self.review(
                Action(
                    "Post comment",
                    [
                        target["command"],
                        "comment",
                        str(target["number"]),
                        "--repo",
                        target["cli_repo"],
                        "--body",
                        body,
                    ],
                    context=context,
                )
            )

    def review(self, action):
        self.app.state.modal, self.app.state.modal_index = (
            (
                "confirm",
                action.label + "?",
                [("Cancel", lambda: None), (action.label, lambda: self.execute(action))],
            ),
            0,
        )

    def add_item(self):
        project = dict(self.app.state.project)
        url = self.app.input.prompt("GitHub issue / PR URL")
        if url is not None:
            url = url.strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
        if url and re.fullmatch("https://[^/]+/[\\w.-]+/[\\w.-]+/(issues|pull)/\\d+", url):
            self.review(
                Action(
                    "Add item",
                    [
                        "project",
                        "item-add",
                        str(project["number"]),
                        "--owner",
                        self.app.args.owner or "@me",
                        "--url",
                        url,
                    ],
                    context=dict(kind="add", project=project, url=url),
                )
            )
        elif url:
            self.app.state.message = "Expected a GitHub issue or pull request URL."

    def change_status(self):
        if self.app.args.demo:
            self.execute(Action("", []))
            return
        self.app.state.busy = True
        project, row = (dict(self.app.state.project), dict(self.app.navigation.current()))
        self.app.launch("fields", lambda: self.app.metadata.project_fields(project), (project, row))

    def status_menu(self, result, context):
        project, row = context
        field = next(
            (f for f in result.get("fields", []) if f.get("name") == "Status" and f.get("options")),
            None,
        )
        if not field:
            self.app.state.modal = (
                "text",
                "No Status field",
                "This project has no single-select field named Status.",
            )
            return
        actions = [
            Action(
                o["name"],
                [
                    "project",
                    "item-edit",
                    "--id",
                    row["id"],
                    "--project-id",
                    project["id"],
                    "--field-id",
                    field["id"],
                    "--single-select-option-id",
                    o["id"],
                ],
                True,
                context=dict(
                    kind="status",
                    project=project,
                    identity=row["id"],
                    base=row.get("status", ""),
                    desired=o["name"],
                    target=project["id"] + ":" + row["id"],
                ),
            )
            for o in field["options"]
        ]
        self.app.state.modal, self.app.state.modal_index = (
            ("menu", "Set status: " + row.get("title", ""), actions),
            0,
        )
