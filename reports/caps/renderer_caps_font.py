"""
renderer_caps_font.py — Ukuran teks bersama SEMUA report CAPS
(/caps: by LoS, by Segmen, by Channel, by Reason)

Kenapa ada file ini:
  Dulu tiap sel dikecilkan sendiri-sendiri (_shrink_to_fit) supaya muat di
  kolomnya. Akibatnya font antar baris belang — "WONOSOBO BANJARNEGARA"
  mengecil, "SEMARANG 2" tetap besar. Dibikin seragam pun hasilnya jadi
  kekecilan, karena satu string terpanjang menyeret seluruh kolom.

  Pendekatan di sini dibalik: font DIPATOK di FS_DATA/FS_LABEL, lalu LEBAR
  KOLOM yang dihitung agar isi terpanjang pasti muat. Jadi tulisannya tidak
  pernah mengecil dan ukurannya sama di keempat report CAPS.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Ukuran font baku report CAPS — ubah di sini kalau mau besar/kecil serentak
FS_DATA   = 14.0   # angka di baris data
FS_LABEL  = 14.0   # nama territory / branch / WOK / reason
FS_HDR    = 12.5   # judul grup kolom
FS_SUBHDR = 10.5   # sub-header (M-1, MtD, Cont., MoM)

_FIG = None        # figure sekali pakai khusus buat mengukur teks


def measure_w(s, fs, bold=False) -> float:
    """
    Lebar teks dalam INCI pada fontsize fs.

    Renderer CAPS memakai 1 data unit = 1 inci (ax.set_xlim(0, FW) dengan FW =
    lebar figsize), jadi hasilnya bisa langsung dipakai sebagai lebar kolom.
    Diukur via renderer sungguhan, bukan diestimasi dari jumlah karakter —
    estimasi meleset jauh untuk teks bold.
    """
    global _FIG
    if _FIG is None:
        # Figure TERPISAH dari pyplot (bukan plt.figure): kalau didaftarkan ke
        # pyplot ia jadi "figure aktif" dan renderer yang menyimpan lewat
        # plt.savefig() malah menyimpan figure ukur yang kosong.
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        _FIG = Figure(figsize=(1, 1), dpi=100)
        FigureCanvasAgg(_FIG)
    t = _FIG.text(0, 0, str(s), fontsize=fs,
                  fontweight="bold" if bold else "normal")
    w = t.get_window_extent(renderer=_FIG.canvas.get_renderer()).width / _FIG.dpi
    t.remove()
    return w


def col_width(samples, fs=FS_DATA, minw=0.0, pad=0.24, bold=True) -> float:
    """
    Lebar kolom yang dijamin memuat SEMUA isi pada fontsize fs (font tidak
    pernah dikecilkan). bold=True dipakai sebagai kasus terburuk karena baris
    Branch/Region dicetak tebal dan lebih lebar dari baris WOK biasa.
    """
    samples = [str(s) for s in samples if s not in (None, "")]
    if not samples:
        return minw
    # cukup uji beberapa yang terpanjang — sisanya pasti lebih sempit
    kandidat = sorted(set(samples), key=len, reverse=True)[:8]
    return max(minw, max(measure_w(s, fs, bold) for s in kandidat) + pad)


def fit_fs(txt, fs, maxw, bold=True, floor=4.5, pad=0.20, step=0.3) -> float:
    """
    Ukuran font terbesar <= fs agar `txt` MUAT di kolom selebar maxw inci
    (dikurangi pad kiri-kanan). Diukur dengan lebar teks sungguhan (measure_w),
    bukan estimasi per karakter — estimasi lama meleset utk label panjang
    seperti "DAERAH ISTIMEWA YOGYAKARTA" sehingga tulisan melewati garis sel.
    """
    f = fs
    while f > floor and measure_w(str(txt), f, bold) > maxw - pad:
        f -= step
    return f
