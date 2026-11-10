"""
renderer_klaim.py — Render tabel Rekap Data Pelanggan Klaim
3 tabel: ringkasan per Nama Program, per Branch/WOK/Nama Program,
dan detail per Nama Program/Product Commercial Name.
Style mengikuti file referensi manual (Meta/Rekap Data Pelanggan Klaim.xlsx):
header & grand total merah solid, %C3MR (nilai ACH) pakai threshold warna
absolut: <90% merah, 90-95% oranye, >=95% hijau.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from io import BytesIO

C_BG      = "white"
C_HDR     = "#C00000"
C_ODD     = "white"
C_EVEN    = "#EDEDED"
C_SEP     = "#BDC3C7"
C_DARK    = "#1A1A1A"
C_WHITE   = "white"

C_ACH_HIJAU  = "#63BE7B"
C_ACH_ORANYE = "#FFA500"
C_ACH_MERAH  = "#F8696B"


def _fmt_num(v) -> str:
    if v is None:
        return "-"
    return f"{int(round(v)):,}"


def _fmt_pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:.1f}%"


def _pct_color_scale_abs(value):
    """Threshold warna nilai ACH (%C3MR): <90% merah, <95% oranye, >=95% hijau."""
    if value is None:
        return None, None
    if value < 90:
        bg_hex = C_ACH_MERAH
    elif value < 95:
        bg_hex = C_ACH_ORANYE
    else:
        bg_hex = C_ACH_HIJAU
    return bg_hex, C_DARK


def _render_table(label_cols, rows, grand_total, title, subtitle, cutoff, bill_period) -> BytesIO:
    """
    label_cols: list of (key, header_text, width) untuk kolom label di kiri.
    rows: list of dict berisi key label_cols + jml_pelanggan/jml_paid/jml_unpaid/pct_c3mr.
    grand_total: dict jml_pelanggan/jml_paid/jml_unpaid/pct_c3mr untuk baris total.
    """
    CW_METRIC = [1.35, 1.15, 1.20, 1.15]  # Jml Pelanggan, Jml Paid, Jml Unpaid, %C3MR
    metric_headers = ["Jml\nPelanggan", "Jml Paid", "Jml\nUnpaid", "%C3MR"]

    label_widths = [w for _, _, w in label_cols]
    col_widths = label_widths + CW_METRIC
    n_label = len(label_cols)
    TW = sum(col_widths)

    RH = 0.42
    HH = 0.62
    TH = 0.68
    MG = 0.22

    FH = TH + HH + (len(rows) + 1) * RH + MG * 2 + 0.35
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + col_widths[i] / 2

    ax.text(MG, FH - 0.10, title, ha="left", va="top",
            fontsize=17, fontweight="bold", color=C_DARK)
    if subtitle:
        ax.text(MG, FH - 0.40, subtitle, ha="left", va="top",
                fontsize=11, color="#7F8C8D")

    yh = FH - TH - HH

    def hcell(x, y, w, h, txt, fs=11):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=C_HDR, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=C_WHITE, zorder=3,
                multialignment="center", linespacing=1.15)

    for i, (_, htext, w) in enumerate(label_cols):
        hcell(xs[i], yh, w, HH, htext, fs=12)
    for j, htext in enumerate(metric_headers):
        hcell(xs[n_label + j], yh, CW_METRIC[j], HH, htext, fs=10.5)

    cur_y = yh
    for ri, row in enumerate(rows):
        cur_y -= RH
        bg = C_ODD if ri % 2 == 0 else C_EVEN
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        for i, (key, _, w) in enumerate(label_cols):
            txt = str(row.get(key, "-"))
            avail = w - 0.20
            f2 = 10.5
            while f2 > 6.5 and len(txt) * 0.078 * f2 / 10 > avail:
                f2 -= 0.3
            t = txt
            while len(t) > 4 and len(t) * 0.078 * f2 / 10 > avail:
                t = t[:-1]
            if t != txt:
                t = t.rstrip() + "…"
            txt_obj = ax.text(xs[i] + 0.06, mid_y, t, ha="left", va="center",
                               fontsize=f2, color=C_DARK, zorder=3, clip_on=True)
            clip_rect = plt.Rectangle((xs[i], cur_y), w, RH, transform=ax.transData)
            txt_obj.set_clip_path(clip_rect)

        ax.text(cx(n_label + 0), mid_y, _fmt_num(row.get("jml_pelanggan")),
                ha="center", va="center", fontsize=10.5, color=C_DARK, zorder=3)
        ax.text(cx(n_label + 1), mid_y, _fmt_num(row.get("jml_paid")),
                ha="center", va="center", fontsize=10.5, color=C_DARK, zorder=3)
        ax.text(cx(n_label + 2), mid_y, _fmt_num(row.get("jml_unpaid")),
                ha="center", va="center", fontsize=10.5, color=C_DARK, zorder=3)

        pct_ci = n_label + 3
        pct_v = row.get("pct_c3mr")
        bg_cs, fg_cs = _pct_color_scale_abs(pct_v)
        if bg_cs:
            pad = 0.03
            ax.add_patch(plt.Rectangle(
                (xs[pct_ci] + pad, cur_y + pad),
                col_widths[pct_ci] - pad * 2, RH - pad * 2,
                color=bg_cs, zorder=2
            ))
            ax.text(cx(pct_ci), mid_y, _fmt_pct(pct_v), ha="center", va="center",
                    fontsize=10.5, fontweight="bold", color=fg_cs, zorder=3)
        else:
            ax.text(cx(pct_ci), mid_y, "-", ha="center", va="center",
                    fontsize=10.5, color=C_DARK, zorder=3)

        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.25, zorder=5)

    # ── Baris grand total ───────────────────────────────────────────────────
    cur_y -= RH
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=C_HDR, zorder=2))
    mid_y = cur_y + RH / 2
    ax.text(xs[0] + 0.06, mid_y, "JATENG DIY", ha="left", va="center",
            fontsize=11, fontweight="bold", color=C_WHITE, zorder=3)
    ax.text(cx(n_label + 0), mid_y, _fmt_num(grand_total.get("jml_pelanggan")),
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=C_WHITE, zorder=3)
    ax.text(cx(n_label + 1), mid_y, _fmt_num(grand_total.get("jml_paid")),
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=C_WHITE, zorder=3)
    ax.text(cx(n_label + 2), mid_y, _fmt_num(grand_total.get("jml_unpaid")),
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=C_WHITE, zorder=3)
    ax.text(cx(n_label + 3), mid_y, _fmt_pct(grand_total.get("pct_c3mr")),
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=C_WHITE, zorder=3)

    bottom_y = cur_y

    # ── Grid ──────────────────────────────────────────────────────────────
    for x in xs + [xs[-1] + col_widths[-1]]:
        ax.plot([x, x], [bottom_y, yh], color=C_SEP, lw=0.25, zorder=5)
    ax.add_patch(plt.Rectangle(
        (xs[0], bottom_y), TW, yh - bottom_y + HH,
        fill=False, edgecolor="#7F8C8D", lw=0.8, zorder=7
    ))

    if cutoff:
        footer = f"Paid Flag live dari DB (bwmp_c3mr_dd), cutoff :  {cutoff.strftime('%d %b %Y')}"
        if bill_period:
            footer += f"  |  bill_period {bill_period.strftime('%b %Y')}"
        ax.text(xs[0], bottom_y - 0.08, footer,
                fontsize=9, color="#555555", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(180, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_klaim_program(data: dict) -> BytesIO:
    """Tabel ringkasan per Nama Program."""
    return _render_table(
        label_cols=[("Nama Program", "Nama Program", 3.60)],
        rows=data["program_rows"],
        grand_total=data["grand_total"],
        title="Rekap Data Pelanggan Klaim — per Nama Program",
        subtitle="IndiHome Jateng-DIY",
        cutoff=data.get("cutoff"),
        bill_period=data.get("bill_period"),
    )


def render_klaim_geo(data: dict) -> BytesIO:
    """Tabel per Branch / WOK / Nama Program."""
    return _render_table(
        label_cols=[
            ("Branch", "Branch", 1.90),
            ("WOK", "WOK", 2.60),
            ("Nama Program", "Nama Program", 3.60),
        ],
        rows=data["geo_rows"],
        grand_total=data["grand_total"],
        title="Rekap Data Pelanggan Klaim — per Branch/WOK/Nama Program",
        subtitle="IndiHome Jateng-DIY",
        cutoff=data.get("cutoff"),
        bill_period=data.get("bill_period"),
    )


def render_klaim_detail(data: dict) -> BytesIO:
    """Tabel detail per Nama Program / Product Commercial Name."""
    return _render_table(
        label_cols=[
            ("Nama Program", "Nama Program", 3.20),
            ("Product Commercial Name", "Product Commercial Name", 3.80),
        ],
        rows=data["detail_rows"],
        grand_total=data["grand_total"],
        title="Rekap Data Pelanggan Klaim — per Program/Product",
        subtitle="IndiHome Jateng-DIY",
        cutoff=data.get("cutoff"),
        bill_period=data.get("bill_period"),
    )
