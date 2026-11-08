"""Parse a saved MPM approvalLog page (HTML) into an MpmPage, using config/scraper_selectors.yaml.

The parser works on HTML text only, so it is tested without a browser and without MPM access.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .models import ApprovalRow, MpmPage

_EMPTY_DATES = {"", "-", "—", "–"}


class ParseError(Exception):
    """Page loaded but the expected structure was not found (E-PARSE)."""


def parse_mpm_date(text: str, fmt: str, tz: ZoneInfo) -> datetime | None:
    """Parse an MPM date such as '06/11/2026, 10.02.06' with an explicit format (never guess day/month)."""
    t = (text or "").strip()
    if t in _EMPTY_DATES:
        return None
    try:
        return datetime.strptime(t, fmt).replace(tzinfo=tz)
    except ValueError as exc:
        raise ParseError(f"Format tanggal tidak dikenal: {t!r} (diharapkan {fmt})") from exc


def _text(node) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _section_number(text: str) -> int:
    m = re.search(r"\d+", text or "")
    if not m:
        raise ParseError(f"Nomor section tidak ditemukan: {text!r}")
    return int(m.group())


def parse_approval_page(html: str, selectors: dict, tz: ZoneInfo) -> MpmPage:
    soup = BeautifulSoup(html, "lxml")
    h = selectors["header"]
    doc_id = _text(soup.select_one(h["doc_id"]))
    if not doc_id:
        raise ParseError("DOC ID tidak ditemukan di halaman")
    main_doc_node = soup.select_one(h["main_document"])
    row_nodes = soup.select(selectors["rows"])
    if not row_nodes:
        raise ParseError("Tabel approval tidak ditemukan atau kosong")

    c = selectors["cells"]
    fmt = selectors["date_format"]
    rows = []
    for tr in row_nodes:
        cells = {k: tr.select_one(sel) for k, sel in c.items()}
        missing = [k for k, node in cells.items() if node is None]
        if missing:
            raise ParseError(f"Kolom tidak ditemukan: {', '.join(missing)}")
        rows.append(
            ApprovalRow(
                section=_section_number(_text(cells["section"])),
                role=_text(cells["role"]),
                name=_text(cells["name"]),
                raw_status=_text(cells["status"]),
                request_date=parse_mpm_date(_text(cells["request_date"]), fmt, tz),
                response_date=parse_mpm_date(_text(cells["response_date"]), fmt, tz),
            )
        )
    return MpmPage(
        doc_id=doc_id,
        project_name=_text(soup.select_one(h["project_name"])),
        flow_badge=_text(soup.select_one(h["flow_badge"])),
        status_badge=_text(soup.select_one(h["status_badge"])),
        main_document=(main_doc_node.get("href") or _text(main_doc_node)) if main_doc_node else "",
        rows=tuple(rows),
    )
