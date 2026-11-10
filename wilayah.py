"""
wilayah.py — Pemetaan KABUPATEN -> WOK & BRANCH (struktur WOK baru, 14 WOK).

Sumber: lampiran pemetaan WOK baru (08-Okt-2026). Satu-satunya tempat yang
menyimpan aturan ini; semua query/report memakai fungsi di sini, jadi kalau
ada kabupaten pindah WOK cukup ubah _DAFTAR di bawah.

Aturan:
- Pencocokan nama kabupaten TIDAK peka huruf besar/kecil dan mengabaikan SEMUA
  spasi, jadi "GUNUNG KIDUL" (kolom city/kabupaten di churn_dd, bwmp_c3mr_dd,
  dsb) dan "GUNUNGKIDUL" (indihome_ordering_detail.kabupaten) sama-sama
  terbaca sebagai GUNUNGKIDUL.
- Kabupaten kosong / NULL / 'NAN' / kota di luar JATENG-DIY (tidak ada di
  daftar) = TIDAK TERPETAKAN. Baris seperti ini TETAP dihitung: kabupatennya
  diisi dari GEOTAGGING longitude/latitude (boundary desa Jateng-DIY, sama
  seperti report /agresif -> geotag_kab()). Kalau koordinat tidak valid
  (kosong, 0/0, atau di luar Jateng-DIY) dipakai kabupaten lokasi STO
  (kabupaten_sto). Hanya kalau semuanya gagal baris dibuang
  (selesaikan_wilayah() -> None).
- Pemetaan murni berdasar kabupaten; kolom wok/branch bawaan DB tidak dipakai.
"""
import re

# (BRANCH, WOK, KABUPATEN)
_DAFTAR = [
    ("MAGELANG",   "KEBUMEN",                    "KEBUMEN"),
    ("MAGELANG",   "KEBUMEN",                    "PURWOREJO"),
    ("MAGELANG",   "MAGELANG TEMANGGUNG",        "KOTA MAGELANG"),
    ("MAGELANG",   "MAGELANG TEMANGGUNG",        "MAGELANG"),
    ("MAGELANG",   "MAGELANG TEMANGGUNG",        "TEMANGGUNG"),
    ("PEKALONGAN", "BATANG",                     "BATANG"),
    ("PEKALONGAN", "BATANG",                     "KOTA PEKALONGAN"),
    ("PEKALONGAN", "BATANG",                     "PEKALONGAN"),
    ("PEKALONGAN", "BATANG",                     "PEMALANG"),
    ("PEKALONGAN", "TEGAL BREBES",               "BREBES"),
    ("PEKALONGAN", "TEGAL BREBES",               "KOTA TEGAL"),
    ("PEKALONGAN", "TEGAL BREBES",               "TEGAL"),
    ("PURWOKERTO", "BANJARNEGARA",               "BANJARNEGARA"),
    ("PURWOKERTO", "BANJARNEGARA",               "PURBALINGGA"),
    ("PURWOKERTO", "BANJARNEGARA",               "WONOSOBO"),
    ("PURWOKERTO", "CILACAP BANYUMAS",           "BANYUMAS"),
    ("PURWOKERTO", "CILACAP BANYUMAS",           "CILACAP"),
    ("SEMARANG",   "DEMAK",                      "DEMAK"),
    ("SEMARANG",   "DEMAK",                      "KOTA SALATIGA"),
    ("SEMARANG",   "DEMAK",                      "SEMARANG"),
    ("SEMARANG",   "JEPARA KUDUS",               "JEPARA"),
    ("SEMARANG",   "JEPARA KUDUS",               "KUDUS"),
    ("SEMARANG",   "PATI",                       "PATI"),
    ("SEMARANG",   "PATI",                       "REMBANG"),
    ("SEMARANG",   "SEMARANG",                   "KENDAL"),
    ("SEMARANG",   "SEMARANG",                   "KOTA SEMARANG"),
    ("SURAKARTA",  "BOYOLALI",                   "BOYOLALI"),
    ("SURAKARTA",  "BOYOLALI",                   "KLATEN"),
    ("SURAKARTA",  "BOYOLALI",                   "SUKOHARJO"),
    ("SURAKARTA",  "SRAGEN",                     "BLORA"),
    ("SURAKARTA",  "SRAGEN",                     "GROBOGAN"),
    ("SURAKARTA",  "SRAGEN",                     "SRAGEN"),
    ("SURAKARTA",  "SURAKARTA",                  "KARANGANYAR"),
    ("SURAKARTA",  "SURAKARTA",                  "KOTA SURAKARTA"),
    ("SURAKARTA",  "SURAKARTA",                  "WONOGIRI"),
    ("YOGYAKARTA", "DAERAH ISTIMEWA YOGYAKARTA", "BANTUL"),
    ("YOGYAKARTA", "DAERAH ISTIMEWA YOGYAKARTA", "GUNUNGKIDUL"),   # tanpa spasi (keputusan user)
    ("YOGYAKARTA", "DAERAH ISTIMEWA YOGYAKARTA", "KOTA YOGYAKARTA"),
    ("YOGYAKARTA", "DAERAH ISTIMEWA YOGYAKARTA", "KULON PROGO"),
    ("YOGYAKARTA", "DAERAH ISTIMEWA YOGYAKARTA", "SLEMAN"),
]


