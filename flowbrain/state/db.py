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


def get_outcome_metrics() -> dict:
    """Return compact local evidence about preview-vs-execute outcomes."""
    with get_db() as conn:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS total_runs,
                SUM(CASE WHEN auto_execute = 1 THEN 1 ELSE 0 END) AS auto_execute_requests,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS executed_successes,
                SUM(CASE WHEN success = 0 AND auto_execute = 1 AND needs_webhook = 1 THEN 1 ELSE 0 END) AS missing_webhook_blocks,
                SUM(CASE WHEN success = 0 AND auto_execute = 0 THEN 1 ELSE 0 END) AS preview_only_runs,
                SUM(CASE WHEN success = 0 AND auto_execute = 1 AND needs_webhook = 0 THEN 1 ELSE 0 END) AS blocked_or_failed_runs,
                AVG(duration_ms) AS avg_duration_ms
            FROM runs
            """
        ).fetchone()

        preview_totals = conn.execute(
            "SELECT COUNT(*) AS total_previews, SUM(CASE WHEN blocked = 1 THEN 1 ELSE 0 END) AS blocked_previews FROM previews"
        ).fetchone()

        risk_rows = conn.execute(
            "SELECT risk_level, COUNT(*) AS count FROM runs GROUP BY risk_level ORDER BY count DESC"
        ).fetchall()

    total_runs = int(totals["total_runs"] or 0)
    auto_execute_requests = int(totals["auto_execute_requests"] or 0)
    executed_successes = int(totals["executed_successes"] or 0)
    missing_webhook_blocks = int(totals["missing_webhook_blocks"] or 0)
    preview_only_runs = int(totals["preview_only_runs"] or 0)
    blocked_or_failed_runs = int(totals["blocked_or_failed_runs"] or 0)
    total_previews = int(preview_totals["total_previews"] or 0)
    blocked_previews = int(preview_totals["blocked_previews"] or 0)

    executed_success_rate = round(executed_successes / auto_execute_requests, 3) if auto_execute_requests else None
    preview_block_rate = round(blocked_previews / total_previews, 3) if total_previews else None

    return {
        "total_runs": total_runs,
        "auto_execute_requests": auto_execute_requests,
        "executed_successes": executed_successes,
        "missing_webhook_blocks": missing_webhook_blocks,
        "preview_only_runs": preview_only_runs,
        "blocked_or_failed_runs": blocked_or_failed_runs,
        "total_previews": total_previews,
        "blocked_previews": blocked_previews,
        "executed_success_rate": executed_success_rate,
        "preview_block_rate": preview_block_rate,
        "avg_duration_ms": round(float(totals["avg_duration_ms"] or 0.0), 1),
        "risk_breakdown": {row["risk_level"] or "unknown": int(row["count"] or 0) for row in risk_rows},
        "note": "Local runtime evidence from FlowBrain's SQLite state; not a benchmark or claim about general agent reliability.",
    }


def record_doctor(checks: list[dict], passed: int, failed: int, warnings: int):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO doctor_results (id, created_at, checks, passed, failed, warnings)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (f"doc_{uuid.uuid4().hex[:12]}", _now(), json.dumps(checks), passed, failed, warnings),
        )
