# SPDX-License-Identifier: Apache-2.0
"""Credential rotation must preserve work without crossing account boundaries."""

import tempfile
import unittest
from unittest.mock import Mock, patch

from github import GhError, GitHub
from identity import auth_namespace, bind_workspace
from local_store import Store
from sync import Sync


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        environment = patch.dict("os.environ", {"GH_HOST": "github.com"})
        environment.start()
        self.addCleanup(environment.stop)
        self.gh = Mock()
        self.gh.run.return_value = {"id": 7, "login": "octocat"}

    def resolve(self, fingerprint, *, offline=False):
        store = Store(self.tmp.name, fingerprint)
        with patch("identity.auth_namespace", return_value=fingerprint):
            bind_workspace(store, self.gh, offline=offline)
        return store

    def seed(self, store):
        store.put("private", {"body": "original"})
        return store.enqueue(
            "Comment",
            dict(
                kind="comment",
                args=["issue", "comment", "7", "--body", "draft"],
                repo="me/repo",
                tab=1,
                identity=7,
                body="draft",
            ),
        )

    def test_rotation_and_login_rename_keep_jobs_snapshots_and_journal(self):
        legacy = Store(self.tmp.name, "credential-one")
        job = self.seed(legacy)
        first = self.resolve("credential-one")
        self.gh.run.return_value = {"id": 7, "login": "example-user"}
        rotated = self.resolve("credential-two")
        self.assertEqual(first.namespace, rotated.namespace)
        self.assertEqual(rotated.credential_namespace, "credential-two")
        self.assertEqual(rotated.get("private")[0], {"body": "original"})
        self.assertEqual(rotated.jobs()[0]["id"], job)
        with rotated.connection() as db:
            self.assertEqual(
                db.execute("SELECT namespace FROM job_events").fetchone()[0], rotated.namespace
            )
            self.assertEqual(
                db.execute("SELECT namespace FROM history").fetchone()[0], rotated.namespace
            )
        self.gh.run.assert_called_with(["api", "--hostname", "github.com", "user"], parse=True)

    def test_real_token_and_config_rotation_reconnects_same_account(self):
        with patch.dict(
            "os.environ", {"GH_CONFIG_DIR": self.tmp.name, "GH_TOKEN": "synthetic-one"}
        ):
            original = auth_namespace()
            first = Store(self.tmp.name, original)
            bind_workspace(first, self.gh, offline=False)
            job = self.seed(first)
        with patch.dict(
            "os.environ", {"GH_CONFIG_DIR": self.tmp.name, "GH_TOKEN": "synthetic-two"}
        ):
            rotated = auth_namespace()
            self.assertNotEqual(original, rotated)
            second = Store(self.tmp.name, rotated)
            bind_workspace(second, self.gh, offline=False)
            self.assertEqual(second.namespace, first.namespace)
            self.assertEqual(second.jobs()[0]["id"], job)

    def test_migration_failure_rolls_back_data_and_binding(self):
        legacy = Store(self.tmp.name, "credential-one")
        job = self.seed(legacy)
        with legacy.connection() as db:
            db.execute(
                "CREATE TRIGGER fail_migration BEFORE UPDATE OF namespace ON jobs "
                "BEGIN SELECT RAISE(ABORT, 'synthetic migration failure'); END"
            )
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            self.resolve("credential-one")
        self.assertEqual(legacy.get("private")[0], {"body": "original"})
        self.assertEqual(legacy.jobs()[0]["id"], job)
        with legacy.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM account_bindings").fetchone()[0], 0)

    def test_known_credentials_open_offline_without_gh(self):
        first = self.resolve("credential-one")
        self.seed(first)
        self.gh.reset_mock()
        offline = self.resolve("credential-one", offline=True)
        self.assertEqual(offline.namespace, first.namespace)
        self.assertEqual(len(offline.jobs()), 1)
        self.gh.run.assert_not_called()

    def test_unknown_credentials_offline_do_not_expose_other_account(self):
        self.seed(self.resolve("credential-one"))
        offline = self.resolve("credential-two", offline=True)
        self.assertEqual(offline.jobs(), [])
        self.assertEqual(offline.get("private"), (None, 0))
        # Offline drafts made with new credentials join that account on verification.
        self.seed(offline)
        self.assertEqual(len(self.resolve("credential-two").jobs()), 2)

    def test_different_accounts_and_hosts_stay_separate(self):
        first = self.resolve("credential-one")
        self.seed(first)
        self.gh.run.return_value = {"id": 8}
        second = self.resolve("credential-two")
        self.assertNotEqual(first.namespace, second.namespace)
        self.assertEqual(second.jobs(), [])
        self.gh.run.return_value = {"id": 7}
        with patch.dict("os.environ", {"GH_HOST": "github.example.com"}):
            enterprise = self.resolve("credential-three")
        self.assertNotEqual(first.namespace, enterprise.namespace)
        self.assertEqual(enterprise.jobs(), [])

    def test_keychain_account_switch_same_fingerprint_does_not_move_work(self):
        first = self.resolve("same-config")
        job = self.seed(first)
        self.gh.run.return_value = {"id": 8}
        second = self.resolve("same-config")
        self.assertEqual(second.jobs(), [])
        self.assertEqual(first.jobs()[0]["id"], job)
        self.gh.run.return_value = {"id": 7}
        self.assertEqual(self.resolve("same-config").jobs()[0]["id"], job)

    def test_failed_verification_does_not_rebind_or_migrate(self):
        legacy = Store(self.tmp.name, "credential-one")
        job = self.seed(legacy)
        self.gh.run.side_effect = GhError("offline")
        with self.assertRaises(GhError):
            self.resolve("credential-one")
        self.assertEqual(legacy.jobs()[0]["id"], job)
        with legacy.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM account_bindings").fetchone()[0], 0)

    def test_invalid_identity_and_mid_verification_switch_do_not_migrate(self):
        legacy = Store(self.tmp.name, "credential-one")
        self.seed(legacy)
        for user in ({}, {"id": True}, {"id": "7"}):
            self.gh.run.return_value = user
            with self.assertRaisesRegex(RuntimeError, "valid account ID"):
                self.resolve("credential-one")
        self.gh.run.return_value = {"id": 7}
        with patch("identity.auth_namespace", return_value="changed"):
            with self.assertRaisesRegex(RuntimeError, "credentials changed"):
                bind_workspace(legacy, self.gh, offline=False)
        self.assertEqual(len(legacy.jobs()), 1)

    def test_rotated_workspace_sync_checks_credentials_not_account_hash(self):
        store = self.resolve("credential-two")
        with patch("sync.auth_namespace", return_value="credential-two"):
            self.assertIn("0 unresolved", Sync(store, self.gh).run())
        with patch("sync.auth_namespace", return_value="changed"):
            with self.assertRaisesRegex(RuntimeError, "account/config changed"):
                Sync(store, self.gh).run()
        gh = GitHub(namespace="credential-two")
        with patch("github.auth_namespace", return_value="changed"):
            with patch("github.subprocess.run") as run:
                with self.assertRaises(GhError):
                    gh.run(["api", "user"])
                run.assert_not_called()

    def test_snapshot_collision_keeps_newest_and_all_history(self):
        stable = self.resolve("credential-one")
        stable.put("private", "newer")
        legacy = Store(self.tmp.name, "credential-two")
        legacy.put("private", "older")
        with legacy.connection() as db:
            db.execute("UPDATE snapshots SET updated=1 WHERE namespace=?", (legacy.namespace,))
        merged = self.resolve("credential-two")
        self.assertEqual(merged.get("private")[0], "newer")
        with merged.connection() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM history WHERE namespace=?", (merged.namespace,)
                ).fetchone()[0],
                2,
            )
        # A repeated launch is idempotent.
        self.assertEqual(self.resolve("credential-two").get("private")[0], "newer")


if __name__ == "__main__":
    unittest.main()
