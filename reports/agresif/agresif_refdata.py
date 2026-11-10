"""
Daftar referensi statis untuk report /agresif (native, tanpa Excel).

Diekstrak VERBATIM dari master `tika/TEMPLATE AGRESIVE TAHAP 1 JULI.xlsx`
(sheet `REPORT AGRESIF` baris 7-58, sheet `REPORT FMC` baris 7-32) pada 31-Jul-2026.
Kalau daftar kecamatan/city agresif berubah di masa depan, extract ulang dari
master terbaru dan timpa isi file ini (bukan di-hardcode ulang manual).

KEC_47      : 47 kecamatan agresif (report 1 "LOKASI AGRESIF" & report 2 "RE
              KECAMATAN AGRESIF"), key = (city, kec).
AGRESIF_CITY_4 : 4 "Agresif city" tambahan level city (TANPA kecamatan), HANYA
              dipakai di report 1 (PS) — report 2 (RE) sengaja tidak menampilkannya
              (target=0 -> ACH #DIV/0 di versi Excel lama; native cukup guard
              divide-by-zero, tapi utk PARITY perilaku existing tetap dikecualikan
              dari report RE).
FMC_NEW_13  : 25 city "NEW FMC CITY" (report 3; nama var historis, PURWOREJO
              ditambahkan 14-Okt-2026 sbg no. 14, +11 city 04-Nov-2026).
FMC_OLD_12  : 12 city "OLD FMC CITY" (report 3, seksi tambahan).
"""

