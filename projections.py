# SPDX-License-Identifier: Apache-2.0
"""Pure local previews. Each operation can change only its own domain fields."""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from typing import Any

from mutations import (
    Comment,
    CreateIssue,
    DateChange,
    JobStatus,
    MembershipChange,
    Mutation,
    ProjectAdd,
    ProjectRemove,
    StateChange,
    StatusChange,
    parse_mutation,
)
from text_utils import canonical

Row = dict[str, Any]


@dataclass(frozen=True)
class ViewContext:
    tab: int
    repo: str | None = None
    project: str | None = None
    state: str = "open"


def _issue_match(operation: Mutation, view: ViewContext) -> bool:
    return operation.repo == view.repo and operation.tab == view.tab


def _linked_match(row: Row, operation: Comment | MembershipChange) -> bool:
    url = (row.get("content") or {}).get("url") or ""
    match = re.fullmatch(r"https://([^/]+)/([\w.-]+/[\w.-]+)/(issues|pull)/(\d+)/?(?:[?#].*)?", url)
    return bool(
        match
        and match[1] == (operation.hostname or os.environ.get("GH_HOST", "github.com"))
        and match[2] == operation.repo
        and match[4] == str(operation.identity)
    )


def _pending(row: Row, status: str) -> None:
    row["_pending"] = status


def _placeholder(job: Row, operation: CreateIssue | ProjectAdd, waiting: bool) -> Row:
    url = operation.result_url if isinstance(operation, CreateIssue) else operation.url
    url = url or ""
    return dict(
        id="local-" + job["id"],
        title=operation.title or "Adding " + url,
        status="",
        repository=operation.repo or "",
        content=dict(
            type="Issue",
            body=operation.body or "",
            url=url,
            number=url.rsplit("/", 1)[-1] if url else "",
        ),
        _local=True,
        _pending="link pending" if waiting else job["status"],
    )


def project_rows(
    view: ViewContext, rows: list[Row], jobs: list[Row], fetched: float = 0
) -> list[Row]:
    """Return a new view without mutating the remote snapshot or queued payloads."""
    result = copy.deepcopy(rows)
    active_parents = {
        job["payload"].get("parent")
        for job in jobs
        if job["status"] not in (JobStatus.DONE, JobStatus.ARCHIVED)
    }
    for job in jobs:
        if job["status"] == JobStatus.ARCHIVED:
            continue
        try:
            operation = parse_mutation(job["payload"])
        except ValueError:
            # Invalid legacy jobs remain inspectable in the outbox. A read-only
            # projection never discards or attempts to execute an unknown payload.
            continue
        waiting = (
            isinstance(operation, CreateIssue)
            and bool(operation.project)
            and job["id"] in active_parents
        )
        if job["status"] == JobStatus.DONE and fetched > job["updated"] and not waiting:
            continue
        if isinstance(operation, (CreateIssue, ProjectAdd)):
            in_project = bool(
                view.project
                and view.tab == 4
                and operation.project
                and operation.project["id"] == view.project
            )
            url = operation.result_url if isinstance(operation, CreateIssue) else operation.url
            if in_project:
                if isinstance(operation, ProjectAdd) and operation.parent:
                    continue
                if not any(url and (row.get("content") or {}).get("url") == url for row in result):
                    result.insert(0, _placeholder(job, operation, waiting))
            elif isinstance(operation, CreateIssue) and _issue_match(operation, view):
                if not any(url and row.get("url") == url for row in result):
                    result.insert(
                        0,
                        dict(
                            number="local-" + job["id"][:6],
                            title=operation.title,
                            body=operation.body,
                            state="OPEN",
                            labels=[],
                            author={},
                            _local=True,
                        ),
                    )
            continue
        if isinstance(operation, ProjectRemove):
            if view.tab == 4 and view.project == operation.project["id"]:
                result = [
                    row for row in result if (row.get("content") or {}).get("url") != operation.url
                ]
            continue
        if isinstance(operation, StateChange) and _issue_match(operation, view) and operation.row:
            if not any(str(row.get("number")) == str(operation.identity) for row in result):
                result.append(copy.deepcopy(operation.row))
        for row in result:
            if isinstance(operation, (StatusChange, DateChange)):
                matches = (
                    view.tab == 4
                    and view.project == operation.project["id"]
                    and row.get("id") == operation.identity
                )
            elif (
                isinstance(operation, (Comment, MembershipChange))
                and view.tab == 4
                and view.project
            ):
                matches = _linked_match(row, operation)
            elif isinstance(operation, (StateChange, Comment, MembershipChange)):
                matches = _issue_match(operation, view) and str(row.get("number")) == str(
                    operation.identity
                )
            else:
                matches = False
            if not matches:
                continue
            _pending(row, job["status"])
            if isinstance(operation, StateChange):
                row["state"] = operation.desired
            elif isinstance(operation, StatusChange):
                row["status"] = operation.desired
            elif isinstance(operation, DateChange):
                key = next(
                    (key for key in row if canonical(key) == canonical(operation.field_name)),
                    operation.field_name,
                )
                row[key] = operation.desired
            elif isinstance(operation, MembershipChange):
                attribute = "login" if operation.field == "assignees" else "name"
                values = [
                    str(value.get(attribute) or "") if isinstance(value, dict) else str(value)
                    for value in row.get(operation.field, [])
                ]
                if operation.desired and operation.value not in values:
                    values.append(operation.value)
                elif not operation.desired:
                    values = [value for value in values if value != operation.value]
                row[operation.field] = [{attribute: value} for value in values]
            elif isinstance(operation, Comment):
                destination = row.setdefault("content", {}) if view.tab == 4 else row
                destination["body"] = (
                    (destination.get("body") or "")
                    + "\n\n── Local comment ("
                    + job["status"]
                    + ") ──\n"
                    + operation.body
                )
    if view.tab in (1, 2) and view.state != "all":
        result = [row for row in result if row.get("state", "").lower() == view.state]
    return result
