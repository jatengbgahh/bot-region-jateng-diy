"""
renderer_childps.py — PNG tabel Child per PS Telkomsel One per WOK NEW (/childps).
Style = Performance MtD Sales by WOK (renderer_daily_performance.py).
Input = hasil calculator_childps.hitung_childps().
"""

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

C_HEADER_PS = "#1E6B31"; C_HEADER_IO = "#1B3A6B"; C_HEADER_SUB = "#2C3E50"; C_HEADER_MB = "#6C3483"
C_REGION_BG = "#1F3864"; C_BRANCH_BG = "#D5D8DC"   # JATENG-DIY: biru navy (font putih)
C_WOK_ODD = "white"; C_WOK_EVEN = "#F4F6F7"; C_SEP = "#BDC3C7"
C_DARK = "#1A1A1A"; C_MID = "#2C3E50"; C_POS = "#1E8449"; C_NEG = "#C0392B"


def render_childps(res: dict, cutoff: str = None) -> BytesIO:
    rows, bl, bi, tgl = res["rows"], res["bl"], res["bi"], res["tgl"]
    cutoff = cutoff or tgl.strftime("%d-%m-%Y")
    periode = f"FM {bi} vs {bl}" if res["full_month"] else f"MtD 1–{tgl.day} {bi} vs {bl}"

    CW = dict(br=1.9, wok=4.4, num=1.15, rat=1.15, dlt=1.25)
    # (key, width, kind)
    COLS = [("br", CW["br"], None), ("wok", CW["wok"], None),
            ("ps_l", CW["num"], "num"), ("ps_i", CW["num"], "num"),
            ("member_l", CW["num"], "num"), ("member_i", CW["num"], "num"),
            ("mpp_l", CW["rat"], "rat"), ("mpp_i", CW["rat"], "ratb"), ("mpp_d", CW["dlt"], "dlt"),
            ("child_l", CW["num"], "num"), ("child_i", CW["num"], "num"),
            ("cpp_l", CW["rat"], "rat"), ("cpp_i", CW["rat"], "ratb"), ("cpp_d", CW["dlt"], "dlt")]
    cw = [c[1] for c in COLS]; TW = sum(cw)
    RH = 0.52; HH1 = 0.54; HH2 = 0.46; TH = 0.75; MG = 0.25
    FH = TH + HH1 + HH2 + len(rows) * RH + MG * 2 + 0.2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor("white")
    xs = [MG]
    for w in cw[:-1]:
        xs.append(xs[-1] + w)
    cx = lambda i: xs[i] + cw[i] / 2

    ax.text(MG, FH - 0.18, "Child per PS Telkomsel One JATENG-DIY by WOK",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - 0.50, f"Update {tgl.strftime('%d-%m-%Y')}  |  {periode}",
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fs=14):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=fs, fontweight="bold", color="white", zorder=3)

    yh1 = FH - TH - HH1; yh2 = yh1 - HH2
    hcell(xs[0], yh2, CW["br"] + CW["wok"], HH1 + HH2, "TERRITORY", C_HEADER_SUB)
    grps = [(2, 4, "PS", C_HEADER_PS), (4, 6, "ALL MEMBER", C_HEADER_MB),
            (6, 9, "ALL MEMBER per PS", C_HEADER_MB),
            (9, 11, "CHILD", C_HEADER_IO), (11, 14, "CHILD per PS", C_HEADER_IO)]
    for cs, ce, lb, col in grps:
        hcell(xs[cs], yh1, sum(cw[cs:ce]), HH1, lb, col)
        subs = [bl, bi] if ce - cs == 2 else [bl, bi, "Δ MoM"]
        for j, s in enumerate(subs):
            hcell(xs[cs + j], yh2, cw[cs + j], HH2, s, col, fs=12)

    cy = yh2; wi = 0
    for row in rows:
        cy -= RH; t = row["_t"]
        if t == "reg":
            bg, fg, bd = C_REGION_BG, "white", True
        elif t == "br":
            bg, fg, bd = C_BRANCH_BG, C_DARK, True
        else:
            bg, fg, bd = (C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN), C_DARK, False; wi += 1
        ax.add_patch(plt.Rectangle((xs[0], cy), TW, RH, color=bg, zorder=1))
        my = cy + RH / 2; fs = 16.0

        def txt(ci, s, color=None, bold=bd):
            f2 = fs
            while f2 > 4.5 and len(s) * 0.085 * f2 / 10 > cw[ci] - 0.12:
                f2 -= 0.3
            ax.text(cx(ci), my, s, ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bold else "normal", color=color or fg, zorder=3)

        def lbl(ci, s):
            f2 = fs
            while f2 > 4.5 and len(s) * 0.085 * f2 / 10 > cw[ci] - 0.20:
                f2 -= 0.3
            ax.text(xs[ci] + 0.08, my, s, ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3)

        lbl(0, row["branch"] if t == "wok" else row["name"])
        lbl(1, row["name"] if t != "br" else "")

        for ci, (key, _, kind) in enumerate(COLS[2:], start=2):
            v = row.get(key)
            if v is None:
                txt(ci, "-"); continue
            if kind == "num":
                txt(ci, f"{v:,.0f}")
            elif kind in ("rat", "ratb"):
                txt(ci, f"{v:.2f}", bold=bd or kind == "ratb")
            else:
                v = round(v, 2)
                s = f"{v:+.2f}" if v != 0 else "0.00"
                col = fg if t == "reg" or v == 0 else (C_POS if v > 0 else C_NEG)
                txt(ci, s.replace("-", "−"), color=col, bold=True)

        ax.plot([xs[0], xs[0] + TW], [cy, cy], color=C_SEP,
                lw=0.8 if t in ("reg", "br") else 0.25, zorder=5)

    for x in xs + [xs[-1] + cw[-1]]:
        ax.plot([x, x], [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    for gx in [xs[2], xs[4], xs[6], xs[9], xs[11], xs[-1] + cw[-1]]:
        ax.plot([gx, gx], [cy, yh1], color=C_MID, lw=0.7, zorder=6)
    ax.add_patch(plt.Rectangle((xs[0], cy), TW, yh2 - cy + HH1 + HH2,
                               fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7))
    ax.text(xs[0], cy - 0.06,
            "PS = distinct bb_id (activation_date_ih)  |  All Member = PS + Child  |  "
            "Child = distinct msisdn_child ≠ parent  |  "
            f"Wilayah: city → WOK NEW  |  Cutoff data: {cutoff}",
            fontsize=7, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=min(300, int(8500 / (FW + FH))), facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
