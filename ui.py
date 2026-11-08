"""HTML fragments for the dashboard, following the Design canvas (Ringkasan, Daftar aplikasi, Detail dokumen).

Every value from MPM, msForm or master data goes through esc() / safe_url() before it reaches HTML.
"""
from __future__ import annotations

import html
import math
from datetime import datetime
from urllib.parse import quote

from .data import GROUPS, AgingRow, AppRow, BurnPoint, DeptSummary, fmt_day

INK, INK2, MUTED, FAINT, LINE = "#1C1C1F", "#4A4A4F", "#6B6B70", "#A1A1A8", "#F0F0F3"
BLUE = "#2A78D6"
COLOR = {"fso": "#1F8A5B", "pending": "#E5A00D", "rej": "#D9453B", "review": "#6E56CF", "belum": "#C9CBD1"}
ROW_COLOR = {"APPROVED": COLOR["fso"], "PENDING": COLOR["pending"], "REJECTED": COLOR["rej"],
             "CANCELLED": COLOR["rej"], "NOT_STARTED": COLOR["belum"]}
VALIDATION_COLOR = {"Match": COLOR["fso"], "Alternate": BLUE, "Mismatch": COLOR["rej"], "Unknown": COLOR["review"]}
DOC_STATUS_COLOR = {"FSO": COLOR["fso"], "WET_SIGN": COLOR["fso"], "PENDING": COLOR["pending"],
                    "REJECTED": COLOR["rej"], "CANCELLED": COLOR["rej"], "ANOMALY": COLOR["review"],
                    "INCOMPLETE_CHAIN": COLOR["review"], "ERROR": COLOR["review"]}
MONO = "font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace"

CSS = f"""
<style>
.stApp {{ background: #F4F4F6; color: {INK}; }}
.stApp, .stApp button, .stApp input, .stApp select {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  font-variant-numeric: tabular-nums;
}}
header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stToolbar"], footer {{ display: none !important; }}
.block-container {{ max-width: 1248px !important; padding: 0 24px 72px !important; }}
[class*="st-key-card"] {{ background: #FFFFFF; border-radius: 18px; padding: 28px 32px; gap: 12px; }}
@media (max-width: 640px) {{ [class*="st-key-card"] {{ padding: 22px 18px; }} }}
.ct a {{ color: #0A6AD1; text-decoration: none; }}
.ct a:hover {{ color: #0753A6; text-decoration: underline; }}
.ct h2 {{ margin: 0; padding: 0; font-size: 21px; font-weight: 600; letter-spacing: -0.015em; color: {INK}; }}
.ct p {{ margin: 0; }}
.ct table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
.ct th {{ font-weight: 500; color: {MUTED}; font-size: 12px; text-align: left; padding: 10px 12px;
         border-bottom: 1px solid #E3E3E8; }}
.ct td {{ padding: 14px 12px; border-bottom: 1px solid {LINE}; vertical-align: top; }}
.ct .scroll {{ overflow-x: auto; }}
.ct .muted {{ color: {MUTED}; }}
.ct .sub {{ font-size: 12px; color: {MUTED}; margin-top: 2px; }}
.ct .mono {{ {MONO}; font-size: 12px; white-space: nowrap; }}
.ct .dot {{ width: 8px; height: 8px; border-radius: 50%; flex: none; display: inline-block; }}
.ct .st {{ display: inline-flex; align-items: center; gap: 8px; font-weight: 500; white-space: nowrap; }}
.ct dl {{ margin: 0; }} .ct dt {{ font-size: 12px; color: {MUTED}; }} .ct dd {{ margin: 0 0 12px; }}
a:focus-visible, button:focus-visible, input:focus-visible {{ outline: 3px solid #8DB8EE; outline-offset: 2px; }}
</style>
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def safe_url(u: str | None) -> str | None:
    """Only http(s) links reach an href: msForm answers are free text and could hold javascript: URLs."""
    u = (u or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else None


def link(u: str | None, text: str) -> str:
    url = safe_url(u)
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>' if url else esc(text)


def page_href(page: str, **params) -> str:
    q = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"?page={page}" + (f"&{q}" if q else "")


def dot(color: str, size: int = 8) -> str:
    return f'<span aria-hidden="true" class="dot" style="background:{color};width:{size}px;height:{size}px"></span>'


def status_badge(color: str, label: str) -> str:
    return f'<span class="st">{dot(color)}{esc(label)}</span>'


def wrap(inner: str) -> str:
    return f'<div class="ct">{inner}</div>'


def section_head(title: str, sub: str = "") -> str:
    s = f'<p class="muted" style="margin-top:4px;font-size:14px">{esc(sub)}</p>' if sub else ""
    return wrap(f"<h2>{esc(title)}</h2>{s}")


# Header
NAV = [("ringkasan", "Ringkasan"), ("aplikasi", "Daftar aplikasi"), ("review", "Perlu review"),
       ("master", "Master data"), ("runlog", "Run log")]


def header(active: str, data_label: str) -> str:
    links = "".join(
        f'<a href="{page_href(k)}" target="_self" {"aria-current=page" if k == active else ""} '
        f'style="padding:16px 0;color:{INK if k == active else INK2};font-weight:{600 if k == active else 400};'
        f'text-decoration:none">{esc(label)}</a>'
        for k, label in NAV
    )
    return f"""
