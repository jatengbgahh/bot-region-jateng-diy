"""
renderer_salahhomepass.py — Render tabel Monitoring RE : Fallout Salah
Tagging/Salah Homepass ke gambar PNG.
Layout meniru contoh manual (folder Willy/image_2026-07-15...png): 1 tabel
menyatu (tanpa celah antar kolom), 2 kolom nama (BRANCH | WOK), baris WOK
dikelompokkan/di-banding per BRANCH, lalu section Branch (subtotal) & baris
total JATENG-DIY di baris terakhir.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from io import BytesIO

C_HEADER_GREY  = "#4D4D4D"   # header BRANCH/WOK
C_HEADER_RE    = "#C0392B"   # header RE
C_HEADER_TITLE = "#1B2A4A"   # header "Fallout Salah Tagging/Salah Homepass"
C_HEADER_SUB   = "#2E5B8A"   # header AGENCY/NON AGENCY/ALL CHANNEL
C_TOTAL_BG     = "#C0392B"   # baris total JATENG-DIY
C_SEP_BG       = "#808080"   # bar pemisah section WOK -> Branch
C_BAND_A       = "#FFFFFF"
C_BAND_B       = "#D6D6D6"   # abu-abu per kelompok BRANCH (dibuat lebih jelas)
C_NEG_TEXT     = "#C0392B"   # merah = kondisi memburuk (fallout naik / RE turun)
C_POS_TEXT     = "#1E8449"   # hijau = kondisi membaik (fallout turun / RE naik)
C_TEXT_MAIN    = "#1A1A1A"
C_TEXT_LIGHT   = "#FFFFFF"
C_GRID         = "#BFBFBF"
C_BORDER       = "#4D4D4D"   # garis batas antar grup kolom (lebih tegas)

# Kolom pertama tiap GRUP (BRANCH|WOK|RE|AGENCY|NON AGENCY|ALL CHANNEL) — hanya
# di sini garis vertikal digambar (tebal/jelas). Sub-kolom di dalam satu grup
# (mis. Mtd/MoM di RE, atau Mtd/%/MoM di tiap channel) TIDAK diberi garis sama
# sekali supaya grupnya terlihat menyatu/merger.
GROUP_STARTS = [0, 1, 2, 4, 7, 10]

_HEATMAP = LinearSegmentedColormap.from_list("heat", ["#D5F5E3", "#F5B7B1"])


def _fmt_num(v) -> str:
    return "-" if v is None else f"{int(v):,}"


def _fmt_pct_plain(v) -> str:
    return "-" if v is None else f"{v:.2f}%"


def _fmt_pct_sign(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def _heat_bg(val, vmin, vmax):
    if val is None or vmax is None or vmin is None or vmax <= vmin:
        frac = 0.0
    else:
        frac = max(0.0, min(1.0, (val - vmin) / (vmax - vmin)))
    r, g, b, _ = _HEATMAP(frac)
    return (r, g, b)


def _col_range(rows: list, key: str):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return 0, 0
    return min(vals), max(vals)


def render_salah_homepass(data: dict, cutoff: str = None) -> BytesIO:
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]
    period_label = data["period_label"]

    n_rows = 1 + len(branches) + len(woks) + 1  # sep bar + branch rows + wok rows + total

    ROW_H   = 0.24
    HEAD_H  = 0.78
    TITLE_H = 0.42
    PAD     = 0.12
    fig_h   = TITLE_H + HEAD_H + n_rows * ROW_H + PAD * 2

    # Kolom: BRANCH | WOK | RE:Mtd,MoM | AGENCY:Mtd,%,MoM | NON AGENCY:Mtd,%,MoM | ALL CHANNEL:Mtd,%,MoM
    COL_W = [1.35, 1.9,
             0.58, 0.62,
             0.55, 0.85, 0.62,
             0.62, 0.85, 0.62,
             0.60, 0.85, 0.62]
    fig_w = sum(COL_W) + 0.3

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    # Tabel menyatu (tanpa celah antar kolom) — grup dibedakan lewat warna
    # header saja, sesuai contoh manual.
    xs = [0.15]
    for w in COL_W[:-1]:
        xs.append(xs[-1] + w)

    def cx(ci):
        return xs[ci] + COL_W[ci] / 2

    x_end = xs[-1] + COL_W[-1]

    # ── Judul ─────────────────────────────────────────────────────────────
    ax.text(0.15, fig_h - 0.15, "Monitoring RE : Fallout Salah Tagging / Salah Homepass",
            fontsize=10, fontweight="bold", color=C_TEXT_MAIN, va="top")
    subtitle = f"period : {period_label}"
    if cutoff:
        subtitle += f"   |   Update data indihome_ordering_detail: {cutoff}"
    ax.text(0.15, fig_h - 0.32, subtitle,
            fontsize=7.5, color="#7F8C8D", va="top", style="italic")

    # ── Header (3 tingkat) ──────────────────────────────────────────────────
    y0_head = fig_h - TITLE_H - HEAD_H
    h = HEAD_H / 3   # tinggi tiap tingkat

    def hcell(x, y, w, hh, text, bg, fg=C_TEXT_LIGHT, fs=6.5):
        ax.add_patch(plt.Rectangle((x, y), w, hh, color=bg, zorder=2))
        ax.text(x + w/2, y + hh/2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.1)

    # BRANCH / WOK — sel tinggi penuh (3 tingkat)
    hcell(xs[0], y0_head, COL_W[0], HEAD_H, "BRANCH", C_HEADER_GREY, fs=8)
    hcell(xs[1], y0_head, COL_W[1], HEAD_H, "WOK",    C_HEADER_GREY, fs=8)

    # RE — label di 2/3 atas, Mtd/MoM di 1/3 bawah (menyatu, tanpa garis internal)
    hcell(xs[2], y0_head + h, COL_W[2] + COL_W[3], 2*h, "RE", C_HEADER_RE, fs=8.5)
    hcell(xs[2], y0_head, COL_W[2], h, "Mtd", C_HEADER_RE, fs=7)
    hcell(xs[3], y0_head, COL_W[3], h, "MoM", C_HEADER_RE, fs=7)

    # Judul besar "Fallout Salah Tagging/Salah Homepass" — 1/3 atas, span 9 kolom
    w_fallout = sum(COL_W[4:13])
    hcell(xs[4], y0_head + 2*h, w_fallout, h,
          "Fallout Salah Tagging / Salah Homepass", C_HEADER_TITLE, fs=8.5)

    groups = [
        (4, "AGENCY",      ["Mtd", "% Salah Tagging-\nHomepass", "MoM"]),
        (7, "NON AGENCY",  ["Mtd", "% Salah Tagging-\nHomepass", "MoM"]),
        (10, "ALL CHANNEL", ["Mtd", "% Salah Tagging-\nHomepass", "MoM"]),
    ]
    for start, label, subs in groups:
        w_grp = sum(COL_W[start:start + 3])
        hcell(xs[start], y0_head + h, w_grp, h, label, C_HEADER_SUB, fs=7.5)
        for i, lbl in enumerate(subs):
            fs_sub = 5.6 if "%" in lbl else 6.5
            hcell(xs[start + i], y0_head, COL_W[start + i], h, lbl, C_HEADER_SUB, fs=fs_sub)

    # Garis horizontal antar tingkat header (judul grup vs sub-label).
    # Baris bawah (y=h) berlaku utk RE juga (RE label vs Mtd/MoM), tapi baris
    # atas (y=2h) HANYA utk blok Agency/NonAgency/AllChannel — kalau ikut
    # ditarik sampai ke kolom RE, garisnya nembus tengah label "RE" (yang
    # sel-nya menyatu 2 tingkat, tanpa pembagi di y=2h).
    ax.plot([xs[2], x_end], [y0_head + h, y0_head + h], color="white", linewidth=0.7, zorder=5)
    ax.plot([xs[4], x_end], [y0_head + 2*h, y0_head + 2*h], color="white", linewidth=0.7, zorder=5)

    ax.add_patch(plt.Rectangle((xs[0], y0_head), x_end - xs[0], HEAD_H,
                                fill=False, edgecolor=C_BORDER, linewidth=1.0, zorder=6))
    # Garis kolom TIDAK ditarik menembus judul besar "Fallout Salah Tagging /
    # Salah Homepass" (1/3 teratas) supaya judulnya bersih/menyatu — kolom 7 &
    # 10 (AGENCY|NON AGENCY|ALL CHANNEL) berhenti tepat di bawah judul.
    for c in GROUP_STARTS[1:]:
        y_atas = y0_head + (2 * h if c in (7, 10) else HEAD_H)
        ax.plot([xs[c], xs[c]], [y0_head, y_atas], color=C_BORDER, linewidth=1.1, zorder=7)

    cur_y = y0_head

    def draw_row(name_branch, name_wok, r, bg, text_col, heat_ranges,
                 fs=7.2, bold=False, use_heat=True, indent_wok=False):
        nonlocal cur_y
        cur_y -= ROW_H
        ax.add_patch(plt.Rectangle((xs[0], cur_y), x_end - xs[0], ROW_H,
                                   color=bg, zorder=1))

        def cell(col, text, color=None):
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=color or text_col, zorder=3)

        def mom_cell(col, val, naik_bagus=False):
            """
            MoM selalu persen (kalkulator sudah menjamin tidak pernah None).

            Warna mengikuti ARTI angkanya, bukan tandanya:
            - Kolom fallout (naik_bagus=False): fallout NAIK = jelek -> MERAH,
              fallout TURUN = bagus -> HIJAU.
            - Kolom RE (naik_bagus=True): RE itu jumlah sales, naik = bagus ->
              HIJAU, turun = jelek -> MERAH.

            Pewarnaan dilewati kalau background baris sendiri sudah merah (baris
            total) supaya teks tidak "hilang" (merah/hijau di atas merah).
            """
            text = _fmt_pct_sign(val)
            if val is None or val == 0 or bg == C_TOTAL_BG:
                cell(col, text)
                return
            bagus = (val > 0) if naik_bagus else (val < 0)
            cell(col, text, color=C_POS_TEXT if bagus else C_NEG_TEXT)

        def heat_cell(col, val, key):
            if not use_heat:
                cell(col, _fmt_num(val))
                return
            vmin, vmax = heat_ranges.get(key, (0, 0))
            rgb = _heat_bg(val, vmin, vmax)
            ax.add_patch(plt.Rectangle(
                (xs[col] + 0.03, cur_y + 0.03),
                COL_W[col] - 0.06, ROW_H - 0.06,
                color=rgb, zorder=2))
            ax.text(cx(col), cur_y + ROW_H/2, _fmt_num(val),
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=C_TEXT_MAIN, zorder=3)

        if name_branch is not None:
            ax.text(xs[0] + 0.1, cur_y + ROW_H/2, name_branch,
                    ha="left", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=text_col, zorder=3)
        wok_x = xs[1] + (0.25 if indent_wok else 0.1)
        ax.text(wok_x, cur_y + ROW_H/2, name_wok,
                ha="left", va="center", fontsize=fs,
                fontweight="bold" if bold else "normal",
                color=text_col, zorder=3)

        cell(2, _fmt_num(r["re_mtd"]))
        mom_cell(3, r["re_mom"], naik_bagus=True)   # RE = sales, naik = bagus

        heat_cell(4, r["agency_mtd"], "agency_mtd")
        cell(5, _fmt_pct_plain(r["agency_pct"]))
        mom_cell(6, r["agency_mom"])

        heat_cell(7, r["nonagency_mtd"], "nonagency_mtd")
        cell(8, _fmt_pct_plain(r["nonagency_pct"]))
        mom_cell(9, r["nonagency_mom"])

        heat_cell(10, r["all_mtd"], "all_mtd")
        cell(11, _fmt_pct_plain(r["all_pct"]))
        mom_cell(12, r["all_mom"])

        ax.plot([xs[0], x_end], [cur_y, cur_y], color=C_GRID, linewidth=0.3, zorder=5)
        for c in GROUP_STARTS[1:]:
            ax.plot([xs[c], xs[c]], [cur_y, cur_y + ROW_H], color=C_BORDER, linewidth=0.7, zorder=5)

    def heat_ranges_for(rows):
        return {
            "agency_mtd":    _col_range(rows, "agency_mtd"),
            "nonagency_mtd": _col_range(rows, "nonagency_mtd"),
            "all_mtd":       _col_range(rows, "all_mtd"),
        }

    # ── WOK, di-banding per BRANCH ───────────────────────────────────────────
    wok_heat = heat_ranges_for(woks)
    band = C_BAND_A
    last_branch = None
    for i, wok in enumerate(woks):
        show_branch = (i == 0) or (woks[i - 1]["branch"] != wok["branch"])
        if show_branch and last_branch is not None:
            band = C_BAND_B if band == C_BAND_A else C_BAND_A
        last_branch = wok["branch"]
        draw_row(wok["branch"] if show_branch else "", wok["name"], wok,
                 band, C_TEXT_MAIN, wok_heat, fs=7.0)

    # ── Bar pemisah (blank) ──────────────────────────────────────────────────
    cur_y -= ROW_H * 0.5
    ax.add_patch(plt.Rectangle((xs[0], cur_y), x_end - xs[0], ROW_H * 0.5,
                               color=C_SEP_BG, zorder=1))

    # ── Branch (subtotal) ────────────────────────────────────────────────────
    branch_heat = heat_ranges_for(branches)
    for br in branches:
        draw_row(None, br["name"], br, C_BAND_A, C_TEXT_MAIN, branch_heat,
                 fs=7.3, bold=True, indent_wok=True)

    # ── Total JATENG-DIY ─────────────────────────────────────────────────────
    draw_row(None, region["name"], region, C_TOTAL_BG, C_TEXT_LIGHT, {},
              fs=7.8, bold=True, use_heat=False, indent_wok=True)

    # ── Border luar tebal + garis batas grup tembus penuh ──────────────────
    for c in GROUP_STARTS[1:]:
        ax.plot([xs[c], xs[c]], [cur_y, y0_head], color=C_BORDER, linewidth=1.1, zorder=7)
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), x_end - xs[0], y0_head - cur_y + HEAD_H,
        fill=False, edgecolor=C_BORDER, linewidth=1.2, zorder=6))

    footer_line1 = (
        "Catatan: Agency = channel_group 'AGENCY'; Non Agency = seluruh channel lainnya.  |  "
        "Fallout dihitung jika fallout_reason mengandung \"SALAH TAGGING\" atau \"SALAH HOMEPASS\"."
    )
    footer_line2 = "Persentase dihitung terhadap RE pada channel yang sama.  |  Sumber: indihome_ordering_detail"
    if cutoff:
        footer_line2 += f"  |  Cutoff data: {cutoff}"
    footer = footer_line1 + "\n" + footer_line2
    ax.text(xs[0], cur_y - 0.05, footer,
            fontsize=5.0, color="#95A5A6", va="top", style="italic", linespacing=1.4)

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(9500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
