"""Admin dashboard (Streamlit). Shows the last PUBLISHED run only.

Run:  streamlit run src/cptracker/dashboard/app.py
Layout follows the Design canvas: Ringkasan, Daftar aplikasi and Detail dokumen. Perlu review, Master data and
Run log are not in the canvas yet and reuse its cards and colours.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cptracker.config import load_config  # noqa: E402
from cptracker.dashboard import data as D  # noqa: E402
from cptracker.dashboard import ui  # noqa: E402
from cptracker.master_data import MasterDataError, load_master_data  # noqa: E402
from cptracker.store import Store  # noqa: E402

PAGE_SIZE = 50
PILLS = {"Semua": "Semua", "FSO": "fso", "Pending": "pending", "Rejected/Cancelled": "rej",
         "Perlu review": "review", "Belum submit": "belum"}
SORTS = {"Urutan default": "none", "Aging terlama dulu": "desc", "Aging tersingkat dulu": "asc"}

st.set_page_config(page_title="Capacity Planning Tracker", layout="wide", initial_sidebar_state="collapsed")
cfg = load_config()
store = Store(cfg.path("database"))
row_status = {str(k): v for k, v in cfg.status_mapping["row_status"].items()}
hints = cfg.messages.get("error_hints", {})
now = datetime.now(cfg.tz)


@st.cache_resource(show_spinner=False)
def _load_master(path: str):
    try:
        return load_master_data(Path(path))
    except Exception:  # dashboard still works without master data (codes fall back to full names)
        return None


def active_master():
    p = store.active_master_path()
    if not p:
        return None
    p = p.replace("\\", "/")  # paths stored on Windows must still resolve on a Linux host
    full = Path(p) if Path(p).is_absolute() else cfg.root / p
    return _load_master(str(full))


def card(key: str):
    return st.container(key=f"card-{key}")


def svg_html(fragment: str):
    """st.html strips inline <svg>; markdown keeps it. Blank lines would end the HTML block, so drop them.
    Fragments come from ui.py, which escapes every data value."""
    st.markdown("\n".join(line for line in fragment.splitlines() if line.strip()), unsafe_allow_html=True)


md = active_master()
pub = D.published(store)
rows = D.app_rows(store, md, pub) if pub else []
page = st.query_params.get("page", "ringkasan")
if page not in {k for k, _ in ui.NAV} | {"dokumen"}:
    page = "ringkasan"

st.html(ui.CSS)
st.html(ui.header("aplikasi" if page == "dokumen" else page,
                  f"Data per {D.fmt_dt(pub.read_at)} WIB" if pub else "Belum ada data yang dipublish"))
if pub and pub.failed_after:
    st.warning(
        f"{pub.failed_after} run setelah data ini gagal atau dihentikan (terakhir {D.fmt_dt(pub.last_failed_at)} WIB). "
        "Data di bawah belum diperbarui; cek Error sistem di Ringkasan."
    )


def page_ringkasan():
    counts = D.composition(rows)
    total = len(rows)
    st.html(ui.hero(cfg.cycle_year, counts["fso"], total, counts["pending"], counts["belum"],
                    (cfg.deadline - now).days, cfg.deadline))
    if not pub:
        st.info("Belum ada run yang dipublish. Jalankan `python -m cptracker run` lalu `python -m cptracker publish`.")
        return

    with card("comp"):
        st.html(ui.composition(counts))

    left, right = st.columns([2, 1], gap="medium")
    with left, card("burn"):
        svg_html(ui.burnup(D.burnup(store, cfg.cycle_year), total, now, cfg.deadline, counts["belum"],
                          D.submissions_needed_per_week(counts["belum"], now, cfg.deadline)))
    with right, card("err"):
        errs = store.conn.execute("SELECT * FROM errors WHERE resolved_at IS NULL ORDER BY error_id DESC").fetchall()
        resolved = store.conn.execute("SELECT COUNT(*) FROM errors WHERE resolved_at IS NOT NULL").fetchone()[0]
        color = "#B3261E" if errs else ui.MUTED
        st.html(ui.wrap(f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:12px">'
                        f'<h2>Error sistem</h2><span style="font-size:13px;color:{color};font-weight:600">'
                        f'{len(errs)} terbuka</span></div>'))
        if not errs:
            st.html(ui.wrap('<p class="muted">Tidak ada error terbuka.</p>'))
        for e in errs:
            st.html(ui.error_item(e["code"], D.parse_iso(e["at"]), e["message"], hints.get(e["code"], "")))
            if st.button("Tandai selesai", key=f"err{e['error_id']}"):
                store.resolve_error(e["error_id"], "Admin", datetime.now(cfg.tz))
                st.rerun()
        st.html(ui.wrap(f'<p class="muted" style="font-size:12px;padding-top:8px">Penandaan selesai tercatat dengan '
                        f'nama Admin dan waktunya. <a href="{ui.page_href("runlog")}" target="_self">'
                        f'{resolved} sudah selesai</a></p>'))

    with card("dept"):
        h, toggle = st.columns([3, 1], vertical_alignment="center")
        h.html(ui.section_head("Per departemen", "Panjang bar = jumlah aplikasi Live."))
        view = toggle.segmented_control("Tampilan", ["Grafik", "Tabel"], default="Grafik",
                                        key="dept_view", label_visibility="collapsed") or "Grafik"
        depts = D.dept_breakdown(rows, md)
        st.html(ui.dept_legend())
        st.html(ui.dept_chart(depts) if view == "Grafik" else ui.dept_table(depts))

    with card("aging"):
        st.html(ui.aging(D.pending_aging(store, md, rows, pub, row_status)))

    times = cfg.settings["schedule"]["publish_times"]
    st.html(ui.footer(f"Publish berikutnya {D.next_publish(now, times):%H:%M} WIB · jadwal {', '.join(times)}",
                      f"Dipublish {D.fmt_dt(pub.published_at)} WIB"))


def _excel(view: list[D.AppRow]) -> bytes:
    df = pd.DataFrame([{
        "Departemen": r.dept_code, "Aplikasi": r.app, "Team Leader": r.team_leader, "Status": r.status_label,
        "CPR": r.cpr, "CPD": r.cpd, "Keterangan": r.note, "Flag": ", ".join(r.flags),
        "Aging (hari)": round(r.aging_days, 1) if r.aging_days is not None else None,
        "Request": r.request_date.strftime("%d/%m/%Y") if r.request_date else "",
        "FSO": r.fso_date.strftime("%d/%m/%Y") if r.fso_date else "",
    } for r in view])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Daftar aplikasi")
    return buf.getvalue()


def page_aplikasi():
    head, export = st.columns([4, 1], vertical_alignment="bottom")
    head.html(ui.page_title("Daftar aplikasi", f"{len(rows)} aplikasi Live, periode {cfg.cycle_year}. "
                            "Status aplikasi mengikuti dokumen dengan prioritas tertinggi."))
    if not pub:
        st.info("Belum ada data yang dipublish.")
        return

    dept = st.session_state.get("f_dept", "Semua")
    tl = st.session_state.get("f_tl", "")
    base = D.filter_rows(rows, dept=dept, tl=tl)
    counts = {label: (len(base) if g == "Semua" else sum(r.group == g for r in base)) for label, g in PILLS.items()}

    pill = st.segmented_control("Filter status", list(PILLS), default="Semua", key="f_group",
                                format_func=lambda l: f"{l}  {counts[l]}", label_visibility="collapsed") or "Semua"
    _, f2, f3, f4 = st.columns([3, 1.4, 1.6, 1.6], vertical_alignment="bottom")
    f2.selectbox("Departemen", ["Semua"] + sorted({r.dept_code for r in rows}), key="f_dept")
    f3.text_input("Team Leader", key="f_tl", placeholder="Cari nama")
    sort = f4.selectbox("Urutkan", list(SORTS), key="f_sort")

    view = D.sort_by_aging(D.filter_rows(base, group=PILLS[pill]), SORTS[sort])
    export.download_button("Export ke Excel", _excel(view), f"daftar_aplikasi_{now:%Y%m%d}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", width="stretch")

    sig = (pill, dept, tl, sort)
    if st.session_state.get("p_sig") != sig:
        st.session_state.p_sig, st.session_state.p_page = sig, 0
    pages = max((len(view) - 1) // PAGE_SIZE + 1, 1)
    cur = min(st.session_state.get("p_page", 0), pages - 1)
    chunk = view[cur * PAGE_SIZE:(cur + 1) * PAGE_SIZE]

    with card("table"):
        st.html(ui.app_table(chunk))
        info, prev, nxt = st.columns([4, 1, 1], vertical_alignment="center")
        first = cur * PAGE_SIZE + 1 if view else 0
        info.html(ui.wrap(f'<span class="muted" style="font-size:13px">{first}–{cur * PAGE_SIZE + len(chunk)} '
                          f'dari {len(view)} aplikasi · {PAGE_SIZE} per halaman</span>'))
        if prev.button("Sebelumnya", disabled=cur == 0, width="stretch"):
            st.session_state.p_page = cur - 1
            st.rerun()
        if nxt.button("Berikutnya", disabled=cur >= pages - 1, width="stretch"):
            st.session_state.p_page = cur + 1
            st.rerun()
    st.html(ui.wrap('<p class="muted" style="font-size:12px;padding:0 4px">Tanggal FSO dokumen tanda tangan basah '
                    '= tanggal submit msForm. Aging = lama Pending sejak Request Date baris yang Pending.</p>'))


def page_dokumen():
    st.html(ui.back_link())
    name = st.query_params.get("app", "")
    row = next((r for r in rows if r.app == name), None)
    if row is None:
        st.info("Aplikasi tidak ditemukan di data yang dipublish.")
        return
    st.html(ui.detail_head(row.dept_code, row.team_leader, row.app))

    types = [t for t in ("CPR", "CPD") if t in row.docs]
    if not types:
        with card("status"):
            st.html(ui.status_card(ui.COLOR["belum"], row.status_label, row.note, []))
        return
    sel, docid = st.columns([2, 3], vertical_alignment="center")
    doc_type = sel.segmented_control("Dokumen", types, default=types[0], key="doc_type",
                                     format_func=lambda t: f"{t} {cfg.cycle_year}",
                                     label_visibility="collapsed") or types[0]
    key = row.docs[doc_type]["key"]
    missing = "" if "CPD" in types else '<span class="muted" style="font-size:13px;margin-right:16px">CPD · tidak dilacak</span>'
    docid.html(ui.wrap(f'{missing}<span class="mono" style="font-size:13px;color:{ui.INK2}">'
                       f'{ui.esc(key if row.docs[doc_type]["method"] == "MPM" else "Tanda tangan basah")}</span>'))

    d = D.doc_detail(store, md, key, row.departemen, pub, row_status)
    if d is None:
        st.info("Dokumen belum punya status di run yang dipublish.")
        return

    label = D.STATUS_LABEL.get(d.status, d.status)
    headline = label + (f" · Section {d.pending_section} dari {d.template}" if d.pending_section and d.template else "")
    text = d.pending_text or d.reason or label
    pending_age = D.fmt_duration(pub.read_at - d.pending_since) if d.status == "PENDING" and d.pending_since else "—"
    lead = (f"{d.lead_time_hours / 24:.1f} hari ({d.lead_time_hours:.0f} jam)" if d.lead_time_hours is not None
            else "Belum terhitung")
    with card("status"):
        st.html(ui.status_card(ui.DOC_STATUS_COLOR.get(d.status, ui.COLOR["belum"]), headline, text, [
            ("Aging Pending", pending_age, True),
            ("Request Approval", D.fmt_dt(d.request_date), False),
            ("Tanggal FSO", D.fmt_dt(d.fso_date) if d.fso_date else "Belum FSO", False),
            ("Lead time", lead if d.method == "MPM" else "—", False),
        ]))

    left, right = st.columns([2, 1], gap="medium")
    with left:
        if d.method == "WET":
            with card("log"):
                st.html(ui.section_head("Tanda tangan basah", "MPM tidak dibaca. Approver Validation N/A."))
                st.html(ui.wrap(f'<p style="margin-top:8px">{ui.link(d.pdf, "Buka PDF full sign-off ›")}</p>'))
        else:
            with card("log"):
                tpl = f"Template {row.dept_code}: {d.template} section · " if d.template else ""
                read = f"dibaca {D.fmt_day(d.read_at)}, {d.read_at:%H:%M}" if d.read_at else "belum terbaca"
                st.html(ui.wrap(f'<div style="display:flex;flex-wrap:wrap;justify-content:space-between;'
                                f'align-items:baseline;gap:8px"><h2>Approval log MPM</h2>'
                                f'<span class="muted" style="font-size:13px">{ui.esc(tpl + read)}</span></div>'))
                st.html(ui.approval_log(d.log, row_status) if d.log
                        else ui.wrap('<p class="muted">Halaman belum berhasil dibaca.</p>'))
            with card("val"):
                st.html(ui.section_head("Approver Validation", "Tidak mengubah status dokumen. Dibekukan saat dokumen FSO."))
                st.html(ui.validation_table(d.validation))
    with right:
        with card("mpm"):
            st.html(ui.wrap("<h2>Header MPM</h2>" if d.method == "MPM" else "<h2>Dokumen</h2>"))
            st.html(ui.header_mpm(d.header, row.app, "NAME_MISMATCH" in d.flags, d.link, d.pdf))
        with card("hist"):
            st.html(ui.section_head("Riwayat", "Hanya run yang mengubah status atau wording."))
            for i, h in enumerate(d.history):
                st.html(ui.history_item(ui.DOC_STATUS_COLOR.get(h.status, ui.COLOR["belum"]),
                                        D.fmt_dt(h.at), h.text))
                snaps = [(p, lbl, mime) for p, lbl, mime in ((h.html_path, "Snapshot HTML", "text/html"),
                                                            (h.png_path, "Screenshot", "image/png"))
                         if p and Path(p).is_file()]
                for j, (p, lbl, mime) in enumerate(snaps):
                    st.download_button(lbl, Path(p).read_bytes(), Path(p).name, mime=mime, key=f"snap{i}-{j}")


def page_review():
    st.html(ui.page_title("Perlu review", "Status yang butuh tindakan Admin, dari data yang dipublish."))
    if not pub:
        st.info("Belum ada data yang dipublish.")
        return
    with card("rev-status"):
        st.html(ui.section_head("Anomaly, chain belum lengkap, dan error"))
        st.html(ui.app_table([r for r in rows if r.group == "review"]))
    with card("rev-val"):
        st.html(ui.section_head("Approver Validation: Mismatch / Unknown",
                                "Tidak mengubah status; cek apakah approver memang berwenang."))
        keys = [d["key"] for r in rows for d in r.docs.values()]
        found = []
        for k in keys:
            res = store.conn.execute("SELECT validation_json, flags_json FROM document_status WHERE doc_key=? "
                                     "AND run_id<=? ORDER BY run_id DESC LIMIT 1", (k, pub.run_id)).fetchone()
            if res:
                found += [{"Dokumen": k, "Section": v["section"], "Jabatan": v["jabatan"], "Nama": v["name"],
                           "Hasil": v["result"], "Dasar": v["basis"]}
                          for v in json.loads(res["validation_json"] or "[]") if v["result"] in ("Mismatch", "Unknown")]
        if found:
            st.dataframe(pd.DataFrame(found), hide_index=True, width="stretch")
        else:
            st.html(ui.wrap('<p class="muted">Tidak ada.</p>'))
        names = [r.app for r in rows if "NAME_MISMATCH" in r.flags]
        st.html(ui.wrap(f'<p style="font-size:14px">NAME_MISMATCH: {ui.esc(", ".join(names) or "-")}</p>'))
    with card("rev-sub"):
        st.html(ui.section_head("Submission tidak valid", "Tidak masuk staging sampai SME submit ulang."))
        inv = store.conn.execute("SELECT response_id, submitted_at, email, errors_json FROM submissions "
                                 "WHERE errors_json != '[]' ORDER BY submitted_at DESC").fetchall()
        if inv:
            st.dataframe(pd.DataFrame([{"Response": r["response_id"], "Waktu": r["submitted_at"], "Email": r["email"],
                                        "Error": "; ".join(json.loads(r["errors_json"]))} for r in inv]),
                         hide_index=True, width="stretch")
        else:
            st.html(ui.wrap('<p class="muted">Tidak ada.</p>'))


def page_master():
    st.html(ui.page_title("Master data", f"Versi aktif: {store.active_master_path() or 'belum ada'}"))
    with card("md-up"):
        st.html(ui.section_head("Cek file master data baru", "Validasi saja; aktivasi lewat perintah di bawah."))
        up = st.file_uploader("File master data baru (.xlsx)", type="xlsx")
        if up is not None:
            # Master data holds real officials' names: never leave a copy behind in %TEMP%.
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(up.getvalue())
            try:
                try:
                    new = load_master_data(Path(tmp.name))
                finally:
                    os.unlink(tmp.name)
                st.success(f"Lolos validasi: {len(new.apps)} aplikasi ({len(new.live_apps())} Live)")
                for w in new.warnings:
                    st.warning(w)
                st.code("python -m cptracker master <file.xlsx> --by <nama>", language=None)
            except MasterDataError as exc:
                st.error(f"Ditolak: {len(exc.errors)} error")
                st.write(exc.errors)
    with card("md-ver"):
        st.html(ui.section_head("Riwayat versi"))
        vers = store.conn.execute("SELECT * FROM master_versions ORDER BY version_id DESC").fetchall()
        st.dataframe(pd.DataFrame([dict(r) for r in vers]), hide_index=True, width="stretch")


def page_runlog():
    st.html(ui.page_title("Run log", "100 run terakhir, termasuk publish dan aktivasi master data."))
    with card("runs"):
        runs = store.conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 100").fetchall()
        st.dataframe(pd.DataFrame([dict(r) for r in runs]), hide_index=True, width="stretch")
    with card("resolved"):
        st.html(ui.section_head("Error yang sudah ditandai selesai"))
        res = store.conn.execute("SELECT * FROM errors WHERE resolved_at IS NOT NULL ORDER BY error_id DESC").fetchall()
        st.dataframe(pd.DataFrame([dict(r) for r in res]), hide_index=True, width="stretch")


{"ringkasan": page_ringkasan, "aplikasi": page_aplikasi, "dokumen": page_dokumen, "review": page_review,
 "master": page_master, "runlog": page_runlog}[page]()
