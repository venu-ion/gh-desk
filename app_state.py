# SPDX-License-Identifier: Apache-2.0
"""Explicit UI state. Components never create attributes on one another."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from terminal_input import TerminalInput


@dataclass
class Options:
    owner: str | None = None
    repo: str | None = None
    limit: int = 100
    offline: bool = False
    demo: bool = False
    data_dir: str = str(Path.home() / ".local/share/gh-desk")


@dataclass
class UIState:
    tab: int = 0
    repo: str | None = None
    project: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    selected: int = 0
    top: int = 0
    query: str = ""
    issue_state: str = "open"
    focus: str = "list"
    scroll: int = 0
    message: str = ""
    error: str = ""
    loading: bool = False
    generation: int = 0
    detail_generation: int = 0
    detail: str = ""
    detail_cache: dict[str, str] = field(default_factory=dict)
    modal: tuple[str, str, Any] | None = None
    modal_index: int = 0
    modal_max: int = 0
    modal_box: tuple[int, int, int, int] = (0, 0, 0, 0)
    hitboxes: list[Any] = field(default_factory=list)
    running: bool = True
    busy: bool = False
    height: int = 10
    split: int = 25
    snapshot: str | int | None = None
    syncing: bool = False
    next_sync: float = 0
    readme_due: tuple[float, str, int] | None = None
    view_key: str = ""
    status_filter: str | None = None
    board_status: str | None = None
    board_enabled: bool = True
    board_offsets: dict[str, int] = field(default_factory=dict)
    board_hits: list[Any] = field(default_factory=list)
    card_lines: int = 7
    card_stride: int = 8
    list_stride: int = 1
    colors: bool = False
    actions_permalink: str | None = None
    item_detail_id: str | int | None = None
    item_detail_permalink: str | None = None
    copy_notice: str = ""
    terminal_input: TerminalInput = field(default_factory=TerminalInput)
    mouse_protocol_enabled: bool = False
    text_documents: dict[str, Any] = field(default_factory=dict)
    text_surfaces: dict[str, Any] = field(default_factory=dict)
    text_selection: tuple[str, int, int] | None = None
    text_dragging: bool = False
    text_drag_surface: str | None = None
    text_anchor: int = 0
