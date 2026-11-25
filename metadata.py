# SPDX-License-Identifier: Apache-2.0
"""Cached GitHub metadata queries; contains no terminal/UI state."""

import json
import os
import time

from github import GhError


class Metadata:
    def __init__(self, store, gh, args):
        self.store, self.gh, self.args = (store, gh, args)

    def metadata_key(self, target):
        return f"issue-meta:{target.get('hostname') or os.environ.get('GH_HOST', 'github.com')}:{target['repo']}:{target['number']}"

    def issue_metadata(self, target):
        key = self.metadata_key(target)
        data, fetched = self.store.get(key)
        if data is not None and (self.args.offline or time.time() - fetched < 60):
            return data
        if self.args.offline:
            row = target.get("snapshot") or {}
            return dict(
                labels=row.get("labels") or [],
                assignees=row.get("assignees") or [],
                url=(row.get("content") or {}).get("url") or row.get("url", ""),
            )
        data = self.gh.run(
            [
                target["command"],
                "view",
                str(target["number"]),
                "--repo",
                target["cli_repo"],
                "--json",
                "id,labels,assignees,url",
            ],
            parse=True,
        )
        self.store.put(key, data)
        return data

    def date_fields(self, project):
        key = "date-fields:" + project["id"]
        data, fetched = self.store.get(key)
        if data is not None and (self.args.offline or time.time() - fetched < 300):
            return data
        if self.args.offline:
            raise ValueError(
                "Date-field definitions are not cached. Open Due date once while online, then you can edit dates offline."
            )
        query = "query($id:ID!,$endCursor:String){node(id:$id){... on ProjectV2{fields(first:100,after:$endCursor){nodes{... on ProjectV2Field{id name dataType}}pageInfo{hasNextPage endCursor}}}}}"
        pages = self.gh.run(
            [
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                "query=" + query,
                "-f",
                "id=" + project["id"],
            ],
            parse=True,
        )
        if not pages or any(not (p.get("data") or {}).get("node") for p in pages):
            raise ValueError("Cannot read this Project’s date fields. Check Project permissions.")
        data = [
            field
            for page in pages
            for field in page["data"]["node"]["fields"]["nodes"]
            if field.get("dataType") == "DATE"
        ]
        self.store.put(key, data)
        return data

    def project_memberships(self, target):
        key = "memberships:" + self.metadata_key(target)
        cached, fetched = self.store.get(key)
        if cached is not None and (self.args.offline or time.time() - fetched < 60):
            return cached
        if self.args.offline:
            raise ValueError(
                "Project memberships are not cached. Open Projects for this issue once while online."
            )
        meta = self.issue_metadata(target)
        connection = "projectItems(first:100,after:$endCursor){nodes{id project{id number title url owner{... on User{login} ... on Organization{login}}}}pageInfo{hasNextPage endCursor}}"
        query = (
            "query($id:ID!,$endCursor:String){node(id:$id){... on Issue{"
            + connection
            + "} ... on PullRequest{"
            + connection
            + "}}}"
        )
        args = [
            "api",
            "graphql",
            "--paginate",
            "--slurp",
            "-f",
            "query=" + query,
            "-f",
            "id=" + meta["id"],
        ]
        if target.get("hostname"):
            args += ["--hostname", target["hostname"]]
        pages = self.gh.run(args, parse=True)
        if not pages or any(not (p.get("data") or {}).get("node") for p in pages):
            raise ValueError("Cannot read issue Project memberships. Check Project permissions.")
        cached = [item for page in pages for item in page["data"]["node"]["projectItems"]["nodes"]]
        self.store.put(key, cached)
        return cached

    def project_catalog(self):
        key = "project-catalog:" + (self.args.owner or "@me")
        cached, stamp = self.store.get(key)
        if cached is not None and (self.args.offline or time.time() - stamp < 60):
            return cached
        if self.args.offline:
            for state in ("open", "all", "closed"):
                legacy = json.dumps(
                    dict(
                        tab=4,
                        owner=self.args.owner,
                        repo=None,
                        state=state,
                        limit=self.args.limit,
                        project=None,
                    ),
                    sort_keys=True,
                )
                cached, _ = self.store.get(legacy)
                if cached is not None:
                    return cached
            return []
        cached = self.gh.listing(4, self.args.owner, None, "open", self.args.limit)
        self.store.put(key, cached)
        return cached

    def project_fields(self, project):
        key = "fields:" + project["id"]
        data, fetched = self.store.get(key)
        if data is not None and (self.args.offline or time.time() - fetched < 300):
            return data
        if self.args.offline:
            raise GhError("Project fields are not cached yet. Open this project once while online.")
        result = self.gh.run(
            [
                "project",
                "field-list",
                str(project["number"]),
                "--owner",
                self.args.owner or "@me",
                "--limit",
                "100",
                "--format",
                "json",
            ],
            parse=True,
        )
        self.store.put(key, result)
        return result

    def label_catalog(self, target):
        """Return cached labels and a diagnostic when optional discovery fails."""
        key = "repo-labels:" + target["cli_repo"]
        cached, stamp = self.store.get(key)
        if not self.args.offline and (cached is None or time.time() - stamp > 300):
            try:
                cached = self.gh.run(
                    [
                        "label",
                        "list",
                        "--repo",
                        target["cli_repo"],
                        "--limit",
                        "1000",
                        "--json",
                        "name",
                    ],
                    parse=True,
                )
                self.store.put(key, cached)
            except (RuntimeError, ValueError, OSError) as exc:
                return cached, str(exc)
        return cached, ""