<header class="ct" style="background:rgba(255,255,255,0.86);border-bottom:1px solid #E3E3E8;margin:0 -24px">
  <div style="max-width:1200px;margin:0 auto;padding:0 24px;display:flex;flex-wrap:wrap;align-items:center;gap:4px 28px;min-height:52px">
    <span style="font-weight:600;font-size:15px;letter-spacing:-0.01em">Capacity Planning Tracker</span>
    <nav aria-label="Halaman" style="display:flex;flex-wrap:wrap;gap:2px 20px;flex:1 1 auto;font-size:13px">{links}</nav>
    <span style="font-size:12px;color:{MUTED}">{esc(data_label)}</span>
  </div>
</header>"""


# Ringkasan
def hero(cycle: int, fso: int, total: int, pending: int, belum: int, days_left: int, deadline: datetime) -> str:
    dl = f"{deadline.day} {['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus','September','Oktober','November','Desember'][deadline.month - 1]}, {deadline:%H:%M}"
    return wrap(f"""
<section style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:24px 48px;padding:56px 4px 12px">
  <div style="flex:1 1 560px">
    <p style="margin:0 0 8px;font-size:14px;font-weight:600;color:{MUTED}">Capacity Plan · Cycle {cycle}</p>
    <h1 style="margin:0;padding:0;font-size:clamp(34px,5vw,48px);line-height:1.08;font-weight:600;letter-spacing:-0.025em;color:{INK}">{fso} dari {total} aplikasi<br>sudah FSO.</h1>
    <p style="margin:14px 0 0;font-size:19px;line-height:1.4;color:{INK2};max-width:620px">{pending} masih menunggu approver dan {belum} belum submit msForm. Semua harus selesai sebelum {esc(dl)}.</p>
  </div>
  <div style="text-align:right">
    <div style="font-size:56px;line-height:1;font-weight:600;letter-spacing:-0.03em">{max(days_left, 0)}</div>
    <div style="font-size:14px;color:{MUTED};margin-top:6px">hari ke deadline</div>
  </div>
</section>""")


def composition(counts: dict[str, int]) -> str:
    total = sum(counts.values()) or 1
    aria = ", ".join(f"{label} {counts[k]}" for k, label in GROUPS)
    bar = "".join(
        f'<div title="{esc(label)}: {counts[k]}" style="flex:{counts[k]} 1 0;background:{COLOR[k]}"></div>'
        for k, label in GROUPS if counts[k]
    )
    legend = "".join(f"""
<div style="flex:1 1 150px;display:flex;flex-direction:column;gap:2px">
  <div style="display:flex;align-items:center;gap:8px;font-size:13px;color:{INK2}">{dot(COLOR[k], 10)}{esc(label)}</div>
  <div style="display:flex;align-items:baseline;gap:8px">
    <span style="font-size:30px;font-weight:600;letter-spacing:-0.02em">{counts[k]}</span>
    <span style="font-size:13px;color:{MUTED}">{round(counts[k] / total * 100)}%</span>
  </div>
