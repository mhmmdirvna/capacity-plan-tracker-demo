"""SQLite storage. Status records are append-only (one row per document per run) for audit."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .models import DocResult, DocStatus, MpmPage, TrackedDocument

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                 -- run | publish
  started_at TEXT NOT NULL,
  finished_at TEXT,
  responses_new INTEGER DEFAULT 0,
  docs_read INTEGER DEFAULT 0,
  result TEXT,
  published_run_id INTEGER
);
CREATE TABLE IF NOT EXISTS submissions (
  response_id TEXT PRIMARY KEY,
  submitted_at TEXT, email TEXT, name TEXT,
  values_json TEXT, errors_json TEXT, skipped TEXT, late INTEGER, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS documents (
  key TEXT PRIMARY KEY,
  app TEXT, departemen TEXT, period INTEGER, doc_type TEXT, method TEXT,
  link TEXT, pdf TEXT, response_id TEXT, submitted_at TEXT,
  superseded_by TEXT, created_run INTEGER
);
CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_key TEXT, run_id INTEGER, html_path TEXT, png_path TEXT, header_json TEXT
);
CREATE TABLE IF NOT EXISTS approval_rows (
  snapshot_id INTEGER, idx INTEGER, section INTEGER, role TEXT, name TEXT, raw_status TEXT,
  request_date TEXT, response_date TEXT, PRIMARY KEY (snapshot_id, idx)
);
CREATE TABLE IF NOT EXISTS document_status (
  doc_key TEXT, run_id INTEGER, status TEXT, reason TEXT, pending_text TEXT,
  request_date TEXT, fso_date TEXT, lead_time_hours REAL, pending_since TEXT,
  validation_json TEXT, flags_json TEXT, error_code TEXT,
  PRIMARY KEY (doc_key, run_id)
);
CREATE TABLE IF NOT EXISTS application_status (
  app TEXT, period INTEGER, run_id INTEGER, departemen TEXT, status TEXT,
  cpr_status TEXT, cpd_status TEXT, detail_json TEXT,
  PRIMARY KEY (app, period, run_id)
);
CREATE TABLE IF NOT EXISTS errors (
  error_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER, code TEXT, doc_key TEXT, message TEXT, at TEXT,
  resolved_by TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS master_versions (
  version_id INTEGER PRIMARY KEY AUTOINCREMENT,
  uploaded_at TEXT, uploaded_by TEXT, file_hash TEXT, file_path TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS published (
  publish_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL, published_at TEXT NOT NULL
);
"""


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # runs
    def start_run(self, kind: str, now: datetime) -> int:
        with self.tx() as c:
            return c.execute("INSERT INTO runs(kind, started_at) VALUES (?, ?)", (kind, _iso(now))).lastrowid

    def finish_run(self, run_id: int, now: datetime, result: str, responses_new=0, docs_read=0, published_run_id=None):
        with self.tx() as c:
            c.execute(
                "UPDATE runs SET finished_at=?, result=?, responses_new=?, docs_read=?, published_run_id=? WHERE run_id=?",
                (_iso(now), result, responses_new, docs_read, published_run_id, run_id),
            )

    def add_error(self, run_id: int, code: str, message: str, now: datetime, doc_key: str = ""):
        with self.tx() as c:
            c.execute(
                "INSERT INTO errors(run_id, code, doc_key, message, at) VALUES (?, ?, ?, ?, ?)",
                (run_id, code, doc_key, message, _iso(now)),
            )

    def resolve_error(self, error_id: int, admin: str, now: datetime):
        with self.tx() as c:
            c.execute("UPDATE errors SET resolved_by=?, resolved_at=? WHERE error_id=?", (admin, _iso(now), error_id))

    # submissions and documents
    def has_submission(self, response_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM submissions WHERE response_id=?", (response_id,)).fetchone() is not None

    def add_submission(self, sub, run_id: int):
        with self.tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO submissions VALUES (?,?,?,?,?,?,?,?,?)",
                (sub.response_id, _iso(sub.submitted_at), sub.email, sub.name, json.dumps(sub.values),
                 json.dumps(sub.errors), sub.skipped, int(sub.late), run_id),
            )

    def add_document(self, doc: TrackedDocument, run_id: int):
        """Insert a document; an older active document of the same app × period × type becomes Superseded."""
        with self.tx() as c:
            if c.execute("SELECT 1 FROM documents WHERE key=?", (doc.key,)).fetchone():
                return
            c.execute(
                "UPDATE documents SET superseded_by=? WHERE app=? AND period=? AND doc_type=? AND superseded_by IS NULL",
                (doc.key, doc.app, doc.period, doc.doc_type),
            )
            c.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)",
                (doc.key, doc.app, doc.departemen, doc.period, doc.doc_type, doc.method, doc.link, doc.pdf,
                 doc.response_id, _iso(doc.submitted_at), run_id),
            )

    def active_documents(self, period: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM documents WHERE period=? AND superseded_by IS NULL ORDER BY app, doc_type", (period,)
        ).fetchall()

    def latest_status(self, doc_key: str) -> DocStatus | None:
        r = self.conn.execute(
            "SELECT status FROM document_status WHERE doc_key=? ORDER BY run_id DESC LIMIT 1", (doc_key,)
        ).fetchone()
        return DocStatus(r["status"]) if r else None

    def latest_result_row(self, doc_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM document_status WHERE doc_key=? ORDER BY run_id DESC LIMIT 1", (doc_key,)
        ).fetchone()

    # MPM snapshots and statuses
    def add_snapshot(self, doc_key: str, run_id: int, page: MpmPage | None, html_path: str, png_path: str) -> int:
        header = (
            {"doc_id": page.doc_id, "project_name": page.project_name, "flow_badge": page.flow_badge,
             "status_badge": page.status_badge, "main_document": page.main_document}
            if page else {}
        )
        with self.tx() as c:
            sid = c.execute(
                "INSERT INTO snapshots(doc_key, run_id, html_path, png_path, header_json) VALUES (?,?,?,?,?)",
                (doc_key, run_id, html_path, png_path, json.dumps(header)),
            ).lastrowid
            for i, r in enumerate(page.rows if page else ()):
                c.execute(
                    "INSERT INTO approval_rows VALUES (?,?,?,?,?,?,?,?)",
                    (sid, i, r.section, r.role, r.name, r.raw_status, _iso(r.request_date), _iso(r.response_date)),
                )
            return sid

    def add_status(self, doc_key: str, run_id: int, res: DocResult):
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO document_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_key, run_id, res.status.value, res.reason, res.pending_text, _iso(res.request_date),
                 _iso(res.fso_date), res.lead_time_hours, _iso(res.pending_since),
                 json.dumps([{"section": v.section, "jabatan": v.jabatan, "name": v.name,
                              "result": v.result.value, "basis": v.basis} for v in res.validation]),
                 json.dumps(res.flags), res.error_code),
            )

    def add_app_status(self, app: str, period: int, run_id: int, departemen: str, status: str,
                       cpr: str | None, cpd: str | None, detail: dict):
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO application_status VALUES (?,?,?,?,?,?,?,?)",
                (app, period, run_id, departemen, status, cpr, cpd, json.dumps(detail)),
            )

    # publish
    def last_completed_run(self) -> int | None:
        r = self.conn.execute(
            "SELECT run_id FROM runs WHERE kind='run' AND finished_at IS NOT NULL "
            "AND result NOT IN ('stopped', 'failed') ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        return r["run_id"] if r else None

    def publish(self, run_id: int, now: datetime):
        """Atomic: the dashboard switches to run_id in one insert, or not at all."""
        with self.tx() as c:
            c.execute("INSERT INTO published(run_id, published_at) VALUES (?, ?)", (run_id, _iso(now)))

    def published_run(self) -> sqlite3.Row | None:
        """Latest publish, with run_started_at = when that data was actually read (may be older than published_at)."""
        return self.conn.execute(
            "SELECT p.*, r.started_at AS run_started_at FROM published p JOIN runs r ON r.run_id = p.run_id "
            "ORDER BY p.publish_id DESC LIMIT 1"
        ).fetchone()

    def failed_runs_after(self, run_id: int) -> list[sqlite3.Row]:
        """Runs newer than the published one that stopped or failed, i.e. why the dashboard data is stale."""
        return self.conn.execute(
            "SELECT * FROM runs WHERE kind='run' AND run_id > ? AND result IN ('stopped', 'failed') ORDER BY run_id",
            (run_id,),
        ).fetchall()

    # master data versions
    def add_master_version(self, now: datetime, by: str, file_hash: str, file_path: str, summary: str) -> int:
        with self.tx() as c:
            return c.execute(
                "INSERT INTO master_versions(uploaded_at, uploaded_by, file_hash, file_path, summary) VALUES (?,?,?,?,?)",
                (_iso(now), by, file_hash, file_path, summary),
            ).lastrowid

    def active_master_path(self) -> str | None:
        r = self.conn.execute("SELECT file_path FROM master_versions ORDER BY version_id DESC LIMIT 1").fetchone()
        return r["file_path"] if r else None
