"""
renderer_agresif.py — Render 3 tabel report /agresif native (tanpa Excel):
  render_agresif_ps()  -> REPORT NEW SALES LOKASI AGRESIF
  render_agresif_re()  -> REPORT RE NEW KECAMATAN AGRESIF
  render_agresif_fmc() -> REPORT NEW SALES ALL FMC CITY

Satu "engine" tabel dipakai bersama ketiganya — lihat `_render_table()`. Tiap
kolom data dispesifikasikan sbg tuple (label, fmt_fn, kind, raw_field):
  label     : teks sub-header
  fmt_fn    : row -> string tampilan
  kind      : None | "mom" | "ach_bar" | "contr1_bar" | "contr_bar" | "gap_icon"
  raw_field : nama field di row dict berisi NILAI MENTAH (fraksi/ppt) dipakai
              utk mewarnai (fmt_fn hanya utk teks, kind+raw_field utk warna).

Warna MOM/ACH/CONTR/GAP CONTR dari agresif_colors.py — diekstrak LANGSUNG dari
conditionalFormatting master Excel, bukan tebakan. Ukuran font/kolom dari
renderer_caps_font.py (dipatok, kolom yang menyesuaikan, bukan font mengecil).
"""
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from renderer_caps_font import col_width, measure_w, FS_DATA, FS_LABEL, FS_HDR, FS_SUBHDR
import agresif_colors as C

C_BG = "white"
C_WHITE = "white"
C_DARK = "#1A1A1A"
C_SEP = "#BDC3C7"
C_HDR_ID = "#1F3864"
C_HDR_RED = "#C00000"
C_HDR_GREY = "#404040"
C_ROW_A = "white"
C_ROW_B = "#F4F6F7"
C_BRANCH_BG = "#D9D9D9"
C_JATENG_BG = "#E8D5F0"
C_SECTION_BG = "#BFBFBF"


def _num(v):
    return "-" if v is None else f"{int(round(v)):,}"


def _pct(v):
    return "-" if v is None else f"{v*100:.1f}%"


def _pct0(v):
    return "-" if v is None else f"{v*100:.0f}%"


def _ppt(v):
    return "-" if v is None else f"{v:+.2f}"


# key=(label, fmt_fn, kind, raw_field)
def _col(label, fmt_fn, kind=None, raw_field=None):
    return (label, fmt_fn, kind, raw_field)


def _ps_like_blocks(has_re_to_ps=True, has_mtd1=True):
    """Kolom LOW & MID HIGH block, dipakai report PS & FMC (sama2 PS-lens).

    Field mentah di row dict (dari calculator_agresif._ps_row/_derive_ps_metrics)
    pakai SUFFIX ("target_low","ps_mtd_low","re_mtd_low",...), sedangkan field
    turunan (%-metric) pakai PREFIX ("low_mom","low_ach",...) — dua pola beda,
    JANGAN disamakan formulanya.

    has_mtd1: report PS (Lokasi Agresif) TIDAK menampilkan kolom mentah
    "PS MTD-1" (cuma dipakai internal utk MoM/CONTR MTD-1), sedangkan report
    FMC menampilkannya — beda tampilan sesuai master masing2 sheet.
    """
    def block(suf):  # suf = "low" | "mid"
        # GAP CONTR: icon warna cuma dipasang di blok LOW (kind="gap_icon",
        # polaritas dibalik — lihat agresif_colors.gap_icon_color). Blok MID
        # HIGH sengaja polos tanpa warna (kind=None), permintaan user 06-Aug.
        gap_kind = "gap_icon" if suf == "low" else None
        cols = [
            _col("TARGET", lambda r, s=suf: _num(r.get(f"target_{s}"))),
        ]
        if has_re_to_ps:
            cols.append(_col("RE MTD", lambda r, s=suf: _num(r.get(f"re_mtd_{s}"))))
        if has_mtd1:
            cols.append(_col("PS MTD-1", lambda r, s=suf: _num(r.get(f"ps_mtd1_{s}"))))
        cols.append(_col("PS MTD", lambda r, s=suf: _num(r.get(f"ps_mtd_{s}"))))
        if has_re_to_ps:
            cols.append(_col("RE to PS", lambda r, s=suf: _pct0(r.get(f"{s}_re_to_ps"))))
        cols += [
            _col("MOM PS", lambda r, s=suf: _pct(r.get(f"{s}_mom")), "mom", f"{suf}_mom"),
            _col("ACH MTD", lambda r, s=suf: _pct(r.get(f"{s}_ach")), "ach_bar", f"{suf}_ach"),
            _col("CONTR\nMTD-1", lambda r, s=suf: _pct(r.get(f"{s}_contr_mtd1")), "contr1_bar", f"{suf}_contr_mtd1"),
            _col("CONTR\nMTD", lambda r, s=suf: _pct(r.get(f"{s}_contr_mtd")), "contr_bar", f"{suf}_contr_mtd"),
            _col("GAP CONTR\n(ppt)", lambda r, s=suf: _ppt(r.get(f"{s}_gap_contr")), gap_kind, f"{suf}_gap_contr"),
        ]
        return cols
    return block("low"), block("mid")


