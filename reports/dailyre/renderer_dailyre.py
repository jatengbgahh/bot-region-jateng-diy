"""
renderer_dailyre.py — Render tabel "Monitoring New Daily RE" (perintah /dailyre).

Tone warna mengikuti template Excel
`tika/TEMPLATE REPORT TARGET RE BARU - fixed.xlsx` (sheet REPORT TARGET) —
header navy #1F3864, baris subtotal branch abu #D9D9D9, baris total region
ungu muda #E8D5F0, ACH hijau bila >=100% / merah bila <100%.

Kolom:
  BRANCH | WOK | Target RE Daily Weekday | Target RE Daily Weekend |
  TGT RE D | RE D | GAP | (ikon) | ACH DAILY TGT | TGT RE D+1

Data dict = output calculator_dailyre.hitung_dailyre().
"""

import math
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Tone warna (samakan dgn tema template) ─────────────────────────────────────
C_HDR        = "#1F3864"   # header navy
C_HDR_TEXT   = "#FFFFFF"
C_TITLE      = "#1F3864"
C_WOK_ODD    = "#FFFFFF"
C_WOK_EVEN   = "#F2F2F2"
C_BRANCH_BG  = "#D9D9D9"
C_REGION_BG  = "#E8D5F0"
C_TEXT       = "#1A1A1A"
C_ACH_POS    = "#0B8043"   # hijau  -> ACH >= 100%
C_ACH_NEG    = "#C00000"   # merah  -> ACH < 100%
C_GRID       = "#BFBFBF"
C_BORDER     = "#7F8C8D"
C_FOOT       = "#95A5A6"

# ── Ikon GAP (lingkaran + simbol) — polaritas dari %ACH ────────────────────────
ICON_COL = {
    "hijau" : "#27AE60",
    "kuning": "#F1C40F",
    "merah" : "#E74C3C",
}
ICON_SYM = {"hijau": "✓", "kuning": "!", "merah": "✕"}   # ✓ ! ✕

_MONTHS_EN = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# BRANCH | WOK | TgtWD | TgtWE | TGT RE D | RE D | GAP | ACH (+ikon) | TGT RE D+1
COL_W = [1.62, 2.42, 1.02, 1.02, 0.90, 0.74, 0.68, 1.46, 0.94]
C_BRANCH, C_WOK, C_TWD, C_TWE, C_TD, C_RD, C_GAP, C_ACH, C_TD1 = range(9)

ROW_H  = 0.31
HEAD_H = 0.82
TITLE_H = 0.64
MARGIN = 0.16
PAD    = 0.12


def _fmt_tgl(d) -> str:
    return f"{d.day} {_MONTHS_EN[d.month]} {d.year}"


def _r(x) -> int:
    """Round half up ke int (0 bila None)."""
    if x is None:
        return 0
    return int(math.floor(float(x) + 0.5))


# ─────────────────────────────────────────────────────────────────────────────
def build_caption(data: dict) -> str:
    """Caption Telegram untuk laporan /dailyre.

    Semua angka di-derive dari nilai yang SAMA dgn tabel gambar (dibulatkan
    `_r`), jadi caption & tabel selalu konsisten.
    """
    tgl      = data["tanggal"]
    cutoff   = data.get("cutoff")
    daytype  = "WEEKEND" if data.get("is_weekend") else "WEEKDAY"
    region   = data["region"]
    woks     = data["woks"]
    branches = data["branches"]

    def _line(it):
        return f"- {it['name']} : {it['ach']:.1f}%"

    re_reg  = _r(region["re_d"])
    tgt_reg = _r(region["tgt_d"])
    gap_reg = re_reg - tgt_reg
    ach_reg = (re_reg / tgt_reg * 100) if tgt_reg else None
    d1_reg  = _r(region["tgt_d1"])

    wok_ok  = sorted((w for w in woks if w["ach"] is not None and w["ach"] >= 100),
                     key=lambda w: w["ach"], reverse=True)
    br_ok   = sorted((b for b in branches if b["ach"] is not None and b["ach"] >= 100),
                     key=lambda b: b["ach"], reverse=True)
    wok_low = min((w for w in woks if w["ach"] is not None),
                  key=lambda w: w["ach"], default=None)
    br_low  = min((b for b in branches if b["ach"] is not None),
                  key=lambda b: b["ach"], default=None)

    L = [f"📊 *MONITORING NEW DAILY RE* | {_fmt_tgl(tgl)}"]
    ket = f"🕐 Cutoff: {cutoff}  |  {daytype}" if cutoff else f"🕐 {daytype}"
    L += [ket, ""]

    L.append(f"ACH Region: {ach_reg:.1f}%  (RE {re_reg} / TGT {tgt_reg})"
             if ach_reg is not None else "ACH Region: -")
    L.append(f"Sisa gap: {abs(min(0, gap_reg))} RE" if gap_reg < 0
             else f"Sisa gap: 0 RE (surplus {gap_reg})")
    L.append("")

    L.append("✅ WOK ACH TARGET (≥100%)")
    L += ([_line(w) for w in wok_ok] if wok_ok else ["- NO WOK"])
    L.append("")

    L.append("✅ BRANCH ACH TARGET (≥100%)")
    L += ([_line(b) for b in br_ok] if br_ok else ["- NO BRANCH"])
    L.append("")

    L.append("❌ WOK ACH TERENDAH")
    L.append(_line(wok_low) if wok_low else "- -")
    L.append("")

    L.append("❌ BRANCH ACH TERENDAH")
    L.append(_line(br_low) if br_low else "- -")
    L.append("")

    L.append(f"🎯 Target RE besok (region): {d1_reg} RE")
    return "\n".join(L)


