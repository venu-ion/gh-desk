# SPDX-License-Identifier: Apache-2.0
"""Reconcile typed outbox operations without blind retries or terminal coupling."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from identity import auth_namespace
from mutations import (
    Comment,
    CreateIssue,
    DateChange,
    JobStatus,
    MembershipChange,
    Mutation,
    OnlineCommand,
    ProjectAdd,
    ProjectRemove,
    StateChange,
    StatusChange,
    parse_mutation,
)
from ports import GitHubClient

if TYPE_CHECKING:
    from local_store import Store

FIELD_CHANGES = (StateChange, StatusChange, DateChange, MembershipChange, ProjectRemove)


class Sync:
    """An uncertain outcome can be verified, never automatically replayed."""

    def __init__(self, store: Store, gh: GitHubClient):
        self.store, self.gh = store, gh

    def run(self) -> str:
        if auth_namespace() != self.store.credential_namespace:
            raise RuntimeError(
                "gh account/config changed. Restart gh-desk before syncing. Local edits are preserved in their original account workspace."
            )
        seen: set[str] = set()
        while True:
            batch = [job for job in self.store.jobs() if job["id"] not in seen]
            if not batch:
                break
            for job in batch:
                seen.add(job["id"])
                if job["status"] == JobStatus.CONFLICT:
                    continue
                try:
                    operation = parse_mutation(job["payload"])
                except ValueError as exc:
                    self.store.update(
                        job["id"],
                        JobStatus.CONFLICT,
                        f"Invalid queued operation: {exc}. Original payload retained; no command sent.",
                    )
                    continue
                if job["status"] in (JobStatus.SENDING, JobStatus.UNCERTAIN):
                    self.verify(job)
                elif (
                    job["status"] == JobStatus.PENDING
                    and not isinstance(operation, OnlineCommand)
                    and self.store.claim(job["id"])
                ):
                    self.send(job)
        return f"Sync finished · {len(self.store.jobs())} unresolved · o outbox"

    def send_online(self, identifier: str) -> str:
        if auth_namespace() != self.store.credential_namespace:
            raise RuntimeError("gh account changed. Write kept locally; restart before continuing.")
        job = next(job for job in self.store.jobs() if job["id"] == identifier)
        if self.store.claim(identifier):
            self.send(job)
        return "Online action recorded · o outbox for any unresolved result"

    def acknowledge(self, job: dict[str, Any], note: str) -> None:
        operation = parse_mutation(job["payload"])
        if isinstance(operation, MembershipChange):
            host = operation.hostname or os.environ.get("GH_HOST", "github.com")
            key = f"issue-meta:{host}:{operation.repo}:{operation.identity}"
            data, _ = self.store.get(key)
            if data is not None:
                attribute = "login" if operation.field == "assignees" else "name"
                values = [
                    value.get(attribute) if isinstance(value, dict) else str(value)
                    for value in data.get(operation.field, [])
                ]
                values = [value for value in values if value != operation.value] + (
                    [operation.value] if operation.desired else []
                )
                data[operation.field] = [{attribute: value} for value in values]
                self.store.put(key, data)
        elif isinstance(operation, DateChange):
            self.store.put(self._date_key(operation), operation.desired)
        elif isinstance(operation, (ProjectAdd, ProjectRemove)):
            match = re.fullmatch(
                r"https://([^/]+)/([^/]+/[^/]+)/(issues|pull)/(\d+)", operation.url or ""
            )
            if match:
                self.store.expire(f"memberships:issue-meta:{match[1]}:{match[2]}:{match[4]}")
        self.store.update(job["id"], JobStatus.DONE, note)

    @staticmethod
    def _date_key(operation: DateChange) -> str:
        return f"item-date:{operation.project['id']}:{operation.identity}:{operation.field_id}"

    def date_values(self, identity: str) -> dict[str, str]:
        query = """query($id:ID!,$endCursor:String){node(id:$id){... on ProjectV2Item{fieldValues(first:100,after:$endCursor){nodes{... on ProjectV2ItemFieldDateValue{date field{... on ProjectV2Field{id}}}}pageInfo{hasNextPage endCursor}}}}}"""
        pages = self.gh.run(
            [
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                "query=" + query,
                "-f",
                "id=" + identity,
            ],
            parse=True,
        )
        if not pages or any(not (page.get("data") or {}).get("node") for page in pages):
            raise ValueError("Project item is missing or inaccessible; date edit retained locally.")
        return {
            value["field"]["id"]: value["date"]
            for page in pages
            for value in page["data"]["node"]["fieldValues"]["nodes"]
            if value.get("field")
        }

    def remote_value(self, payload: dict[str, Any] | Mutation) -> str | bool | None:
        operation = parse_mutation(payload)
        if isinstance(operation, DateChange):
            value = self.date_values(operation.identity).get(operation.field_id, "")
            self.store.put(self._date_key(operation), value)
            return value
        if isinstance(operation, MembershipChange):
            args = operation.args
            result = self.gh.run(
                [
                    args[0],
                    "view",
                    str(operation.identity),
                    "--repo",
                    args[args.index("--repo") + 1],
                    "--json",
                    operation.field,
                ],
                parse=True,
            )
            host = operation.hostname or os.environ.get("GH_HOST", "github.com")
            cache_key = f"issue-meta:{host}:{operation.repo}:{operation.identity}"
            data, _ = self.store.get(cache_key)
            if data is not None:
                data[operation.field] = result[operation.field]
                self.store.put(cache_key, data)
            attribute = "login" if operation.field == "assignees" else "name"
            return operation.value in [
                value.get(attribute) if isinstance(value, dict) else str(value)
                for value in result[operation.field]
            ]
        if isinstance(operation, ProjectRemove):
            return self.project_contains(operation.to_payload())
        if isinstance(operation, StateChange):
            result = self.gh.run(
                [
                    operation.args[0],
                    "view",
                    str(operation.identity),
                    "--repo",
                    operation.repo or "",
                    "--json",
                    "state",
                ],
                parse=True,
            )
            return str(result["state"])
        if isinstance(operation, StatusChange):
            query = """query($id:ID!,$endCursor:String){node(id:$id){... on ProjectV2{items(first:100,after:$endCursor){nodes{id fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}}}pageInfo{hasNextPage endCursor}}}}}"""
            pages = self.gh.run(
                [
                    "api",
                    "graphql",
                    "--paginate",
                    "--slurp",
                    "-f",
                    "query=" + query,
                    "-f",
                    "id=" + operation.project["id"],
                ],
                parse=True,
            )
            for page in pages:
                for row in (
                    (page.get("data", {}).get("node") or {}).get("items", {}).get("nodes", [])
                ):
                    if row["id"] == operation.identity:
                        return str((row.get("fieldValueByName") or {}).get("name", ""))
            raise ValueError("Project item no longer exists or is inaccessible. Local edit kept.")
        return None

    def project_contains(self, payload: dict[str, Any]) -> bool:
        query = """query($id:ID!,$endCursor:String){node(id:$id){... on ProjectV2{items(first:100,after:$endCursor){nodes{content{... on Issue{url} ... on PullRequest{url}}}pageInfo{hasNextPage endCursor}}}}}"""
        pages = self.gh.run(
            [
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                "query=" + query,
                "-f",
                "id=" + payload["project"]["id"],
            ],
            parse=True,
        )
        if not pages or any(not (page.get("data") or {}).get("node") for page in pages):
            raise ValueError(
                "Cannot read the target Project. Check gh auth refresh -s project and Project access."
            )
        return any(
            (item.get("content") or {}).get("url") == payload["url"]
            for page in pages
            for item in page["data"]["node"].get("items", {}).get("nodes", [])
        )

    def marker_result(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        operation = parse_mutation(payload)
        if not isinstance(operation, (Comment, CreateIssue)) or not operation.marker:
            return None
        endpoint = f"repos/{operation.repo}/issues"
        if isinstance(operation, Comment):
            endpoint += f"/{operation.identity}/comments"
        args = ["api", endpoint, "--method", "GET", "--paginate", "--slurp", "-f", "per_page=100"]
        if operation.hostname:
            args += ["--hostname", operation.hostname]
        if isinstance(operation, CreateIssue):
            args += ["-f", "state=all"]
        pages = self.gh.run(args, parse=True)
        return next(
            (row for page in pages for row in page if operation.marker in (row.get("body") or "")),
            None,
        )

    def marker_exists(self, payload: dict[str, Any]) -> bool:
        return self.marker_result(payload) is not None

    def verify(self, job: dict[str, Any]) -> None:
        try:
            operation = parse_mutation(job["payload"])
            if isinstance(operation, (Comment, CreateIssue)) and operation.marker:
                remote = self.marker_result(job["payload"])
                if remote is not None:
                    if isinstance(operation, CreateIssue):
                        self.store.finish_create(
                            job["id"],
                            remote.get("html_url") or remote.get("url") or "",
                            "Verified remote issue; creation not replayed.",
                        )
                    else:
                        self.acknowledge(job, "Verified remote marker; not replayed.")
            elif (
                isinstance(operation, ProjectAdd)
                and operation.project
                and self.project_contains(operation.to_payload())
            ):
                self.acknowledge(job, "Verified issue is in the Project; add not replayed.")
            elif isinstance(operation, FIELD_CHANGES):
                if self.remote_value(operation) == operation.desired:
                    self.acknowledge(job, "Verified requested remote value; not replayed.")
        except (RuntimeError, ValueError, OSError) as exc:
            # A read failure never authorizes replay. Retain the diagnostic rather
            # than silently hiding why verification could not finish.
            self.store.update(job["id"], job["status"], "Verification failed: " + str(exc))

    def send(self, job: dict[str, Any]) -> None:
        started = False
        try:
            operation = parse_mutation(job["payload"])
            if auth_namespace() != self.store.credential_namespace:
                raise ValueError("gh account changed; restart before syncing.")
            if isinstance(operation, FIELD_CHANGES):
                remote = self.remote_value(operation)
                self.store.put("remote-before-write:" + job["id"], {"value": remote})
                if remote == operation.desired:
                    self.acknowledge(job, "Remote already has requested value.")
                    return
                if remote != operation.base:
                    self.store.update(
                        job["id"],
                        JobStatus.CONFLICT,
                        f"Remote changed. Base: {operation.base!r}; local: {operation.desired!r}; remote: {remote!r}. No write sent.",
                    )
                    return
            if (
                isinstance(operation, ProjectAdd)
                and operation.project
                and self.project_contains(operation.to_payload())
            ):
                self.acknowledge(job, "Issue is already in the Project.")
                return
            started = True
            result = self.gh.run(list(operation.args))
            if isinstance(operation, CreateIssue):
                match = re.search(r"https://[^/\s]+/[\w.-]+/[\w.-]+/issues/\d+", result)
                self.store.finish_create(job["id"], match.group(0) if match else "", result)
            else:
                self.acknowledge(job, result or "GitHub acknowledged the write.")
        except (RuntimeError, ValueError, OSError) as exc:
            self.store.update(
                job["id"], JobStatus.UNCERTAIN if started else JobStatus.PENDING, str(exc)
            )
