"""
renderer_djpprio.py — Render report "DJP ODP Priority" (/djpprio) jadi PNG +
caption Telegram. Gantikan langkah manual (buka djp_report_generator.html,
klik Generate, download PNG) — dipanggil bot.py, SINKRON di event loop (render
matplotlib tidak boleh masuk asyncio.to_thread, lihat memory
concurrency-model-bot-re-jateng).

Desain SAMA PERSIS dengan template web asli (Willy/_djp_template.html) — warna,
border, layout diambil literal dari CSS/JS-nya (bukan re-desain):
  - Judul: kotak putih border navy, teks judul bold #0f2544 kiri, tanggal
    italic #333 kanan (persis .rtitle).
  - Header tabel: navy (#12335b) polos, satu warna sama utk baris label grup
    (P1A..P3B/TOTAL) maupun sub-header (ODP/%Visit) — tidak ada warna kedua.
  - Grid: semua sel (header & data) punya border tipis #b9c3d1 (header pakai
    #274a78), sama seperti `table.report th,td{border:1px solid #b9c3d1}`.
  - Baris data & subtotal: putih polos (TIDAK zebra) — bedanya cuma subtotal
    bold, tidak ada tint warna.
  - Baris JATENG DIY: merah solid (#c00000), teks putih, TIDAK ada sel
    berwarna tambahan (persis `tr.grand` di JS — pctCell utk grand row polos).
  - Sel %Visit (non-grand): 3-color scale PERSIS CS_LOW/CS_MID/CS_HIGH JS,
    relatif per kolom utk detail/subtotal, absolut 0-100% utk grand.
  - Spacer antar seksi: abu-hangat tipis (#F3EFEE), tanpa border.

Satu-satunya yg BUKAN dari template asli: lebar kolom BRANCH/WOK dihitung dari
isi terpanjang (col_width), bukan dipatok — supaya nama panjang (mis.
"WONOSOBO BANJARNEGARA") tidak nabrak kolom sebelah. Ini bugfix, bukan desain.
"""
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from calculator_djpprio import FLAGS
from renderer_caps_font import col_width

# ── Palet — literal dari _djp_template.html (:root vars + CSS rules) ────────
C_NAVY = "#12335B"
C_NAVY_BORDER = "#274A78"
C_RED = "#C00000"
C_RED_BORDER = "#8A0000"
C_TITLE_TEXT = "#0F2544"
C_DATE_TEXT = "#333333"
C_DARK = "#2B2B2B"
C_GRID = "#B9C3D1"
C_SPACER_BG = "#F3EFEE"
C_WHITE = "#FFFFFF"

# Abu-abu netral (BUKAN dari template) — dipakai KHUSUS utk garis penegas
# batas kolom yang ditambahkan di atas desain asli (group boundary + TOTAL,
# TOTAL cuma beda ketebalan lw, warnanya sama). Sengaja bukan C_NAVY/
# C_NAVY_BORDER — itu bikin garisnya kebaca "biru", padahal maksudnya cuma
# garis struktur netral.
C_BOUND_GRAY = "#6B7280"

# Ukuran font — dipatok konstan (BUKAN dikecilkan menyesuaikan tabel yg lebar/
# banyak kolom), supaya selalu terbaca walau di-scale-down Telegram (mis. di
# HP, gambar lebar otomatis diperkecil sampai muat layar).
FS_TITLE = 26
FS_DATE = 19
FS_HDR_GROUP = 22     # label grup P1A..P3B / TOTAL
FS_HDR_SUB = 18       # sub-header ODP / %Visit / Visit ODP
FS_HDR_ID = 21        # header BRANCH / WOK
FS_BRANCH = 17        # nama branch di baris data
FS_WOK = 19           # nama WOK di baris data (bold)
FS_DATA = 18          # angka ODP & %Visit
FS_MERGED = 21        # label branch/JATENG DIY di baris subtotal/grand

# 3-color scale — literal dari CS_LOW/CS_MID/CS_HIGH (agresif_colors-style,
# tapi ini emang persis nilai JS-nya, bukan re-pick warna)
CS_LOW = (0xF8, 0x69, 0x6B)
CS_MID = (0xFC, 0xFC, 0xFF)
CS_HIGH = (0x63, 0xBE, 0x7B)


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


