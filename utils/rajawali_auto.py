"""
rajawali_auto.py — otomasi penuh report pagi lewat Prisma Browser + SQL Console Rajawali.

Alur (berhenti dengan pesan jelas di langkah yang gagal):
  1. Buka Prisma bila tertutup, bawa ke depan & maksimalkan (tata letak sama di resolusi mana pun).
  2. Layar PIN -> isi PIN dari Windows Credential Manager (bila sudah diatur), kalau tidak tunggu kamu.
  3. Buka Rajawali: tab yang sudah ada di-refresh (F5), kalau tidak ada dibuka di tab baru.
  4. Halaman login -> isi dari Credential Manager (bila langkah login sudah direkam), kalau tidak tunggu kamu.
  5. Buka SQL Console (langkah hasil rekaman rajawali_rekam.py, disimpan di rajawali_auto.json).
  6. Untuk tiap query: tempel SQL, Ctrl+Enter, tunggu "... rows • N s", klik Export, tunggu unduhan.
  7. Generate report (utils/csv_report_runner.py) dan, dengan --kirim, kirim ke grup koordinasi.

Langkah tambahan (laporan 5so7so / clockin): SCRAPING SELA dulu (sources.detail_sf_indihome --auto di folder
scraping) -> file detail-homepass_<awal bulan>_sd_<tanggal laporan>.xlsx = DJP bulan ini untuk 5SO/7SO, lalu
setelah 7SO file itu dikirim (caption 'Raw Data Clockin Homepass MTD ...') dan Report Clock-in SF Teritory dibuat.
  --lewati-scraping  pakai file homepass yang sudah ada (--djp-file atau yang terbaru)

Semua pencarian tombol pakai OCR teks di jendela (rajawali_ui.py) -> tidak tergantung resolusi layar.
Hanya SQL SELECT/WITH yang boleh dijalankan (Console sekarang "read + writes").

  python utils/rajawali_auto.py                       # tanggal laporan = kemarin, dry-run (TIDAK kirim)
  python utils/rajawali_auto.py --kirim               # kirim ke grup koordinasi
  python utils/rajawali_auto.py --tanggal 25-10-2026 --hanya query      # sampai unduhan saja
  python utils/rajawali_auto.py --hanya report --tanggal 25-10-2026     # pakai unduhan yang sudah ada
  python utils/rajawali_auto.py --atur-pin            # simpan PIN Prisma ke Windows Credential Manager
  python utils/rajawali_auto.py --atur-login          # simpan user/password Rajawali ke Credential Manager
  python utils/rajawali_auto.py --pakai-rekaman rekaman/<waktu>/langkah.json   # jadikan langkah buka SQL Console
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # root proyek (script ini ada di utils/)
sys.path.insert(0, BASE)
# utils/ tetap PALING DEPAN: di PC yang dulu memakai versi lama masih ada rajawali_ui.py di root proyek, yang
# kalau terbaca duluan bikin error (mis. "module 'rajawali_ui' has no attribute 'uia_cari'", server 28-10).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _sub in ("logs", "logs/screenshots", "state", "locks", "sql_packets", "downloads"):
    os.makedirs(os.path.join(BASE, "storage", _sub), exist_ok=True)
KONFIG = os.path.join(BASE, "storage", "state", "rajawali_auto.json")
ENV = os.path.join(BASE, ".env")


def _default_rajawali_url() -> str:
    if os.environ.get("RAJAWALI_URL"):
        return os.environ["RAJAWALI_URL"].strip()
    if os.path.exists(ENV):
        try:
            from dotenv import dotenv_values
            v = (dotenv_values(ENV, interpolate=False, encoding="utf-8-sig").get("RAJAWALI_URL") or "").strip()
            if v:
                return v
        except Exception:
            pass
    return ""


DEFAULT = {
    "url": _default_rajawali_url(),
    "pola_tab": "Rajawali|Worklist|IO-RE-PS|Performance",
    "pola_pin": "Enter your PIN|unlock the browser",
    "pola_login": r"Masuk ke Rajawali|login manual|Login dengan SSO",
    "pola_siap": "WORKLIST|SUMMARY|ANALYTIC|DASHBOARD|SALES",
    "pola_console": r"read \+ writes|\bin use\b",   # modal SQL Console sudah tampil
    "pola_menu_console": r"Console",           # item "SQL Console" di menu profil (OCR kadang membaca SOL/su)
    "avatar_dari_kanan_atas": [92, 140],                   # px (skala 100%) dari pojok kanan atas jendela
    "avatar_dari_nama": 144,                   # px (skala 100%) dari ujung kanan nama pengguna di header
    "buka_console": [],          # langkah klik hasil rekaman (lihat --pakai-rekaman)
    "login": [],                 # langkah isi login hasil rekaman (opsional)
    "editor_dari_history": [-250, 65],   # titik klik editor relatif teks "History" (UI SQL Console baru)
    "batas_query_detik": 1800,
    "batas_unduh_detik": 600,
    "maks_blok_detik": 120,      # blok tanpa jeda lebih lama dari ini -> dianggap macet, program berhenti
    "folder_unduhan": os.path.join(os.path.expanduser("~"), "Downloads"),
    "maks_ulang": 3,             # percobaan per tahap (siapkan sesi / tiap query); ulang dari awal: refresh -> login bila perlu
    "stabil_detik": 8,           # halaman dianggap selesai dimuat bila layarnya tidak berubah selama sekian detik
    "batas_muat_detik": 120,     # batas tunggu halaman Rajawali selesai dimuat
    "hari_simpan_bukti": 14,     # tangkapan layar kegagalan di rajawali_bukti/ dihapus setelah sekian hari
    "folder_scraping": os.path.join(BASE, "storage", "sela"),   # folder data scraping SELA (python -m utils.sela_scraper)
    "scraping_delay": "0.5",      # DIGIPOS_SF_DELAY
    "scraping_size": "200",       # DIGIPOS_SF_SIZE
    "scraping_headless": False,   # True = tanpa jendela (hanya bila sesi login SELA masih tersimpan)
    "batas_scraping_detik": 5400,
}
BUKTI_DIR = os.path.join(BASE, "storage", "logs", "screenshots")
CRED = "rajawali_auto"


class TidakDiulang(RuntimeError):
    """Kegagalan yang percuma diulang (atau berbahaya diulang, mis. login ditolak -> akun bisa terkunci)."""
TULIS = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE\s+INTO|GRANT|REVOKE|RENAME|"
                   r"LOAD\s+DATA|INTO\s+OUTFILE|CALL|SET)\b", re.I)


def _kunci_ui(batas=3600):
    """Kunci file antar-proses: runner lain (dari bot Telegram / WhatsApp / manual) menunggu sampai langkah UI
    Prisma runner ini selesai. Lepas otomatis saat proses berakhir. Return handle file (simpan selama dipakai)."""
    import msvcrt
    f = open(os.path.join(BASE, "storage", "locks", "rajawali_auto.lock"), "a+")
    t0, dilapor = time.time(), False
    while True:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return f
        except OSError:
            if not dilapor:
                log("Otomasi Rajawali lain sedang berjalan -> menunggu giliran")
                dilapor = True
            if time.time() - t0 > batas:
                raise RuntimeError(f"Menunggu otomasi Rajawali lain lebih dari {batas // 60} menit")
            time.sleep(3)


def log(t):
    s = f"[{datetime.now():%H:%M:%S}] {t}"
    print(s, flush=True)
    with open(os.path.join(BASE, "storage", "logs", "rajawali_auto.log"), "a", encoding="utf-8") as f:
        f.write(s + "\n")


def konfig():
    k = dict(DEFAULT)
    if os.path.exists(KONFIG):
        k.update(json.load(open(KONFIG, encoding="utf-8")))
    return k


ENV = os.path.join(BASE, ".env")
ENV_KUNCI = {"prisma_pin": "PRISMA_PIN", "rajawali_user": "RAJAWALI_USER", "rajawali_pass": "RAJAWALI_PASS"}


def rahasia(nama):
    """PIN/login dari .env (PRISMA_PIN, RAJAWALI_USER, RAJAWALI_PASS); fallback Windows Credential Manager."""
    from dotenv import dotenv_values
    k = ENV_KUNCI[nama]
    v = dotenv_values(ENV, interpolate=False, encoding="utf-8-sig").get(k)
    if v:
        return v
    try:
        import keyring
        return keyring.get_password(CRED, nama) or None
    except Exception:
        return None


def tulis_env(kunci, nilai):
    """Ganti/tambah baris KUNCI=nilai di .env menggunakan python-dotenv."""
    from dotenv import set_key
    if not os.path.exists(ENV):
        open(ENV, "w", encoding="utf-8").close()
    set_key(ENV, kunci, str(nilai), quote_mode="never")


# ── langkah UI ───────────────────────────────────────────────────────────────
def _bukti(R, h, nama):
    """Simpan tangkapan layar + hasil OCR (teks & posisi) jendela Prisma, untuk diagnosa di PC lain
    (resolusi/skala/bahasa OCR berbeda). Return path png, atau '' bila gagal."""
    try:
        img, (l, t, r, b) = R.layar(h)
        os.makedirs(BUKTI_DIR, exist_ok=True)
        dasar = os.path.join(BUKTI_DIR, f"rajawali_gagal_{nama}_{datetime.now():%Y%m%d_%H%M%S}")
        img.save(dasar + ".png")
        eng = R._engine()
        with open(dasar + ".txt", "w", encoding="utf-8") as f:
            f.write(f"jendela={R.judul(h)!r} rect={(l, t, r, b)} ukuran={r - l}x{b - t} "
                    f"dpi={R.skala_dpi(h):.2f} bahasa_ocr={getattr(getattr(eng, 'recognizer_language', None), 'language_tag', None)}\n")
            for k in R.ocr(img, 1.5):
                f.write(f"{k.x},{k.y},{k.w},{k.h}\t{k.teks}\n")
        log(f"  bukti diagnosa: {dasar}.png / .txt")
        return dasar + ".png"
    except Exception as e:
        log(f"  gagal menyimpan bukti diagnosa: {e}")
        return ""


def _tunggu_manual(R, h, selesai_jika, pesan, batas=900):
    terblok = R.blok_aktif()
    if terblok:
        R.blok_input(False)          # lepas blok supaya kamu bisa mengisi sendiri
    log(f"MENUNGGU KAMU: {pesan} (maks {batas // 60} menit)")
    try:
        return _tunggu_loop(R, h, selesai_jika, pesan, batas)
    finally:
        if terblok:
            time.sleep(1)
            R.blok_input(True)
            log("Input mouse/keyboard diblok lagi")


def _tunggu_loop(R, h, selesai_jika, pesan, batas):
    t0 = time.time()
    while time.time() - t0 < batas:
        time.sleep(5)
        ws = [w for w in R.jendela_prisma() if w[1].strip()] or R.jendela_prisma()
        h = ws[0][0] if ws else h
        if selesai_jika(h):
            return h
    raise RuntimeError(f"Tidak selesai dalam {batas // 60} menit: {pesan}")


def _keadaan_prisma(R, K, batas=45):
    """Tunggu Prisma stabil: ('pin', hwnd) bila layar PIN tampil, ('browser', hwnd) bila jendela browser
    (berjudul, mis. 'New Tab - ...') sudah ada. Layar PIN bisa muncul beberapa detik SETELAH jendela pertama
    tampil, jadi jangan menyimpulkan 'terbuka' dari satu kali cek."""
    t0, dibuka_ulang = time.time(), 0
    t_mulai, diperpanjang = t0, False
    while time.time() - t0 < batas:
        ws = R.jendela_prisma()
        # layar "Please wait / Thank you for your patience" (Prisma masih connect/sign-in) bisa > 1 menit
        # di PC lain (diamati di server 27-10) -> selama layar itu tampil, tunggu sampai maks 5 menit
        if ws and time.time() - t_mulai < 300 and any(R.cari(w[0], r"Please wait|patience") for w in ws):
            if not diperpanjang:
                log("Prisma masih 'Please wait' (connect) -> menunggu lebih lama (maks 5 menit)")
                diperpanjang = True
            t0 = time.time()
            R.tidur(3)
            continue

        if not ws and dibuka_ulang < 2:
            # Prisma tertutup sendiri (diamati 27-10 12:20) -> buka lagi & ulang hitung waktu
            log("Jendela Prisma hilang -> membuka ulang")
            R.pastikan_prisma(log=log)
            t0, dibuka_ulang = time.time(), dibuka_ulang + 1
            continue
        for h, judul, _ in ws:
            if R.cari(h, K["pola_pin"]):
                return "pin", h
        br = [w for w in ws if w[1].strip()]
        if br and time.time() - t0 > 8:        # beri waktu layar PIN menyusul
            return "browser", br[0][0]
        R.tidur(2)
    ws = R.jendela_prisma()
    bukti = ""
    if ws:
        img, _ = R.layar(ws[0][0])
        os.makedirs(BUKTI_DIR, exist_ok=True)
        bukti = os.path.join(BUKTI_DIR, f"rajawali_gagal_prisma_{datetime.now():%Y%m%d_%H%M%S}.png")
        img.save(bukti)
    raise RuntimeError(f"Prisma tidak menampilkan layar PIN maupun jendela browser "
                       f"(jendela: {[w[1] for w in ws]}){' — tangkapan layar: ' + bukti if bukti else ''}")


def buka_prisma_dan_pin(R, K):
    R.pastikan_prisma(log=log)
    keadaan, h = _keadaan_prisma(R, K)
    log(f"Prisma: {'layar PIN' if keadaan == 'pin' else 'browser sudah terbuka'}")
    R.depan(h, maksimal=False)
    if keadaan == "pin":
        pin = rahasia("prisma_pin")
        if pin:
            log("Layar PIN -> mengisi PIN dari .env")
            R.ketik(pin)
            R.tidur(6)

        def terbuka(_):
            ws = R.jendela_prisma()
            return any(w[1].strip() for w in ws) and not any(R.cari(w[0], K["pola_pin"]) for w in ws)
        if not terbuka(None):
            _tunggu_manual(R, h, terbuka, "buka kunci Prisma (isi PIN)", 600)
        log("Prisma terbuka")
        R.tidur(3)
    h = _jendela_browser(R)
    R.depan(h, maksimal=True)
    return h


def _jendela_browser(R):
    """Jendela browser utama = jendela Prisma berjudul terbesar (layar PIN tidak berjudul)."""
    ws = [w for w in R.jendela_prisma() if w[1].strip()]
    if not ws:
        raise RuntimeError("Jendela browser Prisma tidak ditemukan.")
    return ws[0][0]


def buka_rajawali(R, K, h):
    """Urutan (sengaja ketat; SQL Console TIDAK disentuh sebelum halaman benar-benar selesai dimuat, karena reload
    yang datang belakangan membuat langkah query macet):
      1. buka ULANG URL dashboard di tab Rajawali yang ada (tab baru hanya bila belum ada) -> menyegarkan sesi/401;
      2. tunggu sampai halaman selesai dimuat dan layar diam beberapa detik;
      3. halaman login (sesi habis) -> login dari .env, lalu tunggu selesai dimuat lagi;
      4. halaman dashboard (sesi masih berlaku) -> lanjut."""
    if any(R.cari(w[0], K["pola_pin"]) for w in R.jendela_prisma()):
        raise RuntimeError("Layar PIN Prisma masih tampil; tidak mengetik apa pun supaya tidak salah PIN.")
    _muat_url(R, K, h)
    R.tidur(5)
    kead = _tunggu_halaman_stabil(R, K, h, K["batas_muat_detik"])
    if kead == "login":
        log("Sesi habis (halaman login) -> login")
        h = masuk_login(R, K, h)
        kead = _tunggu_halaman_stabil(R, K, h, K["batas_muat_detik"])
        if kead != "siap":
            raise RuntimeError("Setelah login, halaman Rajawali tidak menampilkan dashboard.")
    log("Rajawali siap (halaman selesai dimuat)")
    return h


# Halaman galat / sesi habis. "401" hanya dipercaya di judul tab (angka 401 bisa saja ada di isi dashboard).
POLA_GALAT_TEKS = (r"Unauthori[sz]ed|ERR_[A-Z_]{4,}|can.?t be reached|This site can|Bad Gateway|Service Unavailable|"
                   r"Gateway Time-?out|HTTP ERROR|Session (expired|timed? ?out)|Sesi\b.*\b(habis|berakhir|kedaluwarsa)")
POLA_GALAT_JUDUL = r"\b401\b|Unauthori[sz]ed|\bError\b|ERR_[A-Z_]{4,}"


def _muat_url(R, K, h):
    """Buka ulang URL dashboard lewat address bar (bukan F5: F5 pada halaman 401 hanya mengulang halaman galat).
    Tab Rajawali yang ada dipakai ulang; tab kosong/galat dipakai di tempat; baru kalau tidak ada, tab baru."""
    tab = R.cari(h, K["pola_tab"], area=(0, 0, 1, _fy(R, h, TAB_PX)))
    if tab:
        log(f"Tab Rajawali sudah ada ({tab.teks!r}) -> buka ulang URL")
        R.klik(h, tab)
    elif re.search(POLA_GALAT_JUDUL + r"|New Tab|Tab Baru|about:blank", R.judul(h), re.I):
        log("Tab aktif kosong/galat -> dipakai untuk membuka Rajawali")
    else:
        log("Membuka Rajawali di tab baru")
        R.tekan("^t")
        R.tidur(1)
    R.tekan("^l")
    R.ketik(K["url"])
    R.tekan("{ENTER}")


def _tunggu_halaman_stabil(R, K, h, batas=120):
    """Tunggu halaman Rajawali SELESAI dimuat: keadaannya ('login' atau 'siap') sama dan layarnya tidak berubah
    selama K['stabil_detik']. Layar yang masih berubah = masih memuat/redirect/reload. Halaman galat/sesi habis
    (401) -> URL dibuka ulang (maks 2x). Return 'login' | 'siap'."""
    from PIL import ImageChops
    t0, prev, tenang, keadaan, ulang_url = time.time(), None, 0, None, 0
    butuh = max(2, round(K["stabil_detik"] / 2))
    while time.time() - t0 < batas:
        img, _ = R.layar(h)
        isi = img.crop((0, int(_fy(R, h, ISI_PX) * img.height), img.width, img.height))
        teks = " ".join(k.teks for k in R.ocr(isi, 1.5))
        judul = R.judul(h)
        if re.search(POLA_GALAT_TEKS, teks, re.I) or re.search(POLA_GALAT_JUDUL, judul, re.I):
            kead = "galat"
        elif re.search(r"^\s*(Login|Masuk)\b", judul, re.I) or re.search(K["pola_login"], teks, re.I):
            kead = "login"
        elif re.search(K["pola_siap"], teks, re.I):
            kead = "siap"
        else:
            kead = None
        kecil = isi.convert("L").resize((320, 180))
        # piksel yang berubah nyata di antara dua cuplikan; jam/watermark yang berdetak hanya mengubah segelintir piksel
        ubah = (ImageChops.difference(kecil, prev).point(lambda v: 255 if v > 40 else 0).histogram()[255]
                if prev is not None else 10 ** 6)
        prev = kecil
        if kead in ("login", "siap") and kead == keadaan and ubah <= 150:
            tenang += 1
        else:
            tenang = 0
        keadaan = kead
        if tenang >= butuh:
            return kead
        if kead == "galat":
            ulang_url += 1
            if ulang_url > 2:
                _bukti(R, h, "halaman_galat")
                raise RuntimeError(f"Halaman Rajawali tetap galat/sesi habis setelah URL dibuka ulang 2x (judul: {judul!r}).")
            log(f"Halaman galat/sesi habis (judul {judul!r}) -> buka ulang URL ({ulang_url}/2)")
            _muat_url(R, K, h)
            R.tidur(5)
            prev, tenang = None, 0
            continue
        R.tidur(2)
    if keadaan in ("login", "siap"):
        log(f"PERINGATAN: layar tak pernah sepenuhnya diam dalam {batas}s (jam/animasi?) -> lanjut, keadaan '{keadaan}'")
        return keadaan
    _bukti(R, h, "halaman_tak_termuat")
    raise RuntimeError(f"Halaman Rajawali belum selesai dimuat dalam {batas} detik (keadaan terakhir: {keadaan}; cek VPN/Prisma).")


# Tinggi bar tab & address bar Prisma TETAP dalam piksel (x skala DPI), tidak ikut tinggi jendela; jadi batasnya
# dihitung dari piksel, bukan persen (di layar 2560x1080, 7% tinggi sudah mencakup address bar berisi URL ".../rajawali").
TAB_PX, ISI_PX = 50, 92       # bawah bar tab / bawah address bar, px pada skala 100%


def _fy(R, h, px):
    l, t, r, b = R.rect(h)
    return min(1.0, px * R.skala_dpi(h) / max(1, b - t))


def _isi(R, h):
    """Area isi halaman (tanpa tab & address bar, yang memuat URL .../dashboard)."""
    return (0, _fy(R, h, ISI_PX), 1, 1)


def _halaman(R, K, h):
    """'login' / 'siap' / None. Judul jendela = judul tab aktif (mis. 'Login — Rajawali - Prisma Browser')."""
    if re.search(r"^\s*(Login|Masuk)\b", R.judul(h), re.I) or R.cari(h, K["pola_login"], area=_isi(R, h)):
        return "login"
    if R.cari(h, K["pola_siap"], area=_isi(R, h)):
        return "siap"
    return None


def _patokan_login_manual(ks):
    """Baris "atau login manual". Watermark Telkomsel (nama/email + jam) sering menimpa sebagian kata, mis. di server
    27-10 terbaca "atau in manual" -> cukup "atau ... manual" / "login ... manual", atau kata "manual" sendiri."""
    return (next((k for k in ks if re.search(r"\b(atau|login)\b.*\bmanual\b", k.teks, re.I)), None)
            or next((k for k in ks if re.fullmatch(r"manual", k.teks.strip(), re.I)), None))


def _login_uia(R, h, user, pw):
    """Login lewat UI Automation: kolom #username / #password dicari per id, fokus dipindah langsung (bukan klik) dan
    DIPASTIKAN sebelum mengetik; isi Username dibaca balik dari elemennya. Password hanya diketik bila fokus terbukti
    di kolom Password. Return True = sudah Enter, None = form tak terbaca lewat UIA (pakai OCR).
    Bila ada yang tidak sesuai, kedua kolom dikosongkan lalu RuntimeError (tidak lanjut ke OCR, supaya tak mengetik
    password dua kali)."""
    eu = R.uia_cari(h, aid="username", batas=8)
    ep = R.uia_cari(h, aid="password") if eu else None
    if not (eu and ep):
        return None

    def kosongkan():
        for e in (eu, ep):
            if R.uia_fokus(e):
                R.tekan("^a")
                R.tekan("{BACKSPACE}")

    R._pastikan_depan(h)
    log("Halaman login -> mengisi user/password dari .env (UI Automation)")
    if not R.uia_fokus(eu):
        return None
    R.tekan("^a")
    R.tekan("{BACKSPACE}")
    R.ketik(user, jeda=0.05)
    R.tidur(0.3)
    R.tekan("{ESC}")                      # tutup dropdown riwayat username
    R.tidur(0.3)
    if (R.uia_nilai(eu) or "") != user or not R.uia_fokus(ep):
        kosongkan()
        raise RuntimeError("Isi kolom Username tidak sesuai / fokus ke kolom Password gagal; kolom dikosongkan, "
                           "login dibatalkan (password belum diketik).")
    R.tekan("^a")
    R.tekan("{BACKSPACE}")
    R.ketik(pw, jeda=0.05)
    R.tidur(0.3)
    if (R.uia_nilai(eu) or "") != user or not ep.CurrentHasKeyboardFocus:
        kosongkan()
        raise RuntimeError("Isi kolom Username berubah saat mengetik password; kolom dikosongkan, login dibatalkan.")
    R.tekan("{ENTER}")
    return True


def masuk_login(R, K, h):
    """Login manual LDAP: lewat UI Automation dulu (_login_uia); bila form tak terbaca, klik kolom Username/Password
    berdasarkan OCR (posisi dihitung dari teks "login manual" & tombol "Log In"). Isi dari .env, Enter.
    TIDAK diulang bila gagal, supaya akun tidak terkunci."""
    user, pw = rahasia("rajawali_user"), rahasia("rajawali_pass")
    if user and pw and _login_uia(R, h, user, pw):
        for _ in range(10):
            R.tidur(3)
            if _halaman(R, K, h) == "siap":
                break
        er = R.cari(h, r"salah|invalid|incorrect|gagal|failed|tidak valid|wrong|wajib diisi", area=_isi(R, h))
        if er:
            raise TidakDiulang(f"Login Rajawali ditolak: {er.teks!r} (tidak diulang; cek RAJAWALI_USER/PASS di .env)")
    elif user and pw:
        log("Form login tidak terbaca lewat UI Automation -> pakai OCR")
        _login_ocr(R, K, h, user, pw)
    if _halaman(R, K, h) != "siap":
        h = _tunggu_manual(R, h, lambda x: _halaman(R, K, x) == "siap", "login ke Rajawali")
    log("Login Rajawali OK")
    return h


def _login_ocr(R, K, h, user, pw):
    """Cadangan masuk_login: posisi kolom dari OCR (teks "atau login manual" & tombol "Log In"/"Ingat")."""
    img, (l, t, r, b) = R.layar(h)
    ks = [k for k in R.ocr(img, 1.5) if k.y > ISI_PX * R.skala_dpi(h)]
    atas = _patokan_login_manual(ks)
    bawah = rasio = None
    if atas:
        # patokan bawah: tombol "Log In" (bisa redup/tak terbaca) atau teks "Ingat username saya".
        # rasio = posisi kolom Username & Password di antara "atau login manual" dan patokan bawah.
        for pola, rs in ((r"Log\s*In", (0.285, 0.62)), (r"Ingat\b.*", (0.36, 0.79))):
            bawah = next((k for k in ks if k.y > atas.y + atas.h and re.fullmatch(pola, k.teks.strip(), re.I)), None)
            if bawah:
                rasio = rs
                break
    if atas and bawah:
        y0, y1 = atas.y + atas.h // 2, bawah.y + bawah.h // 2
        x, W_, H_ = atas.tengah[0], r - l, b - t
        log("Halaman login -> mengisi user/password dari .env")
        R.klik(h, (x / W_, (y0 + rasio[0] * (y1 - y0)) / H_))
        R.tekan("^a")
        R.ketik(user, jeda=0.05)
        R.tidur(0.3)
        R.tekan("{ESC}")      # tutup dropdown riwayat username; kalau tidak, klik berikut hanya menutupnya
        R.tidur(0.3)          # dan password ikut terketik di kolom Username (terlihat!)
        R.klik(h, ((x - 60) / W_, (y0 + rasio[1] * (y1 - y0)) / H_))   # agak ke kiri, jauh dari ikon mata
        R.tidur(0.5)
        R.tekan("^a")
        R.tekan("{BACKSPACE}")
        R.ketik(pw, jeda=0.1)
        # pengaman: kolom Username harus tetap berisi username (bukan password yang salah kolom)
        uy = int(y0 + rasio[0] * (y1 - y0))
        img2, _ = R.layar(h)
        isi = next((k.teks for k in R.ocr(img2.crop((x - 175, uy - 18, x + 175, uy + 18)), 2)), "")
        if user.lower() not in isi.lower().replace(" ", ""):
            for fy in (uy, int(y0 + rasio[1] * (y1 - y0))):
                R.klik(h, ((x - 60) / W_, fy / H_))
                R.tekan("^a")
                R.tekan("{BACKSPACE}")
            raise RuntimeError("Isi kolom Username tidak sesuai setelah mengetik; kolom dikosongkan, login dibatalkan.")
        R.tekan("{ENTER}")
        for _ in range(10):
            R.tidur(3)
            if _halaman(R, K, h) == "siap":
                break
        er = R.cari(h, r"salah|invalid|incorrect|gagal|failed|tidak valid|wrong", area=_isi(R, h))
        if er:
            raise TidakDiulang(f"Login Rajawali ditolak: {er.teks!r} (tidak diulang; cek RAJAWALI_USER/PASS di .env)")
    else:
        log(f"Form login manual tidak ditemukan lewat OCR (patokan 'login manual': {bool(atas)}, "
            f"'Log In'/'Ingat': {bool(bawah)})")
        _bukti(R, h, "login")


def putar_klik(R, h, lk):
    """Ulang satu klik rekaman: cari teks anchor-nya dulu (tahan perubahan resolusi), fallback posisi relatif."""
    img, (l, t, r, b) = R.layar(h)
    if lk.get("anchor"):
        k = R.cari(h, re.escape(lk["anchor"]), img=img)
        if k:
            sx = (r - l) / lk["ukuran_jendela"][0] if lk.get("ukuran_jendela") else 1
            sy = (b - t) / lk["ukuran_jendela"][1] if lk.get("ukuran_jendela") else 1
            dx, dy = lk.get("offset_anchor") or (0, 0)
            cx, cy = k.tengah
            R.klik(h, ((cx + dx * sx) / (r - l), (cy + dy * sy) / (b - t)))
            return
    R.klik(h, (lk["fx"], lk["fy"]))


def buka_console(R, K, h):
    """SQL Console = modal dari menu profil: klik avatar (pojok kanan atas) -> 'SQL Console'."""
    if R.cari(h, K["pola_console"]):
        return h
    R.tekan("{ESC}")                              # tutup menu/popup yang mungkin terbuka
    if _buka_console_uia(R, h):
        log("SQL Console terbuka (UI Automation)")
        return h
    if K["buka_console"]:                         # langkah hasil rekaman (opsional) didahulukan
        for lk in K["buka_console"]:
            if lk["jenis"] == "klik":
                putar_klik(R, h, lk)
            elif lk.get("keys"):
                R.tekan(lk["keys"])
            R.tidur(1.5)
    else:
        log("Membuka menu profil -> SQL Console")
        m = None
        for i, titik in enumerate(_titik_avatar(R, K, h)):
            if i:
                R.tekan("{ESC}")
                log("  menu profil belum muncul -> coba posisi avatar berikutnya")
            R.klik(h, titik)
            m = R.tunggu_teks(h, K["pola_menu_console"], batas=5, jeda=1, area=(0.4, 0.1, 1, 0.7))
            if m:
                break
        if not m:
            _bukti(R, h, "menu_profil")
            h = _tunggu_manual(R, h, lambda x: bool(R.cari(x, K["pola_console"])),
                               "buka SQL Console (menu profil tidak ditemukan)")
            return h
        R.klik(h, m)
    if not R.tunggu_teks(h, K["pola_console"], batas=30):
        raise RuntimeError("SQL Console tidak terbuka.")
    log("SQL Console terbuka")
    return h


def _buka_console_uia(R, h):
    """Menu profil -> SQL Console lewat UI Automation. Avatar = item TERAKHIR di daftar ikon header yang memuat
    #v3WhatsNew (urutan: #v3MenuSearch, #v3WhatsNew, avatar tanpa nama). Item menu = tombol bernama "... SQL Console".
    Berhasil bila #sqlcText (editor SQL) muncul. Return False (pakai cara OCR) bila ada yang tak ketemu."""
    try:
        wn = R.uia_cari(h, aid="v3WhatsNew", batas=10)
        daftar = R.uia_induk(wn) if wn else None
        anak = R.uia_anak(daftar.element) if daftar else []
        if not anak:
            return False
        log("Membuka menu profil -> SQL Console (UI Automation)")
        R._pastikan_depan(h)
        avatar = anak[-1]
        for _ in range(2):
            if not R.uia_klik(avatar.element):
                return False
            R.tidur(1.2)
            menu = next((e for e in R.uia_turunan(avatar.element)
                         if e.control_type == "Button" and "SQL Console" in (e.name or "")), None)
            if menu:
                break
            R.tekan("{ESC}")
        else:
            log("  menu profil (UI Automation) tidak memuat 'SQL Console'")
            return False
        if not R.uia_klik(menu.element):
            return False
        return bool(R.uia_cari(h, aid="sqlcText", batas=20))
    except Exception as e:
        log(f"  UI Automation gagal ({type(e).__name__}: {e}) -> pakai OCR")
        return False