# ─────────────────────────────────────────────────────────────────────────────
def render_dailyre(data: dict) -> BytesIO:
    tgl        = data["tanggal"]
    besok      = data["besok"]
    is_weekend = data["is_weekend"]
    cutoff     = data.get("cutoff")
    region     = data["region"]
    branches   = data["branches"]
    woks       = data["woks"]

    # Urutan baris: 16 WOK -> baris kosong -> 6 branch -> region
    rows = [{"_t": "wok", **w} for w in woks]
    rows.append({"_t": "spacer"})
    rows += [{"_t": "branch", **b} for b in branches]
    rows.append({"_t": "region", **region})
    n_rows = len(rows)

    total_w = sum(COL_W)
    fig_w = total_w + MARGIN * 2
    fig_h = TITLE_H + HEAD_H + n_rows * ROW_H + PAD * 2 + 0.45

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_position([0, 0, 1, 1])          # 1 data unit == 1 inch (teks & lingkaran presisi)
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [MARGIN]
    for w in COL_W[:-1]:
        xs.append(xs[-1] + w)

    def cx(ci):
        return xs[ci] + COL_W[ci] / 2

    # ── Judul + cutoff ───────────────────────────────────────────────────────
    ax.text(MARGIN, fig_h - 0.12,
            f"MONITORING NEW DAILY RE TO ACHIEVE POSITIF GROWTH | {_fmt_tgl(tgl)}",
            ha="left", va="top", fontsize=11, fontweight="bold", color=C_TITLE)
    sub = "Sumber RE: dashboard_hourly_sales (full day)"
    if cutoff:
        sub = f"Cutoff data: {cutoff}   ·   " + sub
    ax.text(MARGIN, fig_h - 0.40, sub,
            ha="left", va="top", fontsize=7, color="#7F8C8D")

    # ── Header ───────────────────────────────────────────────────────────────
    y_head = fig_h - TITLE_H - HEAD_H
    labels = ["BRANCH", "WOK",
              "Target RE\nDaily\nWeekday", "Target RE\nDaily\nWeekend",
              "TGT RE\nD", "RE D", "GAP", "ACH DAILY\nTGT", "TGT RE\nD+1"]
    for i, lbl in enumerate(labels):
        ax.add_patch(plt.Rectangle((xs[i], y_head), COL_W[i], HEAD_H,
                                   facecolor=C_HDR, edgecolor="white",
                                   linewidth=0.8, zorder=2))
        if lbl:
            ax.text(xs[i] + COL_W[i] / 2, y_head + HEAD_H / 2, lbl,
                    ha="center", va="center", fontsize=8.6, fontweight="bold",
                    color=C_HDR_TEXT, zorder=3, linespacing=1.25)

    # ── Baris data ───────────────────────────────────────────────────────────
    cur_y = y_head
    y_wok_bot = y_head
    wok_i = 0
    for row in rows:
        rt = row["_t"]
        cur_y -= ROW_H
        if rt == "spacer":
            y_wok_bot = cur_y + ROW_H
            continue

        if rt == "region":
            bg, fg, fs = C_REGION_BG, C_TEXT, 9.0
        elif rt == "branch":
            bg, fg, fs = C_BRANCH_BG, C_TEXT, 8.6
        else:
            bg = C_WOK_ODD if wok_i % 2 == 0 else C_WOK_EVEN
            fg, fs = C_TEXT, 8.4
            wok_i += 1

        ax.add_patch(plt.Rectangle((xs[0], cur_y), total_w, ROW_H,
                                   facecolor=bg, edgecolor="none", zorder=1))
        mid = cur_y + ROW_H / 2
        fw = "bold"          # semua teks tabel di-bold (permintaan user: teks terlalu tipis)

        # kolom BRANCH / WOK
        if rt == "wok":
            ax.text(xs[C_BRANCH] + 0.10, mid, row["branch"], ha="left", va="center",
                    fontsize=fs, fontweight="bold", color=fg, zorder=3)
            ax.text(xs[C_WOK] + 0.10, mid, row["name"], ha="left", va="center",
                    fontsize=fs, fontweight="bold", color=fg, zorder=3)
        else:
            # branch/region: sel BRANCH + WOK di-merge, nama rata TENGAH
            cx_merge = xs[C_BRANCH] + (COL_W[C_BRANCH] + COL_W[C_WOK]) / 2
            ax.text(cx_merge, mid, row["name"], ha="center", va="center",
                    fontsize=fs, fontweight="bold", color=fg, zorder=3)

        # angka kolom
        def num(ci, val, b=fw):
            ax.text(cx(ci), mid, f"{val:,}", ha="center", va="center",
                    fontsize=fs, fontweight=b, color=fg, zorder=3)

        td = _r(row["tgt_d"])
        rd = _r(row["re_d"])
        num(C_TWD, _r(row["base_wd"]))
        num(C_TWE, _r(row["base_we"]))
        num(C_TD,  td)
        num(C_RD,  rd)
        num(C_GAP, rd - td)
        num(C_TD1, _r(row["tgt_d1"]))

        # ACH DAILY TGT — ikon status + persen digabung dalam 1 kolom
        ach  = row["ach"]
        stat = row.get("gap_stat")
        acx  = xs[C_ACH] + COL_W[C_ACH] / 2
        if ach is None:
            ax.text(acx, mid, "-", ha="center", va="center",
                    fontsize=fs, fontweight="bold", color=fg, zorder=3)
        else:
            col = C_ACH_POS if ach >= 100 else C_ACH_NEG
            txt = f"{ach:.1f}%"
            has_icon = stat in ICON_COL
            # ikon di kiri, persen di kanan — pasangannya dibuat center di kolom
            ic_x = acx - 0.34 if has_icon else acx
            if has_icon:
                ax.add_patch(plt.Circle((ic_x, mid), 0.088,
                                        facecolor=ICON_COL[stat], edgecolor="white",
                                        linewidth=0.6, zorder=3))
                ax.text(ic_x, mid, ICON_SYM[stat], ha="center", va="center",
                        fontsize=7, fontweight="bold", color="white", zorder=4)
                ax.text(ic_x + 0.17, mid, txt, ha="left", va="center",
                        fontsize=fs, fontweight="bold", color=col, zorder=3)
            else:
                ax.text(acx, mid, txt, ha="center", va="center",
                        fontsize=fs, fontweight="bold", color=col, zorder=3)

        lw = 0.7 if rt in ("branch", "region") else 0.3
        ax.plot([xs[0], xs[0] + total_w], [cur_y, cur_y],
                color=C_GRID, linewidth=lw, zorder=5)

    # ── Grid vertikal + border ───────────────────────────────────────────────
    y_top = y_head + HEAD_H
    y_bot = cur_y
    for k, x in enumerate(xs + [xs[-1] + COL_W[-1]]):
        # garis pemisah BRANCH/WOK (x = xs[1]) berhenti di batas blok WOK
        # supaya sel BRANCH+WOK di baris branch/region tampak ter-merge.
        y0 = y_wok_bot if k == 1 else y_bot
        ax.plot([x, x], [y0, y_top], color=C_GRID, linewidth=0.4, zorder=5)
    ax.add_patch(plt.Rectangle((xs[0], y_bot), total_w, y_top - y_bot,
                               fill=False, edgecolor=C_BORDER, linewidth=1.0,
                               zorder=6))

    # ── Footer ───────────────────────────────────────────────────────────────
    daytype = "WEEKEND" if is_weekend else "WEEKDAY"
    foot = (
        f"{tgl.strftime('%d-%m-%Y')} = {daytype}  |  "
        f"GAP = RE D − TGT RE D  |  "
        f"TGT RE D+1 = TGT RE D besok ({besok.strftime('%d-%m')}) − GAP  |  "
        f"ikon: ✓ ACH≥100% · ! 80–99% · ✕ <80%"
    )
    ax.text(xs[0], y_bot - 0.16, foot, fontsize=5.4, color=C_FOOT,
            va="top", style="italic")

    buf = BytesIO()
    _dpi = min(200, int(9000 / (fig_w + fig_h)))
    fig.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
