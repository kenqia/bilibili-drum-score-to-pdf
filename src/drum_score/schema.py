"""The single supported SQLite service schema; no migration or input SQL execution."""

import re

SCHEMA_VERSION = 1
SCHEMA_STATEMENTS = (
    "CREATE TABLE tasks (\n                  id TEXT PRIMARY KEY, capability_hash TEXT NOT NULL, source TEXT NOT NULL,\n                  ip_key TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL,\n                  created_at REAL NOT NULL, queued_at REAL NOT NULL,\n                  attempt TEXT, completed_at REAL, expires_at REAL,\n                  summary TEXT, error_code TEXT, error_message TEXT\n                )",
    "CREATE TABLE managed_attempts (\n                  task TEXT NOT NULL, attempt TEXT NOT NULL, device INTEGER NOT NULL,\n                  inode INTEGER NOT NULL, files TEXT NOT NULL DEFAULT '[]',\n                  PRIMARY KEY(task,attempt))",
    "CREATE UNIQUE INDEX unfinished_ip ON tasks(ip_key) WHERE state IN ('queued','running','cancelling','finishing')",
    "CREATE UNIQUE INDEX single_active ON tasks((1)) WHERE state IN ('running','cancelling','finishing')",
)


def normalized_sql(sql):
    # SQL keywords ignore case. Quoted string values in partial indexes do not.
    return " ".join(
        "".join(
            fragment if index % 2 else fragment.lower()
            for index, fragment in enumerate(re.split(r"('(?:''|[^'])*')", sql))
        ).split()
    )


def validate_schema(db):
    if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise ValueError("Unsupported service schema")
    expected = {normalized_sql(sql) for sql in SCHEMA_STATEMENTS}
    actual = db.execute(
        "SELECT type,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'"
    ).fetchall()
    if any(row[0] not in ("table", "index") or row[1] is None for row in actual):
        raise ValueError("Unexpected schema object")
    if {normalized_sql(row[1]) for row in actual} != expected:
        raise ValueError("Service schema mismatch")