</div>""" for k, label in GROUPS)
    return wrap(f"""
<h2>Komposisi status</h2>
<p class="muted" style="margin:4px 0 20px;font-size:14px">{sum(counts.values())} aplikasi Live, satu status per aplikasi.</p>
<div role="img" aria-label="{esc(aria)}" style="display:flex;gap:2px;height:36px;border-radius:8px;overflow:hidden;background:#F4F4F6">{bar}</div>
<div style="display:flex;flex-wrap:wrap;gap:20px 32px;margin-top:22px">{legend}</div>""")


def burnup(points: list[BurnPoint], total: int, now: datetime, deadline: datetime, remaining: int, per_week: int) -> str:
    legend = f"""
<div style="display:flex;gap:18px;font-size:13px;color:{INK2}">
  <span style="display:inline-flex;align-items:center;gap:6px"><span aria-hidden="true" style="width:14px;height:2px;background:{BLUE}"></span>Sudah submit</span>
  <span style="display:inline-flex;align-items:center;gap:6px"><span aria-hidden="true" style="width:14px;height:2px;background:{COLOR['fso']}"></span>FSO</span>
</div>"""
    head = f"""
<div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 24px">
  <div><h2>Progres menuju deadline</h2>
  <p class="muted" style="margin-top:4px;font-size:14px">Jumlah kumulatif per minggu dari snapshot publish.</p></div>{legend}
</div>"""
    if not points or total == 0:
        return wrap(head + f'<p class="muted" style="margin-top:24px">Belum ada snapshot publish untuk digambar.</p>')

    start = points[0].day
    span = max((deadline - start).total_seconds(), 1)

    def X(d: datetime) -> float:
        return round(44 + max(min((d - start).total_seconds() / span, 1), 0) * 576, 1)

    def Y(v: int) -> float:
        return round(230 - v / total * 210, 1)

    mid1, mid2 = round(total * 2 / 3), round(total / 3)
    sub_line = " ".join(f"{X(p.day)},{Y(p.submitted)}" for p in points)
    fso_line = " ".join(f"{X(p.day)},{Y(p.fso)}" for p in points)
    dots = "".join(
        f'<circle cx="{X(p.day)}" cy="{Y(p.submitted)}" r="3.5" fill="{BLUE}" stroke="#fff" stroke-width="2">'
        f'<title>Minggu {esc(fmt_day(p.day))}: sudah submit {p.submitted}, FSO {p.fso}</title></circle>'
        f'<circle cx="{X(p.day)}" cy="{Y(p.fso)}" r="3.5" fill="{COLOR["fso"]}" stroke="#fff" stroke-width="2">'
        f'<title>Minggu {esc(fmt_day(p.day))}: sudah submit {p.submitted}, FSO {p.fso}</title></circle>'
        for p in points
    )
    last = points[-1]
    tx = X(now)
    end_x = X(last.day) + 10
    aria = (f"Sudah submit naik dari {points[0].submitted} ke {last.submitted}, FSO dari {points[0].fso} ke {last.fso}, "
            f"antara {fmt_day(start)} dan {fmt_day(last.day)}")
    sub_y, fso_y = Y(last.submitted) + 4, Y(last.fso) + 4
    if abs(sub_y - fso_y) < 12:          # keep the two end labels from overlapping
        fso_y = sub_y + 12
    svg = f"""
