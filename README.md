# gh-desk

Manage GitHub issues and Projects from your terminal. Browse a board, change a status, write a comment, or create an issue without opening the GitHub website.

gh-desk uses the GitHub CLI (`gh`) for GitHub actions. It saves visited views and supported edits on your machine, so you can browse cached work and queue changes offline. Use the keyboard or a mouse.

## Get started

You need Python 3.12 or newer with curses, GitHub CLI, and an interactive terminal on macOS or Linux. On Windows, use WSL. There are no third-party Python packages to install for normal use.

From the project directory:

```sh
# Try sample data without signing in or changing anything on GitHub.
./gh-desk --demo

# Sign in, then open your own workspace.
gh auth login
./gh-desk
```

If you want to work with GitHub Projects, grant the Project scope:

```sh
gh auth refresh -s project
```

Your GitHub permissions still determine which actions are available. Sign in or switch accounts with `gh` before launching gh-desk.

```sh
./gh-desk --repo example-owner/example-repo  # open a repository's issues
./gh-desk --owner YOUR_LOGIN                 # list an owner's repos and Projects
./gh-desk --offline                          # use cached data and queue edits
./gh-desk --limit 300                        # load more items per list
./gh-desk --help
```

Online startup makes one read-only request to verify your account. After that, cached views open locally and stale views refresh in the background. An uncached view needs a connection. Use `--offline` to start without GitHub requests.

## What you can do

- **Issues:** create an issue, write comments, read the conversation, close or reopen it, and manage assignees and labels.
- **Projects:** browse a Kanban board or list, filter by status, change a card's status, and add an existing issue or pull request by URL. Create an issue directly in a Project with `n`.
- **Planning:** add an issue to multiple Projects and edit existing Project date fields. Cards show assignees, labels, start dates, and due or target dates when available.
- **Pull requests:** read discussions and diffs, check CI, comment, close or reopen, and squash merge with confirmation.
- **Workflow runs:** read failed logs, rerun failed jobs, or cancel active runs.
- **Text and links:** select and copy description or comment text, open HTTP/HTTPS links, and copy item or Project permalinks.

This is a focused workbench, not a complete replacement for every GitHub feature. See [limitations](USAGE.md#scope-and-behavior) before relying on it for your workflow.

## Your first few minutes

1. Press `1` for repositories, select one, and press Enter. Press `2` for issues, `3` for pull requests, `4` for workflow runs, or `5` for Projects.
2. Move with the arrow keys or `j` / `k`. Click a row to select it; double-click or press Enter to open it.
3. Press `a` or `:` for actions on the selected item. For an existing issue, choose **Write a comment…** to comment.
4. In a Project, press `f` to filter by status and `b` to switch between board and list. Use left/right to move between columns.
5. Press `o` to inspect queued edits, `S` to sync, and `q` to quit. Press `?` whenever you need help.

Comments and issue bodies open in `$VISUAL`, then `$EDITOR`, falling back to `vi`. Save and exit your editor, then confirm the action. For VS Code, set `EDITOR='code --wait'`.

| Key | Shortcut |
| --- | --- |
| `/` | Search within loaded items |
| `n` | Create an issue from Issues or inside a Project |
| `r` | Refresh the current view |
| `y` | Copy the selected item's permalink |
| `Y` | Copy the containing Project's permalink |
| `c` | Copy selected text in the focused text viewer |
| `C` | Copy all text in the focused viewer |
| `L` | Choose a link to open or copy |
| `Esc` | Clear selection/filter, close a popup, or go back |

Mouse drag selects text in descriptions and conversations. A click opens a link; a drag selects it. Mouse support depends on your terminal and any tmux/SSH setup. A terminal around 110 columns by 30 rows is comfortable.

For the full controls, issue creation, date editing, and recovery steps, read the [usage guide](USAGE.md).

## Keep your settings local

Copy the example and edit it:

```sh
cp config.example.toml config.local.toml
```

For example:

```toml
owner = "example-owner"
repo = "example-owner/example-repo"
limit = 100
offline = false
```

`config.local.toml` is ignored by Git. A user-wide config can also live at `~/.config/gh-desk/config.toml` (or `$XDG_CONFIG_HOME/gh-desk/config.toml`). Settings load in this order: defaults, user config, local config, then command-line flags.

Use `--config PATH` or `GH_DESK_CONFIG` to choose a single config file, `--no-config` to ignore configs, and `--no-offline` to override an offline default. Relative `data_dir` settings are resolved against the config file. Demo mode ignores personal settings.

Keep credentials in `gh`, not in these files. The example config and test fixtures contain generic data.

## Where your data goes

Your cache, queued edits, and retained editor drafts stay in:

```text
~/.local/share/gh-desk/
├── workspace.sqlite3
└── drafts/
```

`$XDG_DATA_HOME` or `--data-dir PATH` can change this location. Back up the directory if you want to keep your cached work and edit history.

The SQLite database is **local and unencrypted**. It may contain private issue text and comments. The database file uses owner-only permissions, and new data directories are private. Databases, drafts, personal config, logs, and development caches are ignored by Git and excluded from source archives. Tokens are not stored in SQLite.

Workspaces belong to a verified GitHub host and account ID, so changing a token or renaming your login preserves your work. New credentials need one online startup before offline mode can reconnect to a previously verified workspace. Legacy data matching the current credentials migrates automatically; see [local data and syncing](USAGE.md#local-data-and-syncing) for migration limits.

## How syncing works

Supported edits are saved locally before sending. While online, queued edits sync after confirmation, on `S`, and periodically while the app is running. Nothing keeps syncing after you quit. Merging and workflow actions require a connection and are recorded separately.

Before changing supported fields, the app reads the remote value and checks for a conflict. If a request times out or its result is uncertain, the app keeps the edit for verification instead of blindly sending it again. Open the outbox with `o` to inspect unresolved work.

This does not guarantee lossless, atomic syncing between devices: another writer can change a remote field between the app's check and its write. Retained snapshots and edit history help with review and recovery. Read the [sync details](USAGE.md#local-data-and-syncing) before resolving a conflict or retrying an uncertain action.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make check
```

`make check` runs lint, formatting, strict type checks for the core contracts, a public-source privacy check, and the test suite. Tests use synthetic data and do not need live GitHub credentials. The UI and GitHub JSON adapters are not fully statically typed.

```sh
make format  # format code and apply safe lint fixes
make dist    # build dist/gh-desk-source.tar.gz from public source files
```

The source archive excludes local settings and runtime data, and strips local account names from archive metadata. Review staged files before committing: ignore rules do not protect files that were already tracked or deliberately force-added. The privacy check is a useful guard, not a complete secret scanner.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules and [CHANGELOG.md](CHANGELOG.md) for changes.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
