# Using gh-desk

See the [README](README.md) for setup and a quick introduction. This guide covers everyday actions, keyboard and mouse controls, and sync recovery.

## Controls

| Key | Action |
| --- | --- |
| `1`–`5` | Switch view |
| `↑` / `↓`, `k` / `j` | Move selection or scroll focused pane |
| `Enter` | Select repository, open project, or focus details |
| `Tab` | Switch list/detail focus |
| `/` | Filter fetched items; type then Enter |
| `:` / `a` | Context actions |
| `n` | New issue from Issues view, or create and add an issue inside a Project |
| `s` | Cycle issue/PR state; filter status inside a Project |
| `f` | Choose a Project status filter, including All and Unassigned |
| `b` | Toggle Project board / list |
| `←` / `→`, `h` / `l` | Move between board columns |
| `r` | Fetch fresh data, keeping cached rows usable |
| `S` | Sync local edits and verify uncertain writes |
| `o` | Open the persistent outbox |
| `y` | Copy the selected repository, issue, PR, run, or Project permalink |
| `Y` | Copy the containing Project URL from its board/list or item details |
| `c` / `Ctrl-C` | Copy selected text in the focused description/comment viewer |
| `C` | Copy all text in the focused viewer |
| `Ctrl-A` | Select all text in the focused viewer |
| `L` | List links in the focused viewer, then open or copy one |
| `Esc` | Close popup, clear filter, or return from Project items |
| `PgUp` / `PgDn` | Move one page |
| `Home` / `End` | First / last item or detail line |
| `?` | Help |
| `q` / `Ctrl-C` | Quit |

Click a tab or row to select it. Double-click a row to open it. Wheel scrolling affects the pane under the pointer. A terminal with mouse reporting is required; tmux must pass mouse input through. Keyboard navigation always works. At least 55 columns × 14 rows are needed; 110 × 30 is comfortable.

Issue bodies and comments open in `$VISUAL`, then `$EDITOR`, falling back to `vi`. Save and exit to continue to confirmation. Empty comments are discarded. Editor commands with arguments are supported (for example `EDITOR='code --wait'`). Cancel at confirmation to avoid queueing the edit. Editor files are retained under the local data directory, including when the editor fails; they are never automatically submitted.

## Select text and follow links

Issue descriptions, Project item details, and **Read conversation** output support mouse selection and clickable links. Focus a description with Enter or Tab, or open a card/conversation popup, then:

- Drag to select text; press `c`, `y`, or Ctrl-C to copy the selection. Double-click selects a word. Selections preserve real line breaks without adding display-wrap line breaks.
- Ctrl-A selects all text; `C` copies all displayed text. Ctrl-C still quits the app when no text is selected. Esc clears a selection before closing the popup.
- Click an underlined HTTP/HTTPS link to open it in your default browser. Markdown links and bare URLs work even when wrapped across rows. Dragging across a link selects text without opening it.
- Right-click for **Copy selection**, **Open link**, **Copy link URL**, and **Copy all text** as applicable.
- `L` lists links for keyboard navigation; select one to open it or copy its URL. No links are opened automatically.

Text remains readable Markdown source. Non-HTTP links and relative Markdown links are not opened. Clipboard operations use the same native tools as permalink copying. Modern SGR mouse reports and drag tracking are handled explicitly for macOS Python builds with older curses libraries; mouse modes are restored on exit. Through tmux/SSH, the terminal must pass mouse reports through. Your terminal may also support its own mouse-selection override (often Shift-drag).

## Copy permalinks

Press `y` or choose **Copy permalink (y)** from Actions to copy the selected item's cached GitHub URL. It works for repositories, issues, pull requests, workflow runs, and Projects. On a Project card, `y` copies the linked issue/PR URL; `Y` or **Copy Project permalink (Y)** copies the containing Project URL. Both shortcuts also work in card details and the Actions menu. They do not make a network request or require confirmation.

The app uses `pbcopy` on macOS, `wl-copy` on Wayland, or `xclip`/`xsel` on X11. If no clipboard tool works, a popup displays the exact URL for manual copying. Unsynced issues and draft cards without a remote URL report that no permalink is available; `Y` can still copy their containing Project. Project URLs are canonical Project links, not links that recreate the TUI's local filters or column layout.

