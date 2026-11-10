# ============================================================
#  KONFIGURASI BOT MONITORING RE JATENG-DIY
#  Seluruh konfigurasi & kredensial dibaca langsung dari `.env`
#  menggunakan `dotenv_values()` dari python-dotenv.
# ============================================================

from pathlib import Path
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
env = dotenv_values(BASE_DIR / ".env", interpolate=False, encoding="utf-8-sig")

# ============================================================
#  1. TELEGRAM BOT & GRUP
# ============================================================
TOKEN           = env.get("TOKEN") or ""
GROUP_ID        = int(env.get("GROUP_ID") or 0)
REPORT_GROUP_ID = int(env.get("REPORT_GROUP_ID") or 0)

BLOCKED_CHAT_IDS = {
    int(x.strip())
    for x in (env.get("BLOCKED_CHAT_IDS") or "").split(",")
    if x.strip()
}

# ============================================================
#  2. LAPORAN TERJADWAL KE GRUP TOPIC
#  Jadwal utama kini dikelola secara dinamis via SQLite (`storage/state/scheduler.db`).
#  Daftar di bawah ini hanya sebagai INITIAL SEED saat database pertama kali dibuat.
# ============================================================
JADWAL_KIRIM_KE_GRUP_REPORT = (env.get("JADWAL_KIRIM_KE_GRUP_REPORT") or "true").lower() == "true"

JADWAL_CEK_DETIK            = int(env.get("JADWAL_CEK_DETIK") or 10)
JADWAL_TUNGGU_MENIT         = int(env.get("JADWAL_TUNGGU_MENIT") or 90)
JADWAL_RETRY_BACKGROUND_JAM = int(env.get("JADWAL_RETRY_BACKGROUND_JAM") or 6)
JADWAL_MISFIRE_GRACE_S      = int(env.get("JADWAL_MISFIRE_GRACE_S") or 1800)
REPORT_TIMEOUT_MENIT        = int(env.get("REPORT_TIMEOUT_MENIT") or 90)

PRIMARY_HOST = env.get("PRIMARY_HOST") or ""

TOPIC_IDS = {
    "SALES":        int(env.get("TOPIC_SALES") or 0) or None,
    "COLLECTION":   int(env.get("TOPIC_COLLECTION") or 0) or None,
    "GTM":          int(env.get("TOPIC_GTM") or 0) or None,
    "CAPS":         int(env.get("TOPIC_CAPS") or 0) or None,
    "PARTNERSHIP":  int(env.get("TOPIC_PARTNERSHIP") or 0) or None,
    "FUNDAMENTAL":  int(env.get("TOPIC_FUNDAMENTAL") or 0) or None,
    "MARKET_SHARE": int(env.get("TOPIC_MARKET_SHARE") or 0) or None,
}

STOCK_ALERT_TOPIC_ID = int(env.get("STOCK_ALERT_TOPIC_ID") or 0) or TOPIC_IDS["PARTNERSHIP"]
STOCK_ALERT_ENABLED  = (env.get("STOCK_ALERT_ENABLED") or "false").lower() == "true"

