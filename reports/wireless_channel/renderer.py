"""
reports/wireless_channel/renderer.py — Render tabel PS EZNet Wireless Jateng-DIY by Channel.
Kolom: TERRITORY (BRANCH | WOK) | ALL SALES | SF HOUSEHOLD | SF MOBILE | GRAPARI |
DIGITAL | COMMUNITY (masing2 MtD + MoM). Baris: WOK -> BRANCH -> REGION.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG, C_MID, C_DARK, C_WHITE = "white", "#2C3E50", "#1A1A1A", "white"
C_REGION_BG, C_BRANCH_BG = "#2C3E50", "#D5D8DC"
C_WOK_ODD, C_WOK_EVEN, C_SEP = "white", "#F4F6F7", "#BDC3C7"
C_POS, C_NEG = "#1E8449", "#C0392B"

# (key, label, warna header, warna sub-header)
GROUPS = [
    ("SF_HH",     "SF HOUSEHOLD", "#C00000", "#8E0000"),
    ("SF_MOBILE", "SF MOBILE",    "#C00000", "#8E0000"),
    ("GRAPARI",   "GRAPARI",      "#1F5F7F", "#154559"),
    ("DIGITAL",   "DIGITAL",      "#2E7D1E", "#1F5714"),
    ("COMMUNITY", "COMMUNITY",    "#E67E22", "#B05F14"),
]


def _pct(v):
    if v is None:
        return "-"
    return f"{'+' if v > 0 else ''}{v:.1f}%"


def render_wireless_channel(data: dict, cutoff: str = None) -> BytesIO:
    region, branches, woks = data["region"], data["branches"], data["woks"]
    all_rows = ([{"_t": "wok", **w} for w in woks] +
                [{"_t": "br", **b} for b in branches] +
                [{"_t": "reg", **region}])

    CW_BR, CW_WOK, CW_ALL, CW_NUM, CW_MOM = 2.15, 4.75, 1.15, 0.95, 1.30
    col_widths = [CW_BR, CW_WOK, CW_ALL] + [CW_NUM, CW_MOM] * len(GROUPS)
    TW = sum(col_widths)

    RH, HH1, HH2, TH, MG = 0.52, 0.55, 0.32, 0.75, 0.25
    FH = TH + HH1 + HH2 + len(all_rows) * RH + MG * 2
    FW = TW + MG * 2
    if FW / FH > 15.0:   # Telegram tolak foto rasio > 20:1
        FH = FW / 15.0

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)
    cx = lambda i: xs[i] + col_widths[i] / 2

    ax.text(MG, FH - 0.18, "PS EZNet Wireless Jateng-DIY by Channel",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - 0.50, f"MtD {data['label_ini']}  |  MoM vs {data['label_lalu']}",
            ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fs=13):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs,
                fontweight="bold", color=C_WHITE, zorder=3)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2
    hcell(xs[0], yh2, CW_BR + CW_WOK, HH1 + HH2, "TERRITORY", C_MID, 14)
    hcell(xs[2], yh2, CW_ALL, HH1 + HH2, "ALL\nSALES", C_MID, 12)
    for g, (_, lbl, col, dcol) in enumerate(GROUPS):
        c = 3 + g * 2
        hcell(xs[c], yh1, CW_NUM + CW_MOM, HH1, lbl, col, 13)
        hcell(xs[c], yh2, CW_NUM, HH2, "MtD", dcol, 10)
        hcell(xs[c + 1], yh2, CW_MOM, HH2, "MoM", dcol, 10)

    cur_y, wi = yh2, 0
    for row in all_rows:
        t = row["_t"]
        cur_y -= RH
        if t == "reg":
            bg, fg, bold = C_REGION_BG, C_WHITE, True
        elif t == "br":
            bg, fg, bold = C_BRANCH_BG, C_DARK, True
        else:
            bg, fg, bold = (C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN), C_DARK, False
            wi += 1
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        def put(x, txt, color, ha="center", maxw=None, fs=15.0):
            if maxw:
                fs = fit_fs(txt, fs, maxw, floor=4.5)
            ax.text(x, mid_y, txt, ha=ha, va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal", color=color,
                    zorder=3, clip_on=True)

        br_lbl  = row["name"] if t == "br" else (REGION_NAME if t == "reg" else row["branch"])
        wok_lbl = row["name"] if t == "wok" else (REGION_NAME if t == "reg" else "")
        put(xs[0] + 0.08, br_lbl, fg, "left", CW_BR)
        put(xs[1] + 0.08, wok_lbl, fg, "left", CW_WOK)
        put(cx(2), f"{row['all']:,}", fg)
        for g, (key, *_r) in enumerate(GROUPS):
            c = 3 + g * 2
            put(cx(c), f"{row[key]:,}", fg)
            mom = row[f"{key}_mom"]
            col = fg if (t == "reg" or mom is None) else (C_POS if mom >= 0 else C_NEG)
            put(cx(c + 1), _pct(mom), col)
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP,
                lw=0.8 if t != "wok" else 0.25, zorder=5)

    for x in xs + [xs[-1] + col_widths[-1]]:
        ax.plot([x, x], [cur_y, yh2], color=C_SEP, lw=0.25, zorder=5)
    for gx in [xs[2]] + [xs[3 + g * 2] for g in range(len(GROUPS))] + [xs[-1] + col_widths[-1]]:
        ax.plot([gx, gx], [cur_y, yh1 + HH1], color=C_MID, lw=0.8, zorder=6)
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, yh1 + HH1 - cur_y, fill=False,
                               edgecolor="#7F8C8D", lw=0.9, zorder=7))

    footer = ("PS = Pasang Sukses produk WIRELESS  |  SF HOUSEHOLD/SF MOBILE = channel AGENCY "
              "per mapping sf_code  |  MoM vs periode sama bulan lalu  |  Sumber: indihome_ordering_detail")
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.06, footer, fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=min(300, int(9500 / (FW + FH))),
                bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