## Dates, assignees, labels, and multiple Projects

Select an issue/PR or a linked Project card, then `a` (or `:`). These actions also work through the item-detail popup's Actions menu:

- **Assignees…** — enter a GitHub username to add an assignee, or select an `[x]` assignee to remove them. Several users can be assigned without replacing the others. Use an explicit login (for example `example-user`) rather than a CLI alias such as `@me`.
- **Labels…** — select a repository label to add/remove it, or type an existing label name. Labels are changed individually; other labels remain. This menu does not create repository labels.
- **Projects…** — `[x]` marks an existing membership; select it to remove the issue from that Project (this does not delete the issue). Select `[ ]` to add it to another Project. Adding a second Project preserves the first. The catalog uses the selected `--owner`, plus every Project already attached to this issue. A pending edit is marked `[pending]` until synced.
- **Due date…** on a Project card — choose an existing Date field (Due date/Target date first), enter `YYYY-MM-DD`, or leave it blank to clear the value. Invalid calendar dates are rejected. Other Date fields, such as Start date, can also be chosen when present.
- **Due date in Project…** from Issues/PRs — select one of this issue's Project memberships, then edit its date. Dates belong to a Project item, so the same issue can have different dates in different Projects. No global issue due date is invented, and no fields are created automatically.

These edits use the durable local outbox. Cached metadata enables offline editing; a date schema or membership list must first be opened online to cache it. Dates compare the saved value with the current remote value before writing. Assignee/label changes use add/remove operations and check only the chosen entry, preserving unrelated entries changed remotely. Project removals are confirmed and checked against current membership. Conflicts and unknown outcomes remain in `o` for review instead of blindly retrying.

## Create an issue directly in a Project

