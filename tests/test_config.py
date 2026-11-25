# SPDX-License-Identifier: Apache-2.0
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import parse_options


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.environment = patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.root / "user-config"),
                "XDG_DATA_HOME": str(self.root / "data"),
            },
            clear=True,
        )
        self.environment.start()
        self.local = self.root / "config.local.toml"

    def tearDown(self):
        self.environment.stop()
        self.tmp.cleanup()

    def config(self, body):
        self.local.write_text(body)
        return self.local

    def parse(self, args=None):
        return parse_options(args or [], local_config=self.local)

    def test_no_config_uses_current_gh_account_without_personal_defaults(self):
        options = self.parse()
        self.assertIsNone(options.owner)
        self.assertIsNone(options.repo)
        self.assertEqual(options.limit, 100)
        self.assertEqual(options.data_dir, str(self.root / "data/gh-desk"))

    def test_local_config_and_cli_precedence(self):
        self.config('owner="octocat"\nrepo="octocat/hello-world"\nlimit=20\noffline=true\n')
        options = self.parse(["--limit", "50", "--no-offline"])
        self.assertEqual(options.owner, "octocat")
        self.assertEqual(options.repo, "octocat/hello-world")
        self.assertEqual(options.limit, 50)
        self.assertFalse(options.offline)

    def test_user_then_local_config_then_flags(self):
        global_file = self.root / "user-config/gh-desk/config.toml"
        global_file.parent.mkdir(parents=True)
        global_file.write_text('owner="octocat"\nlimit=40\n')
        self.config("limit=60\n")
        self.assertEqual(self.parse().limit, 60)
        self.assertEqual(self.parse().owner, "octocat")
        self.assertEqual(self.parse(["--limit", "80"]).limit, 80)

    def test_explicit_config_and_environment_config(self):
        other = self.root / "other.toml"
        other.write_text('owner="example-owner"\n')
        self.config('owner="octocat"\n')
        with patch.dict(os.environ, {"GH_DESK_CONFIG": str(other)}):
            self.assertEqual(self.parse().owner, "example-owner")
            self.assertEqual(self.parse(["--config", str(self.local)]).owner, "octocat")
            self.assertIsNone(self.parse(["--no-config"]).owner)

    def test_demo_never_displays_owner_or_repo_from_private_config(self):
        self.config('owner="example-owner"\nrepo="example-owner/private-repo"\n')
        options = self.parse(["--demo"])
        self.assertIsNone(options.owner)
        self.assertIsNone(options.repo)

    def test_relative_data_dir_is_relative_to_config_file(self):
        self.config('data_dir="data"\n')
        self.assertEqual(self.parse().data_dir, str((self.root / "data").resolve()))

    def test_bad_config_is_rejected_without_echoing_secret_values(self):
        for content in (
            "limit=true",
            'offline="yes"',
            'repo="bad"',
            "limit=5000",
            'owner=""',
            'token="do-not-echo-this"',
        ):
            self.config(content)
            with (
                self.subTest(content=content),
                contextlib.redirect_stderr(io.StringIO()) as stderr,
                self.assertRaises(SystemExit),
            ):
                self.parse()
            self.assertNotIn("do-not-echo-this", stderr.getvalue())

    def test_missing_explicit_config_is_an_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.parse(["--config", str(self.root / "missing.toml")])

    def test_checked_in_template_contains_only_valid_generic_settings(self):
        path = Path(__file__).resolve().parents[1] / "config.example.toml"
        options = self.parse(["--config", str(path)])
        self.assertEqual(options.limit, 100)
        self.assertIsNone(options.owner)
        self.assertIsNone(options.repo)
