"""Domain types shared by parser, rules engine, ingest and store."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DocStatus(str, Enum):
    WET_SIGN = "WET_SIGN"
    ERROR = "ERROR"
    ANOMALY = "ANOMALY"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    INCOMPLETE_CHAIN = "INCOMPLETE_CHAIN"
    FSO = "FSO"


class AppStatus(str, Enum):
    FSO = "FSO"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ANOMALY = "ANOMALY"
    INCOMPLETE_CHAIN = "INCOMPLETE_CHAIN"
    ERROR = "ERROR"
    BELUM_SUBMIT = "BELUM_SUBMIT"
    OVERDUE = "OVERDUE"


# Statuses whose MPM page is read again on the next run (PRD Bagian 4).
REREAD_STATUSES = {DocStatus.PENDING, DocStatus.ERROR, DocStatus.ANOMALY, DocStatus.INCOMPLETE_CHAIN}
FINAL_OK = {DocStatus.FSO, DocStatus.WET_SIGN}

# Aggregation priority for application status: first match wins (highest priority first).
APP_PRIORITY = [
    DocStatus.ERROR,
    DocStatus.ANOMALY,
    DocStatus.CANCELLED,
    DocStatus.REJECTED,
    DocStatus.PENDING,
    DocStatus.INCOMPLETE_CHAIN,
]


class Validation(str, Enum):
    MATCH = "Match"
    ALTERNATE = "Alternate"
    MISMATCH = "Mismatch"
    UNKNOWN = "Unknown"
    NOT_VALIDATED = "Tidak divalidasi"   # extra middle section outside the template
    NOT_APPLICABLE = "N/A"              # wet signature


@dataclass(frozen=True)
class ApprovalRow:
    section: int
    role: str                 # "Reviewer" | "Approver" (as shown in MPM)
    name: str
    raw_status: str           # Approve | Pending | Reject | Cancel | -
    request_date: datetime | None
    response_date: datetime | None

    @property
    def is_approver(self) -> bool:
        return self.role.strip().lower().startswith("approver")

    @property
    def is_reviewer(self) -> bool:
        return self.role.strip().lower().startswith("reviewer")


@dataclass(frozen=True)
class MpmPage:
    doc_id: str
    project_name: str
    flow_badge: str
    status_badge: str
    main_document: str
    rows: tuple[ApprovalRow, ...]


@dataclass(frozen=True)
class SectionRule:
    template: int          # 4 or 3 (jumlah_section)
    section: int           # section_ke
    jabatan: str           # Team Leader | Dept Head | SEITO | GH
    reviewer_min: int
    reviewer_max: int
    alternate: bool


@dataclass(frozen=True)
class SectionValidation:
    section: int
    jabatan: str
    name: str
    result: Validation
    basis: str


@dataclass
class DocResult:
    status: DocStatus
    reason: str = ""
    pending_text: str = ""
    request_date: datetime | None = None
    fso_date: datetime | None = None
    lead_time_hours: float | None = None
    pending_since: datetime | None = None
    validation: list[SectionValidation] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)   # e.g. NAME_MISMATCH
    error_code: str = ""                            # E-STATUS, E-PARSE, ...


@dataclass(frozen=True)
class TrackedDocument:
    """One document (CPR or CPD) of one application in one period, from one submission."""
    key: str               # DOC ID for MPM docs, internal id for wet-signature docs
    app: str
    departemen: str
    period: int
    doc_type: str          # CPR | CPD
    method: str            # MPM | WET
    link: str
    pdf: str
    response_id: str
    submitted_at: datetime | None
