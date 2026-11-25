# SPDX-License-Identifier: Apache-2.0
"""Separate durable account identity from the current credential fingerprint."""

import hashlib
import os
from pathlib import Path


class WorkspaceIdentityError(RuntimeError):
    """Identity could not be verified without risking account isolation."""


def auth_namespace():
    """Local account fingerprint; never persist tokens or invoke a network request."""
    config = Path(
        os.environ.get("GH_CONFIG_DIR")
        or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gh"
    )
    digest = hashlib.sha256()
    for value in (
        os.environ.get("GH_HOST", "github.com"),
        os.environ.get("GH_TOKEN", ""),
        os.environ.get("GITHUB_TOKEN", ""),
        os.environ.get("GH_ENTERPRISE_TOKEN", ""),
        os.environ.get("GITHUB_ENTERPRISE_TOKEN", ""),
        str(config),
    ):
        digest.update(value.encode())
        digest.update(b"\x00")
    try:
        digest.update((config / "hosts.yml").read_bytes())
    except FileNotFoundError:
        pass
    return digest.hexdigest()


def bind_workspace(store, gh, *, offline):
    """Verify the account online; offline only reuse a verified binding.

    Legacy fingerprint workspaces remain usable offline. Only the legacy workspace
    matching the current credentials can be migrated, never an arbitrary account.
    """
    fingerprint = store.credential_namespace
    if offline:
        store.use_account_binding()
        return
    host = os.environ.get("GH_HOST", "github.com").lower()
    user = gh.run(["api", "--hostname", host, "user"], parse=True)
    if (
        not isinstance(user, dict)
        or isinstance(user.get("id"), bool)
        or not isinstance(user.get("id"), int)
        or user["id"] <= 0
    ):
        raise WorkspaceIdentityError(
            "GitHub returned no valid account ID; workspace was not changed."
        )
    if auth_namespace() != fingerprint:
        raise WorkspaceIdentityError(
            "gh credentials changed while verifying the account. Restart gh-desk."
        )
    # GitHub's numeric account ID survives login renames and credential rotation.
    account = "account:" + hashlib.sha256(f"{host}\0{user['id']}".encode()).hexdigest()
    store.bind_account(account)