def normalisasi_kab(nilai) -> str:
    """Huruf besar + buang semua spasi. None/NaN -> ''."""
    if nilai is None:
        return ""
    s = str(nilai)
    if s.lower() == "nan":
        return ""
    return re.sub(r"\s+", "", s.upper())


# kabupaten (ternormalisasi) -> (wok, branch)
KAB_KE_WOK_BRANCH = {
    normalisasi_kab(kab): (wok, branch) for branch, wok, kab in _DAFTAR
}

BRANCH_ORDER = ["MAGELANG", "PEKALONGAN", "PURWOKERTO", "SEMARANG", "SURAKARTA", "YOGYAKARTA"]

# Urutan WOK = urutan kemunculan di lampiran (sudah terurut per branch)
WOK_ORDER = list(dict.fromkeys(wok for _, wok, _ in _DAFTAR))

WOK_TO_BRANCH = {wok: branch for branch, wok, _ in _DAFTAR}


# kabupaten ternormalisasi -> nama resmi (sesuai lampiran, mis. KOTA SEMARANG;
# GUNUNGKIDUL tanpa spasi). Dipakai agar nama city seragam di semua report/target.
NAMA_KAB = {normalisasi_kab(kab): kab for _, _, kab in _DAFTAR}


def nama_kab(kabupaten):
    """Nama kabupaten resmi sesuai lampiran; nilai tak dikenal dikembalikan apa adanya (UPPER)."""
    return NAMA_KAB.get(normalisasi_kab(kabupaten), str(kabupaten or "").strip().upper())


# ── Geotagging longitude/latitude -> kabupaten (boundary sama dgn /agresif) ──
_GEOCODER = None
_GEO_CACHE: dict = {}


def _get_geocoder():
    """Lazy-load boundary Jateng-DIY (zip, fallback folder hasil extract)."""
    global _GEOCODER
    if _GEOCODER is None:
        import os
        from agresif_geocode import Geocoder
        base = os.path.dirname(os.path.abspath(__file__))
        zip_path = os.path.join(base, "resources", "geo", "GeocodingJatengDIY_1.zip")
        js_path = os.path.join(base, "resources", "geo", "GeocodingJatengDIY", "boundaries.js")
        if os.path.exists(zip_path):
            _GEOCODER = Geocoder.from_geocoding_zip(zip_path)
        elif os.path.exists(js_path):
            _GEOCODER = Geocoder.from_boundaries_js(js_path)
        else:
            raise FileNotFoundError(
                f"Data geocoding tidak ditemukan: {zip_path} / {js_path}")
    return _GEOCODER


def geotag_kab(lon, lat):
    """
    (longitude, latitude) -> nama kabupaten resmi, atau None kalau koordinat
    kosong/0,0 atau jatuh di luar Jateng-DIY (hanya hasil EXACT/NEAREST dipakai).
    """
    try:
        x, y = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if x != x or y != y or (abs(x) < 1 and abs(y) < 1):
        return None
    kunci = (round(x, 6), round(y, 6))
    if kunci not in _GEO_CACHE:
        k, _c, _d, status = _get_geocoder().kab_kec(x, y)
        _GEO_CACHE[kunci] = nama_kab(k) if (k and status in ("EXACT", "NEAREST")) else None
    return _GEO_CACHE[kunci]