def _titik_avatar(R, K, h):
    """Calon posisi avatar profil (pecahan 0..1 jendela), dicoba berurutan:
      1. jarak tetap dari pojok kanan atas jendela (header Rajawali rata kanan), ikut skala DPI;
      2. di kanan nama pengguna pada header (teks terkanan di baris header), untuk layar lebar
         yang header-nya tidak menempel ke tepi kanan."""
    l, t, r, b = R.rect(h)
    W_, H_, sk = r - l, b - t, R.skala_dpi(h)
    dx, dy = K["avatar_dari_kanan_atas"]
    img, _ = R.layar(h)
    hasil = []
    p = _avatar_dari_ocr(R.ocr(img, 1.5), W_, H_, sk, K["avatar_dari_nama"])
    if p:
        hasil.append(p)
    hasil.append(((W_ - dx * sk) / W_, (dy * sk) / H_))
    return hasil


def _avatar_dari_ocr(ks, W_, H_, sk, dari_nama):
    """Avatar = kanan nama pengguna di kartu header Rajawali (mis. "Mustika Sari" lalu ikon cari, lonceng, avatar).
    Di layar lebar (2560 px) konten tidak melebar penuh, jadi patokan nama lebih tepat daripada jarak dari tepi
    kanan jendela. Hanya baris kartu header (sekitar 30-90 px di bawah address bar) yang dipakai; baris di bawahnya
    ("Buka Dashboard", "Buka tabel Worklist") sempat salah terpilih di server 27-10."""
    y0, y1 = (ISI_PX + 25) * sk, (ISI_PX + 85) * sk
    cal = [k for k in ks if y0 <= k.y + k.h / 2 <= y1 and k.x > 0.3 * W_ and len(k.teks) >= 4
           and re.search(r"[A-Za-z]{3}", k.teks) and not re.search(r"\d", k.teks)]
    if not cal:
        return None
    nm = max(cal, key=lambda k: k.x + k.w)
    x, y = nm.x + nm.w + dari_nama * sk, nm.y + nm.h // 2
    return (x / W_, y / H_) if x < W_ else None


