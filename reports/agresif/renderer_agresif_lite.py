"""
renderer_agresif_lite.py — Render tabel LITE report /agresif (lihat agresif_lite.py).

Satu tabel datar, kolom persis mockup user (08-Sep-2026):
  NO | BRANCH | CITY | KECAMATAN | RE M-1 | RE M | MoM RE | PS M-1 | PS M | MoM PS | TARGET | ACH

Dipakai utk 2 report:
  render_lite_lokasi() -> REPORT NEW SALES LOKASI AGRESIF
  render_lite_fmc()    -> REPORT NEW SALES ALL FMC CITY  (kolom KECAMATAN kosong)

Warna MoM (hijau/merah) & data-bar ACH diambil dari agresif_colors.py — sama
sumber dgn renderer_agresif.py. Font dipatok (renderer_caps_font), lebar kolom
menyesuaikan isi (tulisan tidak pernah mengecil). Invariant matplotlib: render
SINKRON di event loop, bukan to_thread (lihat memory concurrency-model-bot-re-jateng).
"""
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from renderer_caps_font import col_width, measure_w, FS_DATA, FS_LABEL, FS_SUBHDR
import agresif_colors as C

C_BG = "white"
C_DARK = "#1A1A1A"
C_SEP = "#BDC3C7"
C_HDR = "#1F3864"
C_ROW_A = "white"
C_ROW_B = "#F4F6F7"
C_BRANCH_BG = "#D9D9D9"
C_JATENG_BG = "#1F3864"   # biru navy (sejak 04-Nov-2026), font putih
C_JATENG_FG = "white"
C_SECTION_BG = "#BFBFBF"


def _num(v):
    return "-" if v is None else f"{int(round(v)):,}"


def _pct(v):
    return "-" if v is None else f"{v * 100:.1f}%"


# kolom = (label, getter, kind)  kind: None | "mom" | "ach"
def _columns(has_kec):
    cols = [
        ("NO", None, None),
        ("BRANCH", lambda r: r.get("branch", "") or "", None),
        ("CITY", lambda r: r.get("city", "") or "", None),
    ]
    if has_kec:
        cols.append(("KECAMATAN", lambda r: r.get("kec", "") or "", None))
    cols += [
        ("RE M-1", lambda r: _num(r.get("re_m1")), None),
        ("RE M", lambda r: _num(r.get("re_m")), None),
        ("MoM RE", lambda r: _pct(r.get("mom_re")), "mom"),
        ("PS M-1", lambda r: _num(r.get("ps_m1")), None),
        ("PS M", lambda r: _num(r.get("ps_m")), None),
        ("MoM PS", lambda r: _pct(r.get("mom_ps")), "mom"),
        ("TARGET", lambda r: _num(r.get("target")), None),
        ("ACH", lambda r: _pct(r.get("ach")), "ach"),
    ]
    return cols


