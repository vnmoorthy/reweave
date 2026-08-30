"""SQLite-backed registry: sources, versioned specs, proposals, incidents,
events, and impact ledger.

Single-file local mode (mirrors TrueForge's local-mode philosophy: one
process, one SQLite file, zero infrastructure). Every state transition in the
healing lifecycle lands here, which is what makes the audit trail complete:
``events`` is append-only and ``specs`` are immutable versions — a heal never
mutates history, it only adds version N+1 and moves the active pointer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import ExtractionSpec, HealProposal, new_id

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, name TEXT, url TEXT, status TEXT DEFAULT 'unknown',
    golden TEXT, active_version INTEGER DEFAULT 1, last_checked REAL
);
CREATE TABLE IF NOT EXISTS specs (
    source_id TEXT, version INTEGER, spec TEXT,
    PRIMARY KEY (source_id, version)
);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, source_id TEXT, data TEXT, status TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY, source_id TEXT, kind TEXT, detail TEXT,
    status TEXT DEFAULT 'open', opened_at REAL, closed_at REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source_id TEXT,
    level TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS heals (
    id TEXT PRIMARY KEY, source_id TEXT, ts REAL,
    minutes_saved REAL, dollars_saved REAL, approved_by TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, source_id TEXT, ts REAL, row_count INTEGER,
    healthy INTEGER, confidence REAL, provenance TEXT, rows TEXT
);
"""

RUNS_KEPT_PER_SOURCE = 20


def db_path() -> Path:
    p = Path(os.environ.get("REWEAVE_DB", ".reweave/reweave.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Commit-on-success, close-always connection scope."""
    conn = sqlite3.connect(db_path())
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        with conn:  # transaction scope: commits, or rolls back on error
            yield conn
    finally:
        conn.close()


# -- kv ---------------------------------------------------------------------

def kv_get(key: str, default: str | None = None) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(key: str, value: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# -- sources & specs --------------------------------------------------------

def upsert_source(
    source_id: str, name: str, url: str, golden: list[dict[str, Any]], spec: ExtractionSpec
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO sources(id,name,url,golden,active_version,status) "
            "VALUES(?,?,?,?,?,'unknown') "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, url=excluded.url",
            (source_id, name, url, json.dumps(golden), spec.version),
        )
        c.execute(
            "INSERT OR IGNORE INTO specs(source_id,version,spec) VALUES(?,?,?)",
            (source_id, spec.version, json.dumps(spec.to_dict())),
        )


def get_source(source_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["golden"] = json.loads(d["golden"] or "[]")
        return d


def list_sources() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM sources ORDER BY id").fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["golden"] = json.loads(d["golden"] or "[]")
            out.append(d)
        return out


def set_source_status(source_id: str, status: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sources SET status=?, last_checked=? WHERE id=?",
            (status, time.time(), source_id),
        )


def get_active_spec(source_id: str) -> ExtractionSpec | None:
    with _conn() as c:
        row = c.execute(
            "SELECT s.spec FROM specs s JOIN sources src "
            "ON src.id=s.source_id AND src.active_version=s.version "
            "WHERE s.source_id=?",
            (source_id,),
        ).fetchone()
        return ExtractionSpec.from_dict(json.loads(row["spec"])) if row else None


def save_spec(source_id: str, spec: ExtractionSpec, activate: bool = False) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO specs(source_id,version,spec) VALUES(?,?,?)",
            (source_id, spec.version, json.dumps(spec.to_dict())),
        )
        if activate:
            c.execute(
                "UPDATE sources SET active_version=? WHERE id=?",
                (spec.version, source_id),
            )


def activate_version(source_id: str, version: int) -> None:
    """Move the active pointer to an existing historical version (rollback)."""
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM specs WHERE source_id=? AND version=?", (source_id, version)
        ).fetchone()
        if row is None:
            raise KeyError(f"source {source_id} has no spec v{version}")
        c.execute(
            "UPDATE sources SET active_version=? WHERE id=?", (version, source_id)
        )


def spec_history(source_id: str) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT version, spec FROM specs WHERE source_id=? ORDER BY version",
            (source_id,),
        ).fetchall()
        return [json.loads(r["spec"]) for r in rows]


# -- proposals --------------------------------------------------------------

def add_proposal(p: HealProposal) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO proposals(id,source_id,data,status,created_at) "
            "VALUES(?,?,?,?,?)",
            (p.id, p.source_id, json.dumps(p.to_dict()), p.status, p.created_at),
        )


