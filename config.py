# SPDX-License-Identifier: Apache-2.0
"""Optional local TOML settings; credentials always remain managed by gh."""

from __future__ import annotations

import argparse
import os
import re
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app_state import Options

_ALLOWED = {"owner", "repo", "limit", "offline", "data_dir"}


def default_config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gh-desk/config.toml"


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            values = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Cannot read config {path}: {exc}") from exc
    unknown = values.keys() - _ALLOWED
    if unknown:
        # Name the fields, never their values (which might accidentally contain a secret).
        raise ValueError(
            "Unsupported config fields: "
            + ", ".join(sorted(unknown))
            + ". Credentials belong in gh auth login."
        )
    for field in ("owner", "repo", "data_dir"):
        if field in values and (not isinstance(values[field], str) or not values[field].strip()):
            raise ValueError(
                f"Config {field} must be a nonempty string; omit it to use the default."
            )
    if "limit" in values and type(values["limit"]) is not int:
        raise ValueError("Config limit must be an integer.")
    if "offline" in values and type(values["offline"]) is not bool:
        raise ValueError("Config offline must be true or false.")
    if "data_dir" in values:
        directory = Path(values["data_dir"]).expanduser()
        if not directory.is_absolute():
            directory = path.parent / directory
        values["data_dir"] = str(directory.resolve())
    return values


def parse_options(argv: list[str] | None = None, *, local_config: Path | None = None) -> Options:
    parser = argparse.ArgumentParser(
        description="A local-first GitHub terminal workbench powered by gh."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--config", type=Path, help="Read settings from a specific TOML file")
    group.add_argument(
        "--no-config", action="store_true", help="Ignore all local config files and GH_DESK_CONFIG"
    )
    parser.add_argument("--owner", help="GitHub user or organization (default: gh account)")
    parser.add_argument("--repo", help="Starting repository, OWNER/REPO")
    parser.add_argument("--limit", type=int, help="Maximum fetched items per view (default: 100)")
    parser.add_argument(
        "--offline",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use cached data and queue edits without networking",
    )
    parser.add_argument("--data-dir", help="Local database and drafts directory")
    parser.add_argument(
        "--demo", action="store_true", help="Sample workspace; no account data or writes"
    )
    cli = vars(parser.parse_args(argv))
    explicit = cli.pop("config")
    disabled = cli.pop("no_config")
    defaults = asdict(Options())
    defaults["data_dir"] = str(
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "gh-desk"
    )
    try:
        if not disabled and not cli["demo"]:
            environment = os.environ.get("GH_DESK_CONFIG")
            chosen = explicit or (Path(environment) if environment else None)
            if chosen is not None:
                defaults.update(_load(chosen.expanduser()))
            else:
                # Machine settings load first, repo-local settings override them.
                for candidate in (
                    default_config_path(),
                    local_config or Path(__file__).with_name("config.local.toml"),
                ):
                    if candidate.is_file():
                        defaults.update(_load(candidate))
        defaults.update({key: value for key, value in cli.items() if value is not None})
        options = Options(**defaults)
        if not 1 <= options.limit <= 1000:
            raise ValueError("--limit must be between 1 and 1000")
        if options.owner and not re.fullmatch(r"[\w-]+", options.owner):
            raise ValueError("owner must be a GitHub login")
        if options.repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", options.repo):
            raise ValueError("repo must be OWNER/REPO")
        options.data_dir = str(Path(options.data_dir).expanduser())
        return options
    except ValueError as exc:
        parser.error(str(exc))
        raise AssertionError("argparse.error must exit") from exc
