# SPDX-License-Identifier: Apache-2.0
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.source_package import build_archive, privacy_errors, source_files


class SourcePackageTests(unittest.TestCase):
    def test_public_source_passes_privacy_gate(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(privacy_errors(root), [])

    def test_archive_excludes_local_artifacts_and_strips_account_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "README.md",
                "LICENSE",
                "NOTICE",
                "config.example.toml",
                "gh-desk",
                "main.py",
            ):
                (root / name).write_text("Public example\n")
            for name in (
                "config.local.toml",
                "workspace.sqlite3",
                "private.log",
                ".env",
                "drafts/message.md",
                ".venv/bin/activate",
                "__pycache__/old.pyc",
            ):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Private local data")
            output = root / "dist/source.tar.gz"
            build_archive(root, output)
            with tarfile.open(output) as archive:
                names = archive.getnames()
                self.assertEqual(len(names), 6)
                self.assertIn("gh-desk/config.example.toml", names)
                for info in archive:
                    self.assertFalse(Path(info.name).is_absolute())
                    self.assertEqual((info.uname, info.gname, info.uid, info.gid), ("", "", 0, 0))
                    self.assertNotIn(
                        "Private local data", archive.extractfile(info).read().decode()
                    )

    def test_privacy_gate_rejects_non_example_data_without_echoing_values(self):
        cases = [
            ("https://" + "github.com/" + "private-owner/repository", "non-example GitHub owner"),
            ("/" + "Users/" + "local-account/project", "absolute personal home path"),
            ("ghp_" + "x" * 30, "credential-like literal"),
            ("PVT_" + "x" * 30, "real-looking GitHub Project node ID"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for value, label in cases:
                (root / "sample.py").write_text(repr(value))
                errors = privacy_errors(root)
                self.assertEqual(errors, ["sample.py: " + label])
                self.assertNotIn(value, " ".join(errors))
                with self.assertRaises(ValueError):
                    build_archive(root, root / "out.tar.gz")

    def test_git_ignore_rules_cover_personal_config_and_runtime_data(self):
        original = Path(__file__).resolve().parents[1] / ".gitignore"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text(original.read_text())
            paths = [
                "config.local.toml",
                "config.toml",
                ".env",
                "workspace.sqlite3",
                "drafts/message.md",
                ".venv/bin/activate",
                "dist/source.tar.gz",
                "logs/debug.log",
            ]
            result = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "--stdin"],
                input="\n".join(paths) + "\n",
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(result.stdout.splitlines(), paths)
            result = subprocess.run(
                ["git", "-C", str(root), "check-ignore", "config.example.toml"], capture_output=True
            )
            self.assertEqual(result.returncode, 1)

    def test_symlinks_are_never_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "private.txt").write_text("Private")
            (root / "leak.py").symlink_to(root / "private.txt")
            self.assertEqual(source_files(root), [])


if __name__ == "__main__":
    unittest.main()
