# SPDX-License-Identifier: Apache-2.0
"""Offline demonstration fixtures; never mixed with account data."""


def demo_rows(tab, project=None):
    if tab == 0:
        return [
            dict(
                nameWithOwner=f"octocat/{name}",
                description=desc,
                isPrivate=i % 2 == 0,
                url=f"https://github.com/octocat/{name}",
                primaryLanguage={"name": lang},
                updatedAt="2026-11-20T09:00:00Z",
            )
            for i, (name, desc, lang) in enumerate(
                [
                    (
                        "launchpad",
                        "A small home for big ideas. Personal project dashboard.",
                        "TypeScript",
                    ),
                    (
                        "dotfiles",
                        "A quieter terminal. Shell, editor, and workstation setup.",
                        "Shell",
                    ),
                    ("weekend-builds", "Experiments worth keeping.", "Python"),
                    ("garden", "Notes, writing, and things I am learning.", "Go"),
                ]
            )
        ]
    if tab in (1, 2):
        titles = [
            "Make search feel instant",
            "Add keyboard shortcuts to the command menu",
            "Simplify the onboarding flow",
            "Fix narrow terminal layout",
        ]
        return [
            dict(
                number=42 - i,
                title=t,
                body="Keep the experience fast and focused.\n\n## Acceptance criteria\n- Works with the keyboard and mouse\n- Handles empty and error states\n- Keeps the current selection on refresh",
                state="OPEN",
                url=f"https://github.com/octocat/launchpad/{('issues' if tab == 1 else 'pull')}/{42 - i}",
                author={"login": "octocat"},
                labels=[{"name": "enhancement" if i < 2 else "bug"}],
                assignees=[],
                updatedAt="2026-11-20",
                headRefName="feat/quick-search",
                baseRefName="main",
                headRefOid="demo",
                mergeable="MERGEABLE",
            )
            for i, t in enumerate(titles)
        ]
    if tab == 3:
        return [
            dict(
                databaseId=901 - i,
                displayTitle=t,
                workflowName="CI",
                status=s,
                conclusion=c,
                headBranch="main",
                createdAt="2026-11-20",
                url="https://github.com/octocat/launchpad/actions",
            )
            for i, (t, s, c) in enumerate(
                [
                    ("Make search feel instant", "completed", "success"),
                    ("Add keyboard shortcuts", "in_progress", ""),
                    ("Fix narrow terminal layout", "completed", "failure"),
                ]
            )
        ]
    if project:
        return [
            dict(
                id=f"item{i}",
                title=t,
                status=s,
                labels=["enhancement", {"name": "personal"}],
                assignees=["octocat"],
                startDate="2026-11-20",
                dueDate="2026-12-01",
                content={
                    "type": "Issue",
                    "number": 42 - i,
                    "body": "A focused next step.",
                    "url": "https://github.com/octocat/launchpad/issues/42",
                },
                repository="octocat/launchpad",
            )
            for i, (t, s) in enumerate(
                [
                    ("Make search feel instant", "In Progress"),
                    ("Add keyboard shortcuts", "Todo"),
                    ("Simplify onboarding", "Done"),
                ]
            )
        ]
    return [
        dict(
            id="PVT_demo",
            number=1,
            title="Personal roadmap",
            shortDescription="A little less planning. A little more shipping.",
            url="https://github.com/users/octocat/projects/1",
            items={"totalCount": 3},
            closed=False,
        )
    ]