def _ps_total_block(has_re_to_ps=True, has_mtd1=True):
    cols = [_col("TARGET", lambda r: _num(r.get("target_total")))]
    if has_re_to_ps:
        cols.append(_col("RE MTD", lambda r: _num(r.get("re_mtd_total"))))
    if has_mtd1:
        cols.append(_col("PS MTD-1", lambda r: _num(r.get("ps_mtd1_total"))))
    cols.append(_col("PS MTD" if has_re_to_ps else "MTD", lambda r: _num(r.get("ps_mtd_total"))))
    if has_re_to_ps:
        cols.append(_col("RE to PS", lambda r: _pct0(r.get("total_re_to_ps"))))
    cols += [
        _col("MOM PS" if has_re_to_ps else "MOM", lambda r: _pct(r.get("total_mom")), "mom", "total_mom"),
        _col("ACH MTD", lambda r: _pct(r.get("total_ach")), "ach_bar", "total_ach"),
    ]
    return cols


def _re_blocks():
    """Field mentah row RE pakai SUFFIX ("target_low","mtd_low",...), field
    turunan pakai PREFIX ("low_mom","low_ach",...) — sama pola dgn PS."""
    def block(suf):
        # GAP CONTR: icon warna cuma di blok LOW (polaritas dibalik — lihat
        # agresif_colors.gap_icon_color), MID HIGH polos tanpa warna.
        gap_kind = "gap_icon" if suf == "low" else None
        return [
            _col("TARGET", lambda r, s=suf: _num(r.get(f"target_{s}"))),
            _col("MTD-1", lambda r, s=suf: _num(r.get(f"mtd1_{s}"))),
            _col("MTD", lambda r, s=suf: _num(r.get(f"mtd_{s}"))),
            _col("MOM", lambda r, s=suf: _pct(r.get(f"{s}_mom")), "mom", f"{suf}_mom"),
            _col("ACH MTD", lambda r, s=suf: _pct(r.get(f"{s}_ach")), "ach_bar", f"{suf}_ach"),
            _col("CONTR\nMTD-1", lambda r, s=suf: _pct(r.get(f"{s}_contr_mtd1")), "contr1_bar", f"{suf}_contr_mtd1"),
            _col("CONTR\nMTD", lambda r, s=suf: _pct(r.get(f"{s}_contr_mtd")), "contr_bar", f"{suf}_contr_mtd"),
            _col("GAP CONTR\n(ppt)", lambda r, s=suf: _ppt(r.get(f"{s}_gap_contr")), gap_kind, f"{suf}_gap_contr"),
        ]
    return block("low"), block("mid")


def _re_total_block():
    return [
        _col("TARGET", lambda r: _num(r.get("target_total"))),
        _col("MTD-1", lambda r: _num(r.get("mtd1_total"))),
        _col("MTD", lambda r: _num(r.get("mtd_total"))),
        _col("MOM", lambda r: _pct(r.get("total_mom")), "mom", "total_mom"),
        _col("ACH MTD", lambda r: _pct(r.get("total_ach")), "ach_bar", "total_ach"),
    ]