<svg viewBox="0 0 640 260" role="img" aria-label="{esc(aria)}" style="width:100%;height:auto;display:block;overflow:visible;margin-top:16px">
  <line x1="44" y1="230" x2="620" y2="230" stroke="#D2D2D7"/>
  <line x1="44" y1="20" x2="620" y2="20" stroke="#E8E8ED" stroke-dasharray="3 4"/>
  <line x1="44" y1="{Y(mid1)}" x2="620" y2="{Y(mid1)}" stroke="{LINE}"/>
  <line x1="44" y1="{Y(mid2)}" x2="620" y2="{Y(mid2)}" stroke="{LINE}"/>
  <text x="36" y="24" text-anchor="end" font-size="11" fill="{MUTED}">{total}</text>
  <text x="36" y="{Y(mid1) + 4}" text-anchor="end" font-size="11" fill="{MUTED}">{mid1}</text>
  <text x="36" y="{Y(mid2) + 4}" text-anchor="end" font-size="11" fill="{MUTED}">{mid2}</text>
  <text x="36" y="234" text-anchor="end" font-size="11" fill="{MUTED}">0</text>
  <line x1="{tx}" y1="20" x2="{tx}" y2="230" stroke="#C7C7CC"/>
  <text x="{tx}" y="250" text-anchor="middle" font-size="11" fill="{INK2}">Hari ini</text>
  <line x1="620" y1="20" x2="620" y2="230" stroke="{INK}" stroke-dasharray="2 3"/>
  <text x="620" y="250" text-anchor="end" font-size="11" fill="{INK}">{esc(fmt_day(deadline))}</text>
  <text x="44" y="250" text-anchor="start" font-size="11" fill="{MUTED}">{esc(fmt_day(start))}</text>
  <polyline points="{sub_line}" fill="none" stroke="{BLUE}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  <polyline points="{fso_line}" fill="none" stroke="{COLOR['fso']}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  {dots}
  <text x="{end_x}" y="{sub_y}" font-size="12" font-weight="600" fill="{INK}">{last.submitted}</text>
  <text x="{end_x}" y="{fso_y}" font-size="12" font-weight="600" fill="{INK}">{last.fso}</text>
</svg>"""
    note = (f"Butuh rata-rata {per_week} submission per minggu untuk {remaining} aplikasi yang tersisa."
            if remaining else "Semua aplikasi Live sudah submit msForm.")
    return wrap(head + svg + f'<p class="muted" style="margin-top:8px;font-size:13px">{esc(note)}</p>')


def error_item(code: str, at: datetime, message: str, hint: str) -> str:
    h = f'<p class="muted" style="font-size:13px">{esc(hint)}</p>' if hint else ""
    return wrap(f"""
<div style="display:flex;justify-content:space-between;gap:12px;font-size:12px;color:{MUTED}">
  <span style="{MONO};color:#B3261E;font-weight:600">{esc(code)}</span><span>{esc(fmt_day(at))}, {at:%H:%M}</span>
</div>
<p style="margin:4px 0 2px">{esc(message)}</p>{h}""")


def dept_legend() -> str:
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px">{dot(COLOR[k], 10)}{esc(label)}</span>'
        for k, label in GROUPS
    )
    return wrap(f'<div style="display:flex;flex-wrap:wrap;gap:8px 22px;margin:6px 0 4px;font-size:12px;color:{INK2}">{items}</div>')


def dept_chart(depts: list[DeptSummary]) -> str:
    if not depts:
        return wrap('<p class="muted">Belum ada data.</p>')
    biggest = max(d.live for d in depts) or 1
    rows = []
    for d in depts:
        tpl = f" · {d.template} section" if d.template else ""
        tip = f"{d.code} · {d.live} aplikasi{tpl}\n" + "\n".join(f"{label}: {d.counts[k]}" for k, label in GROUPS)
        segs = "".join(f'<div style="flex:{d.counts[k]} 1 0;background:{COLOR[k]}"></div>' for k, _ in GROUPS if d.counts[k])
        rows.append(f"""
<div title="{esc(tip)}" style="display:grid;grid-template-columns:56px minmax(0,1fr) 72px;align-items:center;gap:16px;min-height:28px">
  <span style="font-size:13px;font-weight:600">{esc(d.code)}</span>
  <div role="img" aria-label="{esc(tip.replace(chr(10), ', '))}" style="display:flex;gap:2px;height:20px;border-radius:4px;overflow:hidden;width:{d.live / biggest * 100:.1f}%">{segs}</div>
  <span style="font-size:13px;color:{INK2};text-align:right">{d.counts['belum']} belum</span>
