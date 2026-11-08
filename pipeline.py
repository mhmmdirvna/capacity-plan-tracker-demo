"""One run (ingest → read MPM → rules → staging) and one publish."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .master_data import MasterData
from .models import REREAD_STATUSES, DocResult, DocStatus
from .msform import read_responses, validate_submission
from .parser import ParseError, parse_approval_page
from .rules import RulesConfig, application_status, evaluate_document, wet_sign_result
from .scraper import Fetcher, LoginError, PageError
from .store import Store

log = logging.getLogger("cptracker")


@dataclass
class RunSummary:
    run_id: int
    responses_new: int = 0
    docs_read: int = 0
    errors: list[str] = field(default_factory=list)
    stopped: bool = False


def ingest(cfg, store: Store, md: MasterData, run_id: int, now: datetime) -> int:
    subs = read_responses(cfg.path("msform_responses"), cfg.form_mapping, cfg.tz)
    new = [s for s in subs if s.response_id and not store.has_submission(s.response_id)]
    new.sort(key=lambda s: (s.submitted_at or now))
    for sub in new:
        validate_submission(sub, md, cfg.form_mapping, cfg.cycle_year, cfg.settings["doc_id_pattern"], cfg.deadline)
        store.add_submission(sub, run_id)
        if sub.valid:
            for doc in sub.documents:
                store.add_document(doc, run_id)
    return len(new)


def run_once(cfg, store: Store, md: MasterData, fetcher: Fetcher, now: datetime) -> RunSummary:
    run_id = store.start_run("run", now)
    summary = RunSummary(run_id)
    try:
        _run_body(cfg, store, md, fetcher, now, summary)
    except BaseException:
        # Unexpected crash (browser died, bug): close the run as failed so it is never published, then re-raise.
        store.finish_run(run_id, now, "failed", summary.responses_new, summary.docs_read)
        raise
    store.finish_run(
        run_id, now, "stopped" if summary.stopped else ("ok_with_errors" if summary.errors else "ok"),
        summary.responses_new, summary.docs_read,
    )
    return summary


def _run_body(cfg, store: Store, md: MasterData, fetcher: Fetcher, now: datetime, summary: RunSummary) -> None:
    run_id = summary.run_id
    rcfg = RulesConfig.from_config(cfg)

    try:
        summary.responses_new = ingest(cfg, store, md, run_id, now)
    except Exception as exc:  # file locked, missing, unreadable
        store.add_error(run_id, "E-SOURCE", f"File response msForm tidak bisa dibaca: {exc}", now)
        summary.errors.append("E-SOURCE")

    for doc in store.active_documents(cfg.cycle_year):
        app = md.apps.get(doc["app"])
        if app is None:
            log.warning("Aplikasi %s tidak ada di master data aktif; dokumen %s dilewati", doc["app"], doc["key"])
            continue
        last = store.latest_status(doc["key"])
        if doc["method"] == "WET":
            if last is None:
                store.add_status(doc["key"], run_id, wet_sign_result())
            continue
        if last is not None and last not in REREAD_STATUSES:
            continue  # FSO, REJECTED, CANCELLED: never read again
        try:
            fetched = fetcher.fetch(doc["key"], doc["link"], run_id)
            summary.docs_read += 1
            page = parse_approval_page(fetched.html, cfg.selectors, cfg.tz)
            store.add_snapshot(doc["key"], run_id, page, fetched.html_path, fetched.png_path)
            result = evaluate_document(page, app, md, rcfg, now)
            if result.error_code:
                store.add_error(run_id, result.error_code, f"{result.reason} di {doc['key']}", now, doc["key"])
                summary.errors.append(result.error_code)
        except LoginError as exc:
            store.add_error(run_id, "E-LOGIN", f"Tidak bisa masuk ke MPM. Run dihentikan supaya akun tidak terkunci. ({exc})", now)
            summary.errors.append("E-LOGIN")
            summary.stopped = True
            break
        except PageError as exc:
            result = DocResult(DocStatus.ERROR, reason=str(exc), error_code="E-PAGE")
            store.add_error(run_id, "E-PAGE", f"Halaman approval {doc['key']} tidak bisa dibuka.", now, doc["key"])
            summary.errors.append("E-PAGE")
        except ParseError as exc:
            store.add_snapshot(doc["key"], run_id, None, fetched.html_path, fetched.png_path)
            result = DocResult(DocStatus.ERROR, reason=str(exc), error_code="E-PARSE")
            store.add_error(run_id, "E-PARSE", f"Format halaman {doc['key']} tidak dikenali: {exc}", now, doc["key"])
            summary.errors.append("E-PARSE")
        store.add_status(doc["key"], run_id, result)

    if not summary.stopped:
        compute_app_statuses(cfg, store, md, run_id, now)


def compute_app_statuses(cfg, store: Store, md: MasterData, run_id: int, now: datetime) -> None:
    docs_by_app: dict[str, list] = {}
    for d in store.active_documents(cfg.cycle_year):
        docs_by_app.setdefault(d["app"], []).append(d)
    for app in md.live_apps():
        docs = docs_by_app.get(app.name, [])
        detail, statuses, per_type = {}, [], {}
        for d in docs:
            row = store.latest_result_row(d["key"])
            if row is None:
                continue
            st = DocStatus(row["status"])
            statuses.append(st)
            per_type[d["doc_type"]] = st.value
            detail[d["doc_type"]] = {
                "key": d["key"], "method": d["method"], "status": st.value, "reason": row["reason"],
                "pending_text": row["pending_text"], "request_date": row["request_date"],
                "fso_date": row["fso_date"], "pending_since": row["pending_since"], "flags": row["flags_json"],
                "submitted_at": d["submitted_at"],
            }
        has_cpr = any(d["doc_type"] == "CPR" for d in docs)
        st = application_status(statuses, has_cpr, now, cfg.deadline)
        store.add_app_status(app.name, cfg.cycle_year, run_id, app.departemen, st.value,
                             per_type.get("CPR"), per_type.get("CPD"), detail)


def publish(store: Store, now: datetime) -> int | None:
    pid = store.start_run("publish", now)
    run_id = store.last_completed_run()
    if run_id is None:
        store.add_error(pid, "E-PUBLISH", "Publish gagal: belum ada run yang selesai di staging.", now)
        store.finish_run(pid, now, "failed")
        return None
    store.publish(run_id, now)
    store.finish_run(pid, now, "ok", published_run_id=run_id)
    return run_id