def _draw_colored_cell(ax, x0, y0, w, h, kind, raw_val, cur_y, mid_y):
    """Gambar overlay warna (data-bar / mom bg / gap icon) di belakang teks sel."""
    if raw_val is None or kind is None:
        return C_DARK
    if kind == "ach_bar":
        frac = max(0.0, min(1.0, float(raw_val)))
        ax.add_patch(plt.Rectangle((x0 + 0.02, cur_y + 0.05), max(0.012, (w - 0.04) * frac),
                                    h - 0.10, color=C.ACH_DATABAR, alpha=0.55, zorder=2))
        return C_DARK
    if kind in ("contr1_bar", "contr_bar"):
        frac = max(0.0, min(1.0, float(raw_val)))
        color = C.CONTR_MTD1_DATABAR if kind == "contr1_bar" else C.CONTR_MTD_DATABAR
        ax.add_patch(plt.Rectangle((x0 + 0.02, cur_y + 0.05), max(0.012, (w - 0.04) * frac),
                                    h - 0.10, color=color, alpha=0.55, zorder=2))
        return C_DARK
    if kind == "mom":
        bg, fg = C.mom_color(raw_val)
        if bg:
            ax.add_patch(plt.Rectangle((x0 + 0.015, cur_y + 0.04), w - 0.03, h - 0.08,
                                        color=bg, zorder=2))
            return fg
        return C_DARK
    if kind == "gap_icon":
        icon_c = C.gap_icon_color(raw_val)
        if icon_c:
            ax.add_patch(plt.Circle((x0 + 0.13, mid_y), 0.07, color=icon_c, zorder=2))
        return C_DARK
    return C_DARK