def _render(title, result, cutoff, has_kec):
    cols = _columns(has_kec)
    rows = result["rows"]
    branch_rows = result["branch_rows"]
    jateng_row = result["jateng_row"]
    sections = result.get("sections")  # list[(label, rows)] optional

    # susunan baris tampilan. Penomeran NO di-RESET ke 1 tiap seksi baru
    # (permintaan user 09-Sep-2026): LOKASI -> 1..47 utk kecamatan, lalu 1..4
    # utk Agresif city; FMC -> 1..14 NEW, lalu 1..12 OLD.
    display = []
    if sections:
        for lbl, rs in sections:
            display.append(("section", lbl))
            for i, r in enumerate(rs, 1):
                display.append(("data", (i, r)))
    else:
        for i, r in enumerate(rows, 1):
            display.append(("data", (i, r)))
    display.append(("blank", None))
    for r in branch_rows:
        display.append(("branch", r))
    display.append(("jateng", jateng_row))

    # ── lebar kolom ────────────────────────────────────────────────────────
    def samples_for(idx, label, getter):
        s = [label]
        n = 1
        for kind, item in display:
            if kind == "data":
                n_i, r = item
                if idx == 0:
                    s.append(str(n_i))
                else:
                    s.append(getter(r))
            elif kind in ("branch", "jateng"):
                if idx == 1:
                    s.append(item.get("branch", ""))
                elif idx != 0 and getter:
                    s.append(getter(item))
        return s

    widths = []
    for idx, (label, getter, kind) in enumerate(cols):
        minw = 0.55 if idx == 0 else (1.6 if idx <= (3 if has_kec else 2) else 0.95)
        pad = 0.55 if idx <= (3 if has_kec else 2) else 0.28
        fs = FS_LABEL if idx <= (3 if has_kec else 2) else FS_DATA
        widths.append(col_width(samples_for(idx, label, getter), fs, minw=minw, pad=pad))

    MG = 0.22
    RH = 0.44
    HH = 0.66
    TITLE_H = 0.95
    TW = sum(widths)
    n_blank = sum(1 for k, _ in display if k == "blank")
    FH = TITLE_H + HH + len(display) * RH - n_blank * RH * 0.5 + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW)
    ax.set_ylim(0, FH)
    ax.axis("off")
    ax.set_position([0, 0, 1, 1])  # WAJIB — lihat memory renderer-text-overlap-fix
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in widths[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + widths[i] / 2

    # ── judul ─────────────────────────────────────────────────────────────
    ax.text(MG, FH - 0.06, title, ha="left", va="top",
            fontsize=15, fontweight="bold", color=C_DARK)
    date_label = result["cutoff"].strftime("%d-%b-%Y").upper()
    ax.text(MG, FH - 0.42, date_label, ha="left", va="top",
            fontsize=12.5, fontweight="bold", color=C_DARK)

    # ── header ────────────────────────────────────────────────────────────
    y_hdr = FH - MG - TITLE_H - HH
    for i, (label, _g, _k) in enumerate(cols):
        ax.add_patch(plt.Rectangle((xs[i], y_hdr), widths[i], HH, color=C_HDR, zorder=2))
        ax.text(cx(i), y_hdr + HH / 2, label, ha="center", va="center",
                fontsize=FS_SUBHDR, fontweight="bold", color="white", zorder=3)

    # ── baris ─────────────────────────────────────────────────────────────
    cur_y = y_hdr
    zebra = 0
    for kind, item in display:
        if kind == "blank":
            cur_y -= RH * 0.5
            continue
        cur_y -= RH
        ax.plot([xs[0], xs[0] + TW], [cur_y + RH, cur_y + RH], color=C_SEP, lw=0.35, zorder=5)

        if kind == "section":
            ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=C_SECTION_BG, zorder=1))
            ax.text(xs[0] + 0.1, cur_y + RH / 2, item, ha="left", va="center",
                    fontsize=FS_LABEL, fontweight="bold", color=C_DARK, zorder=3)
            continue

        if kind == "data":
            n_i, row = item
        else:
            n_i, row = None, item

        bold_row = kind in ("branch", "jateng")
        if kind == "jateng":
            bg = C_JATENG_BG
        elif kind == "branch":
            bg = C_BRANCH_BG
        else:
            bg = C_ROW_A if zebra % 2 == 0 else C_ROW_B
            zebra += 1
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        for i, (label, getter, ckind) in enumerate(cols):
            if i == 0:
                txt = str(n_i) if n_i is not None else ""
            elif kind in ("branch", "jateng"):
                txt = row.get("branch", "") if i == 1 else (getter(row) if getter and i >= (4 if has_kec else 3) else "")
            else:
                txt = getter(row) if getter else ""

            fg = C_JATENG_FG if kind == "jateng" else C_DARK
            if ckind == "mom" and kind != "section":
                raw = row.get("mom_re") if label == "MoM RE" else row.get("mom_ps")
                bgc, fgc = C.mom_color(raw)
                if bgc:
                    ax.add_patch(plt.Rectangle((xs[i] + 0.015, cur_y + 0.04),
                                               widths[i] - 0.03, RH - 0.08,
                                               color=bgc, zorder=2))
                    fg = fgc
            elif ckind == "ach" and kind != "section":
                raw = row.get("ach")
                if raw is not None:
                    frac = max(0.0, min(1.0, float(raw)))
                    ax.add_patch(plt.Rectangle((xs[i] + 0.02, cur_y + 0.05),
                                               max(0.012, (widths[i] - 0.04) * frac),
                                               RH - 0.10, color=C.ACH_DATABAR,
                                               alpha=0.55, zorder=2))

            ha = "left" if (1 <= i <= (3 if has_kec else 2)) else "center"
            tx = xs[i] + 0.10 if ha == "left" else cx(i)
            ax.text(tx, mid_y, txt, ha=ha, va="center",
                    fontsize=FS_DATA if i > (3 if has_kec else 2) else FS_LABEL,
                    fontweight="bold" if bold_row else "normal", color=fg, zorder=3)

    # ── grid & border ─────────────────────────────────────────────────────
    ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.35, zorder=5)
    y_top = y_hdr + HH
    for x in list(xs) + [xs[-1] + widths[-1]]:
        ax.plot([x, x], [cur_y, y_top], color=C_SEP, lw=0.3, zorder=5)
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, y_top - cur_y,
                               fill=False, edgecolor=C_DARK, lw=1.1, zorder=7))

    if cutoff:
        ax.text(xs[0], cur_y - 0.10, f"Cutoff data: {cutoff}",
                fontsize=6.5, color="#95A5A6", va="top", style="italic")

    dpi = min(180, int(8500 / (FW + FH)))
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                pad_inches=0.08, facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_lite_lokasi(result: dict, cutoff: str = None) -> BytesIO:
    rows = result["rows"]
    kec_rows = [r for r in rows if r.get("kec")]
    city_rows = [r for r in rows if not r.get("kec")]
    res = dict(result)
    res["sections"] = [("KECAMATAN AGRESIF", kec_rows), ("AGRESIF CITY", city_rows)]
    return _render("REPORT NEW SALES LOKASI AGRESIF", res, cutoff, has_kec=True)


def render_lite_fmc(result: dict, cutoff: str = None) -> BytesIO:
    res = dict(result)
    res["sections"] = [("FMC City v.1", result["v1_rows"]),
                       ("FMC City v.2", result["v2_rows"]),
                       ("FMC City v.3", result["v3_rows"])]
    return _render("REPORT NEW SALES ALL FMC CITY", res, cutoff, has_kec=False)
