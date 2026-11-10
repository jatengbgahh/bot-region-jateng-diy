"""
renderer_homepass.py — Render tabel Homepass Report ke gambar PNG
Struktur: WOK (semua) → Branch (semua) → Region
Tone warna & gaya cell mengikuti renderer.py (/liveupdate) — header merah gelap,
bar oranye untuk %, cell hijau/merah untuk MoM.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
import textwrap

# ── Warna (sama dengan renderer.py) ─────────────────────────────────────────
C_HEADER_DARK  = "#2C1810"
C_HEADER_MID   = "#8B2500"
C_HEADER_LIGHT = "#C0392B"
C_REGION_BG    = "#2C3E50"
C_SECTION_BG   = "#D5D8DC"
C_BRANCH_ROW   = "#FBEEE6"
C_WOK_ODD      = "#FFFFFF"
C_WOK_EVEN     = "#ECEFF1"   # abu cerah — selang-seling per WOK biar tiap blok WOK kelihatan
C_NEG_BG       = "#FADBD8"
C_POS_BG       = "#D5F5E3"
C_NEG_TEXT     = "#C0392B"
C_POS_TEXT     = "#1E8449"
C_ACH_BAR      = "#F39C12"
C_ACH_FILL     = "#FEF9E7"
C_TEXT_MAIN    = "#1A1A1A"
C_TEXT_LIGHT   = "#FFFFFF"
C_TEXT_MID     = "#2C3E50"
C_GRID         = "#D5D8DC"
C_BORDER       = "#5D6D7E"   # garis batas antar grup kolom (lebih tegas)

# Kolom pertama grup (WOK/BRANCH | Total IO | Home ID) di blok "utama" — hanya
# di sini garis vertikal digambar. Sub-kolom di dalam "Home ID" (IO..RE/PS) dan
# semua sub-kolom "SF Active IO" TIDAK diberi garis sama sekali supaya
# grupnya terlihat menyatu/merger (batas blok SF Active IO sendiri sudah
# dipisahkan lewat celah + border block terpisah).
BOUNDARY_COLS = [1, 2]


def _fmt_num(v) -> str:
    return "-" if v is None else f"{int(v):,}"


def _fmt_pct_plain(v) -> str:
    return "-" if v is None else f"{v:.1f}%"


def _fmt_pct_sign(v) -> str:
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def _cutoff_lines(cutoff) -> str:
    """
    cutoff bisa berupa string (1 sumber, backward compatible) atau dict
    {"ordering_detail": ..., "homepass_sales": ...} untuk menampilkan tanggal
    update tiap sumber data secara terpisah (2 sumber independen dipakai
    /homepass — lihat catatan kaki).
    Dikembalikan sebagai baris tersendiri (tanpa separator " | " di depan)
    supaya ditaruh gulung ke bawah, bukan melebar ke kanan di subtitle.
    """
    if not cutoff:
        return ""
    if isinstance(cutoff, dict):
        parts = []
        if cutoff.get("homepass_sales"):
            parts.append(f"homepass_sales: {cutoff['homepass_sales']}")
        if cutoff.get("ordering_detail"):
            parts.append(f"ordering_detail: {cutoff['ordering_detail']}")
        return "Update data — " + "  ;  ".join(parts) if parts else ""
    return f"Update data ordering_detail: {cutoff}"


def _wrap_to_width(text: str, max_width_in: float, fontsize: float = 7.5) -> str:
    """
    Pecah `text` jadi beberapa baris supaya tidak ada baris yang lebih lebar
    dari `max_width_in` (inch) — dipakai untuk subtitle/cutoff supaya gambar
    tidak melebar ke kanan kalau isinya panjang, berapa pun panjangnya.
    """
    if not text:
        return text
    char_w_in = fontsize * 0.62 / 72.0  # perkiraan lebar rata-rata karakter (sans-serif, dilebihkan dikit buat jaga-jaga)
    max_chars = max(15, int(max_width_in / char_w_in))
    # break_long_words=True -> token tanpa spasi sepanjang apapun tetap
    # dipaksa patah, supaya baris TIDAK PERNAH lebih lebar dari canvas.
    wrapped = textwrap.fill(text, width=max_chars, break_long_words=True, break_on_hyphens=False)
    return wrapped


def render_homepass(data: dict, cutoff=None) -> BytesIO:
    region   = data["region"]
    branches = data["branches"]
    woks     = data["woks"]
    tgl      = data["tgl_closing"]
    bi_label = data["bi_label"]

    n_rows = 1 + 1 + len(branches) + 1 + len(woks)  # region + section + branch + section + wok

    ROW_H  = 0.24
    HEAD_H = 0.70
    PAD    = 0.12

    # Kolom: TERRITORY | Total IO | [HOME ID: IO,%IO,RE,MoM RE,RE Salah,%Salah,PS,MoM PS,RE/PS]
    #        | [SF ACTIVE IO: SF Active,SF w/HomeID,%SF w/HomeID,MoM SF w/HomeID]
    COL_W = [2.7, 0.65,
             0.55, 0.75, 0.55, 0.62, 0.85, 0.85, 0.55, 0.62, 0.62,
             0.68, 0.72, 0.78, 0.72]
    SPLIT_IDX = 11  # kolom pertama grup "SF Active IO" — dikasih jarak dari grup sebelumnya
    GAP       = 0.22
    fig_w = sum(COL_W) + 0.3 + GAP

    # Subtitle (cutoff) dibungkus supaya tidak ada baris yang lebih lebar dari
    # canvas — berapa pun panjang isinya, gambar tidak melebar ke kanan.
    cutoff_txt = _wrap_to_width(_cutoff_lines(cutoff), fig_w - 0.3)
    n_subtitle_lines = 1 + (cutoff_txt.count("\n") + 1 if cutoff_txt else 0)
    TITLE_H = 0.45 + 0.16 * (n_subtitle_lines - 1)
    fig_h   = TITLE_H + HEAD_H + n_rows * ROW_H + PAD * 2

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [0.15]
    for i, w in enumerate(COL_W[:-1]):
        xs.append(xs[-1] + w + (GAP if i == SPLIT_IDX - 1 else 0))

    def cx(ci):
        return xs[ci] + COL_W[ci] / 2

    # Batas kiri/kanan blok "utama" (WOK/BRANCH+Total IO+Home ID) & blok "SF Active IO"
    x_main_end = xs[SPLIT_IDX - 1] + COL_W[SPLIT_IDX - 1]
    x_sf_start = xs[SPLIT_IDX]
    x_sf_end   = xs[-1] + COL_W[-1]
    w_main     = x_main_end - xs[0]
    w_sf_block = x_sf_end - x_sf_start

    # ── Judul ─────────────────────────────────────────────────────────────
    ax.text(0.15, fig_h - 0.15, "Homepass Report",
            fontsize=10, fontweight="bold", color=C_TEXT_MID, va="top")
    subtitle_lines = [f"MtD {tgl.strftime('%d-%m-%Y')}  ({bi_label})"]
    if cutoff_txt:
        subtitle_lines.append(cutoff_txt)
    ax.text(0.15, fig_h - 0.32, "\n".join(subtitle_lines),
            fontsize=7.5, color="#7F8C8D", va="top", linespacing=1.6)

    # ── Header ────────────────────────────────────────────────────────────
    y0_head = fig_h - TITLE_H - HEAD_H
    h1 = HEAD_H * 0.46
    h2 = HEAD_H - h1

    def hcell(x, y, w, h, text, bg, fg=C_TEXT_LIGHT, fs=6.5):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.1)

    hcell(xs[0], y0_head, COL_W[0], HEAD_H, "WOK / BRANCH", C_HEADER_DARK, fs=8.5)
    hcell(xs[1], y0_head, COL_W[1], HEAD_H, "Total\nIO",    C_HEADER_DARK, fs=7)

    w_home = sum(COL_W[2:11])
    hcell(xs[2], y0_head + h2, w_home, h1, "Home ID", C_HEADER_MID, fs=8.5)
    home_labels = [
        "IO", "%IO\nHome ID", "RE", "MoM\nRE", "RE Salah\nHomepass",
        "%Order Salah\nHomepass", "PS", "MoM\nPS", "RE/PS",
    ]
    for i, lbl in enumerate(home_labels):
        hcell(xs[2 + i], y0_head, COL_W[2 + i], h2, lbl, C_HEADER_MID, fs=6.5)

    w_sf = sum(COL_W[11:15])
    hcell(xs[11], y0_head + h2, w_sf, h1, "SF Active IO", C_HEADER_LIGHT, fs=8.5)
    sf_labels = ["SF Active\nIO", "SF with IO\nHome ID", "%SF with\nHome ID", "MoM SF with\nIO Home ID"]
    for i, lbl in enumerate(sf_labels):
        hcell(xs[11 + i], y0_head, COL_W[11 + i], h2, lbl, C_HEADER_LIGHT, fs=6.5)

    ax.add_patch(plt.Rectangle((xs[0], y0_head), w_main, HEAD_H,
                                fill=False, edgecolor=C_BORDER, linewidth=1.0, zorder=4))
    ax.add_patch(plt.Rectangle((x_sf_start, y0_head), w_sf_block, HEAD_H,
                                fill=False, edgecolor=C_BORDER, linewidth=1.0, zorder=4))

    # Garis vertikal HANYA di batas grup (WOK/BRANCH | Total IO | Home ID) —
    # sub-kolom di dalam "Home ID" dan semua sub-kolom "SF Active IO" sengaja
    # tidak diberi garis supaya grupnya terlihat menyatu/merger.
    for c in BOUNDARY_COLS:
        ax.plot([xs[c], xs[c]], [y0_head, y0_head + HEAD_H], color=C_BORDER, linewidth=1.0, zorder=5)
    # Garis horizontal antara baris grup (Home ID / SF Active IO) & sub-label
    ax.plot([xs[2], xs[2] + w_home], [y0_head + h2, y0_head + h2],
            color="white", linewidth=0.7, zorder=5)
    ax.plot([xs[11], xs[11] + w_sf], [y0_head + h2, y0_head + h2],
            color="white", linewidth=0.7, zorder=5)

    cur_y = y0_head

    # ── Section header ────────────────────────────────────────────────────
    def draw_section(label):
        nonlocal cur_y
        sh = ROW_H * 0.8
        cur_y -= sh
        ax.add_patch(plt.Rectangle((xs[0], cur_y), w_main, sh,
                                   color=C_SECTION_BG, zorder=1))
        ax.add_patch(plt.Rectangle((x_sf_start, cur_y), w_sf_block, sh,
                                   color=C_SECTION_BG, zorder=1))
        ax.text(xs[0] + 0.15, cur_y + sh/2, label,
                ha="left", va="center", fontsize=7.5, fontweight="bold",
                color=C_TEXT_MID, zorder=3)
        ax.plot([xs[0], x_main_end], [cur_y, cur_y], color=C_GRID, linewidth=0.4, zorder=5)
        ax.plot([x_sf_start, x_sf_end], [cur_y, cur_y], color=C_GRID, linewidth=0.4, zorder=5)

    # ── Baris data ────────────────────────────────────────────────────────
    def draw_row(r, bg, text_col, fs=7.2, bold=False):
        nonlocal cur_y
        cur_y -= ROW_H
        ax.add_patch(plt.Rectangle((xs[0], cur_y), w_main, ROW_H,
                                   color=bg, zorder=1))
        ax.add_patch(plt.Rectangle((x_sf_start, cur_y), w_sf_block, ROW_H,
                                   color=bg, zorder=1))

        def cell(col, text, color=None):
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=color or text_col, zorder=3)

        def mom_cell(col, val):
            """Cell dengan background merah/hijau untuk MoM."""
            text = _fmt_pct_sign(val)
            if val is None or val == 0:
                cell(col, text)
                return
            bg_c, fg_c = (C_POS_BG, C_POS_TEXT) if val > 0 else (C_NEG_BG, C_NEG_TEXT)
            ax.add_patch(plt.Rectangle(
                (xs[col] + 0.03, cur_y + 0.03),
                COL_W[col] - 0.06, ROW_H - 0.06,
                color=bg_c, zorder=2))
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold", color=fg_c, zorder=3)

        def ach_bar(col, pct):
            """
            Progress bar oranye untuk %IO Home ID / %SF with Home ID.
            Bar ditaruh di KIRI, angkanya di KANAN — dulu angkanya di tengah bar
            sehingga ujung bar memotong tulisannya (kelihatan ter-cross).
            """
            if pct is None:
                cell(col, "-")
                return
            teks    = f"{pct:.1f}%" if not bold else f"{pct:.2f}%"
            w_teks  = 0.34 if bold else 0.28   # ruang khusus angka di kanan
            track_w = COL_W[col] - 0.10        # alas krem selebar sel penuh, supaya
            bar_h   = ROW_H * 0.55             # angkanya selalu di atas krem (kebaca
            bx      = xs[col] + 0.05           # juga di baris Region yang bg-nya gelap)
            by      = cur_y + (ROW_H - bar_h) / 2
            ax.add_patch(plt.Rectangle((bx, by), track_w, bar_h,
                                       color=C_ACH_FILL, zorder=2))
            # Isian oranye dibatasi supaya tidak pernah masuk area angka
            fill_max = max(0.05, track_w - w_teks)
            fill = min(pct / 100, 1.0) * fill_max
            if fill > 0:
                ax.add_patch(plt.Rectangle((bx, by), fill, bar_h,
                                           color=C_ACH_BAR, zorder=3))
            ax.text(xs[col] + COL_W[col] - 0.08, cur_y + ROW_H/2, teks,
                    ha="right", va="center", fontsize=fs - 0.8,
                    fontweight="bold", color="#5D4000", zorder=4)

        def salah_cell(col, val):
            """RE Salah Homepass — merah kalau > 0."""
            text = _fmt_num(val)
            if val is not None and val > 0:
                cell(col, text, color=C_NEG_TEXT)
            else:
                cell(col, text)

        # Col 0: nama territory
        ax.text(xs[0] + 0.12, cur_y + ROW_H/2,
                r.get("name", ""), ha="left", va="center",
                fontsize=fs, fontweight="bold" if bold else "normal",
                color=text_col, zorder=3)

        cell(1, _fmt_num(r["total_io"]))

        cell(2, _fmt_num(r["io"]))
        ach_bar(3, r["pct_io_home_id"])
        cell(4, _fmt_num(r["re"]))
        mom_cell(5, r["mom_re"])
        salah_cell(6, r["re_salah"])
        cell(7, _fmt_pct_plain(r["pct_salah_homepass"]))
        cell(8, _fmt_num(r["ps"]))
        mom_cell(9, r["mom_ps"])
        cell(10, _fmt_pct_plain(r["re_ps"]))

        cell(11, _fmt_num(r["sf_active_io"]))
        cell(12, _fmt_num(r["sf_home_id"]))
        ach_bar(13, r["pct_sf_home_id"])
        mom_cell(14, r["mom_sf_home_id"])

        # Garis baris + garis kolom (semua kolom) pakai tone tema — sub-kolom
        # tipis C_GRID, batas grup tegas C_BORDER.
        ax.plot([xs[0], x_main_end], [cur_y, cur_y], color=C_GRID, linewidth=0.4, zorder=5)
        ax.plot([x_sf_start, x_sf_end], [cur_y, cur_y], color=C_GRID, linewidth=0.4, zorder=5)
        for c in list(range(1, SPLIT_IDX)) + list(range(SPLIT_IDX + 1, len(COL_W))):
            tebal, warna = ((0.6, C_BORDER) if c in BOUNDARY_COLS else (0.35, C_GRID))
            ax.plot([xs[c], xs[c]], [cur_y, cur_y + ROW_H], color=warna, linewidth=tebal, zorder=5)

    # ── Render baris: WOK → Branch → Region ─────────────────────────────────
    draw_section("WOK")
    for i, wok in enumerate(woks):
        bg = C_WOK_ODD if i % 2 == 0 else C_WOK_EVEN
        draw_row(wok, bg, C_TEXT_MAIN, fs=7.2)

    draw_section("Branch")
    for br in branches:
        draw_row(br, C_BRANCH_ROW, C_TEXT_MAIN, fs=7.4, bold=True)

    draw_section("Region")
    draw_row(region, C_REGION_BG, C_TEXT_LIGHT, fs=7.9, bold=True)

    # ── Garis kolom tembus penuh (batas grup tegas, sub-kolom tipis) ──────────
    for c in list(range(1, SPLIT_IDX)) + list(range(SPLIT_IDX + 1, len(COL_W))):
        tebal, warna = ((1.0, C_BORDER) if c in BOUNDARY_COLS else (0.35, C_GRID))
        ax.plot([xs[c], xs[c]], [cur_y, y0_head], color=warna, linewidth=tebal, zorder=5)

    # Border luar (2 blok terpisah, dipisah celah SPLIT_IDX)
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), w_main, y0_head - cur_y + HEAD_H,
        fill=False, edgecolor=C_BORDER, linewidth=1.2, zorder=6))
    ax.add_patch(plt.Rectangle(
        (x_sf_start, cur_y), w_sf_block, y0_head - cur_y + HEAD_H,
        fill=False, edgecolor=C_BORDER, linewidth=1.2, zorder=6))

    # Catatan kaki (tanggal update tiap sumber sudah ditampilkan di subtitle atas)
    # Dibungkus ke bawah (bukan 1 baris panjang) supaya tidak melebar ke kanan
    # melebihi lebar tabel.
    footer = (
        "Total IO/SF Active IO = indihome_ordering_detail channel AGENCY  |  "
        "Home ID (IO/RE/PS) = homepass_sales JOIN indihome_ordering_detail  |  "
        "RE Salah Homepass = fallout_reason mengandung \"SALAH TAGGING\"  |  "
        "Sumber: homepass_sales + indihome_ordering_detail"
    )
    ax.text(xs[0], cur_y - 0.05, _wrap_to_width(footer, w_main, fontsize=5.0),
            fontsize=5.0, color="#95A5A6", va="top", style="italic", linespacing=1.6)

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(9500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def render_homepass_sto(data: dict, cutoff=None, branch_filter=None, part_label=None) -> BytesIO:
    """
    Sama seperti render_homepass(), tapi ditambah 1 kolom STO — tiap WOK
    dipecah jadi baris per STO (diurutkan descending %IO Home ID, paling
    tinggi paling atas, paling rendah paling bawah). Fokus ke STO saja —
    TIDAK ada baris subtotal Branch/Region di bagian bawah (beda dari
    render_homepass()).

    Hanya blok "Home ID" yang ditampilkan (blok "SF Active IO" tidak dipakai
    di report ini supaya kolom Home ID/STO bisa dilebarkan, layar dipakai
    penuh kiri-kanan). Tidak ada baris subtotal per WOK.

    branch_filter: list nama branch untuk dipilih (kalau report dipecah per
    3 branch); None = tampilkan semua branch.
    part_label: teks tambahan di judul, mis. "(1/2)".
    """
    sto_groups = [g for g in data["sto_groups"] if not branch_filter or g["branch"] in branch_filter]
    tgl        = data["tgl_closing"]
    bi_label   = data["bi_label"]

    n_sto = sum(len(g["stos"]) for g in sto_groups)
    n_rows = 1 + n_sto  # section WOK/STO + baris STO

    ROW_H  = 0.24
    HEAD_H = 0.70
    PAD    = 0.12

    # Kolom: WOK/BRANCH | STO | Total IO | [HOME ID: 9 kolom] — dilebarkan
    # (canvas dipakai penuh kiri-kanan) karena blok SF Active IO dihapus.
    COL_W = [2.3, 1.4,
             0.9,
             0.77, 1.05, 0.77, 0.87, 1.19, 1.19, 0.77, 0.87, 0.87]

    fig_w = sum(COL_W) + 0.3

    # Subtitle (cutoff/branch) dibungkus supaya tidak ada baris yang lebih
    # lebar dari canvas — berapa pun panjang isinya, gambar tidak melebar
    # ke kanan.
    max_w = fig_w - 0.3
    cutoff_txt = _wrap_to_width(_cutoff_lines(cutoff), max_w)
    branch_txt = (
        _wrap_to_width(f"Branch: {', '.join(branch_filter)}", max_w)
        if branch_filter else ""
    )
    n_subtitle_lines = (
        1
        + (cutoff_txt.count("\n") + 1 if cutoff_txt else 0)
        + (branch_txt.count("\n") + 1 if branch_txt else 0)
    )
    TITLE_H = 0.45 + 0.16 * (n_subtitle_lines - 1)
    fig_h   = TITLE_H + HEAD_H + n_rows * ROW_H + PAD * 2

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [0.15]
    for w in COL_W[:-1]:
        xs.append(xs[-1] + w)

    def cx(ci):
        return xs[ci] + COL_W[ci] / 2

    x_end = xs[-1] + COL_W[-1]
    w_main = x_end - xs[0]

    BOUNDARY_COLS = [1, 2, 3]

    # ── Judul ─────────────────────────────────────────────────────────────
    title = "Homepass Report — Breakdown per STO"
    if part_label:
        title += f"  {part_label}"
    ax.text(0.15, fig_h - 0.15, title,
            fontsize=10, fontweight="bold", color=C_TEXT_MID, va="top")
    subtitle_lines = [f"MtD {tgl.strftime('%d-%m-%Y')}  ({bi_label})"]
    if cutoff_txt:
        subtitle_lines.append(cutoff_txt)
    if branch_txt:
        subtitle_lines.append(branch_txt)
    ax.text(0.15, fig_h - 0.32, "\n".join(subtitle_lines),
            fontsize=7.5, color="#7F8C8D", va="top", linespacing=1.6)

    # ── Header ────────────────────────────────────────────────────────────
    y0_head = fig_h - TITLE_H - HEAD_H
    h1 = HEAD_H * 0.46
    h2 = HEAD_H - h1

    def hcell(x, y, w, h, text, bg, fg=C_TEXT_LIGHT, fs=6.5):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w/2, y + h/2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.1)

    hcell(xs[0], y0_head, COL_W[0], HEAD_H, "WOK / BRANCH", C_HEADER_DARK, fs=8.5)
    hcell(xs[1], y0_head, COL_W[1], HEAD_H, "STO",          C_HEADER_DARK, fs=8.5)
    hcell(xs[2], y0_head, COL_W[2], HEAD_H, "Total\nIO",    C_HEADER_DARK, fs=7.5)

    w_home = sum(COL_W[3:12])
    hcell(xs[3], y0_head + h2, w_home, h1, "Home ID", C_HEADER_MID, fs=9)
    home_labels = [
        "IO", "%IO\nHome ID", "RE", "MoM\nRE", "RE Salah\nHomepass",
        "%Order Salah\nHomepass", "PS", "MoM\nPS", "RE/PS",
    ]
    for i, lbl in enumerate(home_labels):
        hcell(xs[3 + i], y0_head, COL_W[3 + i], h2, lbl, C_HEADER_MID, fs=7)

    ax.add_patch(plt.Rectangle((xs[0], y0_head), w_main, HEAD_H,
                                fill=False, edgecolor=C_BORDER, linewidth=1.0, zorder=4))
    # Garis antar sub-kolom "Home ID" di header — putih tipis (senada blok
    # header) supaya tiap sub-kolom kebaca terpisah tapi grupnya tetap menyatu.
    for c in range(4, 12):
        ax.plot([xs[c], xs[c]], [y0_head, y0_head + h2], color="white", linewidth=0.6, zorder=5)
    for c in BOUNDARY_COLS:
        ax.plot([xs[c], xs[c]], [y0_head, y0_head + HEAD_H], color=C_BORDER, linewidth=1.0, zorder=5)
    ax.plot([xs[3], xs[3] + w_home], [y0_head + h2, y0_head + h2],
            color="white", linewidth=0.7, zorder=5)

    cur_y = y0_head

    # ── Section header ────────────────────────────────────────────────────
    def draw_section(label):
        nonlocal cur_y
        sh = ROW_H * 0.8
        cur_y -= sh
        ax.add_patch(plt.Rectangle((xs[0], cur_y), w_main, sh, color=C_SECTION_BG, zorder=1))
        ax.text(xs[0] + 0.15, cur_y + sh/2, label,
                ha="left", va="center", fontsize=7.5, fontweight="bold",
                color=C_TEXT_MID, zorder=3)
        ax.plot([xs[0], x_end], [cur_y, cur_y], color=C_GRID, linewidth=0.4, zorder=5)

    # ── Baris data ────────────────────────────────────────────────────────
    def draw_row(name0, name1, r, bg, text_col, fs=7.4, bold=False):
        nonlocal cur_y
        cur_y -= ROW_H
        ax.add_patch(plt.Rectangle((xs[0], cur_y), w_main, ROW_H, color=bg, zorder=1))

        def cell(col, text, color=None):
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=color or text_col, zorder=3)

        def mom_cell(col, val):
            text = _fmt_pct_sign(val)
            if val is None or val == 0:
                cell(col, text)
                return
            bg_c, fg_c = (C_POS_BG, C_POS_TEXT) if val > 0 else (C_NEG_BG, C_NEG_TEXT)
            ax.add_patch(plt.Rectangle(
                (xs[col] + 0.03, cur_y + 0.03),
                COL_W[col] - 0.06, ROW_H - 0.06,
                color=bg_c, zorder=2))
            ax.text(cx(col), cur_y + ROW_H/2, text,
                    ha="center", va="center", fontsize=fs,
                    fontweight="bold", color=fg_c, zorder=3)

        def ach_bar(col, pct):
            """Bar di KIRI, angka di KANAN — biar ujung bar tidak memotong tulisan."""
            if pct is None:
                cell(col, "-")
                return
            teks    = f"{pct:.1f}%" if not bold else f"{pct:.2f}%"
            w_teks  = 0.34 if bold else 0.28
            track_w = COL_W[col] - 0.10
            bar_h   = ROW_H * 0.55
            bx      = xs[col] + 0.05
            by      = cur_y + (ROW_H - bar_h) / 2
            ax.add_patch(plt.Rectangle((bx, by), track_w, bar_h, color=C_ACH_FILL, zorder=2))
            fill_max = max(0.05, track_w - w_teks)
            fill = min(pct / 100, 1.0) * fill_max
            if fill > 0:
                ax.add_patch(plt.Rectangle((bx, by), fill, bar_h, color=C_ACH_BAR, zorder=3))
            ax.text(xs[col] + COL_W[col] - 0.08, cur_y + ROW_H/2, teks,
                    ha="right", va="center", fontsize=fs - 0.8,
                    fontweight="bold", color="#5D4000", zorder=4)

        def salah_cell(col, val):
            text = _fmt_num(val)
            if val is not None and val > 0:
                cell(col, text, color=C_NEG_TEXT)
            else:
                cell(col, text)

        if name0 is not None:
            ax.text(xs[0] + 0.1, cur_y + ROW_H/2, name0,
                    ha="left", va="center", fontsize=fs,
                    fontweight="bold" if bold else "normal",
                    color=text_col, zorder=3)
        ax.text(xs[1] + 0.1, cur_y + ROW_H/2, name1,
                ha="left", va="center", fontsize=fs,
                fontweight="bold" if bold else "normal",
                color=text_col, zorder=3)

        cell(2, _fmt_num(r["total_io"]))

        cell(3, _fmt_num(r["io"]))
        ach_bar(4, r["pct_io_home_id"])
        cell(5, _fmt_num(r["re"]))
        mom_cell(6, r["mom_re"])
        salah_cell(7, r["re_salah"])
        cell(8, _fmt_pct_plain(r["pct_salah_homepass"]))
        cell(9, _fmt_num(r["ps"]))
        mom_cell(10, r["mom_ps"])
        cell(11, _fmt_pct_plain(r["re_ps"]))

        # Garis baris (horizontal) + garis kolom (vertikal) untuk SEMUA kolom,
        # pakai tone tema: sub-kolom tipis C_GRID, batas grup tegas C_BORDER.
        ax.plot([xs[0], x_end], [cur_y, cur_y], color=C_GRID, linewidth=0.4, zorder=5)
        for c in range(1, len(COL_W)):
            tebal, warna = ((0.7, C_BORDER) if c in BOUNDARY_COLS else (0.35, C_GRID))
            ax.plot([xs[c], xs[c]], [cur_y, cur_y + ROW_H], color=warna, linewidth=tebal, zorder=5)

    # ── Render baris: WOK -> STO saja (fokus ke STO, tanpa subtotal Branch/Region) ──
    # Label section sengaja pendek — keterangan urutannya sudah ada di catatan
    # kaki. Kalau panjang, tulisannya tembus melewati garis kolom (ter-cross).
    draw_section("WOK / STO")
    y_batas_wok = []          # posisi y batas antar WOK -> digaris tegas
    for gi, group in enumerate(sto_groups):
        wok_name = group["wok"]
        # Selang-seling per WOK: putih / abu cerah, biar tiap WOK kelihatan
        # sebagai satu blok tanpa perlu garis tebal.
        band = C_WOK_ODD if gi % 2 == 0 else C_WOK_EVEN
        if gi:
            y_batas_wok.append(cur_y)
        for i, sto_row in enumerate(group["stos"]):
            draw_row(wok_name if i == 0 else "", sto_row["name"], sto_row,
                     band, C_TEXT_MAIN, fs=7.0)

    # Garis pemisah antar WOK (lebih tegas dari garis antar baris STO)
    for y in y_batas_wok:
        ax.plot([xs[0], x_end], [y, y], color=C_BORDER, linewidth=0.9, zorder=6)

    # Garis kolom tembus penuh dari header s/d baris terakhir
    for c in range(1, len(COL_W)):
        tebal, warna = ((1.0, C_BORDER) if c in BOUNDARY_COLS else (0.35, C_GRID))
        ax.plot([xs[c], xs[c]], [cur_y, y0_head], color=warna, linewidth=tebal, zorder=5)
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), w_main, y0_head - cur_y + HEAD_H,
        fill=False, edgecolor=C_BORDER, linewidth=1.2, zorder=6))

    # Dibungkus ke bawah supaya tidak melebar ke kanan melebihi lebar tabel.
    footer = (
        "Total IO = indihome_ordering_detail channel AGENCY  |  "
        "Home ID (IO/RE/PS) = homepass_sales JOIN indihome_ordering_detail  |  "
        "RE Salah Homepass = fallout_reason mengandung \"SALAH TAGGING\"  |  "
        "STO diurutkan descending %IO Home ID per WOK (tertinggi di atas, terendah di bawah)  |  "
        "Sumber: homepass_sales + indihome_ordering_detail"
    )
    ax.text(xs[0], cur_y - 0.05, _wrap_to_width(footer, w_main, fontsize=5.0),
            fontsize=5.0, color="#95A5A6", va="top", style="italic", linespacing=1.6)

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(9500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf
