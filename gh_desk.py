#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A local-first GitHub terminal workbench powered by gh."""

import curses
import locale
import os
import shutil

# The launcher delegates to the application composition root.
from application import App
from config import parse_options
from github import GhError
from identity import WorkspaceIdentityError


def main():
    args = parse_options()
    if not args.demo and not args.offline and (not shutil.which("gh")):
        raise SystemExit("GitHub CLI is missing. Install gh and run gh auth login.")
    locale.setlocale(locale.LC_ALL, "")
    try:
        curses.wrapper(lambda screen: App(screen, args).run())
    except (GhError, WorkspaceIdentityError) as exc:
        raise SystemExit(
            f"Account verification failed: {exc}. Use --offline for cached work."
        ) from exc
    except KeyboardInterrupt:
        pass
    except curses.error as exc:
        raise SystemExit(
            f"Terminal unavailable: {exc}. Run gh-desk in an interactive terminal."
        ) from exc
    finally:
        if os.isatty(1):
            os.write(1, b"\x1b[?1002l\x1b[?1006l")


if __name__ == "__main__":
    main()
