# SPDX-License-Identifier: Apache-2.0
"""Native clipboard access without shell interpolation or extra Python packages."""

import os
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


class ClipboardError(Exception):
    pass


def https_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return (
        value
        if parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        else None
    )


def item_permalink(tab, row, repo=None):
    if not row:
        return None
    # Linked issue URLs remain valid when a Project-add operation is pending.
    for value in (row.get("url"), (row.get("content") or {}).get("url")):
        url = https_url(value)
        if url:
            return url
    if not row.get("_local") and tab in (1, 2) and repo and str(row.get("number", "")).isdigit():
        host = os.environ.get("GH_HOST", "github.com")
        return https_url(
            f"https://{host}/{repo}/{'issues' if tab == 1 else 'pull'}/{row['number']}"
        )
    return None


def copy_text(text):
    candidates = []
    if sys.platform == "darwin":
        candidates.append(["pbcopy"])
    if os.environ.get("WAYLAND_DISPLAY"):
        candidates.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        candidates.extend(
            [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        )
    errors = []
    for command in candidates:
        executable = shutil.which(command[0])
        if not executable:
            continue
        try:
            result = subprocess.run(
                [executable, *command[1:]],
                input=text,
                text=True,
                capture_output=True,
                timeout=2,
                check=False,
            )
            if result.returncode == 0:
                return
            errors.append(command[0] + " failed")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(command[0] + ": " + str(exc))
    raise ClipboardError(
        "; ".join(errors)
        or "No native clipboard tool is available. Use pbcopy on macOS, wl-copy on Wayland, or xclip/xsel on X11."
    )
