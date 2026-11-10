"""
mode_query.py — saklar sumber data laporan: query LANGSUNG ke MySQL (butuh VPN) atau lewat
otomasi SQL Console RAJAWALI DASHBOARD di Prisma (rajawali_auto.py).

Mode:
  langsung  : seperti biasa, bot query MySQL internal (db.py).
  rajawali  : laporan yang didukung dijalankan lewat rajawali_auto.py (query di SQL Console ->
              export -> report). Laporan lain dilewati dengan pemberitahuan.
  auto      : pakai langsung bila port DB terjangkau; kalau tidak, laporan yang didukung lewat Rajawali.

Mode tersimpan di mode_query.json (bertahan saat bot restart). Default dari config.MODE_QUERY.
Ubah lewat perintah bot /modequery <langsung|rajawali|auto>.
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE, "storage", "state")
os.makedirs(STATE_DIR, exist_ok=True)
PATH = os.path.join(STATE_DIR, "mode_query.json")
MODE = ("langsung", "rajawali", "auto")

# laporan terjadwal yang bisa dibuat dari export Rajawali (lihat rajawali_auto.py --only)
DIDUKUNG_RAJAWALI = {"closingsql", "dod", "nasional", "agresif", "wireless2", "wirelesschannel2",
                     "murmer", "5so", "7so", "liveupdate",
                     "c3mr", "c3mrnew", "c3mrnewch", "c3mr10s", "c3mrsvp", "caps",
                     "homepass_raw", "clockin_sf_teritory", "clockin_sf_all",
                     "homepass", "salahtagging", "homepass_wok_old", "salahtagging_wok_old",
                     "ms", "msbranch", "childps"}


def _default():
    try:
        import config
        m = str(getattr(config, "MODE_QUERY", "langsung")).lower()
        return m if m in MODE else "langsung"
    except Exception:
        return "langsung"


def ambil():
    try:
        with open(PATH, encoding="utf-8") as f:
            m = json.load(f).get("mode")
        if m in MODE:
            return m
    except Exception:
        pass
    return _default()


def atur(mode):
    mode = mode.lower().strip()
    if mode not in MODE:
        raise ValueError(f"mode harus salah satu: {', '.join(MODE)}")
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump({"mode": mode}, f)
    return mode


def pakai_rajawali(db_terjangkau):
    """True bila laporan yang didukung sebaiknya lewat Rajawali, menurut mode sekarang."""
    m = ambil()
    return m == "rajawali" or (m == "auto" and not db_terjangkau)


def runner_berhasil(kode_keluar, teks):
    """Hasil utils/rajawali_auto.py: berhasil bila kode keluar 0, ada '=== Selesai', dan tidak ada baris akhir
    '[jam] GAGAL: ...'. Baris 'percobaan 1/3 GAGAL (...) -> ulang dari awal' BUKAN kegagalan (run berikutnya bisa
    sukses); dulu dicek dengan "GAGAL " in teks sehingga laporan yang sudah jadi tidak terkirim (WA 29-10 13:03)."""
    import re
    return (kode_keluar == 0 and "=== Selesai" in teks
            and not re.search(r"^\[\d\d:\d\d:\d\d\] GAGAL:", teks, re.M))
