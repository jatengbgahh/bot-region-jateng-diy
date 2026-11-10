"""
pranpc_ref.py — Data referensi report PraNPC (/pranpc*).

Diambil dari workbook "Tracking PraNPC" (sheet SVP-City & Target PraNPC).

WOK PraNPC = "Cluster SVP", di-mapping dari kolom `kabupaten`, BUKAN dari
kolom `wok` di tabel. Kolom `wok` tidak konsisten antar-bulan (mis. 202609
masih pakai "YOGYA 1/YOGYA 2", "SEMARANG 2", "JEPARA KUDUS - PATI"), sedangkan
kabupaten stabil — jadi MoM selalu apple-to-apple.
"""

# Daftar Kabupaten -> (Cluster SVP / WOK, Mitra SVP)
KAB_TO_SVP = {
    "BANJARNEGARA"   : ("BANJARNEGARA",               "PT. SARANA MEDIA SELULAR"),
    "WONOSOBO"       : ("BANJARNEGARA",               "PT. SARANA MEDIA SELULAR"),
    "PURBALINGGA"    : ("BANJARNEGARA",               "PT. SARANA MEDIA SELULAR"),
    "BATANG"         : ("BATANG",                     "PT. SARANA MEDIA SELULAR"),
    "KOTA PEKALONGAN": ("BATANG",                     "PT. SARANA MEDIA SELULAR"),
    "PEKALONGAN"     : ("BATANG",                     "PT. SARANA MEDIA SELULAR"),
    "PEMALANG"       : ("BATANG",                     "PT. SARANA MEDIA SELULAR"),
    "BOYOLALI"       : ("BOYOLALI",                   "PT. RAJAWALI CELLULAR INDONESIA"),
    "SUKOHARJO"      : ("BOYOLALI",                   "PT. RAJAWALI CELLULAR INDONESIA"),
    "KLATEN"         : ("BOYOLALI",                   "PT. RAJAWALI CELLULAR INDONESIA"),
    "BANYUMAS"       : ("CILACAP BANYUMAS",           "PT. SARANA MEDIA SELULAR"),
    "CILACAP"        : ("CILACAP BANYUMAS",           "PT. SARANA MEDIA SELULAR"),
    "SLEMAN"         : ("DAERAH ISTIMEWA YOGYAKARTA", "PT. AKAR DAYA"),
    "GUNUNG KIDUL"   : ("DAERAH ISTIMEWA YOGYAKARTA", "PT. AKAR DAYA"),
    "KOTA YOGYAKARTA": ("DAERAH ISTIMEWA YOGYAKARTA", "PT. AKAR DAYA"),
    "KULON PROGO"    : ("DAERAH ISTIMEWA YOGYAKARTA", "PT. AKAR DAYA"),
    "BANTUL"         : ("DAERAH ISTIMEWA YOGYAKARTA", "PT. AKAR DAYA"),
    "DEMAK"          : ("DEMAK",                      "PT. PERKASA MITRA TELEKOMUNIKASI"),
    "KOTA SALATIGA"  : ("DEMAK",                      "PT. PERKASA MITRA TELEKOMUNIKASI"),
    "SEMARANG"       : ("DEMAK",                      "PT. PERKASA MITRA TELEKOMUNIKASI"),
    "JEPARA"         : ("JEPARA KUDUS",               "PT. PERKASA MITRA TELEKOMUNIKASI"),
    "KUDUS"          : ("JEPARA KUDUS",               "PT. PERKASA MITRA TELEKOMUNIKASI"),
    "PURWOREJO"      : ("KEBUMEN",                    "PT. SELULAR MEDIA INFOTAMA"),
    "KEBUMEN"        : ("KEBUMEN",                    "PT. SELULAR MEDIA INFOTAMA"),
    "KOTA MAGELANG"  : ("MAGELANG TEMANGGUNG",        "PT. RAJAWALI CELLULAR INDONESIA"),
    "MAGELANG"       : ("MAGELANG TEMANGGUNG",        "PT. RAJAWALI CELLULAR INDONESIA"),
    "TEMANGGUNG"     : ("MAGELANG TEMANGGUNG",        "PT. RAJAWALI CELLULAR INDONESIA"),
    "PATI"           : ("PATI",                       "PT. KINARYA SELARAS SOLUSI"),
    "REMBANG"        : ("PATI",                       "PT. KINARYA SELARAS SOLUSI"),
    "KOTA SEMARANG"  : ("SEMARANG",                   "PT. SARANA MEDIA SELULAR"),
    "KENDAL"         : ("SEMARANG",                   "PT. SARANA MEDIA SELULAR"),
    "SRAGEN"         : ("SRAGEN",                     "PT. KINARYA SELARAS SOLUSI"),
    "BLORA"          : ("SRAGEN",                     "PT. KINARYA SELARAS SOLUSI"),
    "GROBOGAN"       : ("SRAGEN",                     "PT. KINARYA SELARAS SOLUSI"),
    "WONOGIRI"       : ("SURAKARTA",                  "PT. MITRA CIPTA TEKNOLOGI"),
    "KARANGANYAR"    : ("SURAKARTA",                  "PT. MITRA CIPTA TEKNOLOGI"),
    "KOTA SURAKARTA" : ("SURAKARTA",                  "PT. MITRA CIPTA TEKNOLOGI"),
    "BREBES"         : ("TEGAL BREBES",               "PT. SARANA MEDIA SELULAR"),
    "KOTA TEGAL"     : ("TEGAL BREBES",               "PT. SARANA MEDIA SELULAR"),
    "TEGAL"          : ("TEGAL BREBES",               "PT. SARANA MEDIA SELULAR"),
}

# Target RR (SSL) PraNPC per Branch, per periode YYYYMM.
# Sumber: sheet "Target PraNPC" kolom "Target RR Oct" (per TERRITORY).
# "_REGION" = target level regional (dipakai di baris JATENG-DIY).
# Bulan baru: tambahkan entry baru; kalau periode belum ada, calculator
# memakai periode terakhir yang tersedia dan menandainya di footer.
TARGET_RR = {
    "202610": {
        "MAGELANG"  : 0.28990627253064166,
        "PEKALONGAN": 0.3717736486486487,
        "PURWOKERTO": 0.34570076877587225,
        "SEMARANG"  : 0.3673640443390812,
        "SURAKARTA" : 0.3358866781971732,
        "YOGYAKARTA": 0.34399272396543884,
        "_REGION"   : 0.34823035501835614,
    },
}

BRANCH_ORDER = ["MAGELANG", "PEKALONGAN", "PURWOKERTO", "SEMARANG", "SURAKARTA", "YOGYAKARTA"]


def wok_of(kabupaten: str) -> str | None:
    v = KAB_TO_SVP.get((kabupaten or "").strip().upper())
    return v[0] if v else None


def target_rr(periode: str) -> tuple[dict, str]:
    """Return (dict target per branch, periode target yang dipakai)."""
    if periode in TARGET_RR:
        return TARGET_RR[periode], periode
    tersedia = sorted(p for p in TARGET_RR if p <= periode) or sorted(TARGET_RR)
    p = tersedia[-1]
    return TARGET_RR[p], p