</div>""")
    return wrap(f'<div style="display:flex;flex-direction:column;gap:10px">{"".join(rows)}</div>'
                f'<p class="muted" style="margin-top:12px;font-size:12px">Arahkan kursor ke bar untuk rinciannya.</p>')


def dept_table(depts: list[DeptSummary]) -> str:
    head = "".join(f'<th style="text-align:right">{esc(h)}</th>'
                   for h in ["Live", "FSO", "Pending", "Rej/Cancel", "Review", "Belum submit"])
    body = "".join(
        f'<tr><th scope="row" style="font-weight:600;color:{INK};font-size:14px">{esc(d.code)} '
        f'<span style="font-weight:400;color:{MUTED};font-size:13px">{esc(f"{d.template} section" if d.template else "")}</span></th>'
        f'<td style="text-align:right">{d.live}</td><td style="text-align:right">{d.counts["fso"]}</td>'
        f'<td style="text-align:right">{d.counts["pending"]}</td><td style="text-align:right">{d.counts["rej"]}</td>'
        f'<td style="text-align:right">{d.counts["review"]}</td>'
        f'<td style="text-align:right;font-weight:600">{d.counts["belum"]}</td></tr>'
        for d in depts
    )
    return wrap(f'<div class="scroll"><table style="min-width:640px"><thead><tr><th>Departemen</th>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>')


def aging(rows: list[AgingRow]) -> str:
    head = section_head("Lama Pending per jabatan",
                        "Bar = median hari Pending; garis tipis = dokumen terlama. Agregat per jabatan, bukan per nama pejabat.")
    if not rows:
        return head + wrap('<p class="muted" style="margin-top:16px">Tidak ada dokumen Pending.</p>')
    scale = max(15, math.ceil(max(r.max_days for r in rows) / 5) * 5)
    lines = []
    for r in rows:
        m, mx = r.median_days / scale * 100, r.max_days / scale * 100
        tip = f"{r.jabatan}: median {r.median_days:.0f} hari, terlama {r.max_days:.0f} hari"
        lines.append(f"""
<div style="display:grid;grid-template-columns:160px minmax(0,1fr) 190px;align-items:center;gap:16px">
  <div><div style="font-size:14px;font-weight:500">{esc(r.jabatan)}</div><div class="sub">{r.docs} dokumen</div></div>
  <div title="{esc(tip)}" role="img" aria-label="{esc(tip)}" style="position:relative;height:12px">
    <div style="position:absolute;left:0;right:0;top:5px;height:2px;background:{LINE};border-radius:1px"></div>
    <div style="position:absolute;left:0;top:5px;height:2px;background:#9BBFEA;border-radius:1px;width:{mx:.1f}%"></div>
    <div style="position:absolute;left:0;top:0;height:12px;background:{BLUE};border-radius:0 4px 4px 0;width:{m:.1f}%"></div>
    <div style="position:absolute;top:0;width:2px;height:12px;background:{BLUE};border-radius:1px;left:calc({mx:.1f}% - 2px)"></div>
  </div>
  <div style="font-size:13px;text-align:right;color:{INK2}">median <strong style="color:{INK}">{r.median_days:.0f} hr</strong> · terlama {r.max_days:.0f} hr</div>
</div>""")
    ticks = "".join(f"<span>{t}</span>" for t in (0, scale // 3, scale * 2 // 3)) + f"<span>{scale} hari</span>"
    return head + wrap(f"""
<div style="display:flex;flex-direction:column;gap:14px;margin-top:20px">{''.join(lines)}</div>
<div style="display:grid;grid-template-columns:160px minmax(0,1fr) 190px;gap:16px;margin-top:10px;font-size:11px;color:{MUTED}">
  <span></span><div style="display:flex;justify-content:space-between">{ticks}</div><span></span>
