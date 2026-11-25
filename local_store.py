# SPDX-License-Identifier: Apache-2.0
"""Durable local snapshots and outbox persistence; no terminal dependencies."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from mutations import JobStatus, parse_mutation
from projections import ViewContext, project_rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS account_bindings (
    fingerprint TEXT PRIMARY KEY, account TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
                    namespace TEXT, key TEXT, value TEXT, updated REAL,
                    PRIMARY KEY(namespace, key));
                CREATE TABLE IF NOT EXISTS history (
                    namespace TEXT, key TEXT, value TEXT, updated REAL);
                CREATE TABLE IF NOT EXISTS job_events (
                    id TEXT, namespace TEXT, status TEXT, payload TEXT, note TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, namespace TEXT, label TEXT, payload TEXT,
                    status TEXT, note TEXT, created REAL, updated REAL);
            
CREATE INDEX IF NOT EXISTS jobs_by_namespace_status ON jobs(namespace,status,created);
CREATE INDEX IF NOT EXISTS events_by_job ON job_events(namespace,id,created);
"""


class Store:
    def __init__(self, directory, namespace):
        directory = Path(directory).expanduser()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path, self.namespace = (directory / "workspace.sqlite3", namespace)
        self.credential_namespace = namespace
        with self.connection() as db:
            db.executescript(SCHEMA)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def use_account_binding(self):
        """Offline lookup never guesses which account owns a legacy workspace."""
        with self.connection() as db:
            row = db.execute(
                "SELECT account FROM account_bindings WHERE fingerprint=?",
                (self.credential_namespace,),
            ).fetchone()
        if row:
            self.namespace = row["account"]

    def bind_account(self, account):
        """Atomically adopt this credential's legacy data and remember its owner.

        Snapshot collisions keep the latest value; history and job journals retain
        every record. A previously bound fingerprint never transfers another
        verified account's work (e.g. an OS keychain account switch).
        """
        legacy = self.credential_namespace
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            bound = db.execute(
                "SELECT account FROM account_bindings WHERE fingerprint=?", (legacy,)
            ).fetchone()
            if not bound or bound["account"] == account:
                db.execute(
                    "INSERT INTO snapshots SELECT ?,key,value,updated FROM snapshots "
                    "WHERE namespace=? "
                    "ON CONFLICT(namespace,key) DO UPDATE SET value=excluded.value, "
                    "updated=excluded.updated WHERE excluded.updated > snapshots.updated",
                    (account, legacy),
                )
                db.execute("DELETE FROM snapshots WHERE namespace=?", (legacy,))
                for table in ("history", "jobs", "job_events"):
                    db.execute(
                        f"UPDATE {table} SET namespace=? WHERE namespace=?", (account, legacy)
                    )
            db.execute("INSERT OR REPLACE INTO account_bindings VALUES (?,?)", (legacy, account))
        self.namespace = account

    def get(self, key):
        with self.connection() as db:
            row = db.execute(
                "SELECT value,updated FROM snapshots WHERE namespace=? AND key=?",
                (self.namespace, key),
            ).fetchone()
        return (json.loads(row["value"]), row["updated"]) if row else (None, 0)

    def put(self, key, value):
        encoded, now = (json.dumps(value), time.time())
        with self.connection() as db:
            db.execute("INSERT INTO history VALUES (?,?,?,?)", (self.namespace, key, encoded, now))
            db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                (self.namespace, key, encoded, now),
            )

    def expire(self, key):
        with self.connection() as db:
            db.execute(
                "UPDATE snapshots SET updated=0 WHERE namespace=? AND key=?", (self.namespace, key)
            )

    def enqueue(self, label, payload):
        identifier, now = (uuid.uuid4().hex, time.time())
        payload = parse_mutation(payload).to_payload()
        args = payload["args"]
        if args[:2] in (["issue", "create"], ["issue", "comment"], ["pr", "comment"]):
            marker = f"<!-- gh-desk:{identifier} -->"
            args[args.index("--body") + 1] += "\n\n" + marker
            payload["marker"] = marker
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            target = payload.get("target")
            if target and payload["kind"] in (
                "state",
                "status",
                "date",
                "membership",
                "project_remove",
                "add",
            ):
                others = db.execute(
                    "SELECT payload FROM jobs WHERE namespace=? AND status NOT IN ('done','archived')",
                    (self.namespace,),
                ).fetchall()
                if any(json.loads(r["payload"]).get("target") == target for r in others):
                    raise ValueError(
                        "This item already has an unsynced edit. Resolve it in the outbox (o) first."
                    )
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                (identifier, self.namespace, label, json.dumps(payload), "pending", "", now, now),
            )
            db.execute(
                "INSERT INTO job_events VALUES (?,?,?,?,?,?)",
                (identifier, self.namespace, "pending", json.dumps(payload), "", now),
            )
        return identifier

    def finish_create(self, identifier, url, note):
        """Commit the issue URL and its unique Project-link dependency together."""
        if not re.fullmatch("https://[^/]+/[\\w.-]+/[\\w.-]+/issues/\\d+", url):
            raise ValueError(
                "Issue creation returned no verifiable issue URL. Check the outbox; it will not be recreated."
            )
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload,status FROM jobs WHERE id=? AND namespace=?",
                (identifier, self.namespace),
            ).fetchone()
            if not row or row["status"] == "archived":
                return
            payload = json.loads(row["payload"])
            payload["result_url"] = url
            project = payload.get("project")
            if project:
                child_id = identifier + "-project"
                child = dict(
                    kind="add",
                    args=[
                        "project",
                        "item-add",
                        str(project["number"]),
                        "--owner",
                        payload.get("project_owner") or "@me",
                        "--url",
                        url,
                    ],
                    project=project,
                    project_owner=payload.get("project_owner") or "@me",
                    url=url,
                    repo=payload["repo"],
                    tab=1,
                    parent=identifier,
                    title=payload["title"],
                    body=payload["body"],
                )
                inserted = db.execute(
                    "INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                    (
                        child_id,
                        self.namespace,
                        "Add created issue to " + project.get("title", "Project"),
                        json.dumps(child),
                        "pending",
                        "",
                        now,
                        now,
                    ),
                ).rowcount
                if inserted:
                    db.execute(
                        "INSERT INTO job_events VALUES (?,?,?,?,?,?)",
                        (
                            child_id,
                            self.namespace,
                            "pending",
                            json.dumps(child),
                            "Issue creation completed; link is a separate durable step.",
                            now,
                        ),
                    )
            encoded = json.dumps(payload)
            db.execute(
                "UPDATE jobs SET status='done',payload=?,note=?,updated=? WHERE id=? AND namespace=?",
                (encoded, note, now, identifier, self.namespace),
            )
            db.execute(
                "INSERT INTO job_events VALUES (?,?,?,?,?,?)",
                (identifier, self.namespace, "done", encoded, note, now),
            )

    def jobs(self, active=True):
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE namespace=? "
                + ("AND status NOT IN ('done','archived') " if active else "")
                + "ORDER BY created",
                (self.namespace,),
            ).fetchall()
        return [dict(r, payload=json.loads(r["payload"])) for r in rows]

    def update(self, identifier, status, note="", payload=None):
        status = JobStatus(status).value
        with self.connection() as db:
            if payload is None:
                db.execute(
                    "UPDATE jobs SET status=?,note=?,updated=? WHERE id=? AND namespace=?",
                    (status, note, time.time(), identifier, self.namespace),
                )
            else:
                db.execute(
                    "UPDATE jobs SET status=?,note=?,payload=?,updated=? WHERE id=? AND namespace=?",
                    (status, note, json.dumps(payload), time.time(), identifier, self.namespace),
                )
            row = db.execute(
                "SELECT payload FROM jobs WHERE id=? AND namespace=?", (identifier, self.namespace)
            ).fetchone()
            if row:
                db.execute(
                    "INSERT INTO job_events VALUES (?,?,?,?,?,?)",
                    (identifier, self.namespace, status, row["payload"], note, time.time()),
                )

    def audit(self, identifier):
        with self.connection() as db:
            return [
                dict(row, payload=json.loads(row["payload"]))
                for row in db.execute(
                    "SELECT * FROM job_events WHERE id=? AND namespace=? ORDER BY created",
                    (identifier, self.namespace),
                )
            ]

    def claim(self, identifier):
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE jobs SET status='sending',updated=? WHERE id=? AND namespace=? AND status='pending'",
                    (time.time(), identifier, self.namespace),
                ).rowcount
                == 1
            )

    def overlay(self, key, rows):
        context = json.loads(key)
        _, fetched = self.get(key)
        view = ViewContext(
            tab=context["tab"],
            repo=context.get("repo"),
            project=context.get("project"),
            state=context.get("state", "open"),
        )
        return project_rows(view, rows, self.jobs(active=False), fetched)
