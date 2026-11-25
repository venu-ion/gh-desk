# Changelog

User-facing changes are recorded here. This repository starts with the existing development version, `0.2.0`; no public release is implied by the initial Git commit.

## Unreleased

### Initial local snapshot — 2026-11-25

#### Features

- Browse repositories, issues, pull requests, workflow runs, and GitHub Projects from the terminal using GitHub CLI.
- Navigate with the keyboard or mouse. Read descriptions and conversations, select and copy text, follow links, and copy permalinks.
- View Projects as Kanban boards or lists, filter cards by status, and show assignees, labels, start dates, and due dates.
- Create issues directly in a Project, add existing issues by URL, comment, update status, and manage assignees, labels, dates, and multiple Project memberships.
- Inspect pull request diffs and checks, squash merge with confirmation, and inspect or manage workflow runs.
- Browse cached views offline and save supported edits in a persistent local outbox. Inspect conflicts and uncertain requests before taking further action.
- Configure personal defaults in ignored local or user-wide config files. Try the app with synthetic data in demo mode.

#### Fixes and reliability

- Handle Project labels returned as strings or objects without crashing.
- Keep status, labels, assignees, dates, and membership changes from overwriting unrelated fields in local previews.
- Preserve a created issue when adding it to a Project fails; retry the Project link without creating another issue.
- Verify uncertain writes instead of automatically replaying them.
- Store work under a verified host and account ID so token rotation and login renames keep the same cache and outbox. Preserve legacy jobs and history during migration.
- Wait for completed terminal frames in the offline restart test and completed file contents in the clipboard test, replacing timing assumptions.

#### Project maintenance

- Split terminal rendering, navigation, GitHub commands, persistence, and syncing into separate modules.
- Add lint, formatting, core type checks, unit and terminal tests, and macOS/Linux CI configuration.
- Add Apache 2.0 licensing, generic example settings, Git exclusions, and a source-only archive with a privacy check.
- Add a shorter README and a separate usage guide.