</div>""")


def footer(left: str, right: str = "") -> str:
    return wrap(f'<div role="contentinfo" style="display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:12px;'
                f'color:{MUTED};padding:0 4px">{esc(left)}<span>{esc(right)}</span></div>')


# Daftar aplikasi
def page_title(title: str, sub: str, top: int = 48) -> str:
    return wrap(f'<div style="padding:{top}px 4px 0"><h1 style="margin:0;padding:0;font-size:clamp(30px,4vw,40px);'
                f'line-height:1.1;font-weight:600;letter-spacing:-0.025em;color:{INK}">{esc(title)}</h1>'
                f'<p style="margin:8px 0 0;font-size:17px;color:{INK2}">{esc(sub)}</p></div>')


def app_table(rows: list[AppRow]) -> str:
    if not rows:
        return wrap('<p class="muted" style="padding:16px 4px">Tidak ada aplikasi dengan filter ini.</p>')
    body = []
    for r in rows:
        flag = "".join(f'<div style="font-size:12px;color:{COLOR["review"]};margin-top:4px;font-weight:500">{esc(f)}</div>'
                       for f in r.flags)
        sub = " · ".join(x for x in (r.dept_code, r.team_leader) if x)
        body.append(f"""<tr>
<td style="padding-left:28px"><a href="{page_href('dokumen', app=r.app)}" target="_self" style="font-weight:600;color:{INK}">{esc(r.app)}</a>
<div class="sub">{esc(sub)}</div></td>
<td style="white-space:nowrap">{status_badge(COLOR[r.group], r.status_label)}{flag}</td>
<td style="font-size:13px;color:{INK2};white-space:nowrap"><div>{esc(r.cpr)}</div><div>{esc(r.cpd)}</div></td>
<td style="font-size:13px;color:{INK2};max-width:340px">{esc(r.note)}</td>
<td style="text-align:right;white-space:nowrap;font-weight:500">{esc(f"{r.aging_days:.0f} hari" if r.aging_days is not None else "—")}</td>
<td style="white-space:nowrap;color:{INK2}">{esc(fmt_day(r.request_date))}</td>
<td style="white-space:nowrap;color:{INK2};padding-right:28px">{esc(fmt_day(r.fso_date))}</td>
</tr>""")
    return wrap(f"""<div class="scroll"><table style="min-width:1080px"><thead><tr>
<th style="padding-left:28px">Aplikasi</th><th>Status</th><th>Dokumen</th><th>Keterangan</th>
<th style="text-align:right">Aging</th><th>Request</th><th style="padding-right:28px">FSO</th>
</tr></thead><tbody>{''.join(body)}</tbody></table></div>""")


# Detail dokumen
def back_link() -> str:
    return wrap(f'<a href="{page_href("aplikasi")}" target="_self" style="font-size:14px;display:inline-flex;'
                f'align-items:center;min-height:36px;padding:24px 4px 0">‹ Daftar aplikasi</a>')


def detail_head(dept_code: str, tl: str, app: str) -> str:
    pre = " · ".join(x for x in (dept_code, f"Team Leader {tl}" if tl else "") if x)
    return wrap(f'<p style="margin:8px 4px 0;font-size:14px;font-weight:600;color:{MUTED}">{esc(pre)}</p>'
                f'<h1 style="margin:6px 4px 0;padding:0;font-size:clamp(32px,4.5vw,44px);line-height:1.08;'
                f'font-weight:600;letter-spacing:-0.025em;color:{INK}">{esc(app)}</h1>')


def status_card(color: str, headline: str, text: str, facts: list[tuple[str, str, bool]]) -> str:
    dl = "".join(
        f'<div><dt>{esc(k)}</dt><dd style="{"font-size:22px;font-weight:600" if big else ("color:" + MUTED if v in ("Belum FSO", "Belum terhitung", "—") else "font-size:17px")};margin-bottom:8px">{esc(v)}</dd></div>'
        for k, v, big in facts
    )
    return wrap(f"""
<div style="display:flex;flex-wrap:wrap;gap:24px 48px;align-items:center">
  <div style="flex:1 1 520px">
    <div style="display:inline-flex;align-items:center;gap:8px;font-size:14px;font-weight:600">{dot(color, 10)}{esc(headline)}</div>
    <p style="margin-top:8px;font-size:22px;line-height:1.3;letter-spacing:-0.015em">{esc(text)}</p>
  </div>
  <dl style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:40px;flex:0 1 360px">{dl}</dl>