Open Projects (`5`), select the Project, and press `n` or `a` → **New issue in this project…**. The `n` shortcut also works while card details or the Actions menu are open. Enter `OWNER/REPO` (the selected card's repository is offered as the default), enter a title, write the body in your editor, then save and exit. Confirm **Create issue and add to [Project]**. No URL copying is needed. The local card appears under Unassigned, with a pending marker, even when offline.

Sync creates the repository issue first and durably records its returned URL plus one dependent Project-add job in the same database transaction. The add runs in the same sync pass. Interrupted creation is reconciled by its unique marker; it is never blindly repeated. If adding fails, `o` shows the separate Project-add job and the existing issue URL. Inspect it, fix access/scopes if necessary (`gh auth refresh -s project`), and choose **Retry adding this existing issue to the Project…**. That retries the link only. Issues are never deleted to roll back a failed add.

To add an existing issue, use `a` → **Add issue or pull request by URL…**. Pasted whitespace, trailing slashes, and comment fragments are stripped. Project membership is checked before adding and when verifying an uncertain result.

## Project boards

Open Projects (`5`) and select a project with Enter. Items open as a Kanban board, grouped by their current Status. Cards and Project list rows show assignees, labels, start dates, and due dates; Target date is used as the due date on Projects that use that field. Empty values show `—`. Cards expand to fit metadata, with fewer cards visible at once. Short terminals show as much as fits; Enter opens the full metadata in details. Display uses local data and pending edits without fetching from GitHub. Columns follow the cached Status field order, including empty columns; items without a status appear in Unassigned. Arrow left/right (or `h`/`l`) changes columns, up/down (or `j`/`k`) selects cards. The viewport scrolls horizontally to keep the active column visible. Click cards or column headers to select, wheel to move through that column, and Enter or double-click to read full details.

Press `f` or `s` to choose a status, or All statuses to clear it. `/` text search combines with the status filter. Esc clears text search first, then status, then leaves the project. `b` switches between board and list without refetching. `:` → Write a comment… opens your editor for the issue/PR linked to the selected card; save and exit, then confirm Post comment. Read conversation displays its discussion. Draft cards have no GitHub conversation. Pending comments appear in card details and the outbox. `:` → Change status uses the existing local write queue; moving across columns only navigates. Filters and column counts apply to loaded items, up to `--limit`.

## Local data and syncing

The default data directory is `$XDG_DATA_HOME/gh-desk` or `~/.local/share/gh-desk`. It contains `workspace.sqlite3` and retained editor files in `drafts/`. Back up this directory to preserve snapshots and edit history. The database file is created with mode 0600 and new directories with mode 0700. Demo mode doesn't open a database.

- **Immediate browsing:** fetched lists, READMEs, Project fields, and viewed conversation/diff/log outputs persist across launches. Fresh list caches avoid another network request for 60 seconds; stale lists display immediately while refreshing. READMEs and Project fields use a five-minute freshness window. READMEs are debounced during fast navigation. The first visit to an uncached view still requires GitHub.
- **Local edits:** issue creation, comments, issue/PR close/reopen, Project item additions, and status changes are recorded in a durable outbox. State/status changes and new issues appear locally right away; pending comments appear in details. Project additions appear as local pending cards until the server returns them. Local issue drafts cannot receive further actions until synced.
- **Sync:** confirmed queued edits sync immediately while online, on `S`, and every 30 seconds while the app is running. No background service runs after quitting. `--offline` performs no GitHub requests; restart without that flag to sync. Only visited views are cached; this is not a full GitHub mirror.
- **Conflict detection:** before a state/status write, sync reads the current remote value. If it differs from the saved base and the desired value, no write is sent. `o` lets you inspect the base/local/remote values, archive the local edit while keeping its journal, or explicitly apply the local value against the last observed remote value. The latter is checked again before sending. Another unsynced field edit to the same target is blocked until resolved.
- **Unknown outcomes:** a timeout, error during a write, or interruption after a request is claimed never causes an automatic replay. Those edits remain `uncertain` or `sending`. Sync checks state/status values; comments and new issues include a unique invisible HTML marker which can be found with a paginated read. Finding the marker marks the edit done. Not finding it does **not** authorize resubmission. Inspect the remote result, then archive the journal entry if appropriate. Workflow/merge ambiguity may require manual verification; Project additions are verified against paginated membership reads and have an explicit link-only retry.
- **Audit retention:** every remote snapshot and queued payload is retained, with an append-only edit event history. Archive removes the local overlay without deleting the payload; it does not undo a remote change. Workspaces are keyed by verified GitHub host and numeric account ID, so token rotation and login renames retain the same cache and outbox. Online startup verifies the account with one read-only request; failed verification leaves the database unchanged (use `--offline` for cached work). Credential/config changes block in-flight requests until restart. Offline startup reuses only a previously verified credential binding; new credentials need one online startup to reconnect older work. Legacy data for the current credential fingerprint migrates transactionally, retaining history and jobs. Unbound legacy workspaces from credentials changed before this upgrade remain preserved; use the original gh configuration to bind them first. No tokens are stored in the database; credentials stay managed by `gh`.
- **Online-only commands:** merging and workflow rerun/cancel require a connection and immediate confirmation. Their payload/result is journaled, but they are never automatically replayed after restart.

This protects local drafts and avoids blind overwrites/retries. It cannot guarantee atomic cross-device conflict prevention: `gh` state/status writes offer no compare-and-swap version precondition, so another writer can change the same field between the preflight read and the write. The journal preserves the observed remote value and local intent; it cannot capture every change made remotely between reads. Issue titles/bodies, comments by other people, and unrelated Project fields are never replaced by sync. Merge additionally uses GitHub's head-SHA check.

## Scope and behavior

- Lists fetch up to `--limit` items (100 by default; max 1000). Search filters only fetched items. No implicit UI-list pagination. Unresolved outbox edits are checked every 30 seconds; views refresh on visit when stale, or on `r`. Large workspaces may need a higher limit.
- Repository listing shows repositories **owned** by the selected user/organization, not every repository they collaborate on. `--repo OWNER/REPO` opens a known accessible repo directly.
- Projects use the modern GitHub Projects API. Their `Status` field must be a single-select field named `Status`. Date-field editing is supported; other custom field types and draft creation are not implemented. Board columns reflect the existing Status options; creating or reordering remote Status options is not implemented.
- Views render Markdown as readable source. Failed workflow logs and diffs open in a scrollable terminal popup. Large outputs are held in memory.
- Clone, local checkout, PR creation, repo deletion, notifications, and multi-host aggregation are not implemented.
- Read/write requests time out after 35 seconds. Ambiguous writes remain in the durable outbox for verification; avoid duplicating them manually.
- Demo mode uses invented data and blocks writes. No GitHub calls are made.