# [DEPRECATED] Digantikan oleh SQLite (storage/state/scheduler.db).
# Disediakan sebagai fallback/initial template bagi database baru.
DEFAULT_INITIAL_SCHEDULE = [
    {"jam": 7,  "menit": 0,  "hari": None, "topic": "SALES", "laporan": [("closingsql", 1), ("dod", 1), ("nasional", 1)]},
    {"jam": 7,  "menit": 15, "hari": None, "topic": "SALES", "laporan": [("agresif", 1), ("wireless2", 1), ("wirelesschannel2", 1), ("murmer", 1)]},
    {"jam": 7,  "menit": 30, "hari": None, "topic": "FUNDAMENTAL", "laporan": [("5so", 1), ("7so", None), ("clockin_sf_teritory", 1), ("clockin_sf_all", 1), ("homepass_raw", 1)]},
    {"jam": 8,  "menit": 0,  "hari": None, "topic": "GTM", "laporan": [("leads", None), ("childps", 1)]},
    {"jam": 10, "menit": 0,  "hari": None, "topic": "MARKET_SHARE", "laporan": [("ms", None)]},
    {"jam": 10, "menit": 0,  "hari": "SENIN", "topic": "GTM", "laporan": [("homepass", 1), ("salahtagging", 1)]},
    {"jam": 13, "menit": 0,  "hari": None, "topic": "CAPS", "laporan": [("caps", 2)]},
    {"jam": 13, "menit": 0,  "hari": None, "topic": "SALES", "laporan": [("liveupdate", None)]},
    {"jam": 13, "menit": 15, "hari": None, "topic": "COLLECTION", "laporan": [("c3mr", 1), ("c3mrnew", 1), ("c3mrnewch", 1), ("c3mr10s", 1)]},
    {"jam": 15, "menit": 0,  "hari": None, "topic": "COLLECTION", "laporan": [("pranpcall", 1), ("pranpcagent", 1), ("moretensi", 1), ("pranpcsp", 1), ("pranpcprio", 1)]},
    {"jam": 15, "menit": 15, "hari": None, "topic": "SALES", "laporan": [("liveupdate", None)]},
    {"jam": 17, "menit": 0,  "hari": None, "topic": "SALES", "laporan": [("liveupdate", None)]},
    {"jam": 19, "menit": 0,  "hari": None, "topic": "SALES", "laporan": [("liveupdate", None)]},
    {"jam": 21, "menit": 0,  "hari": None, "topic": "SALES", "laporan": [("liveupdate", None)]},
]
JADWAL_LAPORAN = DEFAULT_INITIAL_SCHEDULE

REPORT_TITLE = env.get("REPORT_TITLE") or "Hourly Monitoring RE IndiHome JATENG-DIY"
REGION_NAME  = env.get("REGION_NAME") or "JATENG-DIY"

# ============================================================
#  3. KONFIGURASI DATABASE MySQL UTAMA (RAJAWALI)
# ============================================================
DB_HOST         = env.get("DB_HOST") or ""
DB_PORT         = int(env.get("DB_PORT") or 3307)
DB_USER         = env.get("DB_USER") or ""
DB_PASS         = env.get("DB_PASS") or ""
DB_NAME         = env.get("DB_NAME") or ""
DB_TABLE_PREFIX = env.get("DB_TABLE_PREFIX") or "dashboard_hourly_sales_"
DB_REGION       = env.get("DB_REGION") or "JATENG"

# ============================================================
#  4. KONFIGURASI DATABASE INDIANA (PraNPC) — server terpisah
# ============================================================
DB2_HOST     = env.get("DB2_HOST") or ""
DB2_PORT     = int(env.get("DB2_PORT") or 3306)
DB2_USER     = env.get("DB2_USER") or ""
DB2_PASS     = env.get("DB2_PASS") or ""
DB2_NAME     = env.get("DB2_NAME") or "indiana"
DB2_REGIONAL = env.get("DB2_REGIONAL") or "JATENG-DIY"

# ============================================================
#  5. KONFIGURASI FMC API (backup /liveupdateutoip)
# ============================================================
FMC_BASE_URL   = env.get("FMC_BASE_URL") or ""
FMC_COOKIE     = env.get("FMC_COOKIE") or ""
FMC_XTOKEN     = env.get("FMC_XTOKEN") or ""
FMC_VERIFY_SSL = (env.get("FMC_VERIFY_SSL") or "false").lower() == "true"

SCHEDULE_TIMES = [
    (8, 0), (12, 0), (13, 0), (15, 0), (16, 0), (17, 0), (20, 0), (21, 0),
]
SCHEDULE_TIMES_CLOSING = [(7, 0)]
SCHEDULE_TIMES_C3MR    = [(12, 0)]
SCHEDULE_TIMES_DOD     = [(8, 0)]