def _render_table(title, date_label, id_cols, id_labels, low_cols, mid_cols, total_cols,
                   rows_sections, branch_rows, jateng_row, id_minw=None,
                   helper_label=None, helper_cols=None, cutoff=None,
                   low_label="NEW SALES  LOW PACKAGE",
                   mid_label="NEW SALES MID HIGH PACKAGE",
                   total_label="TOTAL SALES"):
    display = []
    for label, rs in rows_sections:
        if label:
            display.append(("section", label))
        for r in rs:
            display.append(("data", r))
    if branch_rows:
        display.append(("blank", None))
        for r in branch_rows:
            display.append(("branch", r))
    display.append(("jateng", jateng_row))

    n_id = len(id_cols)

    def id_samples(i):
        out = [id_labels[i]]
        for kind, r in display:
            if kind == "data":
                out.append(r.get(id_cols[i], "") or "")
            elif kind in ("branch", "jateng") and i == 0:
                out.append(r.get("branch", "") or "")
        return out

    # pad lebih longgar dari kolom angka (0.30 -> 0.60) — kolom ID
    # (FOKUS DISTRIC/BRANCH/CITY/KECAMATAN) isinya teks nama wilayah yg
    # mepet-mepet kalau cuma dikasih jarak standar, apalagi sekarang ada
    # garis grid persis di tepi kolom (lihat _render_table grid section).
    id_widths = [col_width(id_samples(i), FS_LABEL,
                            minw=(id_minw[i] if id_minw else 1.3), pad=0.60)
                 for i in range(n_id)]

    def block_widths(cols):
        widths = []
        for label, fmt, kind, raw in cols:
            samples = [label.replace("\n", " ")]
            for kd, r in display:
                if kd in ("data", "branch", "jateng"):
                    try:
                        samples.append(fmt(r))
                    except Exception:
                        samples.append("-")
            widths.append(col_width(samples, FS_DATA, minw=0.80, pad=0.20))
        return widths

    LBL_LOW = low_label
    LBL_MID = mid_label
    LBL_TOT = total_label

    def _ensure_group_width(widths, label, fs=FS_HDR, pad=0.30):
        """Judul grup (mis. "One Dynamic Promo 20Mbps 30GB") sel-nya di-merge
        horizontal di atas sub-kolomnya — kalau teks judul lebih lebar dari
        jumlah lebar sub-kolom (kejadian nyata di grup helper yg cuma 2
        sub-kolom sempit: "JML RE MTD"/"JML PS MTD"), dia nembus/overlap ke
        kolom grup sebelah. Lebarkan sub-kolom grup ybs (proporsional) supaya
        total >= lebar judul, biar mergernya bener2 nutup teksnya sendiri."""
        if not widths or not label:
            return widths
        need = measure_w(label, fs, bold=True) + pad
        have = sum(widths)
        if need > have and have > 0:
            scale = need / have
            widths = [w * scale for w in widths]
        return widths

    helper_cols = helper_cols or []
    helper_w = block_widths(helper_cols) if helper_cols else []
    low_w = block_widths(low_cols)
    mid_w = block_widths(mid_cols)
    tot_w = block_widths(total_cols)

    helper_w = _ensure_group_width(helper_w, helper_label)
    low_w = _ensure_group_width(low_w, LBL_LOW)
    mid_w = _ensure_group_width(mid_w, LBL_MID)
    tot_w = _ensure_group_width(tot_w, LBL_TOT)

    col_widths = id_widths + helper_w + low_w + mid_w + tot_w

    off_helper = n_id
    off_low = off_helper + len(helper_cols)
    off_mid = off_low + len(low_cols)
    off_tot = off_mid + len(mid_cols)

    TW = sum(col_widths)
    RH = 0.44
    HH_TITLE = 0.60
    HH1 = 0.40
    HH2 = 0.58
    MG = 0.22

    FH = HH_TITLE + HH1 + HH2 + len(display) * RH + 0.5 * sum(1 for k, _ in display if k == "blank") + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW)
    ax.set_ylim(0, FH)
    ax.axis("off")
    # WAJIB: tanpa ini axes default cuma isi ~78% lebar figure (matplotlib
    # nyisain margin buat tick label yg kita gak pakai, axis("off") doang
    # gak ngilangin marginnya) — akibatnya 1 data-unit != 1 inci padahal
    # SEMUA perhitungan lebar kolom (col_width/_ensure_group_width) di file
    # ini asumsi 1:1. Ini penyebab asli judul grup "One Dynamic Promo
    # 20Mbps 30GB" ngerembes ke kolom sebelah walau lebar kolomnya udah
    # dihitung "cukup" — box-nya kekompres jadi lebih sempit dari yang
    # dikira. Lihat memory renderer-text-overlap-fix, sama akar masalah
    # dgn renderer_* lain yg pernah kena bug ini.
    ax.set_position([0, 0, 1, 1])
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + col_widths[i] / 2

    ax.text(MG, FH - 0.06, title, ha="left", va="top",
            fontsize=15, fontweight="bold", color=C_DARK)
    ax.text(MG, FH - 0.32, date_label, ha="left", va="top",
            fontsize=12.5, fontweight="bold", color=C_DARK)

    # Shade sub-header (baris ke-2, per sub-kolom) sedikit lebih GELAP dari
    # judul grup (baris ke-1, sel di-merge horizontal) — supaya 2 baris header
    # kelihatan jelas beda tingkat walau warnanya senada (pola sama spt
    # renderer_channel.py/renderer_kategori_paket.py).
    _HDR_DARKER = {
        C_HDR_ID: "#13223f",
        C_HDR_RED: "#8f0000",
        C_HDR_GREY: "#262626",
    }

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=FS_HDR):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3,
                multialignment="center", linespacing=1.0)

    y_top = FH - MG - HH_TITLE
    yh1 = y_top - HH1
    yh2 = yh1 - HH2

    for i, lbl in enumerate(id_labels):
        hcell(xs[i], yh2, id_widths[i], HH1 + HH2, lbl, C_HDR_ID, fs=FS_SUBHDR)

    groups = []
    if helper_cols:
        groups.append((helper_label or "", off_helper, helper_cols, helper_w, C_HDR_ID))
    groups += [(LBL_LOW, off_low, low_cols, low_w, C_HDR_RED),
               (LBL_MID, off_mid, mid_cols, mid_w, C_HDR_RED),
               (LBL_TOT, off_tot, total_cols, tot_w, C_HDR_GREY)]
    for label, start, cols, widths, bg in groups:
        if not cols:
            continue
        hcell(xs[start], yh1, sum(widths), HH1, label, bg, fs=FS_HDR)
        cur = start
        sub_bg = _HDR_DARKER.get(bg, bg)
        for (clabel, fmt, kind, raw), w in zip(cols, widths):
            hcell(xs[cur], yh2, w, HH2, clabel, sub_bg, fs=FS_SUBHDR)
            cur += 1

    cur_y = yh2
    zebra = 0
    for kind, item in display:
        if kind == "blank":
            cur_y -= RH * 0.5
            continue
        cur_y -= RH
        # Garis horizontal tipis di ATAS tiap baris (batas dgn baris sebelumnya)
        # — bikin tabel kelihatan "proper"/rapi spt grid spreadsheet, bukan
        # cuma blok warna zebra tanpa batas jelas.
        ax.plot([xs[0], xs[0] + TW], [cur_y + RH, cur_y + RH], color=C_SEP,
                 lw=0.35, zorder=5)
        if kind == "section":
            ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=C_SECTION_BG, zorder=1))
            ax.text(xs[0] + 0.1, cur_y + RH / 2, item, ha="left", va="center",
                    fontsize=FS_LABEL, fontweight="bold", color=C_DARK, zorder=3)
            continue

        row = item
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

        for i, f in enumerate(id_cols):
            if kind == "data":
                val = row.get(f, "")
            else:
                # baris subtotal branch/JATENG-DIY: nama-nya tampil di kolom
                # "branch", kolom id lain (fokus/city/kec) dikosongkan.
                val = row.get("branch", "") if f == "branch" else ""
            ax.text(cx(i), mid_y, str(val) if val else "", ha="center", va="center",
                    fontsize=FS_LABEL, fontweight="bold" if bold_row else "normal",
                    color=C_DARK, zorder=3)

        ci = n_id
        for cols, widths in ((helper_cols, helper_w), (low_cols, low_w), (mid_cols, mid_w), (total_cols, tot_w)):
            for (label, fmt, kind2, raw_field), w in zip(cols, widths):
                try:
                    txt = fmt(row)
                except Exception:
                    txt = "-"
                raw_val = row.get(raw_field) if raw_field else None
                fg = _draw_colored_cell(ax, xs[ci], 0, w, RH, kind2, raw_val, cur_y, mid_y)
                ax.text(cx(ci), mid_y, txt, ha="center", va="center",
                        fontsize=FS_DATA, fontweight="bold" if bold_row else "normal",
                        color=fg, zorder=3)
                ci += 1

    # ── Grid & border tabel (bikin tampilan "proper" spt spreadsheet) ───────
    # Garis penutup di bawah baris terakhir.
    ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.35, zorder=5)

    right_edge = xs[-1] + col_widths[-1]

    # "Batas MERGE" — garis di titik ini WAJIB tembus penuh dari body sampai
    # atas judul grup (y_top): batas antar kolom ID (sel ID sendiri-sendiri,
    # tinggi penuh, tidak di-merge horizontal) + titik mulai tiap grup
    # (ID|helper|LOW|MID HIGH|TOTAL). SELAIN titik ini (batas antar sub-kolom
    # DALAM satu grup, mis. "TARGET"|"RE MTD") garis HARUS berhenti di yh1
    # (bawah baris judul grup) — kalau diteruskan sampai y_top dia bakal
    # "ngecros" motong tulisan judul grup yang sel-nya cuma SATU (merged).
    merge_bounds = sorted(set(
        [xs[i] for i in range(n_id + 1)] +
        [xs[off_low], xs[off_mid], xs[off_tot], right_edge]
    ))

    def _is_merge_bound(x):
        return any(abs(x - mx) < 1e-6 for mx in merge_bounds)

    # Garis tipis: sub-kolom (badan tabel penuh + baris sub-header saja,
    # BERHENTI di yh1 supaya tidak menembus judul grup yang di-merge).
    for x in list(xs[1:]) + [right_edge]:
        if _is_merge_bound(x):
            continue
        ax.plot([x, x], [cur_y, yh1], color=C_SEP, lw=0.3, zorder=5)

    # Garis di titik merge: tinggi PENUH (badan + kedua baris header).
    for x in merge_bounds:
        ax.plot([x, x], [cur_y, y_top], color=C_SEP, lw=0.4, zorder=5)

    # Garis LEBIH TEBAL khusus di batas antar grup UTAMA (ID | helper | LOW |
    # MID HIGH | TOTAL) — supaya blok2 kelihatan jelas terpisah, bukan cuma
    # beda warna header doang.
    group_bounds = [xs[off_helper]] if helper_cols else []
    group_bounds += [xs[off_low], xs[off_mid], xs[off_tot], right_edge]
    for gx in sorted(set(group_bounds)):
        ax.plot([gx, gx], [cur_y, y_top], color=C_HDR_GREY, lw=1.0, zorder=6)

    # Garis horizontal pemisah antara baris judul grup (HH1, merged) dan
    # baris sub-header (HH2) — HANYA di area yang benar2 punya 2 baris
    # (helper/LOW/MID HIGH/TOTAL). Kolom ID (FOKUS DISTRIC/BRANCH/CITY/
    # KECAMATAN) satu sel utuh tinggi penuh (merge atas-bawah) — kalau garis
    # ini ditarik dari xs[0], dia nembus TENGAH sel ID itu juga.
    ax.plot([xs[off_helper], right_edge], [yh1, yh1], color=C_WHITE, lw=0.8, zorder=6)

    # Border luar tabel (header + body sekaligus).
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, y_top - cur_y,
        fill=False, edgecolor=C_DARK, lw=1.1, zorder=7
    ))

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


