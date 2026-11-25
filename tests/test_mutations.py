# SPDX-License-Identifier: Apache-2.0
"""Cross-field invariants and backward-compatible durable operation validation."""

import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

from identity import auth_namespace
from local_store import Store
from models import Action
from mutations import DateChange, MembershipChange, parse_mutation
from projections import ViewContext, project_rows
from sync import Sync


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(
            id="ITEM",
            number=7,
            title="Task",
            status="Planning",
            state="OPEN",
            labels=[{"name": "bug"}],
            assignees=[{"login": "alice"}],
            content={"url": "https://github.com/me/repo/issues/7", "body": "Remote description"},
            **{"Start date": "2026-11-20", "Due date": "2026-12-01"},
        )
        self.common = dict(args=["issue", "edit", "7"], repo="me/repo", tab=1, identity=7)

    def job(self, payload):
        return dict(id="job", payload=payload, status="pending", updated=1)

    def assert_only_fields(self, original, result, allowed):
        for key, value in original.items():
            if key not in allowed:
                self.assertEqual(result[key], value, f"Unrelated field changed: {key}")
        self.assertEqual(set(result) - set(original), {"_pending"})

    def test_label_and_assignee_edits_cannot_change_status_or_dates(self):
        for field, value in [("labels", "urgent"), ("assignees", "bob")]:
            for desired in (True, False):
                payload = dict(
                    self.common,
                    kind="membership",
                    field=field,
                    value=value,
                    base=not desired,
                    desired=desired,
                )
                original = copy.deepcopy(self.row)
                result = project_rows(
                    ViewContext(tab=4, project="P"), [self.row], [self.job(payload)]
                )[0]
                self.assert_only_fields(original, result, {field})
                self.assertEqual(result["status"], "Planning")
                self.assertEqual(self.row, original)
                self.assertIsInstance(parse_mutation(payload), MembershipChange)

    def test_date_edits_can_only_change_the_requested_date(self):
        for field in ("Start date", "Due date"):
            for value in ("2026-12-25", ""):
                payload = dict(
                    kind="date",
                    args=["project", "item-edit"],
                    project={"id": "P"},
                    identity="ITEM",
                    field_id="F",
                    field_name=field,
                    base=self.row[field],
                    desired=value,
                )
                result = project_rows(
                    ViewContext(tab=4, project="P"), [self.row], [self.job(payload)]
                )[0]
                self.assertEqual(result[field], value)
                self.assert_only_fields(self.row, result, {field})
                self.assertIsInstance(parse_mutation(payload), DateChange)

    def test_status_and_issue_state_are_independent(self):
        status = dict(
            kind="status",
            args=["project", "item-edit"],
            project={"id": "P"},
            identity="ITEM",
            base="Planning",
            desired="Done",
        )
        result = project_rows(ViewContext(tab=4, project="P"), [self.row], [self.job(status)])[0]
        self.assert_only_fields(self.row, result, {"status"})
        state = dict(self.common, kind="state", base="OPEN", desired="CLOSED")
        result = project_rows(
            ViewContext(tab=1, repo="me/repo", state="all"), [self.row], [self.job(state)]
        )[0]
        self.assert_only_fields(self.row, result, {"state"})

    def test_comment_changes_only_body_and_preserves_snapshot_and_payload(self):
        payload = dict(self.common, kind="comment", body="Local comment")
        before = copy.deepcopy(payload)
        result = project_rows(ViewContext(tab=4, project="P"), [self.row], [self.job(payload)])[0]
        self.assert_only_fields(self.row, result, {"content"})
        self.assertIn("Remote description", result["content"]["body"])
        self.assertIn("Local comment", result["content"]["body"])
        self.assertEqual(payload, before)
        self.assertEqual(self.row["content"]["body"], "Remote description")

    def test_invalid_operations_are_rejected_before_queueing(self):
        payloads = [
            dict(
                self.common,
                kind="membership",
                field="status",
                value="bug",
                base=False,
                desired=True,
            ),
            dict(
                self.common,
                kind="membership",
                field="labels",
                value="bug",
                base=False,
                desired="yes",
            ),
            dict(
                kind="date",
                args=["project", "item-edit"],
                project={"id": "P"},
                identity="ITEM",
                field_id="F",
                field_name="Due date",
                base="",
                desired="2026-02-30",
            ),
            dict(
                kind="status",
                args=["project", "item-edit"],
                project={"id": "P"},
                identity="ITEM",
                base="Todo",
                desired=True,
            ),
            dict(kind="unknown", args=["bad"]),
            dict(kind="online", args=[]),
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, auth_namespace())
            for payload in payloads:
                with self.subTest(kind=payload["kind"]), self.assertRaises(ValueError):
                    store.enqueue("Invalid", payload)
            self.assertEqual(store.jobs(), [])

    def test_menu_commands_own_frozen_validated_operations(self):
        context = dict(
            self.common, kind="membership", field="labels", value="urgent", base=False, desired=True
        )
        action = Action("Add urgent", ["issue", "edit", "7"], context=context)
        self.assertIsInstance(action.operation, MembershipChange)
        with self.assertRaises(FrozenInstanceError):
            action.operation.desired = False
        context["value"] = "different"
        self.assertEqual(action.operation.value, "urgent")

    def test_legacy_payload_round_trip_keeps_unknown_metadata(self):
        payload = dict(
            self.common,
            kind="comment",
            body="Saved draft",
            marker="<!-- old -->",
            future_metadata={"keep": "me"},
        )
        self.assertEqual(parse_mutation(payload).to_payload(), payload)

    def test_unknown_legacy_job_is_retained_and_never_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, auth_namespace())
            payload = dict(kind="future_operation", args=["do", "not", "send"], draft="Retain me")
            with store.connection() as db:
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                    ("legacy", store.namespace, "Legacy", json.dumps(payload), "pending", "", 1, 1),
                )
            gh = Mock()
            Sync(store, gh).run()
            gh.run.assert_not_called()
            job = store.jobs()[0]
            self.assertEqual(job["payload"], payload)
            self.assertEqual(job["status"], "conflict")
            self.assertIn("Original payload retained", job["note"])
            self.assertEqual(
                store.overlay(json.dumps(dict(tab=4, project="P")), [self.row]), [self.row]
            )

    def test_database_created_with_original_schema_is_read_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            namespace = auth_namespace()
            payload = dict(self.common, kind="comment", body="Pre-refactor draft")
            path = Path(directory) / "workspace.sqlite3"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE snapshots(namespace TEXT,key TEXT,value TEXT,updated REAL,PRIMARY KEY(namespace,key));
                CREATE TABLE history(namespace TEXT,key TEXT,value TEXT,updated REAL);
                CREATE TABLE job_events(id TEXT,namespace TEXT,status TEXT,payload TEXT,note TEXT,created REAL);
                CREATE TABLE jobs(id TEXT PRIMARY KEY,namespace TEXT,label TEXT,payload TEXT,status TEXT,note TEXT,created REAL,updated REAL);
            """)
            key = json.dumps(dict(tab=4, project="P"))
            db.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?)",
                (namespace, key, json.dumps([self.row]), 1),
            )
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                ("old", namespace, "Comment", json.dumps(payload), "pending", "", 1, 1),
            )
            db.commit()
            db.close()
            store = Store(directory, namespace)
            self.assertEqual(store.jobs()[0]["payload"], payload)
            self.assertEqual(store.get(key)[0], [self.row])
            self.assertIn(
                "Pre-refactor draft", store.overlay(key, store.get(key)[0])[0]["content"]["body"]
            )
