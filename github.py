# SPDX-License-Identifier: Apache-2.0
"""All GitHub subprocess execution is isolated from the terminal UI."""

import json
import os
import subprocess

from constants import ISSUE_FIELDS, PR_FIELDS, REPO_FIELDS, RUN_FIELDS
from identity import auth_namespace
from text_utils import clean


class GhError(RuntimeError):
    pass


class GitHub:
    def __init__(self, timeout=35, namespace=None):
        self.timeout, self.namespace = (timeout, namespace)

    def run(self, args, *, parse=False):
        if self.namespace and auth_namespace() != self.namespace:
            raise GhError("gh account/config changed. Restart gh-desk. Local edits are preserved.")
        env = dict(
            os.environ,
            GH_PROMPT_DISABLED="1",
            GH_PAGER="cat",
            PAGER="cat",
            NO_COLOR="1",
            CLICOLOR="0",
        )
        try:
            result = subprocess.run(
                ["gh", *map(str, args)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise GhError("GitHub CLI is missing. Install gh, then run gh auth login.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GhError(
                "gh timed out. Check your connection and press r to retry. A write may have completed; refresh before retrying it."
            ) from exc
        if self.namespace and auth_namespace() != self.namespace:
            raise GhError(
                "gh account changed during this request. Result is unverified; restart gh-desk."
            )
        if result.returncode:
            raise GhError(
                clean(
                    result.stderr.strip()
                    or result.stdout.strip()
                    or f"gh exited {result.returncode}"
                )
            )
        if not parse:
            return clean(result.stdout)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GhError("gh returned invalid JSON. Update GitHub CLI and retry.") from exc

    def listing(self, tab, owner, repo, state, limit, project=None):
        if tab == 0:
            return self.run(
                [
                    "repo",
                    "list",
                    *([owner] if owner else []),
                    "--limit",
                    limit,
                    "--json",
                    REPO_FIELDS,
                ],
                parse=True,
            )
        if tab == 4:
            if project:
                return self.run(
                    [
                        "project",
                        "item-list",
                        project["number"],
                        "--owner",
                        owner or "@me",
                        "--limit",
                        limit,
                        "--format",
                        "json",
                    ],
                    parse=True,
                )["items"]
            return self.run(
                [
                    "project",
                    "list",
                    "--owner",
                    owner or "@me",
                    "--limit",
                    limit,
                    "--format",
                    "json",
                ],
                parse=True,
            )["projects"]
        if not repo:
            return []
        if tab in (1, 2):
            return self.run(
                [
                    "issue" if tab == 1 else "pr",
                    "list",
                    "--repo",
                    repo,
                    "--state",
                    state,
                    "--limit",
                    limit,
                    "--json",
                    ISSUE_FIELDS if tab == 1 else PR_FIELDS,
                ],
                parse=True,
            )
        return self.run(
            ["run", "list", "--repo", repo, "--limit", limit, "--json", RUN_FIELDS], parse=True
        )
