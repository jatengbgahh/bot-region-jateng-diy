"""
reports/clockin_sf_all/renderer.py — Gambar (HTML -> PNG lewat Chrome headless/Playwright) dan Excel
Report Clock-In SF All Category. Tampilan mengikuti contoh "Report_Clockin_All_SF_Oktober2026.pdf".
"""
from __future__ import annotations

import html
import os
import tempfile
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as L

from .calculator import BULAN, BULAN_PANJANG, fnum, fpct, label_periode

JUDUL = "Report Clock-In SF All Category"
CHROME_DEFAULT = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f4f6f9;font-family:'Poppins',Arial,sans-serif;color:#1f2a44}
.paper{width:1200px;background:#f7f8fb;padding:28px 34px 22px}
.hd{background:linear-gradient(120deg,#0b1f4d,#13306e);border-radius:18px;padding:26px 30px;color:#fff;
 display:flex;justify-content:space-between;align-items:center;border-bottom:5px solid #f5c518}
.hd h1{font-size:30px;font-weight:700}.hd p{font-size:14px;opacity:.85;margin-top:6px}
.pill{background:#f5c518;color:#0b1f4d;font-weight:700;font-size:15px;padding:10px 18px;border-radius:10px;white-space:nowrap}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:22px}
.k{background:#fff;border-radius:14px;padding:18px 20px;border:1px solid #e3e7ef;border-top:5px solid #0f8a95}
.k.y{border-top-color:#f5c518}.k .l{font-size:15px;font-weight:700;color:#0f6f78}.k.y .l{color:#1f2a44}
.k .v{font-size:38px;font-weight:700;color:#0b1f4d;line-height:1.15;margin-top:4px}
.k .v small{font-size:20px}.k .s{font-size:13px;color:#4a5568;margin-top:2px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:26px}
h2{font-size:21px;color:#0b1f4d;font-weight:700}.hint{font-size:11.5px;color:#6b7280;margin:4px 0 6px}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:12.5px;background:#fff}
th{background:#0b1f4d;color:#fff;font-weight:600;padding:9px 6px;text-align:right;font-size:11.5px;line-height:1.25}
th:nth-child(-n+2){text-align:left}
td{padding:9px 6px;text-align:right;border-bottom:1px solid #e6e9f0}
td:nth-child(-n+2){text-align:left}tr:nth-child(even) td{background:#f5f7fb}
tr.tot td{background:#fde9a6 !important;font-weight:700}
.g{color:#178a3e;font-weight:700}.r{color:#c8102e;font-weight:700}
.boxes{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px}
.box{border-radius:14px;padding:18px 20px}.box.b{background:#e2f1f5}.box.p{background:#fde8ec}
.box h3{font-size:17px;color:#0b1f4d;margin-bottom:8px}.box.p h3{color:#c8102e}
.box div{font-size:13px;line-height:1.6}
.wide{background:#fde8ec;border-radius:14px;padding:18px 20px;margin-top:20px}
.wide h3{font-size:17px;color:#c8102e;margin-bottom:6px}.wide div{font-size:13px;line-height:1.6}
.wide hr{border:0;border-top:1px solid #f3b6c2;margin:12px 0}
.src{font-size:12px;color:#6b7280;margin-top:16px;border-top:1px solid #dfe3ea;padding-top:10px}
"""


def _bar(arr, key, col, fmt, W=560, H=230):
    B, T, n = 22, 40, len(arr)
    bw = (W - 10) / max(1, n)
    mx = max([x[key] for x in arr] + [1])
    act = [x[key] for x in arr if x[key] > 0]
    avg = sum(act) / len(act) if act else 0
    s = []
    for i, x in enumerate(arr):
        v = x[key]
        h = v / mx * (H - B - T)
        xx, y = 5 + i * bw, H - B - h
        cx = xx + bw / 2
        s.append(f'<rect x="{xx + bw * .14:.1f}" y="{y:.1f}" width="{bw * .72:.1f}" height="{max(h, .5):.1f}" fill="{col}"/>')
        if v > 0:
            s.append(f'<text transform="translate({cx + 3.5:.1f} {y - 5:.1f}) rotate(-90)" font-size="10" fill="#414042">'
                     f'{fmt(v)}</text>')
        s.append(f'<text x="{cx:.1f}" y="{H - 8}" font-size="9.5" fill="#6f7074" text-anchor="middle">{x["d"].day}</text>')
    ya = H - B - avg / mx * (H - B - T)
    s.append(f'<line x1="5" y1="{H - B}" x2="{W - 5}" y2="{H - B}" stroke="#6f7074"/>')
    s.append(f'<line x1="5" y1="{ya:.1f}" x2="{W - 5}" y2="{ya:.1f}" stroke="{"#e0a800" if col != "#3b4fa8" else "#888"}" '
             f'stroke-dasharray="5 4" stroke-width="1.2"/>')
    return avg, f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}">{"".join(s)}</svg>'


def _rb(v):
    return fnum(v / 1000, 1) + "rb" if v >= 1000 else str(v)


def _marks(woks, key, top=3, bottom=3, bottom_only=False):
    """{index: 'g'|'r'} — hijau Top N, merah Bottom N."""
    xs = [(w[key], i) for i, w in enumerate(woks) if w[key] is not None]
    hi = [i for _, i in sorted(xs, reverse=True)[:top]] if not bottom_only else []
    lo = [i for _, i in sorted(xs)[:bottom]]
    m = {i: "g" for i in hi}
    m.update({i: "r" for i in lo})
    return m


def build_html(r: dict) -> str:
    t, W = r["total"], r["woks"]
    per = label_periode(r)
    tgl = r["tgl"]
    e = html.escape
    out = [f"<!doctype html><html><head><meta charset='utf-8'>"
           f"<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap'>"
           f"<style>{CSS}</style></head><body><div class='paper' id='paper'>"]
    out.append(f"<div class='hd'><div><h1>{JUDUL}</h1><p>Region Jateng-DIY · periode {per} · Sumber: detail "
               f"homepass SELA (status CHECKOUT)</p></div><div class='pill'>Periode {per}</div></div>")
    out.append("<div class='kpis'>"
               f"<div class='k'><div class='l'>SF Assign DJP</div><div class='v'>{fnum(t['asg'])} <small>dari "
               f"{fnum(t['reg'])}</small></div><div class='s'>{fpct(t['p_asg'])} dari SF Register</div>"
               f"<div class='s'>{fnum(t['belum_asg'])} SF belum di-assign</div></div>"
               f"<div class='k y'><div class='l'>SF Clockin DJP</div><div class='v'>{fnum(t['cl'])} <small>"
               f"({fpct(t['p_cl'])})</small></div><div class='s'>dari {fnum(t['reg'])} SF Register</div>"
               f"<div class='s'>{fnum(t['belum_ck'])} SF sudah di-assign, belum clock-in</div></div>"
               f"<div class='k'><div class='l'>Clock-in ODP</div><div class='v'>{fnum(t['odp_c'])} <small>"
               f"({fpct(t['ach_odp'])})</small></div><div class='s'>Assign {fnum(t['odp_a'])} ODP</div>"
               f"<div class='s'>{fnum(t['odp_day'], 1)} ODP per SF per hari</div></div>"
               f"<div class='k y'><div class='l'>Clock-in Homepass</div><div class='v'>{fnum(t['hp_c'])} <small>"
               f"({fpct(t['ach_hp'])})</small></div><div class='s'>Assign {fnum(t['hp_a'])} homepass</div>"
               f"<div class='s'>{fnum(t['hp_day'], 1)} homepass per SF per hari</div></div></div>")
    a1, s1 = _bar(r["harian"], "odp", "#0f8a95", str)
    a2, s2 = _bar(r["harian"], "hp", "#3b4fa8", _rb)
    out.append("<div class='two'>"
               f"<div><h2>Clock-in ODP per hari</h2><p class='hint'>Rata-rata {fnum(a1)} per hari yang ada clock-in "
               f"(garis putus-putus). Angka di bawah batang = tanggal.</p>{s1}</div>"
               f"<div><h2>Clock-in Homepass per hari</h2><p class='hint'>Rata-rata {fnum(a2)} per hari yang ada "
               f"clock-in (garis putus-putus). Angka di bawah batang = tanggal.</p>{s2}</div></div>")

    m_asg = _marks(W, "p_asg", bottom=1, bottom_only=True)
    m_asg = {i: c for i, c in m_asg.items() if W[i]["p_asg"] < 100}
    m_cl, m_odp, m_hp = _marks(W, "p_cl"), _marks(W, "ach_odp"), _marks(W, "ach_hp")
    c = lambda m, i: f" class='{m[i]}'" if i in m else ""
    out.append("<h2 style='margin-top:26px'>Detail per WOK</h2><table><tr><th>Branch</th><th>WOK</th>"
               "<th>SF<br>Register</th><th>SF Assign<br>DJP</th><th>% SF Assign<br>DJP</th><th>SF Clockin<br>DJP</th>"
               "<th>% SF Clockin<br>DJP</th><th>ODP<br>Assign</th><th>ODP<br>Clockin</th><th>Ach<br>ODP</th>"
               "<th>ODP/SF/Day</th><th>HP<br>Assign</th><th>HP<br>Clockin</th><th>Ach<br>HP</th><th>HP/SF/Day</th></tr>")
    prev = None
    for i, w in enumerate(W):
        br = w["br"] if w["br"] != prev else ""
        prev = w["br"]
        out.append(f"<tr><td>{e(br)}</td><td>{e(w['wok'])}</td><td>{fnum(w['reg'])}</td><td>{fnum(w['asg'])}</td>"
                   f"<td{c(m_asg, i)}>{fpct(w['p_asg'])}</td><td>{fnum(w['cl'])}</td><td{c(m_cl, i)}>{fpct(w['p_cl'])}</td>"
                   f"<td>{fnum(w['odp_a'])}</td><td>{fnum(w['odp_c'])}</td><td{c(m_odp, i)}>{fpct(w['ach_odp'])}</td>"
                   f"<td>{fnum(w['odp_day'], 1)}</td><td>{fnum(w['hp_a'])}</td><td>{fnum(w['hp_c'])}</td>"
                   f"<td{c(m_hp, i)}>{fpct(w['ach_hp'])}</td><td>{fnum(w['hp_day'], 1)}</td></tr>")
    out.append(f"<tr class='tot'><td>Jateng-DIY</td><td></td><td>{fnum(t['reg'])}</td><td>{fnum(t['asg'])}</td>"
               f"<td>{fpct(t['p_asg'])}</td><td>{fnum(t['cl'])}</td><td>{fpct(t['p_cl'])}</td><td>{fnum(t['odp_a'])}</td>"
               f"<td>{fnum(t['odp_c'])}</td><td>{fpct(t['ach_odp'])}</td><td>{fnum(t['odp_day'], 1)}</td>"
               f"<td>{fnum(t['hp_a'])}</td><td>{fnum(t['hp_c'])}</td><td>{fpct(t['ach_hp'])}</td>"
               f"<td>{fnum(t['hp_day'], 1)}</td></tr></table>")

    ok = [w for w in W if w["p_cl"] is not None]
    top = sorted(ok, key=lambda w: -w["p_cl"])[:3]
    low = sorted(ok, key=lambda w: w["p_cl"])[:3]
    out.append("<div class='boxes'><div class='box b'><h3>Highest Clockin DJP (% SF Clockin DJP)</h3>"
               + "".join(f"<div><b>{e(w['wok'])}</b> {fpct(w['p_cl'])}</div>" for w in top)
               + "</div><div class='box p'><h3>Need Attention (% SF Clockin DJP terendah)</h3>"
               + "".join(f"<div><b>{e(w['wok'])}</b> {fpct(w['p_cl'])} · assign "
                         f"{'baru' if (w['p_asg'] or 0) < 90 else 'sudah'} {fpct(w['p_asg'])}</div>" for w in low)
               + "</div></div>")
    bc = " · ".join(f"<b>{e(b)}</b> {fnum(n)}" for b, n in r["belum_ck_br"].items())
    ba = " · ".join(f"<b>{e(w['wok'])}</b> {fnum(w['belum_asg'])}"
                    for w in sorted(W, key=lambda w: -w["belum_asg"]) if w["belum_asg"] > 0) or "-"
    out.append(f"<div class='wide'><h3>SF Assign DJP belum clock-in ({fnum(t['belum_ck'])})</h3><div>{bc}</div><hr>"
               f"<h3>SF belum di-assign ({fnum(t['belum_asg'])})</h3><div>{ba}</div></div>")
    out.append(f"<div class='src'>Source : SELA Clock-in SF {BULAN_PANJANG[tgl.month - 1]} {tgl.year}, Data SF & HADOOP"
               f"</div></div></body></html>")
    return "".join(out)


def render_png(r: dict, timeout_ms: int = 60000) -> BytesIO:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="clockin_all_") as d:
        p_html = os.path.join(d, "report.html")
        with open(p_html, "w", encoding="utf-8") as f:
            f.write(build_html(r))
        with sync_playwright() as p:
            kw = {"channel": "chrome"} if os.path.exists(CHROME_DEFAULT) else {}
            b = p.chromium.launch(headless=True, **kw)
            try:
                page = b.new_page(viewport={"width": 1280, "height": 1000}, device_scale_factor=2)
                page.set_default_timeout(timeout_ms)
                try:
                    page.goto("file:///" + p_html.replace("\\", "/"), wait_until="networkidle", timeout=20000)
                except Exception:                     # tanpa internet: font Poppins tidak termuat -> Arial
                    pass
                page.evaluate("document.fonts && document.fonts.ready")
                png = page.locator("#paper").screenshot(type="png")
            finally:
                b.close()
    return BytesIO(png)


# ── Excel ────────────────────────────────────────────────────────────────────
def build_excel(r: dict) -> tuple[BytesIO, str]:
    hdr_fill, hdr_font = PatternFill("solid", fgColor="0B1F4D"), Font(bold=True, color="FFFFFF")
    wb = Workbook()

    def sheet(ws, header, rows, widths, pct_cols=(), dec_cols=()):
        ws.append(header)
        for c in ws[ws.max_row]:
            c.fill, c.font = hdr_fill, hdr_font
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        h = ws.max_row
        for row in rows:
            ws.append(row)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[L(i)].width = w
        for rr in range(h + 1, ws.max_row + 1):
            for c in pct_cols:
                ws.cell(row=rr, column=c).number_format = "0.0%"
            for c in dec_cols:
                ws.cell(row=rr, column=c).number_format = "0.0"
        ws.freeze_panes = ws.cell(row=h + 1, column=1)
        ws.auto_filter.ref = f"A{h}:{L(len(header))}{ws.max_row}"

    p = lambda v: None if v is None else v / 100
    ws = wb.active
    ws.title = "Ringkasan WOK"
    ws.append([f"{JUDUL} — Jateng-DIY — periode {label_periode(r)}"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(["Clock-in = Journey Status CHECKOUT (detail homepass SELA); SF Register = SF ACTIVE database_sf "
               "(tanpa SF dummy)."])
    ws.append([])
    rows = [[w["br"], w["wok"], w["reg"], w["asg"], p(w["p_asg"]), w["cl"], p(w["p_cl"]), w["odp_a"], w["odp_c"],
             p(w["ach_odp"]), w["odp_day"], w["hp_a"], w["hp_c"], p(w["ach_hp"]), w["hp_day"]] for w in r["woks"]]
    t = r["total"]
    rows.append(["Jateng-DIY", "", t["reg"], t["asg"], p(t["p_asg"]), t["cl"], p(t["p_cl"]), t["odp_a"], t["odp_c"],
                 p(t["ach_odp"]), t["odp_day"], t["hp_a"], t["hp_c"], p(t["ach_hp"]), t["hp_day"]])
    sheet(ws, ["Branch", "WOK", "SF Register", "SF Assign DJP", "% SF Assign DJP", "SF Clockin DJP",
               "% SF Clockin DJP", "ODP Assign", "ODP Clockin", "Ach ODP", "ODP/SF/Day", "HP Assign", "HP Clockin",
               "Ach HP", "HP/SF/Day"], rows, [13, 22] + [12] * 13, pct_cols=(5, 7, 10, 14), dec_cols=(11, 15))
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)

    det = r["detail"]
    sheet(wb.create_sheet("Detail SF"),
          ["Branch", "WOK", "Kode SF", "Nama SF", "Hari Clock-in", "ODP Assign", "ODP Clockin", "HP Assign",
           "HP Clockin", "Status"],
          [[d["br"], d["wok"], d["kode"], d["nama"], d["hari"], d["odp_a"], d["odp_c"], d["hp_a"], d["hp_c"],
            d["status"]] for d in det], [13, 22, 14, 32, 12, 11, 11, 11, 11, 16])
    sheet(wb.create_sheet("SF Belum Clock-in"), ["Branch", "WOK", "Kode SF", "Nama SF", "HP Assign", "Status"],
          [[d["br"], d["wok"], d["kode"], d["nama"], d["hp_a"], d["status"]]
           for d in det if d["status"] != "Sudah clock-in"], [13, 22, 14, 32, 11, 16])
    sheet(wb.create_sheet("Harian Region"), ["Tanggal", "Clock-in ODP", "Clock-in Homepass"],
          [[x["d"], x["odp"], x["hp"]] for x in r["harian"]], [12, 14, 18])
    ws = wb["Harian Region"]
    for rr in range(2, ws.max_row + 1):
        ws.cell(row=rr, column=1).number_format = "yyyy-mm-dd"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    tgl = r["tgl"]
    return buf, f"Report_Clockin_SF_All_Category_{tgl:%Y%m%d}.xlsx"