</div>""")


def approval_log(rows, row_status: dict[str, str]) -> str:
    body = []
    for r in rows:
        canon = row_status.get(r.raw_status, "")
        style = "background:#FFF8E8" if canon == "PENDING" else (f"color:{MUTED}" if canon == "NOT_STARTED" else "")
        body.append(f"""<tr style="{style}">
<td style="padding-left:32px;font-weight:600">{r.section}</td>
<td><div style="font-weight:500">{esc(r.name)}</div><div class="sub">{esc(r.role_label)}</div></td>
<td>{status_badge(ROW_COLOR.get(canon, COLOR['belum']), r.raw_status)}</td>
<td class="mono">{esc(r.request)}</td><td class="mono" style="padding-right:32px">{esc(r.response)}</td></tr>""")
    return wrap(f"""<div class="scroll"><table style="min-width:700px"><thead><tr>
<th style="padding-left:32px">Section</th><th>Peran · Nama</th><th>Status MPM</th><th>Request Date</th>
<th style="padding-right:32px">Response Date</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p class="muted" style="padding:12px 0 0;font-size:12px">Tanggal ditampilkan persis seperti di MPM (DD/MM/YYYY HH.mm.ss, WIB). Status "-" = approver berikutnya yang belum aktif.</p>""")


def validation_table(items: list[dict]) -> str:
    if not items:
        return wrap('<p class="muted">Belum ada hasil validasi.</p>')
    body = "".join(f"""<tr>
<td style="padding-left:32px;font-weight:600">{esc(v['section'] or '-')}</td><td>{esc(v['jabatan'])}</td><td>{esc(v['name'])}</td>
<td style="padding-right:32px">{status_badge(VALIDATION_COLOR.get(v['result'], COLOR['belum']), v['result'])}<div class="sub">{esc(v['basis'])}</div></td>
</tr>""" for v in items)
    return wrap(f"""<div class="scroll"><table style="min-width:600px"><thead><tr>
<th style="padding-left:32px">Section</th><th>Jabatan wajib</th><th>Nama di MPM</th><th style="padding-right:32px">Hasil</th>
</tr></thead><tbody>{body}</tbody></table></div>""")


def header_mpm(header: dict, app_name: str, name_mismatch: bool, link_url: str, pdf_url: str) -> str:
    if not header:
        rows = f'<dt>Dokumen</dt><dd>{link(pdf_url, "Buka PDF full sign-off") if pdf_url else "—"}</dd>'
    else:
        same = (f'<span style="font-size:12px;color:{COLOR["rej"]}">· beda dengan nama di msForm (NAME_MISMATCH)</span>'
                if name_mismatch else f'<span style="font-size:12px;color:#1F7A50">· sama dengan nama di msForm</span>')
        badge = " · ".join(x for x in (header.get("flow_badge"), header.get("status_badge")) if x)
        main = header.get("main_document") or ""
        main_label = main.rsplit("/", 1)[-1] if main else "—"
        rows = (f'<dt>Project Name</dt><dd>{esc(header.get("project_name"))} {same}</dd>'
                f'<dt>Badge</dt><dd>{esc(badge or "—")}</dd>'
                f'<dt>Main Document</dt><dd>{link(main, main_label)}</dd>'
                f'<dt>Approval log</dt><dd>{link(link_url, "Buka di MPM ›") if safe_url(link_url) else "—"}</dd>')
    return wrap(f'<dl style="margin-top:16px">{rows}</dl>')


def history_item(color: str, at: str, text: str) -> str:
    return wrap(f"""<div style="display:grid;grid-template-columns:14px minmax(0,1fr);gap:12px">
<span aria-hidden="true" style="width:10px;height:10px;border-radius:50%;margin-top:5px;background:{color}"></span>
<div><div style="font-size:12px;color:{MUTED}">{esc(at)}</div><div style="font-size:14px">{esc(text)}</div></div></div>""")
