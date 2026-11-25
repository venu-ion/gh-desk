# SPDX-License-Identifier: Apache-2.0
"""Interfaces at the operating-system and GitHub boundaries."""

from collections.abc import Sequence
from typing import Any, Protocol


class GitHubClient(Protocol):
    def run(self, args: Sequence[str | int], *, parse: bool = False) -> Any: ...