# ── 3 fungsi publik ──────────────────────────────────────────────────────────

def render_agresif_ps(result: dict, cutoff: str = None) -> BytesIO:
    low_cols, mid_cols = _ps_like_blocks(has_re_to_ps=True, has_mtd1=False)
    total_cols = _ps_total_block(has_re_to_ps=True, has_mtd1=False)
    date_label = result["cutoff"].strftime("%d-%b-%Y")
    rows_sections = [(None, result["rows"])]
    helper_cols = [
        _col("JML RE MTD", lambda r: _num(r.get("re_mtd_helper"))),
        _col("JML PS MTD", lambda r: _num(r.get("ps_mtd_helper"))),
    ]
    return _render_table(
        "REPORT NEW SALES LOKASI AGRESIF", date_label,
        id_cols=["fokus", "branch", "city", "kec"],
        id_labels=["FOKUS DISTRIC", "BRANCH", "CITY", "KECAMATAN"],
        low_cols=low_cols, mid_cols=mid_cols, total_cols=total_cols,
        rows_sections=rows_sections, branch_rows=result["branch_rows"],
        jateng_row=result["jateng_row"], id_minw=[1.7, 1.5, 1.5, 1.7],
        helper_label="EZnet Promo 20 Mbps", helper_cols=helper_cols, cutoff=cutoff)