def selesaikan_wilayah(lon, lat, kab_sto=None):
    """
    Untuk baris yang kabupatennya tidak terpetakan: geotag koordinat dulu, lalu
    kabupaten STO. Return (wok, branch, nama_kabupaten) atau None.
    """
    for kab in (geotag_kab(lon, lat), kab_sto):
        h = petakan_kab(kab)
        if h:
            return h[0], h[1], nama_kab(kab)
    return None


def petakan_kab(kabupaten):
    """kabupaten -> (wok, branch), atau None kalau tidak terpetakan."""
    return KAB_KE_WOK_BRANCH.get(normalisasi_kab(kabupaten))


def wok_dari_kab(kabupaten):
    h = petakan_kab(kabupaten)
    return h[0] if h else None


def branch_dari_kab(kabupaten):
    h = petakan_kab(kabupaten)
    return h[1] if h else None


def petakan_df(df, kolom_kab="kabupaten", kolom_wok="wok", kolom_branch="branch",
               buang_tak_terpetakan=True):
    """
    Isi/timpa kolom wok & branch di DataFrame berdasar kolom kabupaten.
    Baris yang kabupatennya tidak terpetakan dibuang (default).
    """
    hasil = df.copy()
    hasil[kolom_wok]    = hasil[kolom_kab].map(wok_dari_kab)
    hasil[kolom_branch] = hasil[kolom_kab].map(branch_dari_kab)
    if buang_tak_terpetakan:
        hasil = hasil[hasil[kolom_wok].notna()]
    return hasil


# ─────────────────────────────────────────────────────────────────────────────
#  Ekspresi SQL (MySQL) — dipakai di SELECT / GROUP BY / WHERE tiap query
# ─────────────────────────────────────────────────────────────────────────────
def sql_kab_norm(kolom: str = "kabupaten") -> str:
    """Ekspresi SQL nama kabupaten ternormalisasi (UPPER, tanpa spasi)."""
    return f"REPLACE(UPPER(TRIM({kolom})), ' ', '')"


def _sql_case(kolom: str, indeks: int) -> str:
    kelompok: dict = {}
    for kab, hasil in KAB_KE_WOK_BRANCH.items():
        kelompok.setdefault(hasil[indeks], []).append(kab)
    norm = sql_kab_norm(kolom)
    cabang = " ".join(
        "WHEN " + norm + " IN (" + ", ".join(f"'{k}'" for k in kabs) + f") THEN '{nama}'"
        for nama, kabs in kelompok.items()
    )
    return f"(CASE {cabang} END)"


def sql_wok(kolom: str = "kabupaten") -> str:
    """Ekspresi SQL -> nama WOK baru (NULL kalau kabupaten tidak terpetakan)."""
    return _sql_case(kolom, 0)


def sql_branch(kolom: str = "kabupaten") -> str:
    """Ekspresi SQL -> nama BRANCH (NULL kalau kabupaten tidak terpetakan)."""
    return _sql_case(kolom, 1)


def sql_terpetakan(kolom: str = "kabupaten") -> str:
    """Kondisi SQL: kabupaten ada di lampiran (pakai di WHERE ... AND <ini>)."""
    daftar = ", ".join(f"'{k}'" for k in KAB_KE_WOK_BRANCH)
    return f"{sql_kab_norm(kolom)} IN ({daftar})"


def sql_kab_nama(kolom: str = "kabupaten") -> str:
    """Ekspresi SQL -> nama kabupaten resmi (spasi dikembalikan: KOTA SEMARANG, dst)."""
    norm = sql_kab_norm(kolom)
    cabang = " ".join(
        f"WHEN '{n}' THEN '{kab}'" for n, kab in NAMA_KAB.items() if n != kab
    )
    return f"(CASE {norm} {cabang} ELSE {norm} END)"


# ─────────────────────────────────────────────────────────────────────────────
#  Fallback WOK LAMA -> WOK BARU (untuk tabel yang cuma punya kolom wok lama,
#  mis. dashboard_hourly_sales, saat kolom kabupatennya kosong/nan)
# ─────────────────────────────────────────────────────────────────────────────
UNMAPPED_WOK    = "KABUPATEN UNMAPPED"
UNMAPPED_BRANCH = "UNMAPPED"

