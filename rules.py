"""Rules engine: document status, structure check, Approver Validation, dates, application status.

Pure functions only (no I/O), so every PRD UAT scenario is a plain unit test.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .master_data import App, MasterData
from .models import (
    APP_PRIORITY,
    FINAL_OK,
    AppStatus,
    ApprovalRow,
    DocResult,
    DocStatus,
    MpmPage,
    SectionRule,
    SectionValidation,
    Validation,
)
from .names import normalize_name


class UnknownStatusError(Exception):
    """A row status or header badge is not in status_mapping (E-STATUS)."""


@dataclass(frozen=True)
class RulesConfig:
    row_status: dict[str, str]      # raw -> canonical
    known_badges: set[str]
    complete_badge: str
    pending_template: str
    pending_many_template: str

    @classmethod
    def from_config(cls, cfg) -> "RulesConfig":
        sm = cfg.status_mapping
        return cls(
            row_status={str(k): v for k, v in sm["row_status"].items()},
            known_badges=set(sm["known_badges"]),
            complete_badge=sm["complete_badge"],
            pending_template=cfg.messages["pending"],
            pending_many_template=cfg.messages["pending_many"],
        )


# Section mapping
def section_jabatan(section: int, mpm_sections: list[int], rules: list[SectionRule]) -> SectionRule | None:
    """Map an MPM section to its template rule.

    The last MPM section is always the template's last rule (GH). Sections 1..(template-1) map by
    number. Extra sections in the middle (beyond the template) have no rule and are not validated.
    """
    last = max(mpm_sections)
    if section == last:
        return rules[-1]
    if section <= len(rules) - 1:
        return rules[section - 1]
    return None


def _canonical(rows: tuple[ApprovalRow, ...], cfg: RulesConfig) -> list[str]:
    out = []
    for r in rows:
        if r.raw_status not in cfg.row_status:
            raise UnknownStatusError(f'Status "{r.raw_status}" belum dikenal')
        out.append(cfg.row_status[r.raw_status])
    return out


def structure_problems(page: MpmPage, rules: list[SectionRule]) -> list[str]:
    problems = []
    sections = sorted({r.section for r in page.rows})
    rule1 = rules[0]
    for s in sections:
        approvers = [r for r in page.rows if r.section == s and r.is_approver]
        reviewers = [r for r in page.rows if r.section == s and r.is_reviewer]
        unknown_roles = [r.role for r in page.rows if r.section == s and not (r.is_approver or r.is_reviewer)]
        if len(approvers) != 1:
            problems.append(f"Section {s} punya {len(approvers)} Approver (harus 1)")
        if s == 1:
            if not rule1.reviewer_min <= len(reviewers) <= rule1.reviewer_max:
                problems.append(
                    f"Section 1 punya {len(reviewers)} Reviewer (harus {rule1.reviewer_min}–{rule1.reviewer_max})"
                )
        elif reviewers:
            problems.append(f"Ada Reviewer di Section {s} (hanya boleh di Section 1)")
        if unknown_roles:
            problems.append(f"Peran tidak dikenal di Section {s}: {', '.join(unknown_roles)}")
    return problems


# Approver Validation
def validate_approvers(page: MpmPage, app: App, rules: list[SectionRule], md: MasterData) -> list[SectionValidation]:
    sections = sorted({r.section for r in page.rows})
    out = []
    for s in sections:
        approver = next((r for r in page.rows if r.section == s and r.is_approver), None)
        if approver is None:
            continue
        rule = section_jabatan(s, sections, rules)
        name = normalize_name(approver.name)
        if rule is None:
            out.append(SectionValidation(s, "-", approver.name, Validation.NOT_VALIDATED, "Section di luar template"))
            continue
        out.append(SectionValidation(s, rule.jabatan, approver.name, *_judge(rule, name, app, md)))
    return out


def _judge(rule: SectionRule, name: str, app: App, md: MasterData) -> tuple[Validation, str]:
    if rule.jabatan == "Team Leader":
        primary = {normalize_name(app.team_leader)} - {""}
        pool, pool_label = md.team_leaders(), "Team Leader lain di app_master"
    elif rule.jabatan == "Dept Head":
        primary = md.dept_heads(app.departemen)
        pool, pool_label = md.dept_heads(), "Dept Head lain di position_holders"
    else:  # SEITO, GH: not tied to a department, no alternate
        primary = md.holders_of(rule.jabatan)
        pool, pool_label = set(), ""
    if not primary:
        return Validation.UNKNOWN, f"Daftar {rule.jabatan} kosong di master data"
    if name in primary:
        return Validation.MATCH, f"Pemegang jabatan {rule.jabatan}"
    if rule.alternate and name in pool:
        return Validation.ALTERNATE, f"{pool_label} · lolos"
    return Validation.MISMATCH, f"Tidak ada di daftar {rule.jabatan}"


# Document status
def _jabatan_label(row: ApprovalRow, sections: list[int], rules: list[SectionRule]) -> str:
    if row.is_reviewer:
        return "Reviewer"
    rule = section_jabatan(row.section, sections, rules)
    return rule.jabatan if rule else "Approver"


def evaluate_document(page: MpmPage, app: App, md: MasterData, cfg: RulesConfig, now: datetime) -> DocResult:
    """Apply the PRD precedence table to one MPM page (WET_SIGN and ERROR-from-scraper handled by caller)."""
    rules = md.rules_for_department(app.departemen)
    try:
        canon = _canonical(page.rows, cfg)
        if page.status_badge not in cfg.known_badges:
            raise UnknownStatusError(f'Badge "{page.status_badge}" belum dikenal')
    except UnknownStatusError as exc:
        return DocResult(DocStatus.ERROR, reason=str(exc), error_code="E-STATUS")

    sections = sorted({r.section for r in page.rows})
    requests = [r.request_date for r in page.rows if r.request_date]
    result = DocResult(DocStatus.FSO, request_date=min(requests) if requests else None)
    result.validation = validate_approvers(page, app, rules, md)
    if normalize_name(page.project_name) != normalize_name(app.name):
        result.flags.append("NAME_MISMATCH")

    problems = structure_problems(page, rules)
    if problems:
        result.status, result.reason = DocStatus.ANOMALY, "; ".join(problems)
        return result
    if "CANCELLED" in canon:
        result.status, result.reason = DocStatus.CANCELLED, "Ada baris Cancel"
        return result
    if "REJECTED" in canon:
        rej = page.rows[canon.index("REJECTED")]
        result.status = DocStatus.REJECTED
        result.reason = f"Di-Reject {_jabatan_label(rej, sections, rules)} (Section {rej.section})"
        return result
    if "PENDING" in canon:
        pend = [r for r, c in zip(page.rows, canon) if c == "PENDING"]
        first = pend[0]
        jabatan = _jabatan_label(first, sections, rules)
        if len(pend) == 1:
            text = cfg.pending_template.format(name=first.name, jabatan=jabatan, section=first.section)
        else:
            text = cfg.pending_many_template.format(
                names=", ".join(r.name for r in pend), jabatan=jabatan, section=first.section
            )
        since = min((r.request_date for r in pend if r.request_date), default=None)
        result.status, result.pending_text, result.pending_since = DocStatus.PENDING, text, since
        return result
    if "NOT_STARTED" in canon:
        result.status, result.reason = DocStatus.ANOMALY, "Chain berhenti: tidak ada Pending, tetapi masih ada baris '-'"
        return result

    # All rows Approve from here on.
    if len(sections) < len(rules):
        result.status = DocStatus.INCOMPLETE_CHAIN
        result.reason = f"{len(sections)} dari {len(rules)} section; template departemen butuh {len(rules)}"
        return result
    if page.status_badge != cfg.complete_badge:
        result.status, result.reason = DocStatus.ANOMALY, f"Semua Approve, badge header masih {page.status_badge}"
        return result
    last_approver = next(r for r in page.rows if r.section == sections[-1] and r.is_approver)
    responses = [r.response_date for r in page.rows if r.response_date]
    if last_approver.response_date is None or last_approver.response_date != max(responses):
        result.status, result.reason = DocStatus.ANOMALY, "Tanggal FSO tidak sama dengan Response Date paling akhir"
        return result
    result.fso_date = last_approver.response_date
    if result.request_date:
        result.lead_time_hours = round((result.fso_date - result.request_date).total_seconds() / 3600, 2)
    return result


def wet_sign_result() -> DocResult:
    return DocResult(
        DocStatus.WET_SIGN,
        reason="Tanda tangan basah; MPM tidak dibaca",
        validation=[SectionValidation(0, "-", "-", Validation.NOT_APPLICABLE, "Tanda tangan basah")],
    )


# Application status
def application_status(doc_statuses: list[DocStatus], has_cpr: bool, now: datetime, deadline: datetime) -> AppStatus:
    """Combine the latest CPR (and CPD, if submitted) statuses into one application status."""
    if not has_cpr:
        return AppStatus.OVERDUE if now > deadline else AppStatus.BELUM_SUBMIT
    if doc_statuses and all(s in FINAL_OK for s in doc_statuses):
        return AppStatus.FSO
    for s in APP_PRIORITY:
        if s in doc_statuses:
            return AppStatus(s.value)
    return AppStatus.PENDING
