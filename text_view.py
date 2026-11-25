# SPDX-License-Identifier: Apache-2.0
"""TextViewer component; dependencies are explicit through its application context."""

from __future__ import annotations

import curses
import re
import unicodedata
from typing import TYPE_CHECKING

from clipboard import copy_text
from terminal_input import WHEEL_DOWN
from text_utils import cell_width, clean

if TYPE_CHECKING:
    from application import App

import webbrowser
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class TextLine:
    start: int
    end: int
    text: str


@dataclass
class Link:
    start: int
    end: int
    url: str
    label: str


def browser_url(value):
    if not isinstance(value, str) or any(
        c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        return (
            value
            if parsed.scheme in ("http", "https")
            and parsed.hostname
            and (not parsed.username)
            and (not parsed.password)
            else None
        )
    except ValueError:
        return None


def find_links(text):
    links = []
    for match in re.finditer("!?\\[([^\\]\\n]+)\\]\\(", text):
        position = match.end()
        depth = 1
        while position < len(text) and text[position] != "\n":
            char = text[position]
            if char == "(":
                depth += 1
            if char == ")":
                depth -= 1
                if not depth:
                    break
            position += 1
        if depth:
            continue
        target = text[match.end() : position].split(" ", 1)[0].strip("<>")
        url = browser_url(target)
        if url:
            links.append(Link(match.start(), position + 1, url, match[1]))
    for match in re.finditer("https?://[^\\s<>]+", text):
        if any(link.start <= match.start() < link.end for link in links):
            continue
        value = match[0].rstrip(".,;:!?'\"`]}")
        while value.endswith(")") and value.count(")") > value.count("("):
            value = value[:-1]
        url = browser_url(value)
        if url:
            links.append(Link(match.start(), match.start() + len(value), url, url))
    return sorted(links, key=lambda link: link.start)


class TextDocument:
    def __init__(self, text, width):
        self.text = clean(text)
        self.width = max(1, width)
        self.links = find_links(self.text)
        self.lines = []
        start, used = (0, 0)
        for index, char in enumerate(self.text):
            if char == "\n":
                self.lines.append(TextLine(start, index, self.text[start:index]))
                start, used = (index + 1, 0)
                continue
            size = cell_width(char)
            if used and used + size > self.width:
                self.lines.append(TextLine(start, index, self.text[start:index]))
                start, used = (index, 0)
            used += size
        if start < len(self.text) or not self.lines:
            self.lines.append(TextLine(start, len(self.text), self.text[start:]))

    def index_at(self, line, column):
        row = self.lines[max(0, min(line, len(self.lines) - 1))]
        cells = 0
        for offset, char in enumerate(row.text):
            size = cell_width(char)
            if cells + size > max(0, column):
                return row.start + offset
            cells += size
        return row.end

    def link_at(self, index):
        return next((link for link in self.links if link.start <= index < link.end), None)

    def selection(self, anchor, focus):

        lo, hi = sorted((anchor, focus))
        hi = min(len(self.text), hi + 1)
        while hi < len(self.text) and unicodedata.combining(self.text[hi]):
            hi += 1
        return (lo, hi)


class TextViewer:
    def __init__(self, app: App):
        self.app = app

    def text_document(self, key, text, width):
        documents = self.app.state.text_documents
        previous = documents.get(key)
        if previous is None or previous.width != width or previous.text != text:
            document = TextDocument(text, width)
            if (
                previous is not None
                and previous.text != document.text
                and self.app.state.text_selection
                and (self.app.state.text_selection[0] == key)
            ):
                self.app.state.text_selection = None
                self.app.state.text_dragging = False
            documents[key] = document
        self.app.state.text_documents = documents
        return documents[key]

    def render_text_surface(self, key, text, x, y, width, height, top, style=0):
        document = self.text_document(key, text, width)
        surfaces = self.app.state.text_surfaces
        surfaces[key] = dict(document=document, x=x, y=y, width=width, height=height, top=top)
        self.app.state.text_surfaces = surfaces
        selection = self.app.state.text_selection
        for line, row in enumerate(document.lines[top : top + height]):
            self.app.renderer.put(y + line, x, row.text, style, width)
            for link in document.links:
                lo, hi = (max(row.start, link.start), min(row.end, link.end))
                if lo < hi:
                    self.app.renderer.put(
                        y + line,
                        x + cell_width(document.text[row.start : lo]),
                        document.text[lo:hi],
                        self.app.renderer.color(1) | curses.A_UNDERLINE,
                        width - cell_width(document.text[row.start : lo]),
                    )
            if selection and selection[0] == key:
                lo, hi = (max(row.start, selection[1]), min(row.end, selection[2]))
                if lo < hi:
                    self.app.renderer.put(
                        y + line,
                        x + cell_width(document.text[row.start : lo]),
                        document.text[lo:hi],
                        self.app.renderer.color(2),
                        width - cell_width(document.text[row.start : lo]),
                    )
        return document

    def active_text_surface(self):
        surfaces = self.app.state.text_surfaces
        if self.app.state.modal:
            return (
                ("modal", surfaces["modal"])
                if self.app.state.modal[0] in ("text", "detail") and "modal" in surfaces
                else (None, None)
            )
        if self.app.state.focus == "detail" and (not self.app.navigation.board_active()):
            return ("pane", surfaces["pane"]) if "pane" in surfaces else (None, None)
        return (None, None)

    def copy_view_text(self, text):
        if not text:
            self.app.state.copy_notice = "No text selected · drag text or Ctrl+A, then c"
            return
        self.app.launch("text_clipboard", lambda: copy_text(text), text)

    def open_text_link(self, url):
        url = browser_url(url)
        if not url:
            return

        def open_browser():
            if not webbrowser.open(url, new=2):
                raise RuntimeError("No browser could be opened. Use Copy link instead.")

        self.app.launch("browser", open_browser, url)

    def link_actions(self, link):
        previous, index = (
            self.app.state.modal,
            self.app.state.modal_index if self.app.state.modal else 0,
        )

        def back():
            self.app.state.modal, self.app.state.modal_index = (previous, index)

        self.app.state.modal, self.app.state.modal_index = (
            (
                "menu",
                link.url,
                [
                    ("Open in browser", lambda: self.open_text_link(link.url)),
                    ("Copy link URL", lambda: self.copy_view_text(link.url)),
                    ("Back", back),
                ],
            ),
            0,
        )

    def text_links_menu(self, document):
        previous, index = (
            self.app.state.modal,
            self.app.state.modal_index if self.app.state.modal else 0,
        )

        def back():
            self.app.state.modal, self.app.state.modal_index = (previous, index)

        unique = {}
        for link in document.links:
            unique.setdefault(link.url, link)
        entries = [
            (
                link.label + " · " + link.url if link.label != link.url else link.url,
                lambda link=link: self.link_actions(link),
            )
            for link in unique.values()
        ]
        if not entries:
            self.app.state.copy_notice = "No HTTP links in this text"
            return
        entries.append(("Back to text", back))
        self.app.state.modal, self.app.state.modal_index = (
            ("menu", "Links · choose to open or copy", entries),
            0,
        )

    def text_key(self, key):
        surface_key, surface = self.active_text_surface()
        if surface is None:
            return False
        document = surface["document"]
        selection = self.app.state.text_selection
        selected = selection and selection[0] == surface_key and (selection[1] != selection[2])
        if key == "\x01":
            self.app.state.text_selection = (surface_key, 0, len(document.text))
            return True
        if key in ("c", "\x03") or (key == "y" and selected):
            if key == "\x03" and (not selected):
                return False
            self.copy_view_text(document.text[selection[1] : selection[2]] if selected else "")
            return True
        if key == "C":
            self.copy_view_text(document.text)
            return True
        if key == "L":
            self.text_links_menu(document)
            return True
        if key == "\x1b" and selected:
            self.app.state.text_selection = None
            return True
        return False

    def text_mouse(self, x, y, state):
        key = "modal" if self.app.state.modal else "pane"
        if self.app.state.modal and self.app.state.modal[0] not in ("text", "detail"):
            return False
        surface = self.app.state.text_surfaces.get(key)
        if not surface:
            return False
        if state & (curses.BUTTON4_PRESSED | WHEEL_DOWN):
            return False
        inside = (
            surface["x"] <= x < surface["x"] + surface["width"]
            and surface["y"] <= y < surface["y"] + surface["height"]
        )
        dragging = self.app.state.text_dragging and self.app.state.text_drag_surface == key
        if not inside and (not dragging):
            return False
        document = surface["document"]
        line = surface["top"] + max(0, min(y - surface["y"], surface["height"] - 1))
        column = max(0, min(x - surface["x"], surface["width"]))
        position = document.index_at(line, column)
        link = document.link_at(position) if inside else None
        if not self.app.state.modal:
            self.app.state.focus = "detail"
        if state & (curses.BUTTON3_CLICKED | curses.BUTTON3_PRESSED):
            selected = self.app.state.text_selection
            entries = []
            if selected and selected[0] == key:
                text = document.text[selected[1] : selected[2]]
                entries.append(("Copy selection", lambda text=text: self.copy_view_text(text)))
            if link:
                entries.extend(
                    [
                        ("Open link", lambda link=link: self.open_text_link(link.url)),
                        ("Copy link URL", lambda link=link: self.copy_view_text(link.url)),
                    ]
                )
            entries.append(("Copy all text", lambda: self.copy_view_text(document.text)))
            self.app.state.modal, self.app.state.modal_index = (
                ("menu", "Text actions", entries),
                0,
            )
            return True
        if state & curses.BUTTON1_DOUBLE_CLICKED:
            lo = hi = min(position, max(0, len(document.text) - 1))
            while lo > 0 and (not document.text[lo - 1].isspace()):
                lo -= 1
            while hi < len(document.text) and (not document.text[hi].isspace()):
                hi += 1
            self.app.state.text_selection = (key, lo, hi)
            self.app.state.text_dragging = False
            return True
        if state & curses.BUTTON1_CLICKED:
            self.app.state.text_dragging = False
            if link:
                self.open_text_link(link.url)
            else:
                self.app.state.text_selection = None
            return True
        if state & curses.BUTTON1_PRESSED:
            if not dragging:
                self.app.state.text_anchor = position
                self.app.state.text_drag_surface = key
                self.app.state.text_selection = (key, position, position)
            else:
                lo, hi = document.selection(self.app.state.text_anchor, position)
                self.app.state.text_selection = (key, lo, hi)
            self.app.state.text_dragging = True
            return True
        if state & curses.BUTTON1_RELEASED:
            if dragging:
                if position == self.app.state.text_anchor:
                    self.app.state.text_selection = None
                    if link:
                        self.open_text_link(link.url)
                else:
                    lo, hi = document.selection(self.app.state.text_anchor, position)
                    self.app.state.text_selection = (key, lo, hi)
            self.app.state.text_dragging = False
            return True
        if dragging and state & curses.REPORT_MOUSE_POSITION:
            lo, hi = document.selection(self.app.state.text_anchor, position)
            self.app.state.text_selection = (key, lo, hi)
            return True
        return inside