# Hanya WOK lama yang 1:1 ke WOK baru. PEMALANG PURBALINGGA (Pemalang vs Purbalingga)
# terbelah ke >1 WOK baru -> tidak dimasukkan, jadi jatuh ke UNMAPPED.
# JEPARA KUDUS - PATI juga terbelah, tapi tabel dashboard_hourly_sales punya kolom
# `cluster` yang memisahkannya (nilai 'JEPARA KUDUS' / 'PATI') -> WOK_LAMA_CLUSTER_KE_BARU.
WOK_LAMA_KE_BARU = {
    "KEBUMEN"              : "KEBUMEN",
    "MAGELANG TEMANGGUNG"  : "MAGELANG TEMANGGUNG",
    "BATANG"               : "BATANG",
    "TEGAL BREBES"         : "TEGAL BREBES",
    "CILACAP BANYUMAS"     : "CILACAP BANYUMAS",
    "WONOSOBO BANJARNEGARA": "BANJARNEGARA",
    "DEMAK"                : "DEMAK",
    "SEMARANG 1"           : "SEMARANG",
    "SEMARANG 2"           : "SEMARANG",
    "BOYOLALI"             : "BOYOLALI",
    "SRAGEN"               : "SRAGEN",
    "SURAKARTA"            : "SURAKARTA",
    "YOGYA 1"              : "DAERAH ISTIMEWA YOGYAKARTA",
    "YOGYA 2"              : "DAERAH ISTIMEWA YOGYAKARTA",
}


# (WOK lama, cluster) -> WOK baru, untuk WOK lama yang terbelah tapi clusternya terpisah.
WOK_LAMA_CLUSTER_KE_BARU = {
    ("JEPARA KUDUS - PATI", "JEPARA KUDUS"): "JEPARA KUDUS",
    ("JEPARA KUDUS - PATI", "PATI"): "PATI",
}


def sql_kab_kosong(kolom: str = "kabupaten") -> str:
    """Kondisi SQL: kabupaten NULL / kosong / 'nan' (artinya tidak ada data kabupaten)."""
    return f"({kolom} IS NULL OR {sql_kab_norm(kolom)} IN ('', 'NAN'))"


def _sql_wok_lama(kol_wok: str, ke_branch: bool, kol_cluster: str = "cluster") -> str:
    norm = f"UPPER(TRIM({kol_wok}))"
    cabang = " ".join(
        f"WHEN '{lama}' THEN '" + (WOK_TO_BRANCH[baru] if ke_branch else baru) + "'"
        for lama, baru in WOK_LAMA_KE_BARU.items()
    )
    # WOK lama yang terbelah: pilih WOK baru lewat kolom cluster
    for lama in dict.fromkeys(w for w, _ in WOK_LAMA_CLUSTER_KE_BARU):
        sub = " ".join(
            f"WHEN '{c}' THEN '" + (WOK_TO_BRANCH[baru] if ke_branch else baru) + "'"
            for (w, c), baru in WOK_LAMA_CLUSTER_KE_BARU.items() if w == lama
        )
        cabang += f" WHEN '{lama}' THEN (CASE UPPER(TRIM({kol_cluster})) {sub} END)"
    return f"(CASE {norm} {cabang} END)"


def sql_wok_fallback(kol_kab: str = "kabupaten", kol_wok: str = "wok",
                     kol_cluster: str = "cluster") -> str:
    """WOK baru: dari kabupaten bila terpetakan; kabupaten kosong/nan -> dari WOK lama;
    selain itu (kabupaten ada tapi di luar wilayah, atau WOK lama tak bisa dipetakan)
    -> UNMAPPED_WOK. Tidak pernah NULL."""
    return (f"(CASE WHEN {sql_terpetakan(kol_kab)} THEN {sql_wok(kol_kab)} "
            f"WHEN {sql_kab_kosong(kol_kab)} THEN COALESCE({_sql_wok_lama(kol_wok, False, kol_cluster)}, '{UNMAPPED_WOK}') "
            f"ELSE '{UNMAPPED_WOK}' END)")


def sql_branch_fallback(kol_kab: str = "kabupaten", kol_wok: str = "wok",
                        kol_cluster: str = "cluster") -> str:
    """BRANCH padanan sql_wok_fallback (UNMAPPED_BRANCH bila tak terpetakan)."""
    return (f"(CASE WHEN {sql_terpetakan(kol_kab)} THEN {sql_branch(kol_kab)} "
            f"WHEN {sql_kab_kosong(kol_kab)} THEN COALESCE({_sql_wok_lama(kol_wok, True, kol_cluster)}, '{UNMAPPED_BRANCH}') "
            f"ELSE '{UNMAPPED_BRANCH}' END)")
