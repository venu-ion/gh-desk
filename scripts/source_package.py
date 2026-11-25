# SPDX-License-Identifier: Apache-2.0
"""Audit and package only public source files, never working-directory artifacts."""

from __future__ import annotations

import argparse
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_ALLOWED_OWNERS = {
    "octocat",
    "me",
    "other",
    "example-owner",
    "example-user",
    "users",
    "orgs",
    "openai",
    "apache",
}
_ALLOWED_FILES = {
    "README.md",
    "USAGE.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "Makefile",
    "pyproject.toml",
    "requirements-dev.txt",
    "config.example.toml",
    "gh-desk",
    ".gitignore",
}


def source_files(root: Path) -> list[Path]:
    def public_file(path: Path) -> bool:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.resolve().is_relative_to(root.resolve())
        )

    files = [
        p
        for p in root.iterdir()
        if p.is_file() and not p.is_symlink() and (p.name in _ALLOWED_FILES or p.suffix == ".py")
    ]
    for directory in ("tests", "scripts", ".github/workflows"):
        base = root / directory
        if base.is_dir():
            files.extend(
                p
                for p in base.rglob("*")
                if public_file(p)
                and "__pycache__" not in p.parts
                and p.suffix in (".py", ".yml", ".yaml")
            )
    return sorted(set(files))


def privacy_errors(root: Path) -> list[str]:
    """Check publishable inputs without echoing possible credential values."""
    errors = []
    credential = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
    home = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+(?:/|\b)")
    node = re.compile(r"\b(?:PVT|PVTI|PVTF|PVTSSF|PVTIF)_[A-Za-z0-9_-]{16,}\b")
    email = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
    for path in source_files(root):
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(root))
        checks = [
            ("credential-like literal", credential.search(text)),
            ("absolute personal home path", home.search(text)),
            ("real-looking GitHub Project node ID", node.search(text)),
            ("private key material", re.search(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", text)),
        ]
        for label, match in checks:
            if match:
                errors.append(relative + ": " + label)
        for match in re.finditer(r"https?://github\.com/([A-Za-z0-9_-]+)/", text):
            if match[1] not in _ALLOWED_OWNERS:
                errors.append(relative + ": non-example GitHub owner")
        for match in re.finditer(r"https?://github\.com/(?:users|orgs)/([A-Za-z0-9_-]+)/", text):
            if match[1] not in _ALLOWED_OWNERS:
                errors.append(relative + ": non-example Project owner")
        for match in email.finditer(text):
            if match[1] not in ("example.com", "example.org", "example.net"):
                errors.append(relative + ": non-example email address")
    return sorted(set(errors))


def build_archive(root: Path, output: Path) -> None:
    errors = privacy_errors(root)
    if errors:
        raise ValueError("\n".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for path in source_files(root):
            info = archive.gettarinfo(str(path), arcname="gh-desk/" + str(path.relative_to(root)))
            # Tar's default metadata would disclose the local account owner.
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with path.open("rb") as source:
                archive.addfile(info, source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Only audit public source inputs")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/gh-desk-source.tar.gz")
    args = parser.parse_args()
    errors = privacy_errors(ROOT)
    if errors:
        parser.exit(1, "Public-source privacy check failed:\n" + "\n".join(errors) + "\n")
    if args.check:
        print("Public-source privacy check passed.")
    else:
        build_archive(ROOT, args.output)
        print(
            "Created source archive: "
            + str(
                args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output
            )
        )


if __name__ == "__main__":
    main()