def render_agresif_re(result: dict, cutoff: str = None) -> BytesIO:
    low_cols, mid_cols = _re_blocks()
    total_cols = _re_total_block()
    date_label = result["cutoff"].strftime("%d-%b-%Y")
    rows_sections = [(None, result["rows"])]
    return _render_table(
        "REPORT RE NEW KECAMATAN AGRESIF", date_label,
        id_cols=["fokus", "branch", "city", "kec"],
        id_labels=["FOKUS DISTRIC", "BRANCH", "CITY", "KECAMATAN"],
        low_cols=low_cols, mid_cols=mid_cols, total_cols=total_cols,
        rows_sections=rows_sections, branch_rows=result["branch_rows"],
        jateng_row=result["jateng_row"], id_minw=[1.7, 1.5, 1.5, 1.7], cutoff=cutoff,
        low_label="RE LOW PACKAGE", mid_label="RE MID-HIGH PACKAGE",
        total_label="TOTAL RE")


def render_agresif_fmc(result: dict, cutoff: str = None) -> BytesIO:
    low_cols, mid_cols = _ps_like_blocks(has_re_to_ps=True, has_mtd1=True)
    total_cols = _ps_total_block(has_re_to_ps=True, has_mtd1=True)
    date_label = result["cutoff"].strftime("%d-%b-%Y")
    rows_sections = [("NEW FMC CITY", result["new_rows"]),
                      ("OLD FMC CITY", result["old_rows"])]
    helper_cols = [
        _col("JML RE MTD", lambda r: _num(r.get("re_mtd_helper"))),
        _col("JML PS MTD", lambda r: _num(r.get("ps_mtd_helper"))),
    ]
    return _render_table(
        "REPORT NEW SALES ALL FMC CITY", date_label,
        id_cols=["fokus", "branch", "city"],
        id_labels=["FOKUS DISTRIC", "BRANCH", "CITY"],
        low_cols=low_cols, mid_cols=mid_cols, total_cols=total_cols,
        rows_sections=rows_sections, branch_rows=result["branch_rows"],
        jateng_row=result["jateng_row"], id_minw=[1.7, 1.5, 2.0],
        helper_label="One Dynamic Promo 20Mbps 30GB", helper_cols=helper_cols, cutoff=cutoff)