def get_proposal(pid: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM proposals WHERE id=?", (pid,)).fetchone()
        return json.loads(row["data"]) if row else None


def set_proposal_status(pid: str, status: str, actor: str | None) -> None:
    with _conn() as c:
        row = c.execute("SELECT data FROM proposals WHERE id=?", (pid,)).fetchone()
        if not row:
            return
        data = json.loads(row["data"])
        data["status"] = status
        data["resolved_at"] = time.time()
        data["resolved_by"] = actor
        c.execute(
            "UPDATE proposals SET status=?, data=? WHERE id=?",
            (status, json.dumps(data), pid),
        )


def pending_proposals(source_id: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT data FROM proposals WHERE status='pending'"
    args: tuple = ()
    if source_id:
        q += " AND source_id=?"
        args = (source_id,)
    with _conn() as c:
        return [json.loads(r["data"]) for r in c.execute(q + " ORDER BY created_at", args)]


# -- incidents --------------------------------------------------------------

def open_incident(source_id: str, kind: str, detail: str) -> str:
    existing = [
        i for i in list_incidents(source_id) if i["status"] == "open" and i["kind"] == kind
    ]
    if existing:
        return existing[0]["id"]
    iid = new_id("inc")
    with _conn() as c:
        c.execute(
            "INSERT INTO incidents(id,source_id,kind,detail,status,opened_at) "
            "VALUES(?,?,?,?,'open',?)",
            (iid, source_id, kind, detail, time.time()),
        )
    return iid


def close_incidents(source_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE incidents SET status='resolved', closed_at=? "
            "WHERE source_id=? AND status='open'",
            (time.time(), source_id),
        )


def list_incidents(source_id: str | None = None) -> list[dict[str, Any]]:
    q = "SELECT * FROM incidents"
    args: tuple = ()
    if source_id:
        q += " WHERE source_id=?"
        args = (source_id,)
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY opened_at DESC", args)]


# -- runs (the data itself) -------------------------------------------------

def record_run(
    source_id: str,
    rows: list[dict[str, Any]],
    healthy: bool,
    confidence: float,
    provenance: str,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO runs(id,source_id,ts,row_count,healthy,confidence,provenance,rows) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                new_id("run"),
                source_id,
                time.time(),
                len(rows),
                int(healthy),
                confidence,
                provenance,
                json.dumps(rows),
            ),
        )
        c.execute(
            "DELETE FROM runs WHERE source_id=? AND id NOT IN "
            "(SELECT id FROM runs WHERE source_id=? ORDER BY ts DESC LIMIT ?)",
            (source_id, source_id, RUNS_KEPT_PER_SOURCE),
        )


def latest_run(source_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM runs WHERE source_id=? ORDER BY ts DESC LIMIT 1", (source_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["rows"] = json.loads(d["rows"] or "[]")
        d["healthy"] = bool(d["healthy"])
        return d


def run_history(source_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, ts, row_count, healthy, confidence, provenance FROM runs "
            "WHERE source_id=? ORDER BY ts DESC LIMIT ?",
            (source_id, limit),
        ).fetchall()
        return [dict(r) | {"healthy": bool(r["healthy"])} for r in rows]


def remove_source(source_id: str) -> None:
    with _conn() as c:
        for table in ("sources", "specs", "proposals", "incidents", "runs"):
            c.execute(f"DELETE FROM {table} WHERE {'id' if table == 'sources' else 'source_id'}=?", (source_id,))


# -- events & impact --------------------------------------------------------

def log_event(source_id: str, level: str, message: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO events(ts,source_id,level,message) VALUES(?,?,?,?)",
            (time.time(), source_id, level, message),
        )


def recent_events(limit: int = 60) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def record_heal(
    source_id: str, minutes_saved: float, dollars_saved: float, approved_by: str
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO heals(id,source_id,ts,minutes_saved,dollars_saved,approved_by) "
            "VALUES(?,?,?,?,?,?)",
            (new_id("healrec"), source_id, time.time(), minutes_saved, dollars_saved, approved_by),
        )


def ops_counters() -> dict[str, float]:
    """Aggregate counters for /metrics — cheap COUNT queries, no state kept."""
    with _conn() as c:
        runs = c.execute("SELECT COUNT(*) AS n FROM events WHERE level='run'").fetchone()["n"]
        drift = c.execute("SELECT COUNT(*) AS n FROM events WHERE level='drift'").fetchone()["n"]
        pending = c.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE status='pending'"
        ).fetchone()["n"]
        open_inc = c.execute(
            "SELECT COUNT(*) AS n FROM incidents WHERE status='open'"
        ).fetchone()["n"]
        by_status: dict[str, float] = {}
        for row in c.execute("SELECT status, COUNT(*) AS n FROM sources GROUP BY status"):
            by_status[row["status"]] = row["n"]
        heals = c.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(minutes_saved),0) AS m, "
            "COALESCE(SUM(dollars_saved),0) AS d FROM heals"
        ).fetchone()
        return {
            "runs_total": runs,
            "drift_detected_total": drift,
            "heals_deployed_total": heals["n"],
            "engineer_minutes_saved_total": heals["m"],
            "dollars_saved_total": heals["d"],
            "pending_heals": pending,
            "open_incidents": open_inc,
            **{f"sources_{k}": v for k, v in by_status.items()},
        }


def impact_totals() -> dict[str, Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS heals, COALESCE(SUM(minutes_saved),0) AS minutes, "
            "COALESCE(SUM(dollars_saved),0) AS dollars FROM heals"
        ).fetchone()
        return {
            "heals": row["heals"],
            "engineer_minutes_saved": round(row["minutes"], 1),
            "dollars_saved": round(row["dollars"], 2),
        }


def reset() -> None:
    p = db_path()
    if p.exists():
        p.unlink()
