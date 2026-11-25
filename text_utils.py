# SPDX-License-Identifier: Apache-2.0
"""Terminal-safe text and display width helpers."""

import re
import unicodedata


def clean(value):
    """Never interpret control sequences from GitHub content in the terminal."""
    return "".join(
        c if c in "\n\t" or not unicodedata.category(c).startswith("C") else ""
        for c in str(value or "")
    ).replace("\t", "    ")


def label_names(labels):
    if isinstance(labels, str):
        return [labels]
    if not isinstance(labels, list):
        return []
    return [
        str(label.get("name") or "") if isinstance(label, dict) else str(label)
        for label in labels
        if label is not None
    ]


def cell_width(text):
    return sum(
        0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1
        for c in text
    )


def clip(text, width):
    out, used = ([], 0)
    for c in clean(text).replace("\n", " "):
        size = cell_width(c)
        if used + size > width:
            break
        out.append(c)
        used += size
    return "".join(out)


def canonical(value: str) -> str:
    """Normalize GitHub field names for matching, without changing their display names."""

    return re.sub(r"[^a-z0-9]", "", value.lower())


def names(values, field="name"):
    if isinstance(values, str):
        values = [values]
    return [
        str(value.get(field) or "") if isinstance(value, dict) else str(value)
        for value in values or []
        if value
    ]
