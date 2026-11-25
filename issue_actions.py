# SPDX-License-Identifier: Apache-2.0
"""IssueActions component; dependencies are explicit through its application context."""

from __future__ import annotations

import datetime
import os
import re
from typing import TYPE_CHECKING

from models import Action
from text_utils import canonical, label_names, names

if TYPE_CHECKING:
    from application import App


class IssueActions:
    def __init__(self, app: App):
        self.app = app

    def menu_request(self, fetch, show):
        if self.app.args.demo:
            self.app.state.modal = (
                "text",
                "Demo mode",
                "Metadata editing requires your real gh account. Restart without --demo.",
            )
            return
        self.app.state.busy = True
        self.app.state.modal = (
            "text",
            "Loading actions",
            "Loading metadata. Cached data is used when available.",
        )
        self.app.state.modal_index = 0
        self.app.launch("menu_data", fetch, show)

    def edit_people_or_labels(self, target, field):

        def fetch():
            meta = self.app.metadata.issue_metadata(target)
            catalog = names(meta.get(field), "login" if field == "assignees" else "name")
            warning = ""
            if field == "labels":
                cached, warning = self.app.metadata.label_catalog(target)
                catalog = list(dict.fromkeys(catalog + names(cached)))
            return (meta, catalog, warning)

        self.menu_request(fetch, lambda data: self.people_labels_menu(target, field, *data))

    def people_labels_menu(self, target, field, meta, catalog, warning=""):
        current = set(names(meta.get(field), "login" if field == "assignees" else "name"))
        for job in self.app.store.jobs():
            p = job["payload"]
            if (
                p["kind"] == "membership"
                and p["repo"] == target["repo"]
                and (str(p["identity"]) == str(target["number"]))
                and (p["field"] == field)
            ):
                (current.add if p["desired"] else current.discard)(p["value"])
        singular = "assignee" if field == "assignees" else "label"

        def change(value):
            value = value.strip()
            if field == "assignees":
                value = value.lstrip("@")
                if not re.fullmatch("[A-Za-z0-9][A-Za-z0-9-]*", value):
                    self.app.state.modal = (
                        "text",
                        "Invalid username",
                        "Enter a GitHub login, for example example-user. Use your login rather than @me.",
                    )
                    return
            if not value or "," in value:
                self.app.state.modal = (
                    "text",
                    "Invalid " + singular,
                    "Enter one nonempty value without a comma.",
                )
                return
            base = value in current
            desired = not base
            verb = "Add" if desired else "Remove"
            flag = "--" + ("add-" if desired else "remove-") + singular
            context = dict(
                kind="membership",
                repo=target["repo"],
                tab=target["tab"],
                identity=target["number"],
                field=field,
                value=value,
                base=base,
                desired=desired,
                target=target["cli_repo"] + ":" + str(target["number"]) + ":" + field + ":" + value,
            )
            if target.get("hostname"):
                context["hostname"] = target["hostname"]
            self.app.actions.review(
                Action(
                    f"{verb} {singular}: {value}",
                    [
                        target["command"],
                        "edit",
                        str(target["number"]),
                        "--repo",
                        target["cli_repo"],
                        flag,
                        value,
                    ],
                    context=context,
                )
            )

        def typed():
            value = self.app.input.prompt(
                "GitHub login" if field == "assignees" else "Existing label name"
            )
            if value:
                change(value)

        entries = [
            ("Add " + singular + " by " + ("username…" if field == "assignees" else "name…"), typed)
        ]
        entries += [
            (("[x] " if value in current else "[ ] ") + value, lambda value=value: change(value))
            for value in sorted(set(catalog) | current)
        ]
        if warning:
            self.app.state.message = (
                "Label catalog unavailable; cached labels and typed names still work: " + warning
            )
        self.app.state.modal, self.app.state.modal_index = (
            (
                "menu",
                "Assignees" if field == "assignees" else "Labels · select to add/remove",
                entries,
            ),
            0,
        )

    def edit_due_date(self, project, row):
        project, row = (dict(project), dict(row))

        def fetch():
            fields = self.app.metadata.date_fields(project)
            if not self.app.args.offline and fields:
                from sync import Sync

                values = Sync(self.app.store, self.app.gh).date_values(row["id"])
                for field in fields:
                    self.app.store.put(
                        "item-date:" + project["id"] + ":" + row["id"] + ":" + field["id"],
                        values.get(field["id"], ""),
                    )
            return fields

        self.menu_request(fetch, lambda fields: self.due_date_menu(project, row, fields))

    def due_date_menu(self, project, row, fields):
        if not fields:
            self.app.state.modal = (
                "text",
                "No date field",
                "This Project has no date field. Add a Date field such as Due date to the Project, then refresh.",
            )
            return

        def edit(field):
            cache_key = "item-date:" + project["id"] + ":" + row["id"] + ":" + field["id"]
            base, _ = self.app.store.get(cache_key)
            if base is None:
                base = next(
                    (
                        str(v or "")
                        for k, v in row.items()
                        if canonical(k) == canonical(field["name"])
                    ),
                    "",
                )
            value = self.app.input.prompt(field["name"] + " YYYY-MM-DD (blank clears)", base)
            if value is None:
                return
            value = value.strip()
            if value:
                try:
                    if datetime.date.fromisoformat(value).isoformat() != value:
                        raise ValueError()
                except ValueError:
                    self.app.state.modal = (
                        "text",
                        "Invalid date",
                        "Use a real calendar date in YYYY-MM-DD format, for example 2026-12-15.",
                    )
                    return
            args = [
                "project",
                "item-edit",
                "--id",
                row["id"],
                "--project-id",
                project["id"],
                "--field-id",
                field["id"],
            ]
            args += ["--date", value] if value else ["--clear"]
            context = dict(
                kind="date",
                project=project,
                identity=row["id"],
                field_id=field["id"],
                field_name=field["name"],
                base=base,
                desired=value,
                target=project["id"] + ":" + row["id"] + ":" + field["id"],
            )
            self.app.actions.review(
                Action(
                    ("Set " if value else "Clear ")
                    + field["name"]
                    + (" to " + value if value else ""),
                    args,
                    context=context,
                )
            )

        ordered = sorted(
            fields,
            key=lambda f: (
                0 if canonical(f["name"]) in ("duedate", "targetdate") else 1,
                f["name"],
            ),
        )
        if len(ordered) == 1:
            edit(ordered[0])
        else:
            self.app.state.modal, self.app.state.modal_index = (
                (
                    "menu",
                    "Choose Project date field",
                    [(f["name"], lambda f=f: edit(f)) for f in ordered],
                ),
                0,
            )

    def edit_projects(self, target, dates=False):

        def fetch():
            memberships = self.app.metadata.project_memberships(target)
            return (memberships, [] if dates else self.app.metadata.project_catalog())

        self.menu_request(fetch, lambda data: self.projects_menu(target, *data, dates=dates))

    def projects_menu(self, target, memberships, catalog, dates=False):
        attached = {item["project"]["id"]: item for item in memberships}
        projects = {p["id"]: p for p in catalog}
        projects.update({item["project"]["id"]: item["project"] for item in memberships})
        pending = {
            j["payload"]["project"]["id"]: j
            for j in self.app.store.jobs()
            if j["payload"]["kind"] in ("add", "project_remove")
            and j["payload"].get("url") == self.target_url(target)
            and j["payload"].get("project")
        }

        def choose(project):
            if project["id"] in pending and (not dates):
                self.app.state.modal = (
                    "text",
                    "Project edit pending",
                    "Resolve the existing Project edit in the outbox (o) before changing this membership again.",
                )
                return
            item = attached.get(project["id"])
            if dates:
                self.edit_due_date(project, dict(id=item["id"]))
                return
            owner = (project.get("owner") or {}).get("login") or self.app.args.owner or "@me"
            if item:
                args = [
                    "project",
                    "item-delete",
                    str(project["number"]),
                    "--owner",
                    owner,
                    "--id",
                    item["id"],
                ]
                context = dict(
                    kind="project_remove",
                    project=project,
                    url=self.target_url(target),
                    base=True,
                    desired=False,
                    repo=target["repo"],
                    tab=target["tab"],
                    identity=target["number"],
                    target=project["id"] + ":" + self.target_url(target),
                )
                label = "Remove from " + project["title"]
            else:
                args = [
                    "project",
                    "item-add",
                    str(project["number"]),
                    "--owner",
                    owner,
                    "--url",
                    self.target_url(target),
                ]
                context = dict(
                    kind="add",
                    project=project,
                    url=self.target_url(target),
                    repo=target["repo"],
                    tab=target["tab"],
                    target=project["id"] + ":" + self.target_url(target),
                )
                label = "Add to " + project["title"]
            self.app.actions.review(Action(label, args, context=context))

        selected = [p for p in projects.values() if not dates or p["id"] in attached]
        entries = [
            (
                (
                    "[pending] "
                    if p["id"] in pending and (not dates)
                    else "[x] "
                    if p["id"] in attached
                    else "[ ] "
                )
                + p["title"]
                + " · "
                + str(p["number"]),
                lambda p=p: choose(p),
            )
            for p in selected
        ]
        if not entries:
            self.app.state.modal = (
                "text",
                "No Projects",
                "Add this issue to a Project first."
                if dates
                else "No accessible Projects found for this owner.",
            )
        else:
            self.app.state.modal, self.app.state.modal_index = (
                (
                    "menu",
                    "Choose Project for due date" if dates else "Projects · select to add/remove",
                    entries,
                ),
                0,
            )

    @staticmethod
    def target_url(target):
        host = target.get("hostname") or os.environ.get("GH_HOST", "github.com")
        return f"https://{host}/{target['repo']}/{('issues' if target['command'] == 'issue' else 'pull')}/{target['number']}"

    def date_display_context(self):
        fields, stamp = ([], 0)
        if self.app.store and self.app.state.project:
            fields, _ = self.app.store.get("date-fields:" + self.app.state.project["id"])
            if self.app.state.view_key:
                _, stamp = self.app.store.get(self.app.state.view_key)
        return (fields or [], stamp)

    def display_dates(self, row, context=None):
        fields, snapshot_stamp = context if context is not None else self.date_display_context()
        values = {
            canonical(k): str(v or "") for k, v in row.items() if not isinstance(v, (dict, list))
        }
        for field in fields:
            key = canonical(field["name"])
            if key not in values and self.app.store and row.get("id"):
                cached, stamp = self.app.store.get(
                    "item-date:"
                    + self.app.state.project["id"]
                    + ":"
                    + row["id"]
                    + ":"
                    + field["id"]
                )
                if cached is not None and stamp >= snapshot_stamp:
                    values[key] = cached
        start = next((values[key] for key in ("startdate", "start") if key in values), "")
        due = next(
            (values[key] for key in ("duedate", "targetdate", "enddate", "due") if key in values),
            "",
        )
        return (start, due)

    def display_metadata(self, row, context=None):
        content = row.get("content") or {}
        assignees = names(row.get("assignees", content.get("assignees")), "login")
        labels = label_names(row.get("labels", content.get("labels")))
        start, due = self.display_dates(row, context)
        return [
            "Assignees: " + (", ".join("@" + name.lstrip("@") for name in assignees) or "—"),
            "Labels: " + (", ".join(labels) or "—"),
            "Start: " + (start or "—"),
            "Due: " + (due or "—"),
        ]

    def cached_date_summary(self, row):
        start, due = self.display_dates(row)
        return "\nStart date: " + (start or "—") + "\nDue date: " + (due or "—")
