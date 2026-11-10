"""
renderer_dod.py — Render tabel PS (angka) & %DoD (Day over Day) per BRANCH/WOK.

2 report terpisah, layout sama, tone warna & font mengikuti gaya
renderer_daily_performance.py:
  - render_dod_count() : angka PS harian (report 1)
  - render_dod_pct()   : %DoD harian, hijau/merah (report 2)

Kolom tanggal hanya dirender 1 s/d tgl_closing.day (data["n_days"]) supaya
tabel tidak terlalu panjang. Ukuran baris/kolom dibuat padat, dan garis grid
vertikal tidak menembus cell yang di-merge (judul & bar PRODUCT).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO

C_BG        = "white"
C_HEADER_SUB= "#2C3E50"   # header kolom BRANCH / WOK & bar "PRODUCT"
C_HEADER_PS = "#1E6B31"   # accent report angka (hijau, mengikuti PS di daily performance)
C_HEADER_RE = "#8B2500"   # accent report %DoD (maroon, mengikuti RE di daily performance)
C_REGION_BG = "#2C3E50"   # baris grand total JATENG-DIY (oranye)
C_BRANCH_BG = "#D5D8DC"   # baris ringkasan BRANCH (abu terang)
C_WOK_ODD   = "white"
C_WOK_EVEN  = "#F4F6F7"
C_SEP       = "#BDC3C7"
C_DARK      = "#1A1A1A"
C_MID       = "#2C3E50"
C_WHITE     = "white"
C_POS       = "#1E8449"
C_NEG       = "#C0392B"
C_BORDER    = "#7F8C8D"

# ── Ukuran padat ─────────────────────────────────────────────────────────────
CW_BR  = 1.00
CW_WOK = 2.30
CW_DAY = 0.40
CW_DOD = 0.60   # kolom tambahan %DoD 2 hari terakhir (khusus report PS)
RH     = 0.20
HH1    = 0.24
HH2    = 0.18
SEP    = 0.09
PH     = 0.16
MG     = 0.12
LBL_PAD= 0.04
TH     = 0.46   # tinggi blok judul + subjudul di atas tabel


def _fmt_count(v):
    if v is None:
        return "-"
    return f"{int(v):,}"


def _fmt_pct(v):
    if v is None:
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def _render(data: dict, value_field: str, fmt_fn, header_accent: str,
            header_title: str, use_pos_neg: bool, title: str, subtitle: str,
            extra_dod_col: bool = False, cutoff: str = None,
            bar_chart: bool = False, sub_header: str = "WOK") -> BytesIO:
    n_days        = data["n_days"]
    hari_efektif  = data.get("hari_efektif", n_days)   # acuan kolom %DoD ringkas
    woks          = data["woks"]
    branches      = data["branches"]
    total         = data["total"]
    products      = data.get("products", [])
    product_total = data.get("product_total")

    col_widths = [CW_BR, CW_WOK] + [CW_DAY] * n_days
    if extra_dod_col:
        col_widths.append(CW_DOD)
    TW = sum(col_widths)

    # Tinggi area bar chart (hanya report 1). Batangnya sengaja diletakkan
    # tepat di atas kolom tanggal supaya sejajar dengan angka di tabel.
    gambar_bar = bool(bar_chart and products)
    # Dinaikkan dari 2.1 -> 3.0 supaya tiap segmen cukup tinggi untuk memuat
    # angka + persentase kontribusi di dalamnya.
    CH = 3.6 if gambar_bar else 0.0

    n_rows_total = len(woks) + len(branches) + 1  # +1 grand total
    n_prod_rows  = len(products) + (1 if products and product_total is not None else 0)
    n_prod_extra = (SEP + PH + n_prod_rows * RH) if products else 0.0
    FH = TH + CH + HH1 + HH2 + n_rows_total * RH + SEP + n_prod_extra + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    # Axes dipaksa memenuhi seluruh kanvas figure supaya 1 unit data == 1 inci
    # persis — tanpa ini, margin default matplotlib bikin data unit sedikit
    # lebih kecil dari inci sebenarnya, sehingga perhitungan lebar teks
    # (get_window_extent, dalam inci layar) jadi meleset terhadap lebar kolom
    # (dalam unit data) dan teks label panjang jadi nabrak kolom sebelah.
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)

    def cx(i):
        return xs[i] + col_widths[i] / 2

    _renderer = fig.canvas.get_renderer()

    def _text_width_in(txt, fontsize, bold=True):
        # Lebar teks aktual (get_window_extent), bukan estimasi rumus —
        # akurat untuk label WOK gabungan yang panjang (mis. "WONOSOBO
        # BANJARNEGARA") supaya tidak mepet/nabrak kolom di sebelahnya.
        t = ax.text(0, 0, txt, fontsize=fontsize,
                    fontweight="bold" if bold else "normal")
        w_in = t.get_window_extent(renderer=_renderer).width / fig.dpi
        t.remove()
        return w_in

    def _autofs(txt, w, fs0, fs_min=5.0, bold=True):
        f2 = fs0
        while f2 > fs_min and _text_width_in(txt, f2, bold=bold) > w - 0.15:
            f2 -= 0.2
        return f2

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=9, bold=True):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        f2 = _autofs(txt, w, fs)
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=f2, fontweight="bold" if bold else "normal",
                color=fg, zorder=3)

    def hcell_fit(x, y, w, h, candidates, bg, fg=C_WHITE, fs=9, fs_min=5.0, bold=True):
        """Sama seperti hcell, tapi menerima beberapa kandidat teks (dari paling
        lengkap ke paling singkat) & memilih yang pertama muat pada lebar `w`
        tanpa memaksa font sampai batas minimum. Dipakai untuk header judul yang
        gabung kolom tanggal — supaya saat n_days kecil (mis. tgl 1, cuma 1
        kolom) teksnya tidak tumpang tindih ke kolom sebelah, tapi otomatis
        jatuh ke label singkat (mis. "PS" / "% DoD" tanpa nama bulan)."""
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        chosen_txt, chosen_fs = candidates[-1], fs_min
        for txt in candidates:
            f2 = _autofs(txt, w, fs, fs_min=fs_min)
            if len(txt) * 0.107 * f2 / 10 <= w - 0.15:
                chosen_txt, chosen_fs = txt, f2
                break
        ax.text(x + w / 2, y + h / 2, chosen_txt, ha="center", va="center",
                fontsize=chosen_fs, fontweight="bold" if bold else "normal",
                color=fg, zorder=3)

    # ── Judul & subjudul ─────────────────────────────────────────────────────
    ax.text(MG, FH - MG, title, ha="left", va="top",
            fontsize=14, fontweight="bold", color=C_MID)
    ax.text(MG, FH - MG - 0.24, subtitle, ha="left", va="top",
            fontsize=9.5, color="#7F8C8D")

    # ── Bar chart stacked per tanggal (report 1) ─────────────────────────────
    # Segmen = kategori produk (IH REGULER / EZNET / TSEL ONE), sejajar tepat
    # di atas kolom tanggal masing-masing. Keterangan (legend) di kiri, di area
    # kolom BRANCH/WOK yang kosong.
    if gambar_bar:
        y_bar_bawah = FH - MG - TH - CH + 0.30   # sisakan ruang label total di atas
        tinggi_maks = CH - 0.55

        totals = []
        for d in range(1, n_days + 1):
            totals.append(sum(int(p["count_daily"].get(d) or 0) for p in products))
        skala_maks = max(totals) if any(totals) else 1

        warna_produk = {
            "IH REGULER": "#C0224E",   # merah IndiHome
            "EZNET":      "#1F6E8C",   # biru EZNet
            "TSEL ONE":   "#BDC3C7",   # abu Tsel One
        }
        # Urutan tumpukan dari bawah: EZNET, TSEL ONE, IH REGULER (ikut ilustrasi)
        urutan_stack = ["EZNET", "TSEL ONE", "IH REGULER"]
        produk_map   = {p["name"]: p for p in products}

        # Teks di dalam segmen: putih di segmen gelap, gelap di segmen abu terang
        warna_teks = {"IH REGULER": C_WHITE, "EZNET": C_WHITE, "TSEL ONE": C_DARK}
        FS_NUM     = 5.6   # angka utama di dalam segmen
        FS_PCT     = 4.7   # persentase kontribusi di bawahnya
        # Ambang tinggi segmen (inci) supaya teksnya tidak tabrakan/kepotong
        MIN_2BARIS = 0.205   # cukup untuk angka + persentase
        MIN_1BARIS = 0.110   # cukup untuk angka saja

        # Batang dilebarkan hampir selebar kolomnya (0.78 -> 0.94) supaya angka
        # di dalamnya muat dengan font lebih besar & terbaca jelas.
        lebar_bar = CW_DAY * 0.94
        for d in range(1, n_days + 1):
            ci = 1 + d
            total_hari = totals[d - 1]
            if total_hari <= 0:
                continue
            y_jalan = y_bar_bawah
            for nama_p in urutan_stack:
                p = produk_map.get(nama_p)
                if p is None:
                    continue
                nilai = int(p["count_daily"].get(d) or 0)
                if nilai <= 0:
                    continue
                tinggi = tinggi_maks * (nilai / skala_maks)
                ax.add_patch(plt.Rectangle(
                    (cx(ci) - lebar_bar / 2, y_jalan), lebar_bar, tinggi,
                    color=warna_produk.get(nama_p, "#95A5A6"), zorder=3))

                # Angka & kontribusi (%) di dalam segmen — hanya kalau muat,
                # segmen tipis dilewati supaya tidak tumpang tindih.
                fg  = warna_teks.get(nama_p, C_DARK)
                mid = y_jalan + tinggi / 2
                pct = nilai / total_hari * 100
                if tinggi >= MIN_2BARIS:
                    ax.text(cx(ci), mid + 0.042, f"{nilai:,}".replace(",", "."),
                            ha="center", va="center", fontsize=FS_NUM,
                            fontweight="bold", color=fg, zorder=4, clip_on=False)
                    ax.text(cx(ci), mid - 0.050, f"({pct:.1f}%)",
                            ha="center", va="center", fontsize=FS_PCT,
                            fontweight="bold", color=fg, zorder=4, clip_on=False)
                elif tinggi >= MIN_1BARIS:
                    ax.text(cx(ci), mid, f"{nilai:,}".replace(",", "."),
                            ha="center", va="center", fontsize=FS_NUM,
                            fontweight="bold", color=fg, zorder=4, clip_on=False)

                y_jalan += tinggi
            # Total di atas batang
            ax.text(cx(ci), y_jalan + 0.045, f"{total_hari:,}".replace(",", "."),
                    ha="center", va="bottom", fontsize=4.8, fontweight="bold",
                    color=C_MID, zorder=4, clip_on=False)

        # Legend di kiri (area kolom BRANCH/WOK)
        y_leg = y_bar_bawah + tinggi_maks * 0.72
        for nama_p in ["IH REGULER", "TSEL ONE", "EZNET"]:
            ax.add_patch(plt.Rectangle((xs[0] + 0.10, y_leg), 0.22, 0.11,
                                       color=warna_produk.get(nama_p, "#95A5A6"), zorder=3))
            ax.text(xs[0] + 0.40, y_leg + 0.055, nama_p, ha="left", va="center",
                    fontsize=6.5, color=C_MID, zorder=3)
            y_leg -= 0.19
        ax.text(xs[0] + 0.10, y_bar_bawah - 0.16, "PS harian per kategori produk",
                ha="left", va="center", fontsize=6, color="#7F8C8D", style="italic", zorder=3)
        # Garis dasar batang
        ax.plot([xs[2], xs[2] + CW_DAY * n_days], [y_bar_bawah, y_bar_bawah],
                color=C_BORDER, lw=0.6, zorder=4)

    y_top = FH - MG - TH - CH
    yh1   = y_top - HH1
    yh2   = yh1 - HH2

    # ── Header BRANCH / WOK (gabung 2 baris) ────────────────────────────────
    hcell(xs[0], yh2, CW_BR,  HH1 + HH2, "BRANCH",   C_HEADER_SUB, fs=8)
    hcell(xs[1], yh2, CW_WOK, HH1 + HH2, sub_header, C_HEADER_SUB, fs=8)

    # ── Header judul (gabung kolom tanggal saja, tidak termasuk kolom DoD) ───
    dod_w = CW_DOD if extra_dod_col else 0.0
    hcell_fit(xs[2], yh1, TW - CW_BR - CW_WOK - dod_w, HH1,
              [f"{header_title} {data['bulan_label']}", header_title],
              header_accent, fs=9)

    # ── Header tanggal 1..n_days ─────────────────────────────────────────────
    for d in range(1, n_days + 1):
        ci = 1 + d
        hcell(xs[ci], yh2, CW_DAY, HH2, str(d), header_accent, fs=6)

    # ── Header kolom DoD tambahan (2 hari terakhir), full-height seperti BRANCH/WOK ──
    if extra_dod_col:
        ci_dod = 2 + n_days
        dod_label = f"DoD\n{hari_efektif}/{hari_efektif-1}" if hari_efektif >= 2 else "DoD"
        hcell(xs[ci_dod], yh2, CW_DOD, HH1 + HH2, dod_label, C_HEADER_RE, fs=7)

    def draw_row(cur_y, label_branch, label_wok, daily, bg, fg_label, fs_label, bold_label,
                 value_color_override=None, dod_extra=None):
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid_y = cur_y + RH / 2

        if label_branch is not None:
            f2 = _autofs(label_branch, CW_BR, fs_label)
            ax.text(xs[0] + LBL_PAD, mid_y, label_branch, ha="left", va="center",
                    fontsize=f2, fontweight="bold" if bold_label else "normal",
                    color=fg_label, zorder=3, clip_on=True)
        if label_wok is not None:
            f2 = _autofs(label_wok, CW_WOK, fs_label)
            ax.text(xs[1] + LBL_PAD, mid_y, label_wok, ha="left", va="center",
                    fontsize=f2, fontweight="bold" if bold_label else "normal",
                    color=fg_label, zorder=3, clip_on=True)

        for d in range(1, n_days + 1):
            ci = 1 + d
            v  = daily.get(d)
            txt = fmt_fn(v)
            if value_color_override is not None:
                color = value_color_override
            elif use_pos_neg:
                color = C_DARK if v is None else (C_POS if v >= 0 else C_NEG)
            else:
                color = C_DARK
            f2 = _autofs(txt, CW_DAY, 6.0, fs_min=3.0)
            ax.text(cx(ci), mid_y, txt, ha="center", va="center",
                    fontsize=f2, fontweight="bold", color=color, zorder=3, clip_on=True)

        if extra_dod_col:
            ci_dod = 2 + n_days
            txt_d  = _fmt_pct(dod_extra)
            if value_color_override is not None:
                color_d = value_color_override
            else:
                color_d = C_DARK if dod_extra is None else (C_POS if dod_extra >= 0 else C_NEG)
            f2 = _autofs(txt_d, CW_DOD, 6.0, fs_min=3.0)
            ax.text(cx(ci_dod), mid_y, txt_d, ha="center", va="center",
                    fontsize=f2, fontweight="bold", color=color_d, zorder=3, clip_on=True)

        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.3, zorder=5)

    # ── Baris WOK (zebra per grup branch) ───────────────────────────────────
    cur_y = yh2
    prev_branch = None
    zebra = 0
    for w in woks:
        cur_y -= RH
        if w["branch"] != prev_branch:
            zebra += 1
            prev_branch = w["branch"]
        bg = C_WOK_ODD if zebra % 2 == 1 else C_WOK_EVEN
        draw_row(cur_y, w["branch"], w["name"], w[value_field], bg,
                 C_DARK, 6.5, False, dod_extra=w["daily"].get(hari_efektif))

    # ── Bar pemisah ────────────────────────────────────────────────────────
    cur_y -= SEP
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, SEP, color=C_SEP, zorder=1))

    # ── Baris ringkasan BRANCH ───────────────────────────────────────────
    for b in branches:
        cur_y -= RH
        draw_row(cur_y, b["name"], None, b[value_field], C_BRANCH_BG, C_DARK, 6.8, True,
                  dod_extra=b["daily"].get(hari_efektif))

    # ── Baris grand total JATENG-DIY ─────────────────────────────────────
    cur_y -= RH
    draw_row(cur_y, total["name"], None, total[value_field], C_REGION_BG,
              C_WHITE, 7.2, True, value_color_override=C_WHITE,
              dod_extra=total["daily"].get(hari_efektif))

    # ── Blok breakdown PRODUK (all territory) ────────────────────────────
    product_bar_top = product_bar_bottom = None
    if products:
        cur_y -= SEP
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, SEP, color=C_SEP, zorder=1))

        cur_y -= PH
        product_bar_top    = cur_y + PH
        product_bar_bottom = cur_y
        hcell(xs[0], cur_y, TW, PH, "PRODUCT", C_HEADER_SUB, fs=8)

        for i, p in enumerate(products):
            cur_y -= RH
            bg = C_WOK_ODD if i % 2 == 0 else C_WOK_EVEN
            draw_row(cur_y, p["name"], None, p[value_field], bg, C_DARK, 6.8, True,
                      dod_extra=p["daily"].get(hari_efektif))

        if product_total is not None:
            cur_y -= RH
            draw_row(cur_y, product_total["name"], None, product_total[value_field],
                      C_REGION_BG, C_WHITE, 7.2, True, value_color_override=C_WHITE,
                      dod_extra=product_total["daily"].get(hari_efektif))

    # ── Border luar & grid vertikal ──────────────────────────────────────
    # Grid tidak menembus cell yang di-merge (judul "% DoD .../PS ..." &
    # bar "PRODUCT") — hanya digambar di area kolom tanggal per-baris data.
    ax.add_patch(plt.Rectangle(
        (xs[0], cur_y), TW, y_top - cur_y,
        fill=False, edgecolor=C_BORDER, lw=0.8, zorder=7
    ))

    def vline(x, y0, y1):
        ax.plot([x, x], [y0, y1], color=C_SEP, lw=0.2, zorder=5)

    # batas BRANCH|WOK, WOK|tanggal-pertama, & tanggal-terakhir|DoD (jika ada): garis penuh
    full_xs = list(xs[:3])
    if extra_dod_col:
        full_xs.append(xs[2 + n_days])
    for x in full_xs:
        vline(x, cur_y, y_top)

    # batas antar kolom tanggal (interior): mulai dari bawah judul merge (yh1), skip bar PRODUCT
    interior_day_xs = xs[3:2 + n_days]
    tail_xs = [] if extra_dod_col else [xs[-1] + col_widths[-1]]
    day_xs = interior_day_xs + tail_xs
    for x in day_xs:
        if product_bar_top is not None:
            vline(x, product_bar_top, yh1)
            vline(x, cur_y, product_bar_bottom)
        else:
            vline(x, cur_y, yh1)

    footer = "Sumber: indihome_ordering_detail"
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y - 0.05, footer,
            fontsize=5.5, color="#95A5A6", va="top", style="italic")

    # tight_layout() TIDAK dipakai: axes sudah presisi disesuaikan dengan FW/FH
    # (xlim/ylim = ukuran figure dalam inci). tight_layout() bisa mengecilkan
    # area axes secara tidak proporsional saat figure sangat sempit (mis. n_days=1,
    # kolom tanggal cuma 1) sehingga tabel jadi gepeng & teks tumpang tindih.
    # bbox_inches="tight" di savefig() sudah cukup untuk memangkas margin kosong.
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(180, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_dod_count(data: dict, cutoff: str = None) -> BytesIO:
    """Report 1 — angka PS harian per BRANCH/WOK + kolom %DoD 2 hari terakhir."""
    title    = "Daily PS by Teritori & Kategori Produk"
    subtitle = f"Update {data['tgl_closing'].strftime('%d-%m-%Y')}"
    return _render(data, "count_daily", _fmt_count, C_HEADER_PS, "PS",
                   use_pos_neg=False, title=title, subtitle=subtitle,
                   extra_dod_col=True, cutoff=cutoff, bar_chart=True)


def render_dod_pct(data: dict, cutoff: str = None) -> BytesIO:
    """Report 2 — %DoD (Day over Day) PS per BRANCH/WOK."""
    title    = "Daily DoD by Teritori & Kategori Produk"
    subtitle = f"Update {data['tgl_closing'].strftime('%d-%m-%Y')}"
    return _render(data, "daily", _fmt_pct, C_HEADER_RE, "% DoD",
                   use_pos_neg=True, title=title, subtitle=subtitle, cutoff=cutoff)


def render_dod_city(data: dict, cutoff: str = None) -> BytesIO:
    """Report 3 — PS harian per CITY (kabupaten) + kolom %DoD 2 hari terakhir,
    dikelompokkan per BRANCH. Layout & grafik sama dengan report 1."""
    title    = "DoD Performance FMC City JATENG-DIY"
    subtitle = f"Update {data['tgl_closing'].strftime('%d-%m-%Y')}"
    return _render(data, "count_daily", _fmt_count, C_HEADER_PS, "PS",
                   use_pos_neg=False, title=title, subtitle=subtitle,
                   extra_dod_col=True, cutoff=cutoff, bar_chart=True,
                   sub_header="CITY")


# ── Warna kategori paket (dipakai grafik & label PRODUCT report city×paket) ──
_PROD_FILL = {"IH REGULER": "#C0224E", "EZNET": "#1F6E8C", "TSEL ONE": "#BDC3C7"}
_PROD_TEXT = {"IH REGULER": "#C0224E", "EZNET": "#1F6E8C", "TSEL ONE": "#7F8C8D"}


def render_dod_city_product(data: dict, cutoff: str = None) -> BytesIO:
    """
    DoD FMC City dibreakdown PER CITY × PER PAKET dalam 1 tabel.
    Tiap city (25 whitelist) = 3 baris paket (IH REGULER / EZNET / TSEL ONE),
    kolom PS harian 1..n + kolom %DoD 2 hari terakhir, plus grand total
    JATENG-DIY per paket. Grafik stacked bar per tanggal (all 25 city) di atas.
    """
    n_days   = data["n_days"]
    blocks   = data["city_blocks"]
    tot_prod = data["total_products"]
    chart_p  = data.get("chart_products", [])

    CW_BR, CW_CITY, CW_PROD = 1.00, 1.35, 1.02
    col_widths = [CW_BR, CW_CITY, CW_PROD] + [CW_DAY] * n_days + [CW_DOD]
    TW = sum(col_widths)

    CH = 3.6  # tinggi area grafik
    n_body  = sum(len(b["products"]) for b in blocks)   # 25*3
    n_total = len(tot_prod)                             # 3
    FH = TH + CH + HH1 + HH2 + n_body * RH + SEP + n_total * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    # Axes memenuhi seluruh kanvas — lihat catatan di _render().
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    xs = [MG]
    for w in col_widths[:-1]:
        xs.append(xs[-1] + w)
    IDX_DAY0 = 3               # index kolom tanggal pertama
    IDX_DOD  = 3 + n_days      # index kolom DoD

    def cx(i):
        return xs[i] + col_widths[i] / 2

    _renderer = fig.canvas.get_renderer()

    def _text_width_in(txt, fontsize, bold=True):
        t = ax.text(0, 0, txt, fontsize=fontsize,
                    fontweight="bold" if bold else "normal")
        w_in = t.get_window_extent(renderer=_renderer).width / fig.dpi
        t.remove()
        return w_in

    def _autofs(txt, w, fs0, fs_min=4.0, bold=True):
        f2 = fs0
        while f2 > fs_min and _text_width_in(txt, f2, bold=bold) > w - 0.15:
            f2 -= 0.2
        return f2

    def hcell(x, y, w, h, txt, bg, fg=C_WHITE, fs=8):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=_autofs(txt, w, fs), fontweight="bold", color=fg, zorder=3)

    def hcell_fit(x, y, w, h, candidates, bg, fg=C_WHITE, fs=8, fs_min=4.0):
        """Header judul dengan fallback teks singkat kalau lebar `w` (mis. n_days
        kecil) tidak muat versi lengkap — lihat hcell_fit di _render()."""
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        chosen_txt, chosen_fs = candidates[-1], fs_min
        for txt in candidates:
            f2 = _autofs(txt, w, fs, fs_min=fs_min)
            if len(txt) * 0.107 * f2 / 10 <= w - 0.15:
                chosen_txt, chosen_fs = txt, f2
                break
        ax.text(x + w / 2, y + h / 2, chosen_txt, ha="center", va="center",
                fontsize=chosen_fs, fontweight="bold", color=fg, zorder=3)

    # ── Judul & subjudul ─────────────────────────────────────────────────────
    ax.text(MG, FH - MG, "DoD Performance FMC City JATENG-DIY",
            ha="left", va="top", fontsize=14, fontweight="bold", color=C_MID)
    ax.text(MG, FH - MG - 0.24,
            f"Per City × Paket  |  {data['bulan_label']}  |  Update {data['tgl_closing'].strftime('%d-%m-%Y')}",
            ha="left", va="top", fontsize=9.5, color="#7F8C8D")

    # ── Grafik stacked bar per tanggal (all 25 city) ─────────────────────────
    y_bar_bawah = FH - MG - TH - CH + 0.30
    tinggi_maks = CH - 0.55
    totals = [sum(int(p["count_daily"].get(d) or 0) for p in chart_p)
              for d in range(1, n_days + 1)]
    skala_maks = max(totals) if any(totals) else 1
    urutan_stack = ["EZNET", "TSEL ONE", "IH REGULER"]
    produk_map   = {p["name"]: p for p in chart_p}
    warna_teks   = {"IH REGULER": C_WHITE, "EZNET": C_WHITE, "TSEL ONE": C_DARK}
    lebar_bar    = CW_DAY * 0.94
    MIN_2BARIS, MIN_1BARIS = 0.205, 0.110
    for d in range(1, n_days + 1):
        ci = IDX_DAY0 + (d - 1)
        total_hari = totals[d - 1]
        if total_hari <= 0:
            continue
        y_jalan = y_bar_bawah
        for nama_p in urutan_stack:
            p = produk_map.get(nama_p)
            if p is None:
                continue
            nilai = int(p["count_daily"].get(d) or 0)
            if nilai <= 0:
                continue
            tinggi = tinggi_maks * (nilai / skala_maks)
            ax.add_patch(plt.Rectangle((cx(ci) - lebar_bar / 2, y_jalan), lebar_bar,
                                       tinggi, color=_PROD_FILL.get(nama_p, "#95A5A6"), zorder=3))
            fg  = warna_teks.get(nama_p, C_DARK)
            mid = y_jalan + tinggi / 2
            pct = nilai / total_hari * 100
            if tinggi >= MIN_2BARIS:
                ax.text(cx(ci), mid + 0.042, f"{nilai:,}".replace(",", "."),
                        ha="center", va="center", fontsize=5.6, fontweight="bold",
                        color=fg, zorder=4, clip_on=False)
                ax.text(cx(ci), mid - 0.050, f"({pct:.1f}%)", ha="center", va="center",
                        fontsize=4.7, fontweight="bold", color=fg, zorder=4, clip_on=False)
            elif tinggi >= MIN_1BARIS:
                ax.text(cx(ci), mid, f"{nilai:,}".replace(",", "."), ha="center",
                        va="center", fontsize=5.6, fontweight="bold", color=fg,
                        zorder=4, clip_on=False)
            y_jalan += tinggi
        ax.text(cx(ci), y_jalan + 0.045, f"{total_hari:,}".replace(",", "."),
                ha="center", va="bottom", fontsize=4.8, fontweight="bold",
                color=C_MID, zorder=4, clip_on=False)
    # Legend
    y_leg = y_bar_bawah + tinggi_maks * 0.72
    for nama_p in ["IH REGULER", "TSEL ONE", "EZNET"]:
        ax.add_patch(plt.Rectangle((xs[0] + 0.10, y_leg), 0.22, 0.11,
                                   color=_PROD_FILL.get(nama_p, "#95A5A6"), zorder=3))
        ax.text(xs[0] + 0.40, y_leg + 0.055, nama_p, ha="left", va="center",
                fontsize=6.5, color=C_MID, zorder=3)
        y_leg -= 0.19
    ax.text(xs[0] + 0.10, y_bar_bawah - 0.16, "PS harian per paket (25 city)",
            ha="left", va="center", fontsize=6, color="#7F8C8D", style="italic", zorder=3)
    ax.plot([xs[IDX_DAY0], xs[IDX_DAY0] + CW_DAY * n_days],
            [y_bar_bawah, y_bar_bawah], color=C_BORDER, lw=0.6, zorder=4)

    # ── Header ────────────────────────────────────────────────────────────────
    y_top = FH - MG - TH - CH
    yh1   = y_top - HH1
    yh2   = yh1 - HH2
    hcell(xs[0], yh2, CW_BR,   HH1 + HH2, "BRANCH",  C_HEADER_SUB, fs=8)
    hcell(xs[1], yh2, CW_CITY, HH1 + HH2, "CITY",    C_HEADER_SUB, fs=8)
    hcell(xs[2], yh2, CW_PROD, HH1 + HH2, "PAKET",   C_HEADER_SUB, fs=8)
    hcell_fit(xs[IDX_DAY0], yh1, CW_DAY * n_days, HH1,
              [f"PS {data['bulan_label']}", "PS"], C_HEADER_PS, fs=9)
    for d in range(1, n_days + 1):
        hcell(xs[IDX_DAY0 + (d - 1)], yh2, CW_DAY, HH2, str(d), C_HEADER_PS, fs=6)
    dod_label = f"DoD\n{n_days}/{n_days-1}" if n_days >= 2 else "DoD"
    hcell(xs[IDX_DOD], yh2, CW_DOD, HH1 + HH2, dod_label, C_HEADER_RE, fs=7)

    # ── Baris data (per city × paket) ────────────────────────────────────────
    def draw_prod_row(cur_y, lbl_br, lbl_city, prod, daily, dod_v, bg,
                      is_total=False):
        ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, RH, color=bg, zorder=1))
        mid = cur_y + RH / 2
        fg_lbl = C_WHITE if is_total else C_DARK
        if lbl_br is not None:
            ax.text(xs[0] + LBL_PAD, mid, lbl_br, ha="left", va="center",
                    fontsize=_autofs(lbl_br, CW_BR, 6.4), fontweight="bold",
                    color=fg_lbl, zorder=3, clip_on=True)
        if lbl_city is not None:
            ax.text(xs[1] + LBL_PAD, mid, lbl_city, ha="left", va="center",
                    fontsize=_autofs(lbl_city, CW_CITY, 6.4), fontweight="bold",
                    color=fg_lbl, zorder=3, clip_on=True)
        # kolom PAKET (diberi warna kategori)
        pcol = C_WHITE if is_total else _PROD_TEXT.get(prod, C_DARK)
        ax.text(xs[2] + LBL_PAD, mid, prod, ha="left", va="center",
                fontsize=_autofs(prod, CW_PROD, 6.2), fontweight="bold",
                color=pcol, zorder=3, clip_on=True)
        for d in range(1, n_days + 1):
            v = daily.get(d)
            txt = _fmt_count(v)
            ax.text(cx(IDX_DAY0 + (d - 1)), mid, txt, ha="center", va="center",
                    fontsize=_autofs(txt, CW_DAY, 6.0, 3.0), fontweight="bold",
                    color=C_WHITE if is_total else C_DARK, zorder=3, clip_on=True)
        txt_d = _fmt_pct(dod_v)
        cdod  = C_WHITE if is_total else (C_DARK if dod_v is None else (C_POS if dod_v >= 0 else C_NEG))
        ax.text(cx(IDX_DOD), mid, txt_d, ha="center", va="center",
                fontsize=_autofs(txt_d, CW_DOD, 6.0, 3.0), fontweight="bold",
                color=cdod, zorder=3, clip_on=True)
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_SEP, lw=0.3, zorder=5)

    cur_y = yh2
    prev_branch, zebra = None, 0
    for b in blocks:
        if b["branch"] != prev_branch:
            zebra += 1
            prev_branch = b["branch"]
        bg = C_WOK_ODD if zebra % 2 == 1 else C_WOK_EVEN
        for j, p in enumerate(b["products"]):
            cur_y -= RH
            lbl_br   = b["branch"] if j == 0 else None
            lbl_city = b["city"]   if j == 0 else None
            draw_prod_row(cur_y, lbl_br, lbl_city, p["product"],
                          p["count_daily"], p["daily"].get(n_days), bg)
        # garis pemisah antar city (sedikit lebih tegas)
        ax.plot([xs[0], xs[0] + TW], [cur_y, cur_y], color=C_BORDER, lw=0.5, zorder=6)

    # ── Grand total JATENG-DIY per paket ─────────────────────────────────────
    cur_y -= SEP
    ax.add_patch(plt.Rectangle((xs[0], cur_y), TW, SEP, color=C_SEP, zorder=1))
    for j, p in enumerate(tot_prod):
        cur_y -= RH
        lbl_city = "JATENG-DIY" if j == 0 else None
        draw_prod_row(cur_y, None, lbl_city, p["product"],
                      p["count_daily"], p["daily"].get(n_days), C_REGION_BG,
                      is_total=True)

    bottom = cur_y

    # ── Border luar & grid vertikal ──────────────────────────────────────────
    ax.add_patch(plt.Rectangle((xs[0], bottom), TW, y_top - bottom,
                               fill=False, edgecolor=C_BORDER, lw=0.8, zorder=7))

    def vline(x, y0, y1):
        ax.plot([x, x], [y0, y1], color=C_SEP, lw=0.22, zorder=5)

    for x in [xs[0], xs[1], xs[2], xs[IDX_DAY0], xs[IDX_DOD], xs[IDX_DOD] + CW_DOD]:
        vline(x, bottom, y_top)
    for d in range(1, n_days):    # garis antar kolom tanggal (interior)
        vline(xs[IDX_DAY0 + d], bottom, yh1)

    footer = "Sumber: indihome_ordering_detail  |  Filter: NEW SALES, exclude HWA  |  25 City whitelist"
    if cutoff:
        footer += f"  |  Cutoff: {cutoff}"
    ax.text(xs[0], bottom - 0.05, footer, fontsize=5.5, color="#95A5A6",
            va="top", style="italic")

    # tight_layout() TIDAK dipakai (lihat catatan di _render) — hindari distorsi
    # layout saat n_days kecil. bbox_inches="tight" di savefig() sudah cukup.
    buf = BytesIO()
    _dpi = min(180, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
