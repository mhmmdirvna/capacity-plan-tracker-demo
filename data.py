"""Read models for the dashboard: everything the pages show, computed from the store without Streamlit.

Kept free of UI code so it is unit-tested like the rules engine. All numbers come from the PUBLISHED run.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..master_data import MasterData
from ..models import AppStatus
from ..rules import section_jabatan
from ..store import Store

BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

# Status groups shown on the dashboard, in display order (key, label).
GROUPS = [
    ("fso", "FSO"),
    ("pending", "Pending"),
    ("rej", "Rejected / Cancelled"),
    ("review", "Perlu review"),
    ("belum", "Belum submit"),
]
GROUP_LABEL = dict(GROUPS)
GROUP_OF = {
    AppStatus.FSO.value: "fso",
    AppStatus.PENDING.value: "pending",
    AppStatus.REJECTED.value: "rej",
    AppStatus.CANCELLED.value: "rej",
    AppStatus.ANOMALY.value: "review",
    AppStatus.INCOMPLETE_CHAIN.value: "review",
    AppStatus.ERROR.value: "review",
    AppStatus.BELUM_SUBMIT.value: "belum",
    AppStatus.OVERDUE.value: "belum",
}
STATUS_LABEL = {
    "FSO": "FSO", "WET_SIGN": "Tanda tangan basah", "PENDING": "Pending", "REJECTED": "Rejected",
    "CANCELLED": "Cancelled", "ANOMALY": "Anomaly", "INCOMPLETE_CHAIN": "Chain belum lengkap", "ERROR": "Error",
    "BELUM_SUBMIT": "Belum submit", "OVERDUE": "Overdue",
}
AGING_ORDER = ["Reviewer (Section 1)", "Team Leader", "Dept Head", "SEITO", "GH"]


def parse_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def fmt_day(d: datetime | None) -> str:
    return f"{d.day:02d} {BULAN[d.month - 1]}" if d else "—"


def fmt_dt(d: datetime | None) -> str:
    return f"{d.day:02d} {BULAN[d.month - 1]} {d.year}, {d:%H:%M}" if d else "—"


def fmt_mpm(d: datetime | None) -> str:
    """Show a date exactly as MPM writes it (DD/MM/YYYY HH.mm.ss)."""
    return d.strftime("%d/%m/%Y %H.%M.%S") if d else "—"


def _days(read_at: datetime, since: datetime) -> float:
    """Pending age at the moment the data was read; never negative (clock skew between laptop and MPM)."""
    return max((read_at - since).total_seconds() / 86400, 0.0)


def fmt_duration(td: timedelta) -> str:
    hours = int(td.total_seconds() // 3600)
    days, hours = divmod(max(hours, 0), 24)
    return f"{days} hari {hours} jam" if days else f"{hours} jam"


# Published run
@dataclass(frozen=True)
class Published:
    run_id: int
    read_at: datetime          # when the data was read from MPM (run start)
    published_at: datetime
    failed_after: int          # runs after this one that stopped or failed
    last_failed_at: datetime | None


def published(store: Store) -> Published | None:
    pub = store.published_run()
    if pub is None:
        return None
    failed = store.failed_runs_after(pub["run_id"])
    return Published(
        pub["run_id"], parse_iso(pub["run_started_at"]), parse_iso(pub["published_at"]),
        len(failed), parse_iso(failed[-1]["started_at"]) if failed else None,
    )


# Daftar aplikasi
@dataclass
class AppRow:
    app: str
    departemen: str
    dept_code: str
    team_leader: str
    status: str
    group: str
    cpr: str
    cpd: str
    note: str
    aging_days: float | None
    request_date: datetime | None
    fso_date: datetime | None
    flags: list[str] = field(default_factory=list)
    docs: dict = field(default_factory=dict)        # CPR/CPD -> detail dict from application_status

    @property
    def status_label(self) -> str:
        return STATUS_LABEL.get(self.status, self.status)


def _doc_text(doc_type: str, d: dict | None, has_cpr: bool) -> str:
    if d is None:
        if doc_type == "CPR":
            return "CPR · belum submit"
        return "CPD · tidak dilacak" if has_cpr else ""
    if d["method"] == "WET":
        return f"{doc_type} · tanda tangan basah"
    return f"{doc_type} · {STATUS_LABEL.get(d['status'], d['status'])} (MPM)"


def _doc_note(d: dict) -> str:
    if d["status"] == "PENDING":
        return d.get("pending_text") or ""
    return d.get("reason") or ""


def app_rows(store: Store, md: MasterData | None, pub: Published) -> list[AppRow]:
    rows = store.conn.execute(
        "SELECT * FROM application_status WHERE run_id=? ORDER BY departemen, app", (pub.run_id,)
    ).fetchall()
    out = []
    for r in rows:
        docs = json.loads(r["detail_json"] or "{}")
        app = md.apps.get(r["app"]) if md else None
        status = r["status"]
        cpr, cpd = docs.get("CPR"), docs.get("CPD")

        if status in (AppStatus.BELUM_SUBMIT.value, AppStatus.OVERDUE.value):
            note = "Lewat deadline, belum ada submission msForm" if status == AppStatus.OVERDUE.value \
                else "Belum ada submission msForm"
        elif status == AppStatus.FSO.value:
            note = "—"
        else:
            # The document that decides the application status explains it; prefix CPD so it is not read as CPR.
            decider = next((t for t in ("CPR", "CPD") if t in docs and docs[t]["status"] == status), None)
            note = _doc_note(docs[decider]) if decider else ""
            if decider == "CPD":
                note = f"CPD: {note}"

        aging = None
        for d in docs.values():
            since = parse_iso(d.get("pending_since")) if d["status"] == "PENDING" else None
            if since:
                days = _days(pub.read_at, since)
                aging = days if aging is None else max(aging, days)

        fso_dates = []
        for d in docs.values():
            if d["status"] == "FSO":
                fso_dates.append(parse_iso(d.get("fso_date")))
            elif d["status"] == "WET_SIGN":
                fso_dates.append(parse_iso(d.get("submitted_at")))   # wet signature: FSO date = msForm submit
        fso_date = max(fso_dates) if status == AppStatus.FSO.value and all(fso_dates) and fso_dates else None

        flags = sorted({f for d in docs.values() for f in json.loads(d.get("flags") or "[]")})
        out.append(AppRow(
            app=r["app"], departemen=r["departemen"],
            dept_code=(md.abbreviations.get(r["departemen"]) if md else None) or r["departemen"],
            team_leader=app.team_leader if app else "",
            status=status, group=GROUP_OF.get(status, "review"),
            cpr=_doc_text("CPR", cpr, cpr is not None), cpd=_doc_text("CPD", cpd, cpr is not None),
            note=note, aging_days=aging,
            request_date=parse_iso(cpr.get("request_date")) if cpr else None,
            fso_date=fso_date, flags=flags, docs=docs,
        ))
    return out


def filter_rows(rows: list[AppRow], group: str = "Semua", dept: str = "Semua", tl: str = "") -> list[AppRow]:
    q = tl.strip().lower()
    return [
        r for r in rows
        if (group == "Semua" or r.group == group)
        and (dept == "Semua" or r.dept_code == dept)
        and (not q or q in r.team_leader.lower())
    ]


def sort_by_aging(rows: list[AppRow], direction: str) -> list[AppRow]:
    """direction: 'desc' (longest first), 'asc' (shortest first), anything else keeps order. No aging sorts last."""
    if direction == "desc":
        return sorted(rows, key=lambda r: -1 if r.aging_days is None else r.aging_days, reverse=True)
    if direction == "asc":
        return sorted(rows, key=lambda r: math.inf if r.aging_days is None else r.aging_days)
    return rows


# Ringkasan
def composition(rows: list[AppRow]) -> dict[str, int]:
    counts = {k: 0 for k, _ in GROUPS}
    for r in rows:
        counts[r.group] += 1
    return counts


@dataclass
class DeptSummary:
    code: str
    departemen: str
    template: int | None
    counts: dict[str, int]

    @property
    def live(self) -> int:
        return sum(self.counts.values())


def dept_breakdown(rows: list[AppRow], md: MasterData | None) -> list[DeptSummary]:
    by: dict[str, DeptSummary] = {}
    for r in rows:
        if r.departemen not in by:
            by[r.departemen] = DeptSummary(
                r.dept_code, r.departemen, md.templates.get(r.departemen) if md else None, {k: 0 for k, _ in GROUPS}
            )
        by[r.departemen].counts[r.group] += 1
    return sorted(by.values(), key=lambda d: (-d.live, d.code))


@dataclass(frozen=True)
class BurnPoint:
    day: datetime
    submitted: int
    fso: int


def burnup(store: Store, period: int) -> list[BurnPoint]:
    """Cumulative 'sudah submit' and FSO per week, from the last publish of each week."""
    pubs = store.conn.execute(
        "SELECT p.run_id, p.published_at FROM published p ORDER BY p.publish_id"
    ).fetchall()
    last_per_week: dict[tuple[int, int], tuple[datetime, int]] = {}
    for p in pubs:
        at = parse_iso(p["published_at"])
        last_per_week[at.isocalendar()[:2]] = (at, p["run_id"])
    out = []
    for at, run_id in sorted(last_per_week.values()):
        statuses = [s for (s,) in store.conn.execute(
            "SELECT status FROM application_status WHERE run_id=? AND period=?", (run_id, period))]
        if not statuses:
            continue
        submitted = sum(1 for s in statuses if GROUP_OF.get(s) != "belum")
        out.append(BurnPoint(at, submitted, sum(1 for s in statuses if s == AppStatus.FSO.value)))
    return out


def submissions_needed_per_week(remaining: int, now: datetime, deadline: datetime) -> int:
    weeks = max((deadline - now).total_seconds() / (7 * 86400), 1)
    return math.ceil(remaining / weeks)


@dataclass(frozen=True)
class AgingRow:
    jabatan: str
    docs: int
    median_days: float
    max_days: float


def _snapshot_upto(store: Store, doc_key: str, run_id: int):
    return store.conn.execute(
        "SELECT * FROM snapshots WHERE doc_key=? AND run_id<=? AND header_json != '{}' "
        "ORDER BY run_id DESC LIMIT 1", (doc_key, run_id)
    ).fetchone()


def _approval_rows(store: Store, snapshot_id: int):
    return store.conn.execute(
        "SELECT * FROM approval_rows WHERE snapshot_id=? ORDER BY idx", (snapshot_id,)
    ).fetchall()


def _row_jabatan(role: str, section: int, sections: list[int], md: MasterData | None, departemen: str) -> str:
    if role.strip().lower().startswith("reviewer"):
        return "Reviewer (Section 1)"
    if md is None or departemen not in md.templates:
        return "Approver"
    rule = section_jabatan(section, sections, md.rules_for_department(departemen))
    return rule.jabatan if rule else "Approver (section tambahan)"


def pending_aging(store: Store, md: MasterData | None, rows: list[AppRow], pub: Published,
                  row_status: dict[str, str]) -> list[AgingRow]:
    """Median and longest Pending days per jabatan of the first Pending row. Aggregated, never per person."""
    days_by: dict[str, list[float]] = {}
    for r in rows:
        for d in r.docs.values():
            if d["status"] != "PENDING" or not d.get("pending_since"):
                continue
            snap = _snapshot_upto(store, d["key"], pub.run_id)
            if snap is None:
                continue
            arows = _approval_rows(store, snap["snapshot_id"])
            sections = sorted({a["section"] for a in arows})
            first = next((a for a in arows if row_status.get(a["raw_status"]) == "PENDING"), None)
            if first is None:
                continue
            jab = _row_jabatan(first["role"], first["section"], sections, md, r.departemen)
            days = _days(pub.read_at, parse_iso(d["pending_since"]))
            days_by.setdefault(jab, []).append(days)
    order = {j: i for i, j in enumerate(AGING_ORDER)}
    return [
        AgingRow(j, len(v), statistics.median(v), max(v))
        for j, v in sorted(days_by.items(), key=lambda kv: (order.get(kv[0], 99), kv[0]))
    ]


# Detail dokumen
@dataclass
class LogRow:
    section: int
    role_label: str
    name: str
    raw_status: str
    request: str
    response: str


@dataclass
class HistoryItem:
    at: datetime
    text: str
    status: str
    html_path: str = ""
    png_path: str = ""


@dataclass
class DocDetail:
    key: str
    doc_type: str
    method: str
    link: str
    pdf: str
    status: str
    reason: str
    pending_text: str
    request_date: datetime | None
    fso_date: datetime | None
    lead_time_hours: float | None
    pending_since: datetime | None
    pending_section: int | None
    template: int | None
    read_at: datetime | None
    header: dict
    log: list[LogRow]
    validation: list[dict]
    flags: list[str]
    history: list[HistoryItem]


def _history_text(st: str, reason: str, pending_text: str) -> str:
    if st == "PENDING":
        return pending_text or "Pending"
    label = STATUS_LABEL.get(st, st)
    return f"{label}: {reason}" if reason and st != "FSO" else label


def doc_detail(store: Store, md: MasterData | None, key: str, departemen: str, pub: Published,
               row_status: dict[str, str]) -> DocDetail | None:
    doc = store.conn.execute("SELECT * FROM documents WHERE key=?", (key,)).fetchone()
    if doc is None:
        return None
    statuses = store.conn.execute(
        "SELECT ds.*, r.started_at FROM document_status ds JOIN runs r ON r.run_id = ds.run_id "
        "WHERE ds.doc_key=? AND ds.run_id<=? ORDER BY ds.run_id", (key, pub.run_id)
    ).fetchall()
    if not statuses:
        return None
    last = statuses[-1]

    snap = _snapshot_upto(store, key, pub.run_id)
    header = json.loads(snap["header_json"]) if snap else {}
    log, pending_section = [], None
    if snap:
        arows = _approval_rows(store, snap["snapshot_id"])
        sections = sorted({a["section"] for a in arows})
        for a in arows:
            jab = _row_jabatan(a["role"], a["section"], sections, md, departemen)
            if jab.startswith("Reviewer"):
                label = "Reviewer"
            elif jab == "Approver":
                label = "Approver"
            elif jab.startswith("Approver"):
                label = "Approver · di luar template"
            else:
                label = f"Approver · {jab}"
            if pending_section is None and row_status.get(a["raw_status"]) == "PENDING":
                pending_section = a["section"]
            log.append(LogRow(a["section"], label, a["name"], a["raw_status"],
                              fmt_mpm(parse_iso(a["request_date"])), fmt_mpm(parse_iso(a["response_date"]))))
    read_at = None
    if snap:
        r = store.conn.execute("SELECT started_at FROM runs WHERE run_id=?", (snap["run_id"],)).fetchone()
        read_at = parse_iso(r["started_at"]) if r else None

    # History: only runs that changed status or wording, newest first; plus the msForm submission.
    history, prev = [], None
    snaps = {s["run_id"]: s for s in store.conn.execute(
        "SELECT * FROM snapshots WHERE doc_key=? AND run_id<=?", (key, pub.run_id))}
    for s in statuses:
        sig = (s["status"], s["reason"], s["pending_text"])
        if sig == prev:
            continue
        prev = sig
        sn = snaps.get(s["run_id"])
        history.append(HistoryItem(parse_iso(s["started_at"]), _history_text(*sig), s["status"],
                                   sn["html_path"] if sn else "", sn["png_path"] if sn else ""))
    history.reverse()
    if doc["submitted_at"]:
        history.append(HistoryItem(parse_iso(doc["submitted_at"]), "Submission msForm divalidasi dan masuk staging", ""))

    return DocDetail(
        key=key, doc_type=doc["doc_type"], method=doc["method"], link=doc["link"] or "", pdf=doc["pdf"] or "",
        status=last["status"], reason=last["reason"] or "", pending_text=last["pending_text"] or "",
        request_date=parse_iso(last["request_date"]),
        fso_date=parse_iso(last["fso_date"]) or (parse_iso(doc["submitted_at"]) if last["status"] == "WET_SIGN" else None),
        lead_time_hours=last["lead_time_hours"], pending_since=parse_iso(last["pending_since"]),
        pending_section=pending_section if last["status"] == "PENDING" else None,
        template=md.templates.get(departemen) if md else None, read_at=read_at,
        header=header, log=log, validation=json.loads(last["validation_json"] or "[]"),
        flags=json.loads(last["flags_json"] or "[]"), history=history,
    )


def next_publish(now: datetime, times: list[str]) -> datetime:
    slots = []
    for hhmm in times:
        h, m = map(int, hhmm.split(":"))
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        slots.append(t if t > now else t + timedelta(days=1))
    return min(slots)
