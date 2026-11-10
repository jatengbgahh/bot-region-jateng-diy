"""
reports/sf_momentum/renderer.py — Render tabel /5so & /7so (SF Momentum): Region -> Branch -> WOK,
n metrik x (M1, MTD, MOM %) + Momentum Skor + Status. Urutan metrik = data["metrics"].
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from functools import lru_cache
from io import BytesIO
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath

C_BG     = "white"
C_HDR    = "#1B2A4A"
C_SEP    = "#C9CED6"
C_REG_BG = "#E5E7EB"
C_SEC_BG = "#DDD8DD"
SECTION_LABEL = {"reg": "REGION", "br": "BRANCH", "wok": "WOK"}
C_DARK   = "#1A1A1A"
C_MID    = "#2C3E50"
C_POS    = "#1E8449"
C_NEG    = "#C0392B"

STATUS_STYLE = {          # (bg, fg)
    "OUTPERFORM": ("#E3F4E8", "#1E8449"),
    "ON TRACK":   ("#E3ECFA", "#1F5FBF"),
    "WATCH":      ("#FFF5D6", "#9A7400"),
    "CRITICAL":   ("#C8102E", "#FFFFFF"),
}
SKOR_BG = {"OUTPERFORM": "#E3F4E8", "ON TRACK": "#E3ECFA", "WATCH": "#FFF5D6", "CRITICAL": "#FBE3E6"}

# metrik -> (label header, desimal)
METRIC_INFO = {
    "sf_reg": ("SF REGISTERED", 0), "sf_aktif": ("SF AKTIF", 0),
    "sf_prod": ("SF PRODUKTIF", 0), "prod": ("PRODUKTIVITAS SF", 1),
    "sf_djp": ("SF AKTIF DJP", 0), "odp": ("ODP VISITED", 0),
    "djp_sf_day": ("DJP/SF/DAY", 1),
}


def _sumber_djp() -> str:
    """Sumber DJP untuk footer: runner menandai M1/MTD yang dimuat dari file SELA (csv_report_runner)."""
    import os
    sela = {p for p in ("M1", "MTD") if os.environ.get(f"SFO_DJP_SUMBER_{p}") == "SELA"}
    if sela == {"M1", "MTD"}:
        return "clock-in SELA (CHECKOUT)"
    if sela:
        return f"clock-in SELA (CHECKOUT) utk {'/'.join(sorted(sela))}, sisanya djp_daily_user_detailed"
    return "djp_daily_user_detailed"


def _num(v, dec=0):
    if v is None:
        return "-"
    return f"{v:,.{dec}f}"


def _pct(v):
    return "-" if v is None else f"{v:.2f}%"


@lru_cache(maxsize=4096)
def _text_w(txt: str, fs: float, mono: bool = False, bold: bool = False) -> float:
    """Rendered width of txt in x data units of the scorecard axes."""
    if not txt:
        return 0.0
    fp = FontProperties(family="monospace" if mono else None, weight="bold" if bold else "normal")
    inch = TextPath((0, 0), txt, size=fs, prop=fp).get_extents().width / 72
    # The axes use the default subplot margins (left/right), so 1 x data unit is wider than
    # 1 inch on the page: convert the inch width to x data units.
    frac = matplotlib.rcParams["figure.subplot.right"] - matplotlib.rcParams["figure.subplot.left"]
    return inch / frac


def render_5so(data: dict, cutoff: str = None) -> BytesIO:
    rows = data["rows"]
    n_met = data["n_metrics"]
    basis = data.get("basis", "PS")
    # Judul kolom SF Aktif / SF Produktif / Produktivitas memuat basisnya (PS di /5so, RE di /7so)
    LABEL_BASIS = {"sf_aktif": f"SF AKTIF {basis}", "sf_prod": f"SF PRODUKTIF {basis}",
                   "prod": f"PRODUKTIVITAS {basis} SF"}
    GROUPS = [(m, LABEL_BASIS.get(m, METRIC_INFO[m][0]), METRIC_INFO[m][1]) for m in data["metrics"]]

    # Flexible column widths: every column is at least its default width and grows to fit the
    # longest text in it (e.g. "3,522" + "176000.00%" when M1 is tiny), so values never overlap.
    # Widths are measured from the real rendered text (_text_w), plus a small padding.
    CW_TERR, CW_NUM, CW_MOM, CW_SKOR, CW_ST = 4.3, 1.05, 1.25, 1.45, 1.75
    FS_VAL, PAD = 13.0, 0.24
    fit = lambda texts, base, **kw: max([base] + [_text_w(t, FS_VAL, **kw) + PAD for t in texts])
    CW_TERR = fit([r["name"] for r in rows], CW_TERR, bold=True)
    grp_w = []
    for m, lbl, dec in GROUPS:
        w = [fit([_num(r[f"{m}_m1"], dec) for r in rows], CW_NUM, mono=True, bold=True),
             fit([_num(r[f"{m}_mtd"], dec) for r in rows], CW_NUM, mono=True, bold=True),
             fit([_pct(r[f"{m}_mom"]) for r in rows], CW_MOM, mono=True, bold=True)]
        extra = _text_w(lbl, 12.5, bold=True) + PAD - sum(w)      # group header must fit too
        if extra > 0:
            w = [x + extra / 3 for x in w]
        grp_w += w
    CW_ST = fit(list(STATUS_STYLE), CW_ST, mono=True, bold=True)
    col_w = [CW_TERR] + grp_w + [CW_SKOR, CW_ST]
    TW = sum(col_w)
    RH, HH1, HH2, TH, MG = 0.50, 0.55, 0.50, 0.85, 0.25
    FW = TW + MG * 2
    SH = 0.42                                    # tinggi baris judul section
    n_sec = len(dict.fromkeys(r["kind"] for r in rows))
    FH = TH + HH1 + HH2 + len(rows) * RH + n_sec * SH + MG * 2 + 0.3

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_w[:-1]:
        xs.append(xs[-1] + w)
    cx = lambda i: xs[i] + col_w[i] / 2

    tgl = data["tgl"]
    ax.text(MG, FH - 0.18, data["title"],
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - 0.55,
            f"MTD {data['awal']:%d}-{tgl:%d %b %Y}  vs  M1 {data['lm_awal']:%d}-{data['lm_akhir']:%d %b %Y}"
            f"  |  Channel AGENCY",
            ha="left", va="top", fontsize=14, color="#7F8C8D")

    def hcell(x, y, w, h, txt, fs=12):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=C_HDR, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs,
                fontweight="bold", color="white", zorder=3, linespacing=1.15)

    yh1 = FH - TH - HH1
    yh2 = yh1 - HH2
    hcell(xs[0], yh2, CW_TERR, HH1 + HH2, "TERRITORY", fs=13)
    for gi, (_, lbl, _) in enumerate(GROUPS):
        c0 = 1 + gi * 3
        hcell(xs[c0], yh1, sum(col_w[c0:c0 + 3]), HH1, lbl, fs=12.5)
        for j, sub in enumerate(["M1", "MTD", "MOM %"]):
            hcell(xs[c0 + j], yh2, col_w[c0 + j], HH2, sub, fs=11.5)
    hcell(xs[-2], yh2, CW_SKOR, HH1 + HH2, "MOMENTUM\nSKOR", fs=12)
    hcell(xs[-1], yh2, CW_ST, HH1 + HH2, "STATUS", fs=12.5)

    cur_y = yh2
    sec_ys = []
    prev_kind = None
    for r in rows:
        kind = r["kind"]
        if kind != prev_kind:                    # baris judul section
            cur_y -= SH
            ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, SH, color=C_SEC_BG, zorder=1))
            ax.text(xs[0] + 0.12, cur_y + SH / 2, SECTION_LABEL[kind], ha="left", va="center",
                    fontsize=12.5, fontweight="bold", color=C_DARK, zorder=3)
            ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.9, zorder=5)
            sec_ys.append(cur_y)
            prev_kind = kind
        cur_y -= RH
        bold = kind == "reg"
        bg = C_REG_BG if bold else "white"
        fs = 13.5
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        my = cur_y + RH / 2

        ax.text(xs[0] + 0.12, my, r["name"], ha="left", va="center", fontsize=fs - 0.5,
                fontweight="bold" if bold else "normal", color=C_DARK, zorder=3)

        def cell(ci, txt, color=C_DARK, ha="right"):
            x = xs[ci] + col_w[ci] - 0.08 if ha == "right" else cx(ci)
            ax.text(x, my, txt, ha=ha, va="center", fontsize=fs - 0.5,
                    fontweight="bold" if bold else "normal", color=color,
                    zorder=3, family="monospace")

        for gi, (m, _, dec) in enumerate(GROUPS):
            c0 = 1 + gi * 3
            cell(c0, _num(r[f"{m}_m1"], dec))
            cell(c0 + 1, _num(r[f"{m}_mtd"], dec))
            mom = r[f"{m}_mom"]
            cell(c0 + 2, _pct(mom),
                 C_DARK if mom is None else (C_POS if mom > 0 else C_NEG if mom < 0 else C_DARK))

        st = r["status"]
        sbg, sfg = STATUS_STYLE[st]
        pad = 0.03
        ax.add_patch(plt.Rectangle((xs[-2] + pad, cur_y + pad), CW_SKOR - 2 * pad, RH - 2 * pad,
                                   color=SKOR_BG[st], zorder=2))
        cell(len(col_w) - 2, f"{r['skor']} / {n_met}", color=sfg if st != "CRITICAL" else "#C8102E",
             ha="center")
        ax.add_patch(plt.Rectangle((xs[-1] + pad, cur_y + pad), CW_ST - 2 * pad, RH - 2 * pad,
                                   color=sbg, zorder=2))
        cell(len(col_w) - 1, st, color=sfg, ha="center")

        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.3, zorder=5)

    for i in [0] + [1 + g * 3 for g in range(len(GROUPS))] + [len(col_w) - 2, len(col_w) - 1]:
        ax.plot([xs[i], xs[i]], [cur_y, yh2], color=C_SEP, lw=0.6, zorder=5)
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, yh2 - cur_y + HH1 + HH2,
                               fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7))

    footer = (f"SF Registered = SF ACTIVE database_sf (snapshot tgl akhir periode)  |  "
              f"SF Aktif = SF {basis}>=1  |  SF Produktif = SF {basis}>=10  |  "
              f"Produktivitas = {basis} AGENCY / SF Aktif  |  "
              f"SF Aktif DJP & ODP Visited = {_sumber_djp()}  |  ")
    if "djp_sf_day" in data["metrics"]:
        footer += "DJP/SF/Day = kunjungan DJP / SF Aktif DJP / jumlah hari  |  "
    footer += (f"Momentum Skor = jumlah metrik MoM > 0  (>={n_met - 1} Outperform, {n_met - 2} On Track, "
               f"{n_met - 3} Watch, <={n_met - 4} Critical)")
    if data.get("sf_note"):
        footer += f"  |  {data['sf_note']}"
    if cutoff:
        footer += f"  |  Cutoff ordering detail: {cutoff}"
    ax.text(xs[0], cur_y - 0.08, footer, fontsize=7.5, color="#95A5A6", va="top", style="italic")

    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=min(170, int(9000 / (FW + FH))),
                bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