KEC_47 = [
    {"branch": "MAGELANG", "city": "MAGELANG", "kec": "SAWANGAN"},
    {"branch": "MAGELANG", "city": "TEMANGGUNG", "kec": "JUMO"},
    {"branch": "PEKALONGAN", "city": "PEKALONGAN", "kec": "DORO"},
    {"branch": "PEKALONGAN", "city": "PEKALONGAN", "kec": "PANINGGARAN"},
    {"branch": "PEKALONGAN", "city": "PEKALONGAN", "kec": "SRAGI"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "BANTARBOLANG"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "BELIK"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "COMAL"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "PEMALANG"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "PETARUKAN"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "RANDUDONGKAL"},
    {"branch": "PEKALONGAN", "city": "PEMALANG", "kec": "WATUKUMPUL"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "BOBOTSARI"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "BOJONGSARI"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "BUKATEJA"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "KARANGJAMBU"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "KARANGREJA"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "KEMANGKON"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA", "kec": "MREBET"},
    {"branch": "PEKALONGAN", "city": "TEGAL", "kec": "DUKUHTURI"},
    {"branch": "PEKALONGAN", "city": "TEGAL", "kec": "KRAMAT"},
    {"branch": "PEKALONGAN", "city": "TEGAL", "kec": "PANGKAH"},
    {"branch": "PURWOKERTO", "city": "BANYUMAS", "kec": "JATILAWANG"},
    {"branch": "PURWOKERTO", "city": "BANYUMAS", "kec": "KEBASEN"},
    {"branch": "PURWOKERTO", "city": "BANYUMAS", "kec": "LUMBIR"},
    {"branch": "PURWOKERTO", "city": "BANYUMAS", "kec": "PURWOJATI"},
    {"branch": "PURWOKERTO", "city": "BANYUMAS", "kec": "RAWALO"},
    {"branch": "SEMARANG", "city": "DEMAK", "kec": "WEDUNG"},
    {"branch": "SEMARANG", "city": "SEMARANG", "kec": "PABELAN"},
    {"branch": "SEMARANG", "city": "KENDAL", "kec": "BOJA"},
    {"branch": "SEMARANG", "city": "KENDAL", "kec": "BRANGSONG"},
    {"branch": "SEMARANG", "city": "KENDAL", "kec": "KALIWUNGU SELATAN"},
    {"branch": "SEMARANG", "city": "KENDAL", "kec": "KENDAL"},
    {"branch": "SEMARANG", "city": "KENDAL", "kec": "PLANTUNGAN"},
    {"branch": "SEMARANG", "city": "KENDAL", "kec": "SUKOREJO"},
    {"branch": "SURAKARTA", "city": "BOYOLALI", "kec": "BANYUDONO"},
    {"branch": "SURAKARTA", "city": "BOYOLALI", "kec": "NGEMPLAK"},
    {"branch": "SURAKARTA", "city": "BOYOLALI", "kec": "SAMBI"},
    {"branch": "SURAKARTA", "city": "BOYOLALI", "kec": "SAWIT"},
    {"branch": "SURAKARTA", "city": "BOYOLALI", "kec": "TERAS"},
    {"branch": "SURAKARTA", "city": "KLATEN", "kec": "KEMALANG"},
    {"branch": "SURAKARTA", "city": "SUKOHARJO", "kec": "GATAK"},
    {"branch": "SURAKARTA", "city": "SUKOHARJO", "kec": "MOJOLABAN"},
    {"branch": "SURAKARTA", "city": "SUKOHARJO", "kec": "POLOKARTO"},
    {"branch": "YOGYAKARTA", "city": "SLEMAN", "kec": "KALASAN"},
    {"branch": "YOGYAKARTA", "city": "BANTUL", "kec": "PAJANGAN"},
    {"branch": "YOGYAKARTA", "city": "BANTUL", "kec": "PLERET"},
]
assert len(KEC_47) == 47

AGRESIF_CITY_4 = [
    {"branch": "PEKALONGAN", "city": "BATANG"},
    {"branch": "PEKALONGAN", "city": "KOTA TEGAL"},
    {"branch": "PURWOKERTO", "city": "CILACAP"},
    {"branch": "SEMARANG", "city": "REMBANG"},
]
assert len(AGRESIF_CITY_4) == 4

FMC_NEW_13 = [
    {"branch": "MAGELANG", "city": "KEBUMEN"},
    {"branch": "MAGELANG", "city": "KOTA MAGELANG"},
    {"branch": "PURWOKERTO", "city": "BANJARNEGARA"},
    {"branch": "PURWOKERTO", "city": "CILACAP"},
    {"branch": "SEMARANG", "city": "JEPARA"},
    {"branch": "SEMARANG", "city": "KENDAL"},
    {"branch": "SEMARANG", "city": "KOTA SALATIGA"},
    {"branch": "SEMARANG", "city": "KOTA SEMARANG"},
    {"branch": "SEMARANG", "city": "KUDUS"},
    {"branch": "SURAKARTA", "city": "BOYOLALI"},
    {"branch": "SURAKARTA", "city": "KOTA SURAKARTA"},
    {"branch": "SURAKARTA", "city": "SRAGEN"},
    {"branch": "YOGYAKARTA", "city": "SLEMAN"},
    {"branch": "MAGELANG", "city": "PURWOREJO"},   # ditambahkan 14-Okt-2026
    # ditambahkan 04-Nov-2026: semua city selain REMBANG, TEMANGGUNG, MAGELANG
    {"branch": "PURWOKERTO", "city": "BANYUMAS"},
    {"branch": "PURWOKERTO", "city": "WONOSOBO"},
    {"branch": "SEMARANG", "city": "DEMAK"},
    {"branch": "SEMARANG", "city": "PATI"},
    {"branch": "SEMARANG", "city": "SEMARANG"},
    {"branch": "SURAKARTA", "city": "KARANGANYAR"},
    {"branch": "SURAKARTA", "city": "SUKOHARJO"},
    {"branch": "SURAKARTA", "city": "WONOGIRI"},
    {"branch": "YOGYAKARTA", "city": "BANTUL"},
    {"branch": "YOGYAKARTA", "city": "GUNUNGKIDUL"},
    {"branch": "YOGYAKARTA", "city": "KOTA YOGYAKARTA"},
]
assert len(FMC_NEW_13) == 25

FMC_OLD_12 = [
    {"branch": "PEKALONGAN", "city": "BATANG"},
    {"branch": "PEKALONGAN", "city": "BREBES"},
    {"branch": "PEKALONGAN", "city": "KOTA PEKALONGAN"},
    {"branch": "PEKALONGAN", "city": "KOTA TEGAL"},
    {"branch": "PEKALONGAN", "city": "PEKALONGAN"},
    {"branch": "PEKALONGAN", "city": "PEMALANG"},
    {"branch": "PURWOKERTO", "city": "PURBALINGGA"},
    {"branch": "PEKALONGAN", "city": "TEGAL"},
    {"branch": "SURAKARTA", "city": "BLORA"},
    {"branch": "SURAKARTA", "city": "GROBOGAN"},
    {"branch": "SURAKARTA", "city": "KLATEN"},
    {"branch": "YOGYAKARTA", "city": "KULON PROGO"},
]
assert len(FMC_OLD_12) == 12

# Penamaan seksi report FMC sejak 04-Nov-2026 (nama var *_NEW_13/*_OLD_12 di atas
# dipertahankan krn dipakai modul lain). Urutan tampil: v.1, v.2, v.3.
#   FMC City v.1 = eks OLD FMC CITY (12)
#   FMC City v.2 = eks NEW FMC CITY asli (13, tanpa PURWOREJO)
#   FMC City v.3 = PURWOREJO + 11 city tambahan 04-Nov-2026 (12)
FMC_V1 = FMC_OLD_12
FMC_V2 = FMC_NEW_13[:13]
FMC_V3 = FMC_NEW_13[13:]
assert len(FMC_V1) == 12 and len(FMC_V2) == 13 and len(FMC_V3) == 12
assert FMC_V3[0]["city"] == "PURWOREJO"

# Urutan branch dipakai utk baris subtotal & TOP/Worst ranking level-branch.
BRANCH_ORDER_AGRESIF = ["MAGELANG", "PEKALONGAN", "PURWOKERTO", "SEMARANG",
                         "SURAKARTA", "YOGYAKARTA"]
