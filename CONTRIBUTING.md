# Contributing

This project uses Python 3.12+, the standard library, and GitHub CLI. Development checks are described in README.md; run `make check` before submitting a change.

## Keep source generic

- Use synthetic fixtures and placeholder accounts such as `octocat`, `example-owner`, and `me`.
- Do not copy private issue descriptions, comments, Project IDs, repository names, usernames, emails, or local home paths into source, tests, documentation, or screenshots.
- Put personal defaults only in ignored `config.local.toml` or the user config directory. Keep credentials in GitHub CLI, not config.
- Never commit SQLite snapshots, queued edits, editor drafts, logs, development environments, or caches.
- `make privacy` checks public source inputs. `make dist` packages only those inputs and strips local account metadata from the archive.

## Preserve behavior and data

- Keep local previews pure and test that an operation leaves unrelated fields unchanged.
- Preserve the on-disk queue format, unknown metadata, and recovery behavior.
- Do not replay writes with ambiguous outcomes. Add tests for restarts and partial failure.
- Test terminal behavior with actual pseudo-terminal sequences when changing keyboard or mouse handling.
- Keep optional development dependencies out of runtime code.

Contributions are made under Apache License 2.0, the project's license.