def _lerp3(a, b, t):
    return _to_hex(_lerp(a, b, max(0.0, min(1.0, t))))


def _percentile(sorted_vals, p):
    n = len(sorted_vals)
    if not n:
        return None
    if n == 1:
        return sorted_vals[0]
    idx = p * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    return sorted_vals[lo] if lo == hi else sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def _make_scale(values):
    """makeScale() JS: skala relatif per-kolom, min->CS_LOW, median->CS_MID, max->CS_HIGH."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return lambda v: C_WHITE
    vmin, vmax, vmid = vals[0], vals[-1], _percentile(vals, 0.5)

    def scale(v):
        if v is None:
            return C_WHITE
        if vmax == vmin:
            return _lerp3(CS_MID, CS_MID, 0)
        if v <= vmid:
            d = vmid - vmin
            return _lerp3(CS_LOW, CS_MID, (v - vmin) / d if d else 1)
        d = vmax - vmid
        return _lerp3(CS_MID, CS_HIGH, (v - vmid) / d if d else 0)
    return scale


def _abs_scale(pct):
    """absScale() JS: skala absolut 0-100%, dipakai baris JATENG DIY (grand) —
    TIDAK dipakai di sini krn grand row memang tidak diwarnai (persis JS)."""
    if pct is None:
        return C_WHITE
    t = max(0.0, min(1.0, pct))
    return _lerp3(CS_LOW, CS_MID, t / 0.5) if t <= 0.5 else _lerp3(CS_MID, CS_HIGH, (t - 0.5) / 0.5)


def _fmt_int(n):
    return f"{n:,}" if n else ("-" if n == 0 else "")


def _fmt_pct(p):
    return "-" if p is None else f"{p * 100:.1f}%"


def render_djpprio(result: dict, title: str, date_label: str) -> BytesIO:
    detail, subtotals, grand = result["detail"], result["subtotals"], result["grand"]

    # Skala warna relatif per kolom, TERPISAH utk detail vs subtotal (persis
    # JS: 2 loop scale beda utk row biasa & row subtotal).
    detail_scales = {f: _make_scale([r["cells"][f]["pct"] for r in detail]) for f in FLAGS}
    subtot_scales = {f: _make_scale([r["cells"][f]["pct"] for r in subtotals]) for f in FLAGS}
    detail_tot_scale = _make_scale([r["total"]["pct"] for r in detail])
    subtot_tot_scale = _make_scale([r["total"]["pct"] for r in subtotals])

    # ── Geometri tabel ───────────────────────────────────────────────────────
    # Lebar kolom BRANCH/WOK dihitung dari isi terpanjang (col_width) — SATU-
    # SATUNYA yg bukan dari template asli (bugfix, lihat docstring modul).
    n_flags = len(FLAGS)
    w_branch = col_width([r["branch"] for r in detail] + ["BRANCH"], fs=FS_BRANCH, minw=2.4, pad=0.48, bold=False)
    w_wok = col_width([r["wok"] for r in detail] + ["WOK"], fs=FS_WOK, minw=2.6, pad=0.58, bold=True)
    w_merged = col_width([r["wok"] for r in subtotals] + [grand["wok"]], fs=FS_MERGED, minw=0, pad=0.58, bold=True)
    W_ID_BRANCH = w_branch
    W_ID_WOK = max(w_wok, w_merged - w_branch)
    W_ODP, W_PCT = 1.75, 1.75
    W_TOT_ODP, W_TOT_VISIT, W_TOT_PCT = 1.85, 2.00, 1.75
    col_w = [W_ID_BRANCH, W_ID_WOK] + [W_ODP, W_PCT] * n_flags + [W_TOT_ODP, W_TOT_VISIT, W_TOT_PCT]
    TW = sum(col_w)
    off_flags = 2

    # Tinggi baris DIPADATKAN (font tetap sama, cuma jarak vertikalnya
    # dirapatkan) — sebelumnya kebanyakan padding kosong di atas/bawah teks.
    RH = 0.58
    HH_TITLE = 0.85
    HH1, HH2 = 0.50, 0.62
    SPACER_H = 0.16
    MG = 0.22
    n_rows = len(detail) + len(subtotals) + 1
    FH = HH_TITLE + HH1 + HH2 + n_rows * RH + SPACER_H * 2 + MG * 2
    FW = TW + MG * 2

    # add_axes([0,0,1,1]) -> axes menutupi PERSIS 100% figure (WAJIB, lihat
    # renderer_caps_font.col_width — kalau ada margin, asumsi "1 data-unit =
    # 1 inci" meleset dan kolom lebar bisa nabrak lagi).
    fig = plt.figure(figsize=(FW, FH))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, FW)
    ax.set_ylim(0, FH)
    ax.axis("off")
    fig.patch.set_facecolor(C_WHITE)

    # ── Judul (persis .rtitle: kotak putih border navy) ─────────────────────
    y_title = FH - MG - HH_TITLE
    ax.add_patch(Rectangle((MG, y_title), TW, HH_TITLE, facecolor=C_WHITE,
                            edgecolor=C_NAVY, linewidth=1.0, zorder=2))
    ax.text(MG + 0.14, y_title + HH_TITLE / 2, title, ha="left", va="center",
            fontsize=FS_TITLE, fontweight="bold", color=C_TITLE_TEXT, zorder=3)
    ax.text(MG + TW - 0.14, y_title + HH_TITLE / 2, date_label, ha="right", va="center",
            fontsize=FS_DATE, fontstyle="italic", color=C_DATE_TEXT, zorder=3)

    # ── Header tabel (2 baris, NAVY POLOS — sama utk grup & sub-header) ─────
    xs = [MG]
    for w in col_w[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + col_w[i] / 2

    yh1 = y_title - HH1
    yh2 = yh1 - HH2

    def hcell(x, y, w, h, txt, fs=FS_HDR_SUB):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=C_NAVY, edgecolor=C_NAVY_BORDER,
                                linewidth=1.0, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs,
                fontweight="bold", color=C_WHITE, zorder=3, multialignment="center", linespacing=1.05)

    hcell(xs[0], yh2, col_w[0], HH1 + HH2, "BRANCH", fs=FS_HDR_ID)
    hcell(xs[1], yh2, col_w[1], HH1 + HH2, "WOK", fs=FS_HDR_ID)
    for i, f in enumerate(FLAGS):
        cstart = off_flags + i * 2
        hcell(xs[cstart], yh1, col_w[cstart] + col_w[cstart + 1], HH1, f, fs=FS_HDR_GROUP)
        hcell(xs[cstart], yh2, col_w[cstart], HH2, "ODP", fs=FS_HDR_SUB)
        hcell(xs[cstart + 1], yh2, col_w[cstart + 1], HH2, "%Visit", fs=FS_HDR_SUB)
    tstart = off_flags + n_flags * 2
    hcell(xs[tstart], yh1, col_w[tstart] + col_w[tstart + 1] + col_w[tstart + 2], HH1, "TOTAL", fs=FS_HDR_GROUP)
    hcell(xs[tstart], yh2, col_w[tstart], HH2, "ODP", fs=FS_HDR_SUB)
    hcell(xs[tstart + 1], yh2, col_w[tstart + 1], HH2, "Visit ODP", fs=FS_HDR_SUB)
    hcell(xs[tstart + 2], yh2, col_w[tstart + 2], HH2, "%Visit", fs=FS_HDR_SUB)

    # ── Batas kolom header DIPERTEGAS ────────────────────────────────────────
    # hcell() sendiri sudah ngasih border C_NAVY_BORDER (#274A78) tiap sel,
    # tapi warnanya CUMA SEDIKIT lebih terang dari fill navy (#12335B) — kalau
    # sesama header (navy ketemu navy), garisnya nyaris tak kelihatan (LOW
    # KONTRAS), beda dari sel data yg fill-nya putih/merah (border C_GRID
    # kontras jelas di situ). Ditambah garis putih tipis di atas semua sel
    # header — TAPI ada 2 macam batas yg HARUS dibedakan tingginya:
    #   - Batas "MAJOR" (persis di tepi sel judul grup HH1, mis. BRANCH|WOK,
    #     WOK|P1A, P1A|P1B, ..., P3B|TOTAL, TOTAL|tepi kanan) -> aman tembus
    #     PENUH dari HH2 sampai atas (yh2 -> y_title).
    #   - Batas "MINOR" (di TENGAH judul grup HH1 yg cuma 1 sel merge, mis.
    #     ODP|%Visit di dalam "P1A", atau ODP|Visit ODP|%Visit di dalam
    #     "TOTAL") -> KALAU ditarik sampai y_title dia "ngecros" motong
    #     tulisan judul grup yang sebenarnya 1 sel gabungan. Batas ini cuma
    #     boleh sampai baris sub-header (yh2 -> yh1).
    right_edge_hdr = xs[-1] + col_w[-1]
    major_header_bounds = [xs[0], xs[1], xs[off_flags]]
    major_header_bounds += [xs[off_flags + i * 2] for i in range(1, n_flags)]
    major_header_bounds += [xs[tstart], right_edge_hdr]
    minor_header_bounds = [xs[off_flags + i * 2 + 1] for i in range(n_flags)]
    minor_header_bounds += [xs[tstart + 1], xs[tstart + 2]]

    for gx in major_header_bounds:
        ax.plot([gx, gx], [yh2, y_title], color=C_WHITE, lw=0.8, alpha=0.55, zorder=4)
    for gx in minor_header_bounds:
        ax.plot([gx, gx], [yh2, yh1], color=C_WHITE, lw=0.8, alpha=0.55, zorder=4)
    # Garis horizontal pemisah baris judul grup (HH1: P1A../TOTAL) dari baris
    # sub-header (HH2: ODP/%Visit/Visit ODP) — 2 tingkat header jadi jelas.
    ax.plot([xs[off_flags], right_edge_hdr], [yh1, yh1], color=C_WHITE, lw=0.8, alpha=0.55, zorder=4)

    # ── Baris data ────────────────────────────────────────────────────────────
    cur_y = yh2

    def cell_rect(x, y, w, h, bg, border=C_GRID):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=bg, edgecolor=border, linewidth=0.9, zorder=1))

    def pct_cell(ci, y, val_txt, color, grand_row):
        # persis pctCell() JS: grand row -> POLOS (background row merah tanpa
        # warna skala tambahan, cuma teks putih); non-grand -> sel diwarnai skala.
        # Rect tetap HARUS digambar utk grand row juga (row_border/row_bg) —
        # kalau di-skip, area itu jadi putih (tak ada fill apa pun di bawahnya)
        # dan teks putih di atas putih jadi tak kelihatan.
        cell_rect(xs[ci], y, col_w[ci], RH, C_RED if grand_row else color,
                  C_RED_BORDER if grand_row else C_GRID)
        ax.text(cx(ci), y + RH / 2, val_txt, ha="center", va="center", fontsize=FS_DATA,
                fontweight="bold" if grand_row else "normal", color=C_WHITE if grand_row else C_DARK, zorder=3)

    def draw_row(r, kind, flag_scales, tot_scale):
        nonlocal cur_y
        cur_y -= RH
        bold = kind in ("subtot", "grand")
        row_bg = C_RED if kind == "grand" else C_WHITE
        row_border = C_RED_BORDER if kind == "grand" else C_GRID
        text_color = C_WHITE if kind == "grand" else C_DARK

        if kind in ("subtot", "grand"):
            cell_rect(xs[0], cur_y, col_w[0] + col_w[1], RH, row_bg, row_border)
            ax.text(cx(0) + col_w[1] / 2, cur_y + RH / 2, r["wok"], ha="center", va="center",
                    fontsize=FS_MERGED, fontweight="bold", color=text_color, zorder=3)
        else:
            # persis CSS asli: "table.report td.lbl,td.wok{text-align:left}"
            # — HANYA baris data (bukan subtotal/grand, itu tetap center).
            cell_rect(xs[0], cur_y, col_w[0], RH, row_bg, row_border)
            cell_rect(xs[1], cur_y, col_w[1], RH, row_bg, row_border)
            ax.text(xs[0] + 0.12, cur_y + RH / 2, r["branch"], ha="left", va="center", fontsize=FS_BRANCH,
                    color=C_DARK, zorder=3)
            ax.text(xs[1] + 0.12, cur_y + RH / 2, r["wok"], ha="left", va="center", fontsize=FS_WOK,
                    fontweight="bold", color=C_DARK, zorder=3)

        for i, f in enumerate(FLAGS):
            cstart = off_flags + i * 2
            odp = r["cells"][f]["odp"]
            cell_rect(xs[cstart], cur_y, col_w[cstart], RH, row_bg, row_border)
            ax.text(cx(cstart), cur_y + RH / 2, _fmt_int(odp), ha="center", va="center",
                    fontsize=FS_DATA, fontweight="bold" if bold else "normal", color=text_color, zorder=3)
            pct = r["cells"][f]["pct"]
            color = C_WHITE if kind == "grand" else flag_scales[f](pct)
            pct_cell(cstart + 1, cur_y, _fmt_pct(pct), color, kind == "grand")

        tstart = off_flags + n_flags * 2
        cell_rect(xs[tstart], cur_y, col_w[tstart], RH, row_bg, row_border)
        cell_rect(xs[tstart + 1], cur_y, col_w[tstart + 1], RH, row_bg, row_border)
        ax.text(cx(tstart), cur_y + RH / 2, _fmt_int(r["total"]["odp"]), ha="center", va="center",
                fontsize=FS_DATA, fontweight="bold" if bold else "normal", color=text_color, zorder=3)
        ax.text(cx(tstart + 1), cur_y + RH / 2, _fmt_int(r["total"]["visit"]), ha="center", va="center",
                fontsize=FS_DATA, fontweight="bold" if bold else "normal", color=text_color, zorder=3)
        tot_color = C_WHITE if kind == "grand" else tot_scale(r["total"]["pct"])
        pct_cell(tstart + 2, cur_y, _fmt_pct(r["total"]["pct"]), tot_color, kind == "grand")

    def draw_spacer():
        nonlocal cur_y
        cur_y -= SPACER_H
        ax.add_patch(Rectangle((xs[0], cur_y), TW, SPACER_H, facecolor=C_SPACER_BG,
                                edgecolor="none", zorder=1))

    for r in detail:
        draw_row(r, "data", detail_scales, detail_tot_scale)
    draw_spacer()
    for r in subtotals:
        draw_row(r, "subtot", subtot_scales, subtot_tot_scale)
    draw_spacer()
    draw_row(grand, "grand", None, None)

    # ── Garis batas kolom DIPERTEGAS (di atas semua sel/border tipis per-cell
    # di atas) — batas antar ID|P1A|P1B|...|TOTAL digambar ulang lebih tebal
    # spanning header+body sekaligus, supaya blok2 utama kelihatan jelas
    # terpisah (bukan cuma mengandalkan border 1px tiap sel yang gampang
    # "hilang" krn anti-aliasing). Kolom TOTAL dapat porsi PALING tebal +
    # warna gelap solid (bukan C_GRID/C_NAVY_BORDER) sesuai permintaan.
    right_edge = xs[-1] + col_w[-1]
    group_bounds = [xs[0], xs[off_flags]] + [xs[off_flags + i * 2] for i in range(1, n_flags)]
    for gx in group_bounds:
        ax.plot([gx, gx], [cur_y, y_title], color=C_BOUND_GRAY, lw=1.6, zorder=6)
    # Batas kolom TOTAL — kiri & kanan sekaligus, warna SAMA dgn batas grup
    # lain (C_BOUND_GRAY), cuma sedikit lebih tebal biar tetap kebeda tapi
    # gak beda warna sendiri.
    for gx in (xs[tstart], right_edge):
        ax.plot([gx, gx], [cur_y, y_title], color=C_BOUND_GRAY, lw=2.2, zorder=7)
    # Garis horizontal bawah tabel (penutup baris JATENG DIY) juga dipertegas.
    ax.plot([xs[0], right_edge], [cur_y, cur_y], color=C_BOUND_GRAY, lw=1.6, zorder=6)

    dpi = min(190, int(9000 / (FW + FH)))
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0.10, facecolor=C_WHITE)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_caption(result: dict, title: str, date_label: str) -> str:
    br, wr = result["branch_rank"], result["wok_rank"]

    def line(row):
        return f"{row['wok']} ({_fmt_pct(row['total']['pct'])})" if row else "-"

    return (
        f"{title}\n{date_label}\n\n"
        f"BRANCH\n"
        f"🥇 Top Ach ODP Visit - {line(br['top'])}\n"
        f"🏳️ Bottom Ach ODP Visit - {line(br['bottom'])}\n\n"
        f"WOK\n"
        f"🥇 Top Ach ODP Visit - {line(wr['top'])}\n"
        f"🏳️ Bottom Ach ODP Visit - {line(wr['bottom'])}"
    )
