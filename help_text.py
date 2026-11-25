# SPDX-License-Identifier: Apache-2.0
"""Keyboard and terminal interaction help shown by gh-desk."""

HELP_TEXT = """1–5          Switch views (or click a tab)
↑↓ / j k     Move selection / scroll focused pane
Tab          Switch list / detail focus
Enter        Use repository / open project / focus detail
/            Filter loaded items; Esc cancels input
Esc          Clear filter / leave project / close popup
: or a       Context actions
n            New issue (Issues view or current Project)
s            Toggle issue/PR state; filter Project status
f            Filter Project items by status (All to clear)
b            Toggle Project board / list
←→ / h l     Move between board columns
Enter        Open selected board card details
r            Refresh current view from GitHub
S            Sync saved local edits
o            Outbox: inspect conflicts or uncertain writes
y            Copy selected item permalink (also inside details/actions)
Y            Copy containing Project permalink
c / Ctrl-C   Copy selected text in descriptions/comments
C            Copy all displayed text
Ctrl-A       Select all text in the focused viewer
L            List links to open or copy
PgUp PgDn    Scroll a page
Home End     First / last item or detail line
?            This help
q / Ctrl-C   Quit

Click rows to select; double-click to open. In descriptions/comments, drag to select text, press c to copy, click underlined links to open, or right-click for text actions. Ctrl-C quits when no text is selected. Wheel scrolls the pane under the pointer. Use an SGR-mouse-capable terminal (Terminal, iTerm2, Ghostty, etc.).

Comments and issue bodies use $VISUAL or $EDITOR (default vi). Save and exit to review the action. Escape or choose Cancel to abort.

Only fetched items are filtered. --limit controls list size (default 100). Cached views open immediately. Stale views refresh in the background. Queued edits sync every 30 seconds while online. All network work runs in the background; r fetches fresh data.

gh-desk uses your existing gh authentication. For Projects, grant scopes with: gh auth refresh -s project"""
