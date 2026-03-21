"""
SQLite-backed durable state for FlowBrain.

Stores run history, preview history, and doctor results.
Database is created automatically at data/flowbrain.db.
"""

import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

from flowbrain.config import get_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    intent TEXT NOT NULL,
    workflow_id TEXT,
    workflow_name TEXT,
    confidence REAL,
    params TEXT,
    auto_execute INTEGER,
    success INTEGER,
    execution_result TEXT,
    error_message TEXT,
    needs_webhook INTEGER DEFAULT 0,
    source_url TEXT,
    duration_ms INTEGER,
    risk_level TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS previews (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    intent TEXT NOT NULL,
    workflow_id TEXT,
    workflow_name TEXT,
    confidence REAL,
    params TEXT,
    risk_level TEXT,
    systems_affected TEXT,
    blocked INTEGER DEFAULT 0,
    block_reason TEXT
);

CREATE TABLE IF NOT EXISTS doctor_results (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    checks TEXT NOT NULL,
    passed INTEGER NOT NULL,
    failed INTEGER NOT NULL,
    warnings INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
CREATE INDEX IF NOT EXISTS idx_previews_created ON previews(created_at);
"""


def _db_path() -> str:
    cfg = get_config()
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    return cfg.db_path


def _init_db(conn: sqlite3.Connection):
    conn.executescript(_SCHEMA)


@contextmanager
def get_db():
    """Get a database connection with auto-init."""
    path = _db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def new_preview_id() -> str:
    return f"prev_{uuid.uuid4().hex[:12]}"


def record_run(
    run_id: str,
    intent: str,
    workflow_id: str = "",
    workflow_name: str = "",
    confidence: float = 0.0,
    params: dict | None = None,
    auto_execute: bool = False,
    success: bool = False,
    execution_result: dict | None = None,
    error_message: str = "",
    needs_webhook: bool = False,
    source_url: str = "",
    duration_ms: int = 0,
    risk_level: str = "unknown",
):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO runs (id, created_at, intent, workflow_id, workflow_name,
               confidence, params, auto_execute, success, execution_result,
               error_message, needs_webhook, source_url, duration_ms, risk_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, _now(), intent, workflow_id, workflow_name,
                confidence, json.dumps(params or {}), int(auto_execute),
                int(success), json.dumps(execution_result or {}),
                error_message, int(needs_webhook), source_url,
                duration_ms, risk_level,
            ),
        )


def record_preview(
    preview_id: str,
    intent: str,
    workflow_id: str = "",
    workflow_name: str = "",
    confidence: float = 0.0,
    params: dict | None = None,
    risk_level: str = "unknown",
    systems_affected: list[str] | None = None,
    blocked: bool = False,
    block_reason: str = "",
):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO previews (id, created_at, intent, workflow_id, workflow_name,
               confidence, params, risk_level, systems_affected, blocked, block_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                preview_id, _now(), intent, workflow_id, workflow_name,
                confidence, json.dumps(params or {}), risk_level,
                json.dumps(systems_affected or []), int(blocked), block_reason,
            ),
        )


def get_recent_runs(limit: int = 20) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_previews(limit: int = 20) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM previews ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def record_doctor(checks: list[dict], passed: int, failed: int, warnings: int):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO doctor_results (id, created_at, checks, passed, failed, warnings)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"doc_{uuid.uuid4().hex[:12]}", _now(), json.dumps(checks), passed, failed, warnings),
        )
