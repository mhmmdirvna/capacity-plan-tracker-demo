"""Load and validate the master data workbook (app_master, departemen, section_rules, position_holders)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .models import SectionRule
from .names import normalize_name

SHEETS = ("app_master", "departemen", "section_rules", "position_holders")
APP_STATUSES = {"Live", "Not yet Live", "Dismantle", "Merging"}
JABATAN = {"Team Leader", "Dept Head", "SEITO", "GH"}


class MasterDataError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__(f"Master data ditolak: {len(errors)} error")
        self.errors = errors


@dataclass(frozen=True)
class App:
    departemen: str
    name: str
    team_leader: str
    status: str
    merge_ke: str


@dataclass
class MasterData:
    apps: dict[str, App]
    templates: dict[str, int]                  # departemen -> jumlah_section_wajib
    abbreviations: dict[str, str]              # departemen -> singkatan
    rules: dict[int, list[SectionRule]]        # template -> rules ordered by section
    holders: list[tuple[str, str, str]]        # (departemen, jabatan, nama)
    warnings: list[str] = field(default_factory=list)

    # lookups used by the rules engine
    def rules_for_department(self, departemen: str) -> list[SectionRule]:
        return self.rules[self.templates[departemen]]

    def team_leaders(self) -> set[str]:
        return {normalize_name(a.team_leader) for a in self.apps.values() if a.team_leader}

    def dept_heads(self, departemen: str | None = None) -> set[str]:
        return {
            normalize_name(n) for d, j, n in self.holders
            if j == "Dept Head" and (departemen is None or d == departemen)
        }

    def holders_of(self, jabatan: str) -> set[str]:
        return {normalize_name(n) for _, j, n in self.holders if j == jabatan}

    def live_apps(self) -> list[App]:
        return [a for a in self.apps.values() if a.status == "Live"]


def _clean(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _read(path: Path) -> dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(path)
    missing = [s for s in SHEETS if s not in xls.sheet_names]
    if missing:
        raise MasterDataError([f"Sheet tidak ada: {', '.join(missing)}"])
    return {s: pd.read_excel(xls, s, dtype=object).dropna(how="all") for s in SHEETS}


def load_master_data(path: Path) -> MasterData:
    """Load and validate. Raises MasterDataError with every row-level problem (E-MASTER)."""
    df = _read(path)
    errors: list[str] = []
    warnings: list[str] = []

    # departemen
    templates, abbreviations = {}, {}
    for i, r in df["departemen"].iterrows():
        d = _clean(r.get("departemen"))
        if not d:
            continue
        try:
            templates[d] = int(float(_clean(r.get("jumlah_section_wajib"))))
        except ValueError:
            errors.append(f"departemen baris {i + 2}: jumlah_section_wajib kosong atau bukan angka ({d})")
        abbreviations[d] = _clean(r.get("singkatan")) or d

    # section_rules
    rules: dict[int, list[SectionRule]] = {}
    seen = Counter()
    for i, r in df["section_rules"].iterrows():
        try:
            rule = SectionRule(
                template=int(float(r["jumlah_section"])),
                section=int(float(r["section_ke"])),
                jabatan=_clean(r["jabatan_approver"]),
                reviewer_min=int(float(r.get("reviewer_min") or 0)),
                reviewer_max=int(float(r.get("reviewer_max") or 0)),
                alternate=_clean(r.get("alternate")).lower() == "ya",
            )
        except (TypeError, ValueError, KeyError):
            errors.append(f"section_rules baris {i + 2}: kolom wajib kosong atau bukan angka")
            continue
        seen[(rule.template, rule.section)] += 1
        if rule.jabatan not in JABATAN:
            errors.append(f"section_rules baris {i + 2}: jabatan_approver '{rule.jabatan}' tidak dikenal")
        if rule.reviewer_min > rule.reviewer_max:
            errors.append(f"section_rules baris {i + 2}: reviewer_min lebih besar dari reviewer_max")
        if rule.section != 1 and rule.reviewer_max > 0:
            errors.append(f"section_rules baris {i + 2}: reviewer hanya boleh di Section 1")
        rules.setdefault(rule.template, []).append(rule)
    for (t, s), n in seen.items():
        if n > 1:
            errors.append(f"section_rules: template {t} section {s} muncul {n} kali")
    for t, rs in rules.items():
        rs.sort(key=lambda x: x.section)
        if [x.section for x in rs] != list(range(1, len(rs) + 1)) or len(rs) != t:
            errors.append(f"section_rules: template {t} harus punya section 1 sampai {t}")
        elif rs[-1].jabatan != "GH":
            errors.append(f"section_rules: section terakhir template {t} harus GH")
    for d, t in templates.items():
        if t not in rules:
            errors.append(f"departemen '{d}': jumlah_section_wajib {t} tidak ada di section_rules")

    # app_master
    apps: dict[str, App] = {}
    names = Counter(_clean(n) for n in df["app_master"]["nama_aplikasi"] if _clean(n))
    for n, c in names.items():
        if c > 1:
            errors.append(f"app_master: nama_aplikasi '{n}' muncul {c} kali")
    for i, r in df["app_master"].iterrows():
        row = i + 2
        app = App(
            departemen=_clean(r.get("departemen")),
            name=_clean(r.get("nama_aplikasi")),
            team_leader=_clean(r.get("team_leader")),
            status=_clean(r.get("status_aplikasi")),
            merge_ke=_clean(r.get("merge_ke")),
        )
        if not app.name:
            errors.append(f"app_master baris {row}: nama_aplikasi kosong")
            continue
        if app.departemen not in templates:
            errors.append(f"app_master baris {row}: departemen '{app.departemen}' tidak ada di sheet departemen")
        if app.status not in APP_STATUSES:
            errors.append(f"app_master baris {row}: status_aplikasi '{app.status}' tidak dikenal")
        if app.status == "Merging" and not app.merge_ke:
            errors.append(f"app_master baris {row}: aplikasi Merging tanpa merge_ke ({app.name})")
        if app.status == "Live" and not app.team_leader:
            errors.append(f"app_master baris {row}: aplikasi Live tanpa team_leader ({app.name})")
        apps[app.name] = app

    # position_holders
    holders = []
    for i, r in df["position_holders"].iterrows():
        d, j, n = _clean(r.get("departemen")), _clean(r.get("jabatan")), _clean(r.get("nama"))
        if j not in JABATAN - {"Team Leader"}:
            errors.append(f"position_holders baris {i + 2}: jabatan '{j}' tidak dikenal")
        if j == "Dept Head" and not d:
            errors.append(f"position_holders baris {i + 2}: Dept Head tanpa departemen")
        if j in {"SEITO", "GH"} and d:
            warnings.append(f"position_holders baris {i + 2}: {j} tidak terikat departemen; kolom departemen diabaikan")
        if not n:
            errors.append(f"position_holders baris {i + 2}: nama kosong")
        holders.append((d, j, n))

    md = MasterData(apps, templates, abbreviations, rules, holders, warnings)
    # Catches find-replace accidents, e.g. an abbreviation inside a person's name replaced by the full department name.
    dept_names = [d.lower() for d in templates]
    for a in md.apps.values():
        if any(d in a.team_leader.lower() for d in dept_names):
            warnings.append(f"app_master: team_leader '{a.team_leader}' ({a.name}) memuat nama departemen; cek find-replace")
    for d in {a.departemen for a in md.live_apps()}:
        if not md.dept_heads(d):
            warnings.append(f"Departemen '{d}' belum punya Dept Head; Approver Validation akan Unknown")
    if errors:
        raise MasterDataError(errors)
    return md
