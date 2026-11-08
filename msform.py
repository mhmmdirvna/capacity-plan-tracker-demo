"""Read the msForm response workbook, map columns via config/form_mapping.yaml and validate each response."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .master_data import MasterData
from .models import TrackedDocument


@dataclass
class Submission:
    response_id: str
    submitted_at: datetime | None
    email: str
    name: str
    values: dict[str, str]
    errors: list[str] = field(default_factory=list)
    skipped: str = ""                  # reason when not a Capacity Plan response
    late: bool = False
    documents: list[TrackedDocument] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors and not self.skipped


def _norm(label: str) -> str:
    return " ".join(str(label).split()).lower()


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _columns_for(prefixes: list[str], columns: list[str]) -> list[str]:
    ps = [_norm(p) for p in prefixes]
    return [c for c in columns if any(_norm(c).startswith(p) for p in ps)]


def _first(row: pd.Series, cols: list[str]) -> str:
    for c in cols:
        v = _clean(row.get(c))
        if v:
            return v
    return ""


def _to_dt(v, tz: ZoneInfo) -> datetime | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    ts = pd.Timestamp(v)
    return ts.to_pydatetime().replace(tzinfo=tz) if ts.tzinfo is None else ts.to_pydatetime().astimezone(tz)


def read_responses(path: Path, form_mapping: dict, tz: ZoneInfo) -> list[Submission]:
    df = pd.read_excel(path, dtype=object).dropna(how="all")
    columns = [str(c) for c in df.columns]
    df.columns = columns
    meta_cols = {k: _columns_for(v, columns) for k, v in form_mapping["meta"].items()}
    field_cols = {k: _columns_for(v, columns) for k, v in form_mapping["fields"].items()}
    out = []
    for _, row in df.iterrows():
        out.append(
            Submission(
                response_id=_first(row, meta_cols["response_id"]),
                submitted_at=_to_dt(row.get(meta_cols["submitted_at"][0]) if meta_cols["submitted_at"] else None, tz),
                email=_first(row, meta_cols["email"]),
                name=_first(row, meta_cols["name"]),
                values={k: _first(row, cols) for k, cols in field_cols.items()},
            )
        )
    return out


def validate_submission(
    sub: Submission, md: MasterData, form_mapping: dict, cycle_year: int, doc_id_pattern: str, deadline: datetime
) -> Submission:
    """Fill sub.errors / sub.documents. INVALID_SUBMISSION = any error."""
    opt = form_mapping["options"]
    v = sub.values
    if v.get("jenis_dokumen") != opt["capacity_plan"]:
        sub.skipped = f"Jenis dokumen '{v.get('jenis_dokumen')}' tidak dilacak tracker ini"
        return sub

    dept, app_name = v.get("departemen", ""), v.get("aplikasi", "")
    app = md.apps.get(app_name)
    if dept not in md.templates:
        sub.errors.append(f"Departemen '{dept}' tidak ada di master data")
    if app is None:
        sub.errors.append(f"Aplikasi '{app_name}' tidak ada di master data")
    else:
        if app.departemen != dept:
            sub.errors.append(f"Aplikasi '{app_name}' bukan milik departemen '{dept}'")
        if app.status != "Live":
            sub.errors.append(f"Aplikasi '{app_name}' berstatus {app.status}, bukan Live")
    try:
        period = int(v.get("periode", ""))
        if period != cycle_year:
            sub.errors.append(f"Periode {period} bukan cycle aktif {cycle_year}")
    except ValueError:
        period = cycle_year
        sub.errors.append("Periode kosong atau bukan tahun")
    if not v.get("konfirmasi"):
        sub.errors.append("Konfirmasi Q25 kosong")

    docs = [_document(sub, "CPR", v.get("metode_cpr", ""), app_name, dept, period, opt, doc_id_pattern)]
    kebutuhan = v.get("kebutuhan", "")
    if kebutuhan.startswith(opt["kebutuhan_ya_prefix"]):
        docs.append(_document(sub, "CPD", v.get("metode_cpd", ""), app_name, dept, period, opt, doc_id_pattern))
    elif not kebutuhan.startswith(opt["kebutuhan_tidak_prefix"]):
        sub.errors.append(f"Jawaban Q8 tidak dikenal: '{kebutuhan}'")
    sub.documents = [d for d in docs if d is not None]
    sub.late = bool(sub.submitted_at and sub.submitted_at > deadline)
    return sub


def _document(sub, doc_type, method_raw, app, dept, period, opt, pattern) -> TrackedDocument | None:
    p = doc_type.lower()
    doc_id, link, pdf = sub.values.get(f"{p}_doc_id", ""), sub.values.get(f"{p}_link", ""), sub.values.get(f"{p}_pdf", "")
    if method_raw == opt["method_mpm"]:
        method = "MPM"
        if not re.match(pattern, doc_id):
            sub.errors.append(f"DOC ID {doc_type} '{doc_id}' tidak sesuai format DOC-YYYY-NNNNN")
        if not link:
            sub.errors.append(f"Link approvalLog {doc_type} kosong")
        key = doc_id
    elif method_raw == opt["method_wet"]:
        method = "WET"
        if not pdf:
            sub.errors.append(f"Link PDF {doc_type} wajib untuk tanda tangan basah")
        key = f"WET-{sub.response_id}-{doc_type}"
    else:
        sub.errors.append(f"Metode approval {doc_type} tidak dikenal: '{method_raw}'")
        return None
    return TrackedDocument(key, app, dept, period, doc_type, method, link, pdf, sub.response_id, sub.submitted_at)
