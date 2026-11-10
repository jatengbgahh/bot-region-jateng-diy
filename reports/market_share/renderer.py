"""
reports/market_share/renderer.py — Render 2 tabel PNG Market Share FBB Jateng-DIY.
Style & tone warna mengikuti reports/kategori_paket/renderer.py.

  render_market_share      : City | FBB SHARE (10 pemain) | WoW | MoM | YoY | Status | Closest Competitor
  render_market_share_mom  : City | FBB SHARE (10 pemain) berisi selisih MoM per pemain
WoW/MoM/YoY & selisih MoM: angka % berwarna hijau (naik) / merah (turun).
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO

from config import REGION_NAME

# Warna mengikuti template Excel MSHARE_PER_CITY / MSHARE_GROWTH_PER_CITY
C_BG        = "white"
C_HEAD      = "#0E1A4B"      # navy: CITY, FBB SHARE, WoW/MoM/YoY, Status, Closest Competitor
C_SEP       = "black"
C_DARK      = "black"
C_RED       = "#FF0000"
C_POS       = "#1E8449"      # naik / Win: hijau
C_NEG       = "#C0392B"      # turun / Lose: merah
C_NEUTRAL   = "black"

# label pemain -> (warna header, warna teks header)
STYLE_PEMAIN = {
    "TSEL Group":  ("#FF0000", "white"),
    "CBN Network": ("#BDE0F7", "black"),
    "ICON PLN":    ("#00E5FF", "black"),
    "XL Home":     ("#0070C0", "white"),
    "First Media": ("#000000", "white"),
    "Indosat":     ("#FFFF00", "black"),
    "My Republic": ("#9B2D9B", "white"),
    "MNC Play":    ("#00B050", "white"),
    "Biznet":      ("#FFC000", "white"),
    "Others":      ("#BFBFBF", "black"),
}

# label pemain -> warna cell tipis di isi tabel
TINT_PEMAIN = {
    "TSEL Group": "#FDEDEC", "CBN Network": "#EAF5FC", "ICON PLN": "#E0FBFF",
    "XL Home": "#E1EEF8", "First Media": "#E6E6E6", "Indosat": "#FFFFE0",
    "My Republic": "#F3E3F3", "MNC Play": "#E2F5E9", "Biznet": "#FFF3D6",
    "Others": "#F0F0F0",
}

RH, HH1, HH2, TH, MG = 0.40, 0.46, 0.46, 0.95, 0.25
CW_CITY, CW_PLAYER = 2.30, 1.30
CW_BRANCH, CW_WOK = 1.55, 3.35   # CW_CITY (kolom City) dipakai sebagai lebar kolom ke-3 TERRITORY
CW_DELTA, CW_STATUS, CW_COMP = 1.10, 0.95, 2.30


def _pct(v):
    return "-" if v is None else f"{v + 0.0:.2f}%".replace("-0.00%", "0.00%")


def _warna_delta(v):
    if v is None or abs(v) < 0.005:
        return C_NEUTRAL
    return C_POS if v > 0 else C_NEG


def _judul_ref(data):
    ed = data["event_date"]
    def f(k):
        d = data["ref_dates"].get(k)
        return d.strftime("%d-%m-%Y") if d else "-"
    return (f"Event date {ed.strftime('%d-%m-%Y')}   |   pembanding: WoW {f('wow')}, "
            f"MoM {f('mom')}, YoY {f('yoy')}")


# kolom TERRITORY: (header, lebar, fungsi(baris)->teks). Default: Branch | WOK | City.
TERR_CITY = [("Branch", CW_BRANCH, lambda k: k.get("branch", "-")),
             ("WOK", CW_WOK, lambda k: k.get("wok", "-")),
             ("City", CW_CITY, lambda k: k["city"])]
TERR_BRANCH = [("Branch", CW_CITY, lambda k: k["city"])]


def _gambar(data, judul, kolom, cutoff, sub=None, catatan=None, terr=None,
            sumber="fixed_ms_city & fixed_ms_region"):
    """
    kolom: list (header, lebar, fungsi(kota)->(teks, warna, tebal), rata, tsel_bg)
    """
    kota = list(data["kota"])
    region = data.get("region")
    if region:
        kota.append(region)     # baris JATENG-DIY (fixed_ms_region) paling bawah
    terr = terr or TERR_CITY
    T = len(terr)                                   # jumlah kolom TERRITORY
    lebar = [t[1] for t in terr] + [k[1] for k in kolom]
    TW = sum(lebar)
    FW = TW + MG * 2
    FH = TH + HH1 + HH2 + len(kota) * RH + MG * 2 + 0.3

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    # judul: bagian "Region JATENG-DIY" merah, sisanya hitam (seperti template Excel)
    kepala, _, ekor = judul.partition(f"Region {REGION_NAME}")
    t1 = ax.text(MG, FH - MG, kepala, ha="left", va="top", fontsize=17, fontweight="bold",
                 color="black")
    fig.canvas.draw()
    lebar_t1 = t1.get_window_extent(fig.canvas.get_renderer()).transformed(ax.transData.inverted()).width
    ax.text(MG + lebar_t1, FH - MG, f"Region {REGION_NAME}" + ekor, ha="left", va="top",
            fontsize=17, fontweight="bold", color=C_RED)
    sub = sub or _judul_ref(data)
    if cutoff:
        sub += f"   |   {cutoff}"
    ax.text(MG, FH - MG - 0.42, sub, ha="left", va="top", fontsize=10, color="#7F8C8D")

    x0 = MG
    xs = [x0]
    for w in lebar:
        xs.append(xs[-1] + w)
    y = FH - MG - TH

    # header baris 1 (grup) & 2 (nama kolom)
    ax.add_patch(plt.Rectangle((x0, y - HH1), TW, HH1, facecolor=C_HEAD, edgecolor="none", zorder=2))
    # TERRITORY: judul menyatu di atas 3 kolom, di bawahnya Branch | WOK | City
    ax.add_patch(plt.Rectangle((xs[0], y - HH1 - HH2), xs[T] - xs[0], HH1 + HH2,
                               facecolor=C_HEAD, edgecolor="none", zorder=2))
    ax.text((xs[0] + xs[T]) / 2, y - HH1 / 2, "TERRITORY", ha="center", va="center",
            fontsize=11, fontweight="bold", color="white", zorder=3)
    for j, (nama_k, _w, _f) in enumerate(terr):
        ax.text((xs[j] + xs[j + 1]) / 2, y - HH1 - HH2 / 2, nama_k, ha="center", va="center",
                fontsize=9.5, fontweight="bold", color="white", zorder=3)
        if j > 0:
            ax.plot([xs[j], xs[j]], [y - HH1, y - HH1 - HH2], color="white", lw=0.6, zorder=3)
    ax.plot([xs[0], xs[T]], [y - HH1, y - HH1], color="white", lw=0.6, zorder=3)
    # grup "FBB SHARE" di atas kolom pemain
    pemain_idx = [i for i, k in enumerate(kolom) if k[5] == "pemain"]
    if pemain_idx:
        a, b = xs[pemain_idx[0] + T], xs[pemain_idx[-1] + T + 1]
        ax.text((a + b) / 2, y - HH1 / 2, "FBB SHARE", ha="center", va="center",
                fontsize=11, fontweight="bold", color="white", zorder=3)
    for i, (hdr, w, _fn, _al, _ts, grup) in enumerate(kolom):
        cx = (xs[i + T] + xs[i + T + 1]) / 2
        if grup == "pemain":
            bg_h, fg_h = STYLE_PEMAIN.get(hdr, (C_HEAD, "white"))
            ax.add_patch(plt.Rectangle((xs[i + T], y - HH1 - HH2), w, HH2,
                                       facecolor=bg_h, edgecolor="none", zorder=2))
            ax.text(cx, y - HH1 - HH2 / 2, hdr, ha="center", va="center", fontsize=9.5,
                    fontweight="bold", color=fg_h, zorder=3)
        else:
            # kolom non-pemain: satu blok warna menyatu di 2 baris header, teks di tengah
            ax.add_patch(plt.Rectangle((xs[i + T], y - HH1 - HH2), w, HH1 + HH2,
                                       facecolor=C_HEAD, edgecolor="none", zorder=2))
            ax.text(cx, y - (HH1 + HH2) / 2, hdr, ha="center", va="center", fontsize=9.5,
                    fontweight="bold", color="white", zorder=3)
    y -= HH1 + HH2
    y_head = y

    y_region = None
    for bi, k in enumerate(kota):
        cy = y - RH / 2
        if region is not None and k is region:
            y_region = y
            # baris region: Branch | WOK | City menyatu, isinya nama region
            ax.add_patch(plt.Rectangle((xs[0], y - RH), xs[T] - xs[0], RH, facecolor=C_HEAD,
                                       edgecolor="none", zorder=2.5))
            ax.text((xs[0] + xs[T]) / 2, cy, k["city"], ha="center", va="center", fontsize=9.5,
                    fontweight="bold", color="white", zorder=3)
        else:
            for j, nilai in enumerate(t[2](k) for t in terr):
                ax.text((xs[j] + xs[j + 1]) / 2, cy, nilai, ha="center", va="center", fontsize=9.5,
                        color=C_DARK, zorder=3)
        for i, (hdr, w, fn, al, tint, _g) in enumerate(kolom):
            teks, warna, tebal = fn(k)
            if tint:
                ax.add_patch(plt.Rectangle((xs[i + T], y - RH), w, RH, facecolor=tint,
                                           edgecolor="none", zorder=1))
            bobot = "bold" if tebal else "normal"
            if al == "left":
                ax.text(xs[i + T] + 0.1, cy, teks, ha="left", va="center", fontsize=9.5,
                        color=warna, fontweight=bobot, zorder=3)
            else:
                ax.text((xs[i + T] + xs[i + T + 1]) / 2, cy, teks, ha="center", va="center",
                        fontsize=9.5, color=warna, fontweight=bobot, zorder=3)
        y -= RH
        ax.plot([x0, x0 + TW], [y, y], color=C_SEP, lw=0.6, zorder=2)

    for x in xs[1:-1]:
        ax.plot([x, x], [y, y_head], color=C_SEP, lw=0.6, zorder=2)
    ax.add_patch(plt.Rectangle((x0, y), TW, (y_head - y) + HH1 + HH2, fill=False,
                               edgecolor="black", lw=1.0, zorder=4))
    if y_region is not None:
        # border tebal berwarna header untuk baris region
        ax.add_patch(plt.Rectangle((x0, y_region - RH), TW, RH, fill=False,
                                   edgecolor=C_HEAD, lw=3.0, zorder=6))
    ax.text(x0, y - 0.1, f"Sumber: {sumber}  |  Region {REGION_NAME}  |  "
            "TSEL Group = IndiHome + Tsel Orbit  |  " + (catatan or
            "WoW/MoM/YoY = selisih share TSEL Group (poin %)"),
            fontsize=7.5, color="#95A5A6", va="top", style="italic")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf


def _kolom_pemain(data, nilai_fn, warna_delta=False, warna_status=False):
    """warna_delta: font hijau/merah menurut tanda angka. warna_status: kolom TSEL Group
    hijau kalau city Win, merah kalau Lose."""
    kolom = []
    for key, label in data["pemain"]:
        def fn(k, key=key):
            v = nilai_fn(k, key)
            if warna_delta:
                warna = _warna_delta(v)
            elif warna_status and key == "tsel":
                warna = C_POS if str(k["status"]).lower() == "win" else C_NEG
            else:
                warna = C_DARK
            return (_pct(v), warna, key == "tsel")
        kolom.append((label, CW_PLAYER, fn, "center", TINT_PEMAIN.get(label), "pemain"))
    return kolom


def render_market_share(data: dict, cutoff: str = None) -> BytesIO:
    kolom = _kolom_pemain(data, lambda k, key: k["share"][key], warna_status=True)
    for nama, label in (("wow", "WoW"), ("mom", "MoM"), ("yoy", "YoY")):
        def fn(k, nama=nama):
            return (_pct(k[nama]), _warna_delta(k[nama]), True)
        kolom.append((label, CW_DELTA, fn, "center", False, "delta"))
    kolom.append(("Status", CW_STATUS,
                  lambda k: (k["status"], C_POS if k["status"].lower() == "win" else C_NEG, True),
                  "center", False, "info"))
    kolom.append(("Closest Competitor", CW_COMP,
                  lambda k: (k["closest"], C_DARK, False), "left", False, "info"))
    return _gambar(data, f"Market Share Per City Region {REGION_NAME}", kolom, cutoff)


def render_market_share_mom(data: dict, cutoff: str = None) -> BytesIO:
    kolom = _kolom_pemain(data, lambda k, key: k["mom_pemain"][key], warna_delta=True)
    ed, ref = data["event_date"], data["ref_dates"].get("mom")
    sub = (f"Event date {ed.strftime('%d-%m-%Y')}   |   pembanding MoM "
           f"{ref.strftime('%d-%m-%Y') if ref else '-'}")
    return _gambar(data, f"Market Share MOM Growth Per City Region {REGION_NAME}", kolom, cutoff,
                   sub=sub, catatan="MoM Growth = selisih share tiap pemain vs pembanding (poin %)")


def render_market_share_branch(data: dict, cutoff: str = None) -> BytesIO:
    """Market Share per Branch (fixed_ms_branch): kolom sama dengan per City, TERRITORY = Branch."""
    kolom = _kolom_pemain(data, lambda k, key: k["share"][key], warna_status=True)
    for nama, label in (("wow", "WoW"), ("mom", "MoM"), ("yoy", "YoY")):
        def fn(k, nama=nama):
            return (_pct(k[nama]), _warna_delta(k[nama]), True)
        kolom.append((label, CW_DELTA, fn, "center", False, "delta"))
    kolom.append(("Status", CW_STATUS,
                  lambda k: (k["status"], C_POS if k["status"].lower() == "win" else C_NEG, True),
                  "center", False, "info"))
    kolom.append(("Closest Competitor", CW_COMP,
                  lambda k: (k["closest"], C_DARK, False), "left", False, "info"))
    return _gambar(data, f"Market Share Per Branch Region {REGION_NAME}", kolom, cutoff,
                   terr=TERR_BRANCH, sumber="fixed_ms_branch & fixed_ms_region",
                   catatan="WoW/MoM/YoY = selisih share TSEL Group (poin %)  |  "
                           "Branch mengikuti pengelompokan tabel fixed_ms_branch")