STATUS = re.compile(r"\d[\d.,]*\s+rows?\b|\brows?\b.*\d+(\.\d+)?\s*s\b", re.I)
ERROR = re.compile(r"error|syntax|denied|timed?\s*out|unknown column|doesn'?t exist|not allowed|gagal", re.I)


_LAYAR = {"img": None}


def _status(R, h):
    img, _ = R.layar(h)
    _LAYAR["img"] = img
    ks = R.ocr(img, 1.5)
    st = next((k for k in ks if STATUS.search(k.teks) and "find" not in k.teks.lower()
               and not RUNS_STATUS.match(k.teks)), None)
    # pesan error hanya dicari DI ATAS tabel hasil (isi tabel bisa berisi kata "FAILED"/"gagal")
    batas_y = st.y - 5 if st else int(0.6 * img.height)
    er = next((k for k in ks if ERROR.search(k.teks) and k.y < batas_y), None)
    return st, er, ks


RUNS_STATUS = re.compile(r"^\W*(Done|Running|Stopped|Failed|Error|Queued|Cancel\w*)\b", re.I)


def _baris_runs(R, ks, img):
    """Baris panel "Runs" (query panjang dipindah ke latar): [(status, potongan_sql, y, tombol_Export|None)],
    urut dari atas (= terbaru). Potongan SQL di-OCR ulang dari crop berkontras tinggi (font kode kecil)."""
    from PIL import ImageOps
    judul = next((k for k in ks if k.teks.strip() == "Runs"), None)
    if not judul:
        return []
    stat = []
    for k in sorted((k for k in ks if k.y > judul.y and RUNS_STATUS.match(k.teks)), key=lambda k: -len(k.teks)):
        if all(abs(k.y - s.y) > 6 for s in stat):
            stat.append(k)
    hasil = []
    for st in sorted(stat, key=lambda k: k.y):
        y = st.y + st.h // 2
        baris = [k for k in ks if abs(k.y + k.h // 2 - y) <= 10]
        awal = [k for k in baris if k.x > st.x + 60 and re.match(r"(?i)\W*(select|with|\()", k.teks)]
        tombol = [k for k in baris if re.fullmatch(r"\W*(View|Export|Remove|Use SQL)", k.teks.strip(), re.I)]
        x0 = min(k.x for k in awal) - 6 if awal else st.x + st.w + 20
        x1 = min([k.x for k in tombol if k.x > x0] or [x0 + 360]) - 6
        crop = ImageOps.autocontrast(img.crop((x0, y - 12, x1, y + 16)).convert("L")).convert("RGB")
        teks = next((k.teks for k in R.ocr(crop, 3.0)), "")
        ex = next((k for k in baris if re.fullmatch(r"\W*Export", k.teks.strip(), re.I)), None)
        hasil.append((st.teks.strip(), teks, y, ex))
    return hasil


def _run_kita(runs, sql):
    """Baris Runs teratas (terbaru) yang SQL-nya = sql kita, atau None."""
    return next((r for r in runs if _cocok_sql(r[1], sql)), None)


SELESAI = re.compile(r"Run\s*(finished|failed|error|cancel)\w*\s*\(?([^)]*)\)?\s*:?\s*(.*)", re.I)


def _norm(s):
    """Samakan teks SQL & hasil OCR: huruf kecil, buang non-alfanumerik, o->0, l/i->1 (salah baca OCR umum)."""
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    return s.translate(str.maketrans("olig", "0119"))


def _cocok_sql(teks_sql_ocr, sql):
    """Apakah potongan SQL di baris 'Run finished (...): <SQL...>' adalah awal `sql` kita?
    Longgar terhadap salah baca OCR, tapi angka bulan (20xxxx) harus persis sama."""
    import difflib
    teks_sql_ocr = re.split(r"\.\.\.|…|Open\s*Runs", teks_sql_ocr, flags=re.I)[0]
    v = _norm(teks_sql_ocr)
    if len(v) < 12:
        return False
    awal = _norm(sql)[:len(v) + 15]           # OCR kadang membuang potongan (mis. teks dalam kutip)
    sm = difflib.SequenceMatcher(None, v, awal, autojunk=False)
    if sum(m.size for m in sm.get_matching_blocks()) / len(v) < 0.85:
        return False
    bulan_ocr = re.findall(r"20\d{4}", re.sub(r"[^0-9]", " ", teks_sql_ocr.translate(str.maketrans("OolIg", "00119"))))
    n = len(re.findall(r"20\d{4}", re.sub(r"[^0-9]", " ", sql[:len(teks_sql_ocr) + 10])))
    bulan_sql = re.findall(r"20\d{4}", re.sub(r"[^0-9]", " ", sql))[:max(n, len(bulan_ocr))]
    return bulan_ocr == bulan_sql[:len(bulan_ocr)]


def _baris_selesai(ks):
    """(jenis, keterangan, potongan_sql, Kata) dari baris 'Run finished (done): SELECT ...', atau None."""
    for k in ks:
        m = SELESAI.search(k.teks)
        if m and len(k.teks) > 20:
            return m.group(1).lower(), m.group(2), m.group(3), k
    return None


def siapkan_sesi(R, K):
    """Dari nol sampai SQL Console terbuka: Prisma (+PIN) -> refresh Rajawali -> (login) -> profil -> SQL Console."""
    h = buka_prisma_dan_pin(R, K)
    h = buka_rajawali(R, K, h)
    return buka_console(R, K, h)


def _ulang(R, K, nama, kerjakan):
    """Jalankan kerjakan(percobaan_ke) sampai K['maks_ulang'] kali. Tiap gagal: simpan bukti (rajawali_bukti/), jeda,
    lalu percobaan berikut. TidakDiulang (login ditolak, SQL tulis, query kelewat batas) langsung dilepas."""
    maks = max(1, int(K["maks_ulang"]))
    for i in range(1, maks + 1):
        try:
            return kerjakan(i)
        except TidakDiulang:
            raise
        except Exception as e:
            ws = R.jendela_prisma()
            if ws:
                _bukti(R, ws[0][0], f"{nama}_percobaan{i}")
            if i >= maks:
                raise
            log(f"{nama}: percobaan {i}/{maks} GAGAL ({type(e).__name__}: {e}) -> ulang dari awal")
            R.tidur(5 * i)


T_MULAI = time.time()


def _notifikasi_gagal(e):
    """Kabari grup Telegram bila otomasi gagal setelah SEMUA percobaan (login ditolak juga dikabari). Dilewati kalau
    dijalankan oleh bot (RAJAWALI_DARI_BOT): bot sudah mengirim notifikasi gagalnya sendiri, jangan dobel."""
    if os.environ.get("RAJAWALI_DARI_BOT"):
        return
    try:
        import socket
        import requests
        import config
        api = f"https://api.telegram.org/bot{config.TOKEN}"
        pesan = (f"❌ Otomasi Rajawali GAGAL (setelah semua percobaan ulang)\n"
                 f"PC: {socket.gethostname()} | {datetime.now():%d-%m-%Y %H:%M}\n"
                 f"Perintah: {' '.join(sys.argv[1:])[:200] or '(default)'}\n"
                 f"Sebab: {type(e).__name__}: {str(e)[:600]}"
                 + ("\nTidak diulang otomatis (cek dulu penyebabnya)." if isinstance(e, TidakDiulang) else ""))
        requests.post(api + "/sendMessage", data={"chat_id": config.GROUP_ID, "text": pesan}, timeout=20)
        foto = sorted(glob.glob(os.path.join(BUKTI_DIR, "rajawali_gagal_*.png")), key=os.path.getmtime)
        foto = [p for p in foto if os.path.getmtime(p) >= T_MULAI]
        if foto:
            with open(foto[-1], "rb") as f:
                requests.post(api + "/sendPhoto", data={"chat_id": config.GROUP_ID, "caption": "Layar Prisma saat gagal"},
                              files={"photo": f}, timeout=60)
        log("Notifikasi kegagalan dikirim ke Telegram")
    except Exception as x:             # jangan bocorkan URL (memuat token) lewat pesan error
        log(f"Notifikasi Telegram gagal terkirim ({type(x).__name__})")


def _bersihkan_bukti(hari):
    """Hapus tangkapan layar kegagalan yang lebih tua dari `hari` hari (hanya isi rajawali_bukti/)."""
    if not os.path.isdir(BUKTI_DIR):
        return
    batas = time.time() - hari * 86400
    for p in glob.glob(os.path.join(BUKTI_DIR, "rajawali_gagal_*")):
        try:
            if os.path.getmtime(p) < batas:
                os.remove(p)
        except OSError:
            pass


_MAU_BLOK = {"ya": False}       # user minta blok input (tanpa --tanpa-blok); dipakai hanya di langkah yang perlu


def _blok(nyala):
    """Blok input hanya saat langkah butuh mouse/keyboard/layar (PIN, login, cadangan OCR). Jalur UI Automation
    tidak memakainya, jadi PC bisa dipakai selama query berjalan."""
    import rajawali_ui as R
    if nyala and _MAU_BLOK["ya"] and not R.blok_aktif():
        R.blok_input(True)
    elif not nyala and R.blok_aktif():
        R.blok_input(False)


# Error MySQL tabel tidak ada (fallback sfo + fallback umum tabel bulanan ke month-1)
TABEL_TIDAK_ADA = re.compile(r"42S02|\b1146\b|doesn.?t\s*exist|Base\s*table\s*or\s*view\s*not\s*found", re.I)
# nama tabel bulanan dari pesan error Console: Table 'rajawalidb1.churn_dd_202611' doesn't exist
TABEL_HILANG = re.compile(r"Table\s*'(?:[\w$]+\.)?([\w$]*?(\d{4})(\d{2}))'", re.I)
MAKS_FALLBACK_TABEL = 4


def sql_fallback_bulan_lalu(sql, pesan_error):
    """Tabel bulanan belum ada (awal bulan / tabel baru belum dibuat) -> ganti tabel itu di SQL dengan tabel
    month-1 (churn_dd_202611 -> churn_dd_202610, ih_cb_cvm_prfl_mm_202610 -> _202609). Return (sql_baru, lama, baru)
    atau None bila error bukan 'tabel tidak ada' / nama tabel tak terbaca / tabelnya tidak ada di SQL."""
    if not TABEL_TIDAK_ADA.search(pesan_error or ""):
        return None
    m = TABEL_HILANG.search(pesan_error)
    if not m:
        return None
    lama, y, mo = m.group(1), int(m.group(2)), int(m.group(3))
    if not 1 <= mo <= 12:
        return None
    y, mo = (y - 1, 12) if mo == 1 else (y, mo - 1)
    baru = f"{lama[:-6]}{y:04d}{mo:02d}"
    pola = re.compile(r"(?<![\w$])" + re.escape(lama) + r"(?![\w$])")
    if not pola.search(sql):
        return None
    return pola.sub(baru, sql), lama, baru


def jalankan_query(R, K, h, nama, sql, folder_hasil):
    if TULIS.search(re.sub(r"'[^']*'", "''", sql)):
        raise TidakDiulang(f"{nama}: SQL berisi perintah tulis, DITOLAK.")
    try:
        hasil = _jalankan_query_uia(R, K, h, nama, sql, folder_hasil)
    except RuntimeError as e:
        if len(sql) < UIA_MAKS_NILAI:
            raise
        # isi editor SQL panjang tak bisa dibaca utuh lewat UIA -> bila Console menolak, ulangi dengan tempel (OCR)
        log(f"{nama}: gagal lewat UI Automation ({e}) -> ulang dengan cara OCR karena SQL > {UIA_MAKS_NILAI:,} karakter")
        hasil = None
    if hasil:
        return hasil
    log(f"{nama}: SQL Console tidak terbaca lewat UI Automation -> pakai cara OCR (Prisma di depan)")
    _blok(True)
    try:
        return _jalankan_query_ocr(R, K, h, nama, sql, folder_hasil)
    finally:
        _blok(False)


# ── jalur UI Automation (latar belakang) ─────────────────────────────────────
# Diamati 28-10 lewat UIA (id elemen modal SQL Console):
#   jalan   : #sqlcLoading "Running query", #sqlcMsg "Running… 0:07", #sqlcStop "Force Stop"
#   > ~10 s : #sqlcJobsBtn "Runs N" bertambah, #sqlcSlots "1 of 16 in use (you)"; panel utama tetap mengikuti
#   selesai : teks "Showing 100 of 35,741 rows • 43.3 s" / "1 rows • 0.0 s", #sqlcExport, dan (bila run tercatat)
#             #sqlcMsg "Run finished (done): <awal SQL>… Open Runs."
#   dilempar ke background: #sqlcMsg "Sent to the background. Open Runs to follow it." -> panel utama masih
#             menampilkan hasil LAMA (sumber bug export C3MR = hasil CAPS) -> export harus dari panel Runs.
STATUS_UIA = re.compile(r"^(Showing\s+[\d.,]+\s+of\s+)?[\d.,]+\s+rows?\b", re.I)


def _baca_console_uia(R, h):
    """Ringkasan modal SQL Console dari UIA (tanpa daftar tabel & isi tabel hasil, ~0.1 s):
    {'msg', 'jalan', 'status', 'export', 'runs'} atau None bila modal tak terbaca."""
    modal = R.uia_cari(h, aid="sqlConsoleModal")
    if not modal:
        return None
    u = R._uia()
    W = u.iuia.ControlViewWalker
    out = {"msg": "", "jalan": False, "status": "", "export": None, "runs": ""}

    def jalan(e, d=0):
        try:
            c = W.GetFirstChildElement(e)
        except Exception:
            return
        while c:
            try:
                aid, nm = c.CurrentAutomationId or "", (c.CurrentName or "").strip()
            except Exception:
                aid, nm = "", ""
            if aid not in ("sqlcTables", "sqlcTable") and d < 8:
                if aid in ("sqlcLoading", "sqlcStop"):
                    out["jalan"] = True
                elif aid == "sqlcExport":
                    out["export"] = c
                elif aid == "sqlcJobsBtn":
                    out["runs"] = nm
                elif aid == "sqlcMsg":
                    out["msg"] = nm or out["msg"]
                elif not aid and STATUS_UIA.search(nm) and "estimate" not in nm:
                    out["status"] = nm
                if aid == "sqlcMsg" and not nm:
                    try:
                        t = W.GetFirstChildElement(c)
                        out["msg"] = (t.CurrentName or "").strip() if t else ""
                    except Exception:
                        pass
                else:
                    jalan(c, d + 1)
            try:
                c = W.GetNextSiblingElement(c)
            except Exception:
                c = None

    jalan(modal)
    return out


UIA_MAKS_NILAI = 10000          # Chromium memotong nilai yang DIBACA lewat UIA di 10.000 karakter (diuji 29-10)


def _sama_sql(a, b):
    """Isi editor (dibaca lewat UIA) = sql? Untuk SQL > 10.000 karakter cukup 10.000 karakter pertamanya sama,
    karena bacaan dipotong Chromium (SetValue sendiri mengisi utuh; SQL c3mr 10.147 karakter sempat jatuh ke OCR)."""
    na = re.sub(r"\s+", " ", (a or "").strip())
    nb = re.sub(r"\s+", " ", (b or "").strip())
    if na == nb:
        return True
    return len(a or "") >= UIA_MAKS_NILAI and len(na) > 1000 and nb.startswith(na)


def _jalankan_query_uia(R, K, h, nama, sql, folder_hasil):
    """Isi editor (SetValue), Run (Invoke), tunggu & baca status (UIA), Export (Invoke) — tanpa mouse/keyboard/layar,
    jadi PC boleh dipakai & Prisma boleh tertutup jendela lain. Return path hasil, atau None bila console tak terbaca
    lewat UIA (caller pakai OCR). Galat yang jelas (error SQL, run gagal) -> RuntimeError seperti jalur OCR."""
    ed = R.uia_cari(h, aid="sqlcText", batas=10)
    awal = _baca_console_uia(R, h)
    run = R.uia_cari(h, aid="sqlcRun")
    if not (ed and awal and run):
        return None
    _blok(False)
    if not R.uia_isi(ed, sql, h):
        return None
    for _ in range(10):                     # nilai editor yang dibaca balik baru benar setelah sesaat
        R.tidur(0.5)
        if _sama_sql(R.uia_nilai(ed), sql):
            break
    else:
        log(f"{nama}: isi editor tidak bisa dipastikan lewat UI Automation")
        return None
    t_mulai = time.time()
    log(f"{nama}: menjalankan query ({len(sql):,} karakter) (UI Automation)")
    if not R.uia_invoke(run, h):
        return None
    lihat_jalan, ke_latar, st = False, False, None
    jeda, t_intip = 0.6, time.time()
    while time.time() - t_mulai < K["batas_query_detik"]:
        R.tidur(jeda)
        jeda = min(jeda * 1.3, 5)
        if time.time() - t_intip > 8:
            # Prisma tertutup jendela lain -> Chromium menunda update halaman; tampilkan sebentar tanpa ambil fokus
            R.tampil_atas(h, True)
            R.tidur(1.0)
            c = _baca_console_uia(R, h)
            R.tampil_atas(h, False)
            t_intip = time.time()
        else:
            c = _baca_console_uia(R, h)
        if c is None:
            raise RuntimeError(f"{nama}: SQL Console hilang saat query berjalan")
        msg = c["msg"]
        m = SELESAI.search(msg)
        if c["jalan"] or msg.lower().startswith("running"):
            lihat_jalan = True
            continue
        baru = lihat_jalan or msg != awal["msg"]     # pesan sisa run sebelumnya bukan milik run ini
        if re.search(r"Sent to the background", msg, re.I) and baru:
            if not ke_latar:
                log(f"{nama}: query dipindah ke panel Runs -> menunggu selesai")
            ke_latar = True
            continue
        if m and baru and _cocok_sql(m.group(3), sql):
            if m.group(1).lower() != "finished" or not re.match(r"\s*done", m.group(2) or "done", re.I):
                raise RuntimeError(f"{nama}: Console: {msg!r}")
            st = c["status"] or msg
            break
        if msg and baru and ERROR.search(msg) and not m:
            raise RuntimeError(f"{nama}: Console menampilkan error: {msg!r}")
        if ke_latar:
            continue
        # query cepat: tak sempat terlihat "Running" & tak ada pesan selesai -> status hasil baru/berubah cukup
        if c["status"] and c["export"] and (lihat_jalan or c["status"] != awal["status"]
                                            or time.time() - t_mulai > 5):
            st = c["status"]
            break
    else:
        raise TidakDiulang(f"{nama}: query tidak selesai dalam {K['batas_query_detik']} detik")
    log(f"{nama}: selesai -> {st!r} ({time.time() - t_mulai:.0f}s)")
    if ke_latar:
        # hasil yang tampil di panel utama milik query lain -> export dari baris Runs kita (cara OCR, Prisma di depan)
        _blok(True)
        try:
            return _export_runs_ocr(R, K, h, nama, sql, folder_hasil)
        finally:
            _blok(False)
    # selama klik Export & unduhan berjalan Prisma harus terlihat (tanpa ambil fokus), kalau tidak unduhan tertunda
    R.tampil_atas(h, True)
    try:
        R.tidur(1.0)
        c = _baca_console_uia(R, h)
        if not (c and c["export"]):
            raise RuntimeError(f"{nama}: tombol Export tidak ditemukan (UI Automation)")
        return _unduh(R, K, nama, folder_hasil, lambda: R.uia_invoke(c["export"], h))
    finally:
        R.tampil_atas(h, False)


def _salin_atomik(src, tujuan):
    """Salin export ke folder tanggal lewat file sementara + os.replace, supaya runner lain yang sedang membaca
    zip lama tidak pernah melihat file setengah tersalin."""
    tmp = f"{tujuan}.{os.getpid()}.tmp"
    shutil.copy2(src, tmp)
    for i in range(10):
        try:
            os.replace(tmp, tujuan)
            return
        except PermissionError:
            time.sleep(1 + i)
    os.remove(tmp)
    raise RuntimeError(f"{os.path.basename(tujuan)} sedang dipakai proses lain, tidak bisa diganti")


def _unduh(R, K, nama, folder_hasil, klik_export):
    sebelum = set(glob.glob(os.path.join(K["folder_unduhan"], "*")))
    t_ex = time.time()
    if klik_export() is False:
        raise RuntimeError(f"{nama}: Export gagal diklik")
    log(f"{nama}: Export diklik, menunggu unduhan...")
    f = tunggu_unduhan(R, K["folder_unduhan"], sebelum, t_ex, K["batas_unduh_detik"])
    _cek_export(nama, f, folder_hasil)
    tujuan = os.path.join(folder_hasil, f"{nama}{os.path.splitext(f)[1]}")
    _salin_atomik(f, tujuan)
    log(f"{nama}: tersimpan {tujuan} ({os.path.getsize(tujuan):,} byte)")
    return tujuan


def _export_runs_ocr(R, K, h, nama, sql, folder_hasil):
    """Export dari baris run kita di panel Runs (OCR). Panel dibuka lewat link "Open Runs" bila belum tampil."""
    R._pastikan_depan(h)
    for _ in range(10):
        st, _er, ks = _status(R, h)
        runs = _baris_runs(R, ks, _LAYAR["img"])
        if not _run_kita(runs, sql):
            buka = next((k for k in ks if re.search(r"Open\s*Runs", k.teks, re.I)), None)
            if buka:
                R.klik(h, buka)
                R.tidur(1.5)
                st, _er, ks = _status(R, h)
                runs = _baris_runs(R, ks, _LAYAR["img"])
        kita = _run_kita(runs, sql)
        if kita and re.match(r"\W*Done", kita[0], re.I) and kita[3]:
            log(f"{nama}: export dari panel Runs ({kita[0]})")
            return _unduh(R, K, nama, folder_hasil, lambda: R.klik(h, kita[3]))
        R.tidur(3)
    raise RuntimeError(f"{nama}: baris run di panel Runs tidak ditemukan / belum Done")


def _jalankan_query_ocr(R, K, h, nama, sql, folder_hasil):
    for _ in range(5):                      # modal baru tampil: beri waktu editor ("History") selesai dirender
        st0, _er, ks = _status(R, h)
        hist = next((k for k in ks if re.search(r"History", k.teks, re.I)), None)
        if hist or K.get("editor"):
            break
        R.tidur(1.5)
    lama = _baris_selesai(ks)
    lama_cocok = bool(lama and _cocok_sql(lama[2], sql))     # hasil di layar = SQL yang sama (dijalankan ulang)
    n_run_lama = sum(1 for r in _baris_runs(R, ks, _LAYAR["img"]) if _cocok_sql(r[1], sql))
    if K.get("editor"):
        putar_klik(R, h, K["editor"])
    elif hist:
        dx, dy = K["editor_dari_history"]
        sk = R.skala_dpi(h)                     # offset dlm px skala 100% -> ikut skala tampilan (125%, 150%, ...)
        l, t, r, b = R.rect(h)
        R.klik(h, ((hist.tengah[0] + dx * sk) / (r - l), (hist.tengah[1] + dy * sk) / (b - t)))
    else:
        raise RuntimeError("Editor SQL tidak ditemukan (rekam klik editor sekali).")
    R.tekan("^a")
    R.tempel(sql)
    time.sleep(0.5)
    t_mulai = time.time()
    log(f"{nama}: menjalankan query ({len(sql):,} karakter)")
    R.tekan("^{ENTER}")
    # Perilaku Console (diamati 27-10-2026): baris pesan di bawah editor menampilkan "Running... 0:01" selama
    # query jalan, lalu "Run finished (done): <awal SQL>" (atau pesan error merah, mis. "Not allowed ...").
    # Status hasil LAMA ("Showing 100 of N rows") tetap tampil selama query jalan -> jangan dipakai sendirian.
    lihat_jalan, kosong, st, bs, lain_dilapor = False, 0, None, None, False
    # Penghitung run (angka di tombol daftar, kiri "History") bertambah tiap query dijalankan. OCR tak bisa membaca
    # satu digit, jadi area angkanya dibandingkan sebagai gambar (posisi dikunci sebelum run). Penting untuk query
    # sangat cepat (<1 s): "Running" tak sempat terlihat & status bisa sama persis dgn run sebelumnya.
    run_baru, tenang, kotak, lencana0 = False, 0, None, None
    if hist and _LAYAR["img"] is not None:
        sk0 = R.skala_dpi(h)
        kotak = (int(hist.x - 118 * sk0), hist.y - 8, int(hist.x - 74 * sk0), hist.y + hist.h + 8)
        lencana0 = _LAYAR["img"].crop(kotak).convert("L")
    jeda = 0.6
    while time.time() - t_mulai < K["batas_query_detik"]:
        R.tidur(jeda)
        jeda = min(jeda * 1.3, 5)
        st, er, ks = _status(R, h)
        bs = _baris_selesai(ks)
        jalan = any(re.search(r"Running", k.teks) and not RUNS_STATUS.match(k.teks) for k in ks)
        runs = _baris_runs(R, ks, _LAYAR["img"])
        kita = _run_kita(runs, sql)
        if kita:
            sudah_baru = lihat_jalan or sum(1 for r in runs if _cocok_sql(r[1], sql)) > n_run_lama
            if re.match(r"\W*Running", kita[0], re.I):
                lihat_jalan, kosong = True, 0
                continue
            if re.match(r"\W*(Stopped|Failed|Error|Cancel)", kita[0], re.I) and sudah_baru:
                raise RuntimeError(f"{nama}: run di panel Runs berstatus {kita[0]!r}")
            if re.match(r"\W*Done", kita[0], re.I) and sudah_baru:
                break
        if er and not jalan:
            raise RuntimeError(f"{nama}: Console menampilkan error: {er.teks!r}")
        if jalan:
            lihat_jalan, kosong = True, 0
            continue
        cocok = bool(bs and _cocok_sql(bs[2], sql))
        if cocok and bs[0] != "finished":
            raise RuntimeError(f"{nama}: Console: {bs[3].teks!r}")
        if cocok and (lihat_jalan or not lama_cocok):
            break
        if bs and not cocok and lihat_jalan:
            # hasil yang tampil milik SQL LAIN (Console dipakai bersamaan) -> bukan selesainya query kita
            if not lain_dilapor:
                log(f"{nama}: PERINGATAN: Console menampilkan hasil query lain ({bs[2][:50]!r}) -> tetap menunggu")
                lain_dilapor = True
            kosong = 0
            continue
        if lencana0 is not None and not run_baru:
            from PIL import ImageChops, ImageStat
            beda = ImageStat.Stat(ImageChops.difference(lencana0, _LAYAR["img"].crop(kotak).convert("L"))).mean[0]
            run_baru = beda > 0.8
        if run_baru and not lihat_jalan and (st or bs):
            tenang += 1
            if tenang >= 3:                 # run baru tercatat, tidak "Running", hasil tampil 3x berturut-turut
                break
            continue
        if lihat_jalan:
            kosong += 1
            if kosong >= 2:                 # "Running" sudah hilang 2x berturut-turut
                break
        elif time.time() - t_mulai > 20 and st and st0 and _norm(st.teks) != _norm(st0.teks):
            log(f"{nama}: PERINGATAN: 'Running' tak terlihat, status berubah -> dianggap selesai")
            break
    else:
        raise TidakDiulang(f"{nama}: query tidak selesai dalam {K['batas_query_detik']} detik")
    R.tidur(1.5)                            # beri waktu tabel hasil baru tampil
    st, er, ks = _status(R, h)
    bs = _baris_selesai(ks) or bs
    kita = _run_kita(_baris_runs(R, ks, _LAYAR["img"]), sql)
    if er and not st and not kita:
        raise RuntimeError(f"{nama}: Console menampilkan error: {er.teks!r}")
    if not (st or bs or kita):
        raise RuntimeError(f"{nama}: hasil query tidak terlihat")
    ket = kita[0] if kita else st.teks if st else bs[3].teks
    log(f"{nama}: selesai -> {ket!r} ({time.time() - t_mulai:.0f}s)")
    acuan = st or (bs[3] if bs else None) or R.Kata("", 0, kita[2], 0, 0)   # acuan posisi Export cadangan
    # Query panjang dipindah ke panel "Runs" -> export dari BARIS RUN KITA (bukan hasil yang sedang tampil, yang
    # bisa milik query lain). Panel dibuka lewat link "Open Runs" bila belum tampil.
    runs = _baris_runs(R, ks, _LAYAR["img"])
    buka = next((k for k in ks if re.search(r"Open\s*Runs", k.teks, re.I)), None)
    if not _run_kita(runs, sql) and buka:
        R.klik(h, buka)
        R.tidur(1.5)
        st2, _, ks = _status(R, h)
        runs = _baris_runs(R, ks, _LAYAR["img"])
    kita = _run_kita(runs, sql)
    if kita and not re.match(r"\W*Done", kita[0], re.I):
        raise RuntimeError(f"{nama}: run di panel Runs belum Done: {kita[0]!r}")
    if kita and kita[3]:
        log(f"{nama}: export dari panel Runs ({kita[0]})")
        target = kita[3]
    else:
        img, _ = R.layar(h)
        ex = [k for k in R.ocr(img, 1.5) if re.fullmatch(r"\W*Export", k.teks.strip(), re.I)]
        ex = sorted([k for k in ex if k.y >= acuan.y - 5] or ex, key=lambda k: abs(k.y - acuan.y))
        if not ex:
            raise RuntimeError(f"{nama}: tombol Export tidak ditemukan")
        target = ex[0]
    sebelum = set(glob.glob(os.path.join(K["folder_unduhan"], "*")))
    t_ex = time.time()
    R.klik(h, target)
    log(f"{nama}: Export diklik, menunggu unduhan...")
    f = tunggu_unduhan(R, K["folder_unduhan"], sebelum, t_ex, K["batas_unduh_detik"])
    _cek_export(nama, f, folder_hasil)
    tujuan = os.path.join(folder_hasil, f"{nama}{os.path.splitext(f)[1]}")
    _salin_atomik(f, tujuan)
    log(f"{nama}: tersimpan {tujuan} ({os.path.getsize(tujuan):,} byte)")
    return tujuan


def _baca_export(path):
    """(header, set label kolom q) dari export Rajawali (zip/csv, baris pertama 'sep=;')."""
    import io
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            teks = z.read(z.namelist()[0]).decode("utf-8-sig", "replace")
    else:
        teks = open(path, encoding="utf-8-sig", errors="replace").read()
    baris = io.StringIO(teks)
    pertama = baris.readline().strip()
    header = (baris.readline() if pertama.lower().startswith("sep=") else pertama).strip().split(";")
    label = set()
    if header == ["q", "j"]:
        for b in baris:
            label.add(b.split(";", 1)[0].strip().strip('"'))
    return header, label


def _cek_export(nama, path, folder_hasil):
    """Pastikan file unduhan memang hasil query `nama` (Console bisa dipakai orang/sesi lain bersamaan).
    Gagal -> RuntimeError, file TIDAK disimpan sebagai hasil."""
    header, label = _baca_export(path)
    wajib_label = {"c3mr": {"A_ini", "A_lalu", "N_ini", "N_lalu"},
                   "sfo": {"sf_ini", "sf_lalu", "djp_lalu"}, "c3mr_u": {"U_ini"},   # ordering tidak lagi di sfo (pakai iod_*)
                   "caps": {"churn_ini", "churn_lalu", "ret_ini", "ret_lalu"},
                   "ms": {"city", "branch", "region"}}
    wajib_kolom = {"hourly": {"activity_hour", "io_trx", "re_trx", "ps_trx"}, "uji": {"waktu"},
                   "childps": {"bln", "city", "cluster", "ps", "child"},
                   "iod": {"order_id", "event_date", "io_ts", "re_ts"},
                   "hps": {"bln", "sto_id", "order_transaction", "created_at"}}
    salah = None
    if nama in wajib_label:
        kurang = wajib_label[nama] - label
        if kurang:
            salah = f"label {sorted(kurang)} tidak ada (label di file: {sorted(label)[:8]})"
    elif nama == "nasional_murmer":
        man = os.path.join(BASE, "storage", "sql_packets", f"{os.path.basename(folder_hasil)}.manifest.json")
        kunci = set(json.load(open(man, encoding="utf-8")).get("queries", {})) if os.path.exists(man) else set()
        asing = {x for x in label if x and x not in kunci}
        if header != ["q", "j"] or (kunci and asing):
            salah = f"label bukan milik manifest nasional/murmer (contoh: {sorted(asing)[:5]})"
    else:
        kunci = "iod" if nama.startswith("iod_") else nama
        kurang = wajib_kolom.get(kunci, set()) - set(header)
        if kurang:
            salah = f"kolom {sorted(kurang)} tidak ada (header: {header[:6]})"
    if salah:
        raise RuntimeError(f"{nama}: file unduhan BUKAN hasil query ini — {salah}. Kemungkinan SQL Console "
                           f"dipakai bersamaan oleh orang/sesi lain. Hasil tidak disimpan; jalankan ulang.")


def tunggu_unduhan(R, folder, sebelum, t0, batas):
    while time.time() - t0 < batas:
        baru = [p for p in glob.glob(os.path.join(folder, "*")) if p not in sebelum
                and not p.lower().endswith((".crdownload", ".tmp", ".part")) and os.path.getmtime(p) >= t0 - 2]
        if baru:
            p = max(baru, key=os.path.getmtime)
            s1 = os.path.getsize(p)
            R.tidur(2)
            if os.path.getsize(p) == s1 and s1 > 0:
                return p
        R.tidur(2)
    raise RuntimeError(f"Unduhan tidak muncul di {folder} dalam {batas} detik")


# ── SQL & report ─────────────────────────────────────────────────────────────
def sql_hourly(hari_ini):
    """dashboard_hourly_sales Jateng, awal bulan lalu s/d hari_ini, dijumlah per kabupaten/WOK/cluster/tanggal/jam."""
    from reports.closing.report import ReportLiveUpdate
    return ReportLiveUpdate.build_rajawali_sql(hari_ini)


def daftar_sql(tgl, perlu=None):
    """[(nama, sql)] untuk tanggal laporan tgl. perlu = nama query yang dibutuhkan (None = semua laporan pagi
    + sfo; 'hourly' hanya bila diminta, tanggalnya = HARI INI karena /liveupdate memakai data jam berjalan)."""
    from dateutil.relativedelta import relativedelta
    from commands.market_share import ReportMarketShare
    from commands.nasional import ReportNasional
    from reports.c3mr.report import ReportC3MR, ReportC3MRNew
    from reports.caps.report import ReportCaps
    from reports.childps.report import ReportChildPS
    from reports.closing.report import ReportClosingSQL, ReportLiveUpdate
    from reports.homepass.command import ReportHomepass
    from reports.sf_momentum.report import Report5SO

    perlu = set(perlu) if perlu is not None else {"nasional_murmer", "iod_*", "sfo"}
    hasil = []
    if "hourly" in perlu:
        hasil.append(("hourly", ReportLiveUpdate.build_rajawali_sql(date.today())))
    if "c3mr" in perlu:
        hasil.append(("c3mr", ReportC3MR.save_rajawali_sql(tgl, filename=f"c3mr_{tgl:%Y%m%d}.sql")))
    if "caps" in perlu:
        hasil.append(("caps", ReportCaps.save_rajawali_sql(tgl, filename=f"caps_{tgl:%Y%m%d}.sql")))
    if "hps" in perlu:
        hasil.append(("hps", ReportHomepass.save_rajawali_sql(tgl, filename=f"homepass_{tgl:%Y%m%d}.sql")))
    if "c3mr_u" in perlu:
        hasil.append(("c3mr_u", ReportC3MRNew.save_rajawali_sql(tgl, filename=f"c3mr_{tgl:%Y%m%d}_U.sql", bagian="U")))
    if "childps" in perlu:
        hasil.append(("childps", ReportChildPS.save_rajawali_sql(tgl, filename=f"childps_{tgl:%Y%m%d}.sql")))
    if "ms" in perlu:
        hasil.append(("ms", ReportMarketShare.save_rajawali_sql(tgl, filename=f"ms_{tgl:%Y%m%d}.sql")))
    if not perlu & {"nasional_murmer", "iod_*", "sfo"}:
        return hasil
    nm = ReportNasional.build_rajawali_sql(tgl)
    ini, lalu = tgl.replace(day=1), tgl.replace(day=1) - relativedelta(months=1)
    semua = [
        ("nasional_murmer", nm),
        ("sfo", Report5SO.build_rajawali_sql(tgl)),
        (f"iod_{lalu:%Y%m}", ReportClosingSQL.build_rajawali_sql(lalu)),
        (f"iod_{ini:%Y%m}", ReportClosingSQL.build_rajawali_sql(ini)),
    ]
    return hasil + [j for j in semua if j[0] in perlu or ("iod_*" in perlu and j[0].startswith("iod_"))]


# --query uji: tes alur UI saja. Query terekam di History/Runs Rajawali yang dilihat orang area -> JANGAN ada
# teks/alias/komentar penanda uji atau otomasi di SQL apa pun yang dikirim; buat terlihat seperti query biasa.
SQL_UJI = "SELECT NOW() AS waktu"


def ekstrak(p):
    """zip export -> csv di sebelahnya. Hanya bila csv belum ada / lebih tua dari zip-nya, dan ditulis atomik
    (file sementara lalu os.replace). Dulu SETIAP report mengekstrak ulang semua zip di folder tanggal dan menimpa
    csv-nya; dua runner yang jalan berdekatan (liveupdate Telegram + WhatsApp 15.00, server 29-10) saling menimpa
    file yang sedang dibaca -> utils/csv_report_runner.py gagal."""
    if not p.lower().endswith(".zip"):
        return p
    out = os.path.splitext(p)[0] + ".csv"
    if os.path.exists(out) and os.path.getsize(out) > 0 and os.path.getmtime(out) >= os.path.getmtime(p):
        return out
    with zipfile.ZipFile(p) as z:
        n = next(x for x in z.namelist() if x.lower().endswith(".csv"))
        data = z.read(n)
    tmp = f"{out}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    for i in range(10):
        try:
            os.replace(tmp, out)
            return out
        except PermissionError:          # csv sedang dibaca proses lain (Windows mengunci file yang terbuka)
            time.sleep(1 + i)
    os.remove(tmp)
    raise RuntimeError(f"{os.path.basename(out)} sedang dipakai proses lain, tidak bisa diperbarui")


def jalankan_scraping(tgl, K, pakai_ada=False):
    """Scraping DJP SELA bulan tgl (awal bulan s/d tgl) dengan utils.sela_scraper --auto,
    sama dgn perintah manual:  DIGIPOS_SF_FROM=<awal bulan> DIGIPOS_SF_TO=<tgl> DIGIPOS_SF_DELAY=0.5
    DIGIPOS_SF_SIZE=200 python -m utils.sela_scraper --auto.
    Login SELA (SSO + CAPTCHA) tetap manual kalau sesi tersimpan sudah habis: program scraping menunggu sampai 10 menit.
    Return path file detail-homepass_<dari>_sd_<sampai>.xlsx."""
    folder = K["folder_scraping"]
    os.makedirs(folder, exist_ok=True)
    awal = tgl.replace(day=1)
    nama = f"detail-homepass_{awal:%Y-%m-%d}_sd_{tgl:%Y-%m-%d}.xlsx"
    cari = lambda: glob.glob(os.path.join(folder, "data", "results", "*", "upload_generator", nama))
    if pakai_ada:
        ada = [f for f in cari() if datetime.fromtimestamp(os.path.getmtime(f)).date() == date.today()]
        if ada:
            f = max(ada, key=os.path.getmtime)
            log(f"scraping: {os.path.basename(f)} hari ini sudah ada -> dipakai ulang")
            return f
    env = dict(os.environ, DIGIPOS_SELA_ROOT=folder,
               DIGIPOS_SF_FROM=f"{awal:%Y-%m-%d}", DIGIPOS_SF_TO=f"{tgl:%Y-%m-%d}",
               DIGIPOS_SF_DELAY=str(K["scraping_delay"]), DIGIPOS_SF_SIZE=str(K["scraping_size"]),
               PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "-m", "utils.sela_scraper", "--auto"] + (["--headless"] if K["scraping_headless"] else [])
    log(f"scraping SELA {awal:%d-%m-%Y} s/d {tgl:%d-%m-%Y}: {' '.join(cmd[1:])} (data: {folder})")
    mulai = time.time()
    p = subprocess.Popen(cmd, cwd=BASE, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    ekor = []
    try:
        import threading
        def baca():
            for ln in p.stdout:
                ln = ln.rstrip()
                ekor.append(ln)
                del ekor[:-40]
                if ln.strip().startswith(("[GABUNGAN]", "[OK]", "[!]", "[GAGAL]", "Cakupan", "-----")):
                    log("  scraping | " + ln.strip()[:160])
        th = threading.Thread(target=baca, daemon=True)
        th.start()
        th.join(K["batas_scraping_detik"])
        if th.is_alive():
            p.kill()
            raise RuntimeError(f"Scraping melebihi {K['batas_scraping_detik'] // 60} menit (login SELA belum diselesaikan?)")
        p.wait()
    finally:
        if p.poll() is None:
            p.kill()
    hasil = [f for f in cari() if os.path.getmtime(f) >= mulai - 5]
    if p.returncode != 0 or not hasil:
        raise RuntimeError(f"Scraping SELA gagal (kode {p.returncode}); {nama} tidak terbentuk. "
                           f"Baris terakhir: {' | '.join(ekor[-6:])[:600]}")
    f = max(hasil, key=os.path.getmtime)
    log(f"scraping selesai: {f} ({os.path.getsize(f) / 1048576:.1f} MB, {time.time() - mulai:.0f} dtk)")
    return f


LAPORAN_PAGI = ["closingsql", "dod", "nasional", "agresif", "wireless2", "wirelesschannel2", "murmer"]
LAPORAN_SFO = ["5so", "7so"]
LAPORAN_CLOCKIN = ["clockin_sf_teritory", "clockin_sf_all", "homepass_raw"]   # Clock-in SF Teritory & SF All Category
# (setelah 7SO) + file homepass mentah. clockin_sf_all butuh export sfo (SF Register database_sf).
LAPORAN_HOMEPASS = ["homepass", "homepass_wok_old"]            # butuh export hps (homepass_sales) + iod_*
LAPORAN_SALAHTAG = ["salahtagging", "salahtagging_wok_old"]   # hanya iod_* (ordering_detail)
LAPORAN_C3MR = ["c3mr", "c3mrnew", "c3mrnewch", "c3mr10s", "c3mrsvp"]
LAPORAN_MS = ["ms", "msbranch"]


def query_untuk(only):
    """Nama query Rajawali yang dibutuhkan laporan `only` (None = semua)."""
    only = set(only or LAPORAN_PAGI + LAPORAN_SFO + LAPORAN_CLOCKIN + LAPORAN_MS)
    q = ["hourly"] if "liveupdate" in only else []
    if only & set(LAPORAN_C3MR):
        q += ["c3mr"]
    if "c3mrnew" in only:
        q += ["c3mr_u"]               # lampiran CSV pelanggan unpaid
    if "caps" in only:
        q += ["caps"]
    if "childps" in only:
        q += ["childps"]
    if only & set(LAPORAN_MS):
        q += ["ms"]
    if only & set(LAPORAN_PAGI):
        q += ["nasional_murmer", "iod_*"]
    if only & set(LAPORAN_HOMEPASS):
        q += ["hps"]
    if only & (set(LAPORAN_HOMEPASS) | set(LAPORAN_SALAHTAG)):
        q += ["iod_*"]
    if only & set(LAPORAN_SFO):
        q += ["sfo"] + (["iod_*"] if "iod_*" not in q else [])    # ordering 5SO/7SO = export iod_* (sama dgn closingsql)
    if "clockin_sf_all" in only and "sfo" not in q:
        q += ["sfo"]                                               # SF Register untuk Clock-In SF All Category
    return q


def _report_py(cmd, cwd=None, check=True):
    """Jalankan utils/csv_report_runner.py. Output tetap diteruskan apa adanya, tapi bila gagal, BARIS TERAKHIR error-nya
    (traceback) ikut masuk ke log & pesan gagal - dulu hanya "returned non-zero exit status 1" (server 29-10 15:02)."""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    keluar = (r.stdout or "") + (r.stderr or "")
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"          # konsol cp1252 tak bisa menulis emoji (⏳)
    sys.stdout.write(keluar.encode(enc, "replace").decode(enc, "replace"))
    sys.stdout.flush()
    if check and r.returncode != 0:
        ekor = [b for b in keluar.strip().splitlines() if b.strip()][-12:]
        for b in ekor:
            log(f"  report: {b[:300]}")
        akhir = ekor[-1] if ekor else f"exit {r.returncode}"
        raise RuntimeError(f"pembuat report gagal: {akhir[:400]}")
    return r


def jalankan_report(tgl, folder, kirim, laporan=("pagi", "5so7so"), djp_file=None, djp_definisi="checkout",
                    only=None, topic=None, chat=None, out_dir=None):
    """only = daftar nama laporan (closingsql, ..., 5so, 7so); topic = kirim ke topic terjadwal (SALES, ...)."""
    if only:
        laporan = [x for x, ls in (("pagi", LAPORAN_PAGI), ("5so7so", LAPORAN_SFO),
                                   ("clockin", LAPORAN_CLOCKIN)) if set(only) & set(ls)]
    pagi = [n for n in LAPORAN_PAGI if not only or n in only]
    sfo = [n for n in LAPORAN_SFO if not only or n in only]
    # file homepass mentah dikirim SETELAH 7SO (bagian 5so7so); Report Clock-in SF Teritory paling akhir
    kirim_hp = ("homepass_raw" in only) if only else ("5so7so" in laporan)
    buat_ck = ("clockin_sf_teritory" in only) if only else ("clockin" in laporan)
    buat_ck_all = ("clockin_sf_all" in only) if only else ("clockin" in laporan)
    import djp_homepass
    tg = tgl.strftime("%d-%m-%Y")
    c = {os.path.splitext(os.path.basename(p))[0]: ekstrak(p)
         for p in glob.glob(os.path.join(folder, "*.zip")) + glob.glob(os.path.join(folder, "*.csv"))
         if not p.endswith("_djp.csv")}
    iods = [f"{v}::{k.split('_')[1]}" for k, v in c.items() if k.startswith("iod_")]
    man = os.path.join(BASE, "storage", "sql_packets", f"{tgl:%Y%m%d}.manifest.json")
    py = [sys.executable, os.path.join(BASE, "utils", "csv_report_runner.py"), "--tanggal", tg]
    def kirim_arg(sub):
        if kirim:
            return ["--kirim"] + (["--chat", chat] if chat else ["--topic", topic] if topic else [])
        return ["--out", os.path.join(out_dir or folder, sub)]
    if only and "caps" in only:
        if "caps" not in c:
            raise RuntimeError("Report CAPS butuh export caps di " + folder)
        log("Report caps")
        _report_py(py + ["--caps-export", c["caps"], "--only", "caps"] + kirim_arg("out_caps"), cwd=BASE, check=True)
    c3mr = [n for n in LAPORAN_C3MR if only and n in only]
    if c3mr:
        if "c3mr" not in c:
            raise RuntimeError("Report C3MR butuh export c3mr di " + folder)
        log("Report " + ", ".join(c3mr))
        lamp = []
        if "c3mrnew" in c3mr:
            if "c3mr_u" in c:
                lamp = ["--c3mr-unpaid", c["c3mr_u"]]
            else:
                log("PERINGATAN: export c3mr_u (pelanggan unpaid) tidak ada -> /c3mrnew tanpa lampiran CSV")
        _report_py(py + ["--c3mr-export", c["c3mr"], "--only", ",".join(c3mr)] + lamp + kirim_arg("out_c3mr"),
                       cwd=BASE, check=True)
    if only and "liveupdate" in only:
        if "hourly" not in c:
            raise RuntimeError("Liveupdate butuh export hourly di " + folder)
        log("Report liveupdate (Monitoring RE hourly)")
        _report_py(py + ["--hourly-export", c["hourly"], "--only", "liveupdate"] + kirim_arg("out_liveupdate"),
                       cwd=BASE, check=True)
    if only and "childps" in only:
        if "childps" not in c:
            raise RuntimeError("Report Child per PS butuh export childps di " + folder)
        log("Report childps")
        _report_py(py + ["--childps-export", c["childps"], "--only", "childps"] + kirim_arg("out_childps"),
                   cwd=BASE, check=True)
    ms_list = [n for n in LAPORAN_MS if only and n in only]
    if ms_list:
        if "ms" not in c:
            raise RuntimeError("Report Market Share butuh export ms di " + folder)
        log("Report " + ", ".join(ms_list))
        _report_py(py + ["--ms-export", c["ms"], "--only", ",".join(ms_list)] + kirim_arg("out_ms"),
                   cwd=BASE, check=True)
    if "pagi" in laporan and pagi:
        if not (iods and "nasional_murmer" in c):
            raise RuntimeError("Report pagi butuh export iod_* dan nasional_murmer di " + folder)
        log("Report pagi: " + ", ".join(pagi))
        _report_py(py + ["--csv"] + iods + ["--export", c["nasional_murmer"], "--manifest", man,
                             "--only", ",".join(pagi), "--tanpa-raw-murmer"] + kirim_arg("out_pagi"),
                       cwd=BASE, check=True)
    hpl = [n for n in LAPORAN_HOMEPASS + LAPORAN_SALAHTAG if only and n in only]
    if hpl:
        if not iods:
            raise RuntimeError("Report homepass/salahtagging butuh export iod_* (ordering) di " + folder)
        hps = []
        if set(hpl) & set(LAPORAN_HOMEPASS):
            if "hps" not in c:
                raise RuntimeError("Report homepass butuh export hps (homepass_sales) di " + folder)
            hps = ["--homepass-export", c["hps"]]
        log("Report " + ", ".join(hpl))
        _report_py(py + ["--csv"] + iods + hps + ["--only", ",".join(hpl)] + kirim_arg("out_homepass"),
                       cwd=BASE, check=True)
    urutan = (sfo if "5so7so" in laporan else []) + (["clockin_sf_teritory"] if buat_ck else []) \
        + (["clockin_sf_all"] if buat_ck_all else []) + (["homepass_raw"] if kirim_hp else [])
    if urutan:
        import djp_homepass
        hp = djp_file or djp_homepass.cari_file(tgl)
        arg = []
        if sfo and "5so7so" in laporan:
            if "sfo" not in c:
                raise RuntimeError("Report 5SO/7SO butuh export sfo di " + folder)
            if not iods:
                raise RuntimeError("Report 5SO/7SO butuh export iod_* (ordering, sama dengan closingsql) di " + folder)
            if not hp:
                log("5SO/7SO dilewati: file detail-homepass (DJP bulan ini) tidak ditemukan")
                return
            djp = os.path.join(folder, "homepass_djp.csv")
            info = djp_homepass.buat_csv_djp(hp, djp, djp_homepass.wok_dari_export_sfo(c["sfo"]), djp_definisi)
            log(f"DJP dari {os.path.basename(hp)}: {info}")
            t_max = info.get("tgl_max")
            import pandas as _pd
            if t_max and not _pd.isna(t_max):
                if str(t_max) < (tgl - timedelta(days=2)).strftime("%Y-%m-%d"):
                    log(f"PERINGATAN: data homepass baru s/d {t_max} — DJP MTD kurang lengkap")
            else:
                log("PERINGATAN: data homepass kosong / belum ada kunjungan di file — DJP MTD 0")
            arg += ["--csv"] + iods + ["--sfo-export", c["sfo"], "--djp-ini", djp]
            # DJP M1 (tgl 1..D bulan lalu) dari file SELA bulan lalu yang sudah ada (cache scraping, tanpa
            # scraping ulang). Tidak ada file -> tetap tabel djp_daily_user_detailed dari export sfo.
            from dateutil.relativedelta import relativedelta
            lm_awal = tgl.replace(day=1) - relativedelta(months=1)
            lm_akhir = min(lm_awal + relativedelta(day=tgl.day), tgl.replace(day=1) - timedelta(days=1))
            hp_lalu = djp_homepass.cari_file_periode(lm_awal, lm_akhir)
            if hp_lalu:
                djp_lalu = os.path.join(folder, "homepass_djp_lalu.csv")
                info_l = djp_homepass.buat_csv_djp_periode(hp_lalu, djp_lalu, djp_homepass.wok_dari_export_sfo(c["sfo"]),
                                                           lm_awal, lm_akhir, djp_definisi)
                log(f"DJP M1 dari file SELA {info_l}")
                arg += ["--djp-lalu", djp_lalu]
            else:
                log(f"DJP M1: file detail-homepass {lm_awal:%Y-%m-%d}..{lm_akhir:%Y-%m-%d} tidak ada -> "
                    f"pakai tabel djp_daily_user_detailed (export sfo)")
        elif not hp:
            log("homepass_raw / clockin dilewati: file detail-homepass tidak ditemukan")
            return
        if "clockin_sf_all" in urutan and "--sfo-export" not in arg:
            if "sfo" in c:            # SF Register (database_sf) dari export sfo, tanpa ordering
                arg += ["--sfo-export", c["sfo"]]
            else:
                log("clockin_sf_all dilewati: export sfo (SF Register) tidak ada di " + folder)
                urutan.remove("clockin_sf_all")
                if not urutan:
                    return
        if hp:
            arg += ["--homepass-file", hp]
        log("Report " + ", ".join(x.upper() if x in ("5so", "7so") else x for x in urutan))
        _report_py(py + arg + ["--only", ",".join(urutan)] + kirim_arg("out_5so7so"), cwd=BASE, check=True)


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tanggal", default=(date.today() - timedelta(days=1)).strftime("%d-%m-%Y"))
    ap.add_argument("--hanya", choices=["query", "report"], help="jalankan sebagian saja")
    ap.add_argument("--laporan", default="pagi,5so7so,clockin",
                    help="report yang dibuat: pagi, 5so7so (+file homepass mentah setelah 7SO), clockin (dipisah koma)")
    ap.add_argument("--lewati-scraping", action="store_true",
                    help="jangan scraping SELA; pakai --djp-file atau file detail-homepass terbaru")
    ap.add_argument("--scraping", action="store_true", help="paksa scraping SELA walau --hanya report")
    ap.add_argument("--djp-file", help="file detail-homepass_*.xlsx (default: terbaru di Downloads/results)")
    ap.add_argument("--djp-definisi", default="checkout", choices=["checkout", "terakhir"],
                    help="kunjungan DJP: checkout = Journey Status CHECKOUT; terakhir = Kunjungan Terakhir terisi")
    ap.add_argument("--query", help="nama query yang dijalankan, dipisah koma (default semua)")
    ap.add_argument("--only", help="laporan yang dibuat, mis. closingsql,dod,nasional atau 5so,7so "
                                   "(query yang dijalankan menyesuaikan)")
    ap.add_argument("--pakai-ada", action="store_true",
                    help="lewati query yang hasil export-nya sudah diunduh HARI INI (dipakai ulang antar slot jadwal)")
    ap.add_argument("--out-dir", help="dry-run: folder induk hasil (out_pagi, out_c3mr, ...); default folder tanggal")
    ap.add_argument("--chat", help="--kirim ke chat CHAT_ID[:THREAD_ID] (dipakai command manual bot)")
    ap.add_argument("--topic", help="--kirim ke topic laporan terjadwal (SALES, FUNDAMENTAL, ...) seperti bot")
    ap.add_argument("--kirim", action="store_true", help="kirim report ke grup koordinasi (default dry-run)")
    ap.add_argument("--atur-pin", action="store_true", help="simpan PIN Prisma ke .env (PRISMA_PIN)")
    ap.add_argument("--tanpa-blok", action="store_true", help="jangan blok input mouse/keyboard selama otomasi")
    ap.add_argument("--uji-blok", type=int, metavar="DETIK", help="uji blok input selama N detik lalu lepas")
    ap.add_argument("--atur-login", action="store_true", help="simpan user/password Rajawali ke .env")
    ap.add_argument("--pakai-rekaman", help="langkah.json hasil rajawali_rekam.py -> langkah buka SQL Console")
    a = ap.parse_args()

    if a.atur_pin or a.atur_login:
        import getpass
        if a.atur_pin:
            tulis_env("PRISMA_PIN", getpass.getpass("PIN Prisma (tidak tampil saat diketik): ").strip())
        if a.atur_login:
            tulis_env("RAJAWALI_USER", input("User Rajawali: ").strip())
            tulis_env("RAJAWALI_PASS", getpass.getpass("Password Rajawali (tidak tampil): ").strip())
        print(f"Tersimpan di {ENV}. File ini RAHASIA: jangan dibagikan / di-commit.")
        return
    if a.uji_blok:
        import rajawali_ui as R
        if not R.admin():
            sys.exit("Butuh hak Administrator: jalankan terminal/bat dengan 'Run as administrator'.")
        R.mulai_penjaga(konfig()["maks_blok_detik"], log)
        print(f"Uji {a.uji_blok} detik seperti runner: diblok 3 detik, lepas 3 detik, berulang.\n"
              f"Pintu darurat: tekan {R.TOMBOL_STOP} berulang kali (fisik / Chrome Remote Desktop),\n"
              f"atau buat file {R.STOP_FILE}, atau Ctrl+Alt+Del fisik.")
        R.blok_input(True)
        try:
            t0 = time.time()
            while time.time() - t0 < a.uji_blok:
                time.sleep(3)            # terblok
                R.tidur(3)               # jendela lepas
        finally:
            R.blok_input(False)
        print(f"Selesai tanpa dihentikan. Kalau tadi {R.TOMBOL_STOP} ditekan, program mestinya berhenti sendiri.")
        return
    if a.pakai_rekaman:
        k = json.load(open(KONFIG, encoding="utf-8")) if os.path.exists(KONFIG) else {}
        k["buka_console"] = [s for s in json.load(open(a.pakai_rekaman, encoding="utf-8"))
                             if s["jenis"] in ("klik", "tombol")]
        json.dump(k, open(KONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{len(k['buka_console'])} langkah disimpan ke {KONFIG}")
        return

    tgl = datetime.strptime(a.tanggal, "%d-%m-%Y").date()
    folder = os.path.join(BASE, "storage", "downloads", f"{tgl:%Y%m%d}")
    os.makedirs(folder, exist_ok=True)
    log(f"=== Mulai, tanggal laporan {a.tanggal} | folder {folder}")

    # scraping SELA (DJP bulan ini) bila 5SO/7SO atau clockin diminta: sebelum langkah Rajawali, sekali jalan
    nama_laporan = set(a.only.split(",")) if a.only else set(a.laporan.split(","))
    perlu_homepass = bool(nama_laporan & {"5so", "7so", "5so7so", "homepass_raw", "clockin", "clockin_sf_teritory",
                                          "clockin_sf_all"})
    if perlu_homepass and not a.djp_file and not a.lewati_scraping and (a.hanya != "report" or a.scraping):
        a.djp_file = jalankan_scraping(tgl, konfig(), a.pakai_ada)

    if a.hanya != "report":
        import rajawali_ui as R
        K = konfig()
        if a.query == "uji":
            jobs = [("uji", SQL_UJI)]
        elif a.query:
            pilih = set(a.query.split(","))
            perlu = {"iod_*" if p.startswith("iod_") else p for p in pilih}
            jobs = [j for j in daftar_sql(tgl, perlu) if j[0] in pilih]
        else:
            jobs = daftar_sql(tgl, query_untuk(a.only.split(",")) if a.only else None)
        if a.pakai_ada:
            hari_ini = date.today()
            ada = lambda n: any(datetime.fromtimestamp(os.path.getmtime(p)).date() == hari_ini
                                for p in glob.glob(os.path.join(folder, n + ".*")))
            for n in [j[0] for j in jobs if j[0] != "hourly" and ada(j[0])]:
                log(f"{n}: export hari ini sudah ada -> dipakai ulang")
            jobs = [j for j in jobs if j[0] == "hourly" or not ada(j[0])]   # hourly selalu segar
    if a.hanya != "report" and jobs:
        kunci = _kunci_ui()       # satu otomasi Prisma dalam satu waktu (bot Telegram, WhatsApp, manual)
        R.mulai_penjaga(K["maks_blok_detik"], log)
        _MAU_BLOK["ya"] = not a.tanpa_blok
        if not a.tanpa_blok:
            if R.blok_input(True):
                log(f"Input mouse/keyboard DIBLOK selama buka Prisma/login (query lewat UI Automation tidak diblok; "
                    f"darurat: {R.TOMBOL_STOP} saat jeda, file STOP_OTOMASI, atau Ctrl+Alt+Del fisik)")
            else:
                log("PERINGATAN: input tidak bisa diblok (jalankan sebagai Administrator). Lanjut tanpa blok.")
        _bersihkan_bukti(K["hari_simpan_bukti"])
        try:
            h = _ulang(R, K, "sesi", lambda i: siapkan_sesi(R, K))
            for nama, sql in jobs:
                def coba(i, nama=nama, sql=sql):
                    nonlocal h
                    if i > 1:                    # percobaan ulang = mulai dari awal (refresh URL -> login -> SQL Console)
                        _blok(True)
                        h = siapkan_sesi(R, K)
                    try:
                        return jalankan_query(R, K, h, nama, sql, folder)
                    except RuntimeError as e:
                        if not TABEL_TIDAK_ADA.search(str(e)):
                            raise
                        err = e
                    if nama == "sfo":
                        # Awal bulan: database_sf_<bulan ini> belum dibuat -> Console "1146 Table ... doesn't
                        # exist". Ulang SEKALI di sesi yang sama dgn sf_ini = snapshot terakhir bulan lalu.
                        from reports.sf_momentum.report import Report5SO
                        log(f"sfo: tabel database_sf_{tgl:%Y%m} belum ada -> fallback sf_ini dari "
                            f"snapshot terakhir database_sf bulan lalu")
                        sql = Report5SO.build_rajawali_sql(tgl, sf_ini_fallback=True)
                        try:
                            return jalankan_query(R, K, h, nama, sql, folder)
                        except RuntimeError as e:
                            if not TABEL_TIDAK_ADA.search(str(e)):
                                raise
                            err = e
                    # Tabel bulanan lain belum ada (mis. CAPS: ih_cb_cvm_prfl_mm_202610, churn_dd_202611) ->
                    # ganti tabel itu dengan tabel month-1 lalu ulang di sesi yang sama (bisa beberapa tabel).
                    for _ in range(MAKS_FALLBACK_TABEL):
                        fb = sql_fallback_bulan_lalu(sql, str(err))
                        if not fb:
                            raise err
                        sql, lama, baru = fb
                        log(f"{nama}: tabel {lama} belum ada -> fallback ke tabel month-1 {baru}")
                        try:
                            return jalankan_query(R, K, h, nama, sql, folder)
                        except RuntimeError as e:
                            if not TABEL_TIDAK_ADA.search(str(e)):
                                raise
                            err = e
                    raise err
                _ulang(R, K, nama, coba)
        finally:
            if R.blok_aktif():
                R.blok_input(False)
                log("Blok input dilepas")
    if a.hanya != "query":
        jalankan_report(tgl, folder, a.kirim, a.laporan.split(","), a.djp_file, a.djp_definisi,
                        a.only.split(",") if a.only else None, a.topic, a.chat, a.out_dir)
    log("=== Selesai")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"GAGAL: {type(e).__name__}: {e}")
        _notifikasi_gagal(e)
        sys.exit(1)