# ============================================================
#  DATA STRUKTUR WILAYAH (WOK & BRANCH)
#  Kini dipusatkan sepenuhnya di modul `wilayah.py`.
#  Impor di bawah ini disediakan demi backward-compatibility.
# ============================================================
from wilayah import (
    WOK_TO_BRANCH,
    BRANCH_ORDER,
    WOK_ORDER,
    WOK_TO_BRANCH as WOK_TO_BRANCH_BARU,
    WOK_ORDER     as WOK_ORDER_BARU,
    BRANCH_ORDER  as BRANCH_ORDER_BARU,
)

# ============================================================
#  6. REPORT /agresif & /djpprio
# ============================================================
AGRESIF_KIRIM_KE_TOPIC = (env.get("AGRESIF_KIRIM_KE_TOPIC") or "true").lower() == "true"

_djp_dir = Path(env.get("DJP_PRIORITY_MASTER_DIR") or "resources/djp_priority")
DJP_PRIORITY_MASTER_DIR = str(_djp_dir if _djp_dir.is_absolute() else (BASE_DIR / _djp_dir))

# ============================================================
#  7. REPORT /leads (Caring Order — jatenggayeng.id)
# ============================================================
JATENGGAYENG_BASE_URL = env.get("JATENGGAYENG_BASE_URL") or ""
JATENGGAYENG_USER     = env.get("JATENGGAYENG_USER") or ""
JATENGGAYENG_PASS     = env.get("JATENGGAYENG_PASS") or ""

# ============================================================
#  8. WhatsApp (WAHA HTTP API & Jadwal Otomatis WA)
# ============================================================
WAHA_BASE_URL            = env.get("WAHA_BASE_URL") or "https://localhost:3000"
WAHA_SESSION             = env.get("WAHA_SESSION") or "default"
WAHA_API_KEY             = env.get("WAHA_API_KEY") or ""
WAHA_TARGET_CHAT_ID      = env.get("WAHA_TARGET_CHAT_ID") or ""
WAHA_SEND_IMAGES         = (env.get("WAHA_SEND_IMAGES") or "true").lower() == "true"
WA_JADWAL_OTOMATIS_AKTIF = (env.get("WA_JADWAL_OTOMATIS_AKTIF") or "true").lower() == "true"

# JADWAL_LAPORAN_WA sudah DISATUKAN ke dalam JADWAL_LAPORAN utama di atas.
# Jadwal otomatis pengiriman ke WhatsApp kini mengikuti jadwal Telegram utama (BaseReport.send_wa = True).
JADWAL_LAPORAN_WA = []

# ============================================================
#  9. REPORT /murmer (EZNET Wireless Murmer)
# ============================================================
MURMER_TARGETS = {
    "JATENG-DIY":        int(env.get("MURMER_TARGET_JATENG_DIY") or 1275),
    "JATIM":             int(env.get("MURMER_TARGET_JATIM") or 1443),
    "JABAR":             int(env.get("MURMER_TARGET_JABAR") or 1804),
    "EASTERN JABOTABEK": int(env.get("MURMER_TARGET_EASTERN_JABOTABEK") or 1152),
}
MURMER_PRODUCT_KEYWORD = env.get("MURMER_PRODUCT_KEYWORD") or "murmer"
MURMER_YTD_START_MONTH = int(env.get("MURMER_YTD_START_MONTH") or 5)

# ============================================================
#  10. MODE QUERY LAPORAN TERJADWAL & OTOMASI RAJAWALI
# ============================================================
MODE_QUERY             = env.get("MODE_QUERY") or "rajawali"
RAJAWALI_TIMEOUT_MENIT = int(env.get("RAJAWALI_TIMEOUT_MENIT") or 60)
RAJAWALI_BLOK_INPUT    = (env.get("RAJAWALI_BLOK_INPUT") or "false").lower() == "true"

# ============================================================
#  11. REPORT /childps
# ============================================================
CHILDPS_KIRIM_KE_GRUP = (env.get("CHILDPS_KIRIM_KE_GRUP") or "true").lower() == "true"
CHILDPS_SQL           = env.get("CHILDPS_SQL") or None
