"""
bot.py — Bot utama Monitoring RE Jateng-DIY
Commands:
  /start             — panduan
  /status            — cek status bot
  /target            — lihat target tersimpan
  /closing DD-MM-YYYY      — laporan closing KPRO
  /closinghadoop DD-MM-YYYY
  /dailyreps         — ulang laporan daily RE+PS dari Hadoop terakhir
  /closingdaily DD-MM-YYYY

  [NEW - SQL Source]
  /liveupdate        — generate laporan dari DB sekarang (manual trigger)
  /liveupdateutoip   — backup /liveupdate, sumber data dari FMC API (bukan DB)
  /liveupdatebk      — backup /liveupdate, dihitung ulang dari tabel raw indihome_ordering_detail
  /dailyre DD/MM/YYYY — Monitoring Daily RE (target base weekday/weekend + gap kemarin, sumber hourly)
  /closingsql DD-MM-YYYY — laporan closing dari DB
  /closingutoip DD-MM-YYYY — backup /closingsql, sumber data dari FMC API (bukan DB)
  /closingbk DD-MM-YYYY — backup /closingsql, dihitung ulang dari tabel raw indihome_ordering_detail
  /kategoripaket DD-MM-YYYY — Sales by Kategori Paket (dipisah dari /closingsql)
  /ms [DD-MM-YYYY]   — Market Share per City + MOM Growth Jateng-DIY (sumber fixed_ms_city)
  /jadwal — daftar jadwal laporan otomatis yang aktif
  /reports_schedule — jadwal report otomatis dalam bentuk gambar tabel
  /wireless2, /wirelesschannel2 DD-MM-YYYY — /wireless & /wirelesschannel tanpa produk Murmer (yang dijadwalkan)
  /clockin_sf_teritory, /homepass_raw [DD-MM-YYYY] — Report Clock-in SF Teritory (HTML) & file homepass mentah dari scraping SELA
  /clockin_sf_all [DD-MM-YYYY] — Report Clock-In SF All Category (seluruh SF terdaftar) dari detail homepass SELA
  /dbstatus          — cek koneksi database
"""

import asyncio
import httpx
from telegram.request import HTTPXRequest
import logging
from logging.handlers import RotatingFileHandler
import os
import glob
import socket
import sys
import json
import re
import shutil
import tempfile
import pickle
import pandas as pd
from io import BytesIO
from datetime import datetime, date, timedelta
from types import SimpleNamespace
from dateutil.relativedelta import relativedelta

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters,
    JobQueue, TypeHandler, ApplicationHandlerStop
)

from config import (
    TOKEN, GROUP_ID, REPORT_TITLE, SCHEDULE_TIMES, SCHEDULE_TIMES_DOD, BRANCH_ORDER,
    BLOCKED_CHAT_IDS, REPORT_GROUP_ID, TOPIC_IDS, STOCK_ALERT_TOPIC_ID, STOCK_ALERT_ENABLED,
    JADWAL_LAPORAN,
    JADWAL_CEK_DETIK, JADWAL_TUNGGU_MENIT, JADWAL_MISFIRE_GRACE_S, JADWAL_RETRY_BACKGROUND_JAM,
    PRIMARY_HOST, REPORT_TIMEOUT_MENIT,
    AGRESIF_KIRIM_KE_TOPIC, DJP_PRIORITY_MASTER_DIR,
    WAHA_TARGET_CHAT_ID, WAHA_SEND_IMAGES, WA_JADWAL_OTOMATIS_AKTIF,
)
import config as _config
# True  = laporan TERJADWAL ke topic grup report (REPORT_GROUP_ID) + salinan ke GROUP_ID.
# False = laporan terjadwal HANYA ke grup koordinasi (GROUP_ID), tanpa topic.
# Dibaca dengan getattr supaya config.py lama (tanpa setelan ini) tetap jalan; default False.
JADWAL_KIRIM_KE_GRUP_REPORT = getattr(_config, "JADWAL_KIRIM_KE_GRUP_REPORT", False)
import reports  # mengaktifkan alias modul legacy + grup report BaseReport
from utils import gp_control
import mode_query
import wilayah
import calculator
import calculator_sql
import calculator_daily
import renderer
import renderer_daily
import renderer_simple
import renderer_daily_performance
import childps_bot
import renderer_city_performance
import renderer_channel
import calculator_channel
import calculator_djp
import calculator_djp_daily
import calculator_mb
import calculator_mb_daily
import renderer_djp
import renderer_djp_daily
import renderer_mb
import calculator_c3mr
import renderer_c3mr
import renderer_c3mr_los
import calculator_c3mr10s
import renderer_c3mr10s
import renderer_c3mr10s_seg
import calculator_c3mrnew
import renderer_c3mrnew
import calculator_caps
import calculator_pranpc
import renderer_pranpc
import renderer_caps
import calculator_caps_segment
import renderer_caps_segment
import calculator_caps_channel
import renderer_caps_channel
import calculator_caps_reason
import renderer_caps_reason
import calculator_sf
import renderer_sf
from reports import (
    addon,
    agresif,
    c3mr,
    caps,
    childps,
    closing,
    dailyre,
    djp_mb_sf,
    djpprio,
    dod,
    klaim,
    leads,
    pdd,
    performance,
    pranpc,
    promo,
    sf_momentum,
    wireless,
)


import calculator_dod
import renderer_dod
import calculator_promo
import renderer_promo
import calculator_pdd
import renderer_pdd
import calculator_klaim
import renderer_klaim
import calculator_addon
import renderer_addon
import agresif_data
import calculator_agresif       # dipakai cmd_agresif LITE (kalkulasi PS/FMC penuh utk caption) + cmd_agresif_full (DISABLED)
import renderer_agresif         # dipakai cmd_agresif_full (DISABLED) — dibiarkan supaya gampang di-restore
import agresif_native
import agresif_lite
import renderer_agresif_lite
# CATATAN 09-Sep-2026: /agresif kini = report LITE (2 report: LOKASI AGRESIF +
# ALL FMC CITY, caption tanpa blok "Growth Total PS"). Versi 3-report FULL
# (cmd_agresif_full) DINONAKTIFKAN tapi kodenya DIPERTAHANKAN utuh di bawah —
# untuk restore: ganti "agresif" di dict _LAPORAN & CommandHandler balik ke
# cmd_agresif_full, kembalikan teks HELP lama.
import calculator_djpprio
import renderer_djpprio
import calculator_dailyre
import renderer_dailyre
import calculator_wireless
import renderer_wireless
import calculator_stock_alert
import program_tracking
import calculator_performance
# import renderer_performance (dihapus, digantikan performance_browser)
import performance_browser
import leads_browser
import db

#whatsapp bot module
import whatsapp
from reports import murmer
from reports import c3mrnewch
from reports import kategori_promo
from reports import wireless_channel
from commands import kategori_paket as cmd_kategori_paket_mod
from commands import jadwal as cmd_jadwal_mod
from commands import reports_schedule as cmd_reports_schedule_mod
from commands import market_share as cmd_market_share_mod
from commands import wireless2 as cmd_wireless2_mod
from commands import clockin_sf_teritory as cmd_clockin_mod   # /clockin_sf_teritory, /homepass_raw
from commands import clockin_sf_all as cmd_clockin_all_mod   # /clockin_sf_all
from commands import c3mrsvp as cmd_c3mrsvp_mod
from commands import nasional as cmd_nasional_mod
from commands import homepass as cmd_homepass_mod
from commands import homepass_wok_old as cmd_homepass_wok_old_mod
from commands import salahtagging as cmd_salahtagging_mod
from commands import salahtagging_wok_old as cmd_salahtagging_wok_old_mod
from commands import jobs_manager as cmd_jobs_manager_mod
from utils import scheduler_db
from utils.command_registry import (
    CommandRegistry,
    TelegramCommand,
    post_init_sync_commands,
    sync_commands_to_db,
)

# ── Logging: ke console DAN ke file (biar kejadian scheduler/error ada jejaknya,
# bukan cuma nongol di layar lalu hilang). File dirotasi supaya tidak membengkak
# tanpa batas: maks 5 MB/file, simpan 5 file lama (bot_run.log, .1 ... .5).
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for _sub in ("logs", "logs/screenshots", "state", "locks", "sql_packets", "downloads"):
    os.makedirs(os.path.join(_BASE_DIR, "storage", _sub), exist_ok=True)

_LOG_PATH = os.path.join(_BASE_DIR, "storage", "logs", "bot_run.log")
_log_fmt  = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

_file_handler = RotatingFileHandler(
    _LOG_PATH, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(_log_fmt)

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logger = logging.getLogger(__name__)

_target_df         = None
_target_monthly_df = None
_target_city_df    = None
_target_caps_df    = None
_target_addon_dfs  = {}   # {"FTTR": df, "IP_CAM": df, "MESH_WIFI": df} dari sheet TARGET_MONTHLY_<PRODUK>
_target_agresif_kec_df = None   # sheet TARGET_AGRESIF_KEC — target PS Low/Mid per kecamatan (report 1 & 2 /agresif)
_target_fmc_city_df    = None   # sheet TARGET_FMC_CITY   — target PS Low/Mid per FMC city (report 3 /agresif)
_target_wireless_df    = None   # sheet TARGET_WIRELESS   — target IO/RE/PS EZNet Wireless per WOK (/wireless)
_target_region_df      = None   # sheet TARGET_REGION     — target BULANAN IO/RE/PS per region nasional (/nasional)
_sf_aktif_df       = None
_djp_csv_df        = None   # CSV DJP manual
_mb_csv_df         = None   # CSV MB manual
_last_kpro         = None
_last_kpro_upload_time   = None
_last_hadoop_upload_time = None
_last_djpcsv_upload_time = None

# Path ABSOLUT (anchor ke folder bot.py ini), BUKAN relatif — kalau bot
# dijalankan lewat scheduler/shortcut yang working directory-nya beda dari
# folder bot (mis. Task Scheduler default cwd System32), path relatif bikin
# save/load saved_target.pkl "ketuker folder": upload tersimpan ke satu
# folder, restart berikutnya baca dari folder lain (kosong/basi) -> target
# yang baru di-upload kelihatan hilang/balik ke lama setelah restart.
TARGET_STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "storage", "state", "saved_target.pkl"
)

# File Excel lokal (di folder bot ini) yang dipakai sebagai fallback target Addon/Agresif
# kalau belum ada yang di-upload via Telegram (/target) — supaya tidak perlu upload manual
# tiap kali file target di-update, cukup edit file ini langsung.
#
# Nama file INCREMENT per versi (template_target_2026_bot_v2.xlsx, _v3, _v4, ...) —
# supaya tidak perlu ubah kode tiap kali file baru dibuat, dipilih OTOMATIS file
# "template_target_2026_bot*.xlsx" yang PALING BARU diubah (mtime) di folder bot.
ADDON_TARGET_SHEETS = {
    "FTTR"     : "TARGET_MONTHLY_FTTR",
    "IP_CAM"   : "TARGET_MONTHLY_IN CAMERA",
    "MESH_WIFI": "TARGET_MONTHLY_MESH_WIFI",
}


def _find_latest_target_file() -> str | None:
    """Cari file template_target_2026_bot*.xlsx TERBARU (by mtime) di storage/state/targets/ atau root bot."""
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = glob.glob(os.path.join(base, "storage", "state", "targets", "template_target_2026_bot*.xlsx"))
    candidates += glob.glob(os.path.join(base, "template_target_2026_bot*.xlsx"))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _load_addon_target_from_local_file() -> dict:
    """
    Baca target Addon langsung dari file lokal (template_target_2026_bot*.xlsx
    TERBARU, lihat _find_latest_target_file) sheet TARGET_MONTHLY_FTTR / _IN CAMERA
    / _MESH_WIFI. Dipanggil tiap /addon dijalankan SEBAGAI FALLBACK saat belum ada
    target yang di-upload via Telegram (_target_addon_dfs kosong) — jadi perubahan
    di file lokal langsung kepakai tanpa perlu upload ulang ke bot.
    """
    path = _find_latest_target_file()
    if not path:
        return {}
    out = {}
    for prod, sheet_name in ADDON_TARGET_SHEETS.items():
        try:
            d = pd.read_excel(path, sheet_name=sheet_name)
            d.columns = d.columns.str.strip().str.upper()
            if {"BULAN", "WOK", "TARGET_PS"} <= set(d.columns):
                out[prod] = d
            else:
                logger.warning(f"[addon] Sheet {sheet_name} di {path} kolom tidak lengkap, dilewati.")
        except Exception as e:
            logger.warning(f"[addon] Gagal baca sheet {sheet_name} dari {path}: {e}")
    return out


# Sheet target /agresif — SATU FILE yang sama dengan target Addon (template_target_2026_
# bot*.xlsx TERBARU, lihat _find_latest_target_file), supaya semua target (RE/PS/CAPS/
# Addon/Agresif) terpusat & cukup diedit langsung tanpa upload ulang tiap kali berubah.
# Nama sheet & kolom MENGIKUTI struktur yang dipakai user (bukan nama ideal semula):
SHEET_TARGET_AGRESIF_KEC = "TARGET_KEC AGRESIF"   # BULAN,CITY,KEC,...,TARGET_PS_LOW,TARGET_PS_MIDHIGH
SHEET_TARGET_FMC_CITY    = "TARGET_CITY FMC"      # BULAN,WOK,CITY,...,TARGET_PS_LOW,TARGET_PS_MIDHIGH


def _load_agresif_target_from_local_file() -> tuple:
    """
    Baca target /agresif (kecamatan + FMC city) langsung dari file lokal
    (template_target_2026_bot*.xlsx TERBARU), dipanggil sebagai FALLBACK saat
    belum ada yang di-upload via Telegram — sama pola dengan
    _load_addon_target_from_local_file(). Return (df_kec, df_fmc), masing-masing
    bisa None kalau sheet tidak ada / kolom tidak lengkap.
    """
    path = _find_latest_target_file()
    if not path:
        return None, None
    df_kec = df_fmc = None
    try:
        d = pd.read_excel(path, sheet_name=SHEET_TARGET_AGRESIF_KEC)
        d.columns = d.columns.str.strip().str.upper()
        req = {"BULAN", "CITY", "KEC", "TARGET_PS_LOW", "TARGET_PS_MIDHIGH"}
        if req <= set(d.columns):
            df_kec = d
        else:
            logger.warning(f"[agresif] Sheet {SHEET_TARGET_AGRESIF_KEC} di {path} kolom tidak lengkap "
                            f"(punya: {list(d.columns)}), dilewati.")
    except Exception as e:
        logger.warning(f"[agresif] Gagal baca sheet {SHEET_TARGET_AGRESIF_KEC} dari {path}: {e}")
    try:
        d = pd.read_excel(path, sheet_name=SHEET_TARGET_FMC_CITY)
        d.columns = d.columns.str.strip().str.upper()
        req = {"BULAN", "CITY", "TARGET_PS_LOW", "TARGET_PS_MIDHIGH"}
        if req <= set(d.columns):
            df_fmc = d
        else:
            logger.warning(f"[agresif] Sheet {SHEET_TARGET_FMC_CITY} di {path} kolom tidak lengkap "
                            f"(punya: {list(d.columns)}), dilewati.")
    except Exception as e:
        logger.warning(f"[agresif] Gagal baca sheet {SHEET_TARGET_FMC_CITY} dari {path}: {e}")
    return df_kec, df_fmc


SHEET_TARGET_WIRELESS = "TARGET_WIRELESS"   # BULAN,WOK,TARGET_IO,TARGET_RE,TARGET_PS


def _load_wireless_target_from_local_file():
    """
    Baca target /wireless dari file lokal (template_target_2026_bot*.xlsx TERBARU)
    sheet TARGET_WIRELESS — FALLBACK saat belum ada yang di-upload via /target,
    sama pola dgn _load_agresif_target_from_local_file(). None kalau sheet tidak
    ada / kolom tidak lengkap.
    """
    path = _find_latest_target_file()
    if not path:
        return None
    try:
        d = pd.read_excel(path, sheet_name=SHEET_TARGET_WIRELESS)
        d.columns = d.columns.str.strip().str.upper()
        if {"BULAN", "WOK", "TARGET_IO", "TARGET_RE", "TARGET_PS"} <= set(d.columns):
            return d
        logger.warning(f"[wireless] Sheet {SHEET_TARGET_WIRELESS} di {path} kolom tidak lengkap "
                        f"(punya: {list(d.columns)}), dilewati.")
    except Exception as e:
        logger.warning(f"[wireless] Gagal baca sheet {SHEET_TARGET_WIRELESS} dari {path}: {e}")
    return None


def _save_target_state():
    """Simpan semua dataframe target ke disk supaya tidak hilang saat bot restart."""
    state = {
        "target_df"        : _target_df,
        "target_monthly_df": _target_monthly_df,
        "target_city_df"   : _target_city_df,
        "sf_aktif_df"       : _sf_aktif_df,
        "target_caps_df"   : _target_caps_df,
        "target_addon_dfs" : _target_addon_dfs,
        "target_agresif_kec_df": _target_agresif_kec_df,
        "target_fmc_city_df"   : _target_fmc_city_df,
        "target_wireless_df"   : _target_wireless_df,
        "target_region_df"     : _target_region_df,
    }
    try:
        with open(TARGET_STATE_FILE, "wb") as f:
            pickle.dump(state, f)
        logger.info(f"[TARGET] State tersimpan ke {TARGET_STATE_FILE}")
    except Exception as e:
        logger.warning(f"[TARGET] Gagal menyimpan state ke disk: {e}")


def _load_target_state():
    """Muat kembali dataframe target dari disk saat bot start (kalau ada)."""
    global _target_df, _target_monthly_df, _target_city_df, _sf_aktif_df, _target_caps_df, _target_addon_dfs
    global _target_agresif_kec_df, _target_fmc_city_df, _target_wireless_df, _target_region_df

    try:
        with open(TARGET_STATE_FILE, "rb") as f:
            state = pickle.load(f)
    except FileNotFoundError:
        logger.info("[TARGET] Tidak ada state tersimpan, mulai dari kosong.")
        return
    except Exception as e:
        logger.warning(f"[TARGET] Gagal memuat state dari disk: {e}")
        return

    if not isinstance(state, dict):
        logger.warning("[TARGET] Format state tidak dikenali, dilewati.")
        return

    _target_df         = state.get("target_df")
    _target_monthly_df = state.get("target_monthly_df")
    _target_city_df    = state.get("target_city_df")
    _sf_aktif_df       = state.get("sf_aktif_df")
    _target_caps_df    = state.get("target_caps_df")
    _target_addon_dfs  = state.get("target_addon_dfs", {})
    _target_agresif_kec_df = state.get("target_agresif_kec_df")
    _target_fmc_city_df    = state.get("target_fmc_city_df")
    _target_wireless_df    = state.get("target_wireless_df")
    _target_region_df      = state.get("target_region_df")
    logger.info("[TARGET] State berhasil dimuat dari disk.")
_last_hadoop       = None

KOLOM_KPRO   = {"DATECREATED", "WOK", "BRANCH", "REGION"}
KOLOM_HADOOP = {"re_ts", "wok", "branch", "region"}
KOLOM_DJP    = {"SCHEDULE CATEGORY", "STATUS", "WOK", "BRANCH", "REGION",
                "TUGAS DATE", "USER CODE", "ODP", "TUGAS ID"}

def _validasi_djp(df: pd.DataFrame) -> list:
    cols = set(df.columns.str.upper())
    return list(KOLOM_DJP - cols)


def _parse_excel_csv(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        # Auto-detect separator: coba baca baris pertama
        sample = file_bytes[:2048].decode("utf-8", errors="ignore")
        first_line = sample.split("\n")[0]
        sep = ";" if first_line.count(";") > first_line.count(",") else ","
        df = pd.read_csv(BytesIO(file_bytes), sep=sep, low_memory=False)
    else:
        df = pd.read_excel(BytesIO(file_bytes))
    df.columns = df.columns.str.strip()
    return df


def _validasi_kpro(df: pd.DataFrame) -> list:
    cols_upper = set(df.columns.str.upper())
    return list(KOLOM_KPRO - cols_upper)


def _validasi_hadoop(df: pd.DataFrame) -> list:
    cols_lower = set(df.columns.str.lower())
    return list(KOLOM_HADOOP - cols_lower)


def _greeting() -> str:
    return "Semangat pagi!"


def _buat_caption(result: dict, upload_time: datetime, mode: str = "hourly") -> str:
    woks = [w for w in result["woks"] if w["pct_ach"] is not None]
    woks_sorted = sorted(woks, key=lambda w: w["pct_ach"], reverse=True)

    top5    = woks_sorted[:5]
    bottom5 = woks_sorted[-5:][::-1]

    if mode == "closing":
        tgl = result["hari_ini"]
        label_tgl = f"{tgl.strftime('%d-%m-%Y')} (Closing)"
        label_ach = "Closing"
    else:
        label_tgl = upload_time.strftime('%d-%m-%Y %H.%M')
        label_ach = "HI"

    lines = [
        _greeting(),
        f"Berikut disampaikan checkpoint RE IndiHome {result['region']['name']}",
        f"Update {label_tgl}",
        "-------",
        "",
        f"Top 5 WOK Ach RE {label_ach}",
    ]
    for w in top5:
        lines.append(f"  {w['name']}  {w['pct_ach']:.0f}%")

    lines += ["", f"Bottom 5 WOK Ach RE {label_ach}"]
    for w in bottom5:
        lines.append(f"  {w['name']}  {w['pct_ach']:.0f}%")

    return "\n".join(lines)


def _buat_caption_daily(result: dict, upload_time: datetime, source: str = "sql") -> str:
    """
    Caption laporan daily (report ke-2 /closingsql): ringkasan DoD/WoW/MoM RE
    level region + Top 3 & Bottom 3 WOK berdasarkan %WoW RE.
    """
    hari_ini = result["hari_ini"]
    region   = result.get("region") or {}
    woks     = result.get("woks") or []

    if result.get("mode") == "closing":
        label_waktu = f"Closing {hari_ini.strftime('%d-%m-%Y')}"
    else:
        label_waktu = upload_time.strftime('%d-%m-%Y %H.%M')

    def _pct(v):
        # Tanda +/- ditulis eksplisit — "WoW 14.3%" saja tidak ketahuan naik/turun.
        return "-" if v is None else f"{v:+.1f}%"

    def _num(v):
        return "-" if v is None else f"{int(v):,}"

    # Top 3 & Bottom 3 WOK berdasarkan %WoW RE.
    # WOK yang minggu lalunya 0 -> re_wow None (tidak bisa dihitung) -> dilewati
    # supaya tidak salah masuk daftar bottom.
    valid   = [w for w in woks if w.get("re_wow") is not None]
    urut    = sorted(valid, key=lambda w: w["re_wow"], reverse=True)
    top3    = urut[:3]
    bottom3 = list(reversed(urut[-3:]))

    def _baris(rows):
        if not rows:
            return ["- data tidak tersedia"]
        return [f"- {w['name']} | WoW {_pct(w['re_wow'])}" for w in rows]

    lines = [
        "📊 DoD, WoW & MoM IndiHome Jateng-DIY",
        label_waktu,
        "",
        f"RE JATENG-DIY Today {_num(region.get('re_today'))}",
        f"DoD {_pct(region.get('re_dod'))} | WoW {_pct(region.get('re_wow'))} | MoM {_pct(region.get('re_mom'))}",
        "",
        "📈 Top 3 WoW RE",
        *_baris(top3),
        "",
        "📉 Bottom 3 WoW RE",
        *_baris(bottom3),
    ]
    return "\n".join(lines)


async def _get_cutoff_db() -> str:
    """String singkat cutoff data terakhir dari DB (tabel RE/PS/IO hourly_sales), untuk ditempel di gambar."""
    try:
        info        = db.query_last_update()
        last_update = info.get("last_update")
        if last_update:
            return last_update.strftime('%d-%m-%Y %H:%M')
    except Exception as e:
        logger.warning(f"Gagal ambil info cutoff DB: {e}")
    return None


async def _get_cutoff_raw() -> str:
    """String singkat cutoff data terakhir dari tabel RAW indihome_ordering_detail,
    untuk /liveupdatebk (mode hourly). Lihat db.query_last_update_raw()."""
    try:
        info        = db.query_last_update_raw()
        last_update = info.get("last_update")
        if last_update:
            return last_update.strftime('%d-%m-%Y %H:%M')
    except Exception as e:
        logger.warning(f"Gagal ambil info cutoff raw ordering_detail: {e}")
    return None


async def _get_cutoff_order_terbaru() -> str:
    """Cutoff laporan live /liveupdate: waktu order terbaru hari ini =
    MAX(io_ts, re_ts, ps_ts) — sama dengan batas jam data yang dihitung
    (calculator_sql: cutoff_hour = jam tertinggi hari ini). Bila belum ada
    order hari ini, pakai last_update tabel + keterangan."""
    ket = "diambil dari MAX io_ts/re_ts/ps_ts order hari ini"
    try:
        t = await asyncio.to_thread(db.query_order_terbaru_hari_ini)
        if t:
            return f"{t.strftime('%d-%m-%Y %H:%M')} ({ket})"
        lu = await _get_cutoff_raw()
        return f"{lu} (belum ada order hari ini; dari kolom last_update)" if lu else None
    except Exception as e:
        logger.warning(f"Gagal ambil cutoff order terbaru: {e}")
        return None


def _get_cutoff_upload(upload_time: datetime) -> str:
    """String singkat cutoff berdasarkan waktu file terakhir diupload, untuk ditempel di gambar."""
    return upload_time.strftime('%d-%m-%Y %H:%M') if upload_time else None


async def _get_cutoff_tabel(label_keyword: str) -> str:
    """
    String singkat cutoff data untuk tabel sumber tertentu (DJP/C3MR/CAPS/dsb),
    berdasarkan db.query_all_table_status() (sama yang dipakai /dbstatus), untuk ditempel di gambar.
    label_keyword dicocokkan case-insensitive ke label tabel, mis. "djp", "c3mr".
    """
    try:
        statuses = await asyncio.to_thread(db.query_all_table_status)
        match = next((s for s in statuses if label_keyword.lower() in s["label"].lower()), None)
        if match and not match["error"] and match["last_update"]:
            return match["last_update"].strftime('%d-%m-%Y %H:%M')
    except Exception as e:
        logger.warning(f"Gagal ambil info cutoff tabel ({label_keyword}): {e}")
    return None


async def _kirim_laporan(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                         df: pd.DataFrame, upload_time: datetime,
                         mode: str = "hourly", tgl_closing: date = None,
                         source: str = "kpro", cutoff: str = None):
    result  = calculator.hitung_re(df, _target_df, upload_time,
                                   mode=mode, tgl_closing=tgl_closing)
    img_buf = renderer.render_tabel(result, source=source, cutoff=cutoff)
    caption = _buat_caption(result, upload_time, mode=mode)

    img_buf.seek(0)
    await update.message.reply_photo(
        photo=InputFile(img_buf, filename="monitoring_re.png"),
        caption=caption
    )

    if update.effective_chat.id != GROUP_ID:
        img_buf.seek(0)
        await ctx.bot.send_photo(
            chat_id=GROUP_ID,
            photo=InputFile(img_buf, filename="monitoring_re.png"),
            caption=caption
        )
        await update.message.reply_text("✅ Laporan sudah dikirim ke grup manajemen.")


async def _kirim_laporan_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                                df: pd.DataFrame, upload_time: datetime,
                                tgl_closing: date = None, cutoff: str = None):
    """Generate & kirim laporan daily RE+PS dari Hadoop."""
    mode   = "closing" if tgl_closing else "hourly"
    result = calculator.hitung_re_ps(df, _target_df, upload_time,
                                     mode=mode, tgl_closing=tgl_closing)
    img_buf = renderer_daily.render_daily(result, source="hadoop", cutoff=cutoff)
    caption = _buat_caption_daily(result, upload_time, source="hadoop")

    img_buf.seek(0)
    await update.message.reply_photo(
        photo=InputFile(img_buf, filename="daily_re_ps.png"),
        caption=caption,
        parse_mode="Markdown"
    )

    if update.effective_chat.id != GROUP_ID:
        img_buf.seek(0)
        await ctx.bot.send_photo(
            chat_id=GROUP_ID,
            photo=InputFile(img_buf, filename="daily_re_ps.png"),
            caption=caption,
            parse_mode="Markdown"
        )


# ── SQL Source: core function ─────────────────────────────────────────────────
async def _kirim_laporan_sql(bot, chat_id: int, upload_time: datetime,
                              mode: str = "hourly", tgl_closing: date = None,
                              reply_msg=None, data_source: str = "db"):
    """
    Generate & kirim laporan dari DB (atau FMC API jika data_source="fmc").
    - liveupdate (mode=hourly)  : monitoring RE + monitoring RE PS hourly
    - closingsql (mode=closing) : monitoring RE closing + daily RE PS
    """
    result_daily = calculator_sql.hitung_re_ps_sql(
        _target_df, upload_time, mode=mode, tgl_closing=tgl_closing,
        data_source=data_source
    )

    if mode == "closing":
        # renderer.py/renderer_daily.py cuma kenal source "sql"/"hadoop"/"fmc"/"raw" —
        # mapping supaya footer sumber benar (sama pola dengan branch hourly).
        # Closing "db" (/closingsql) sejak 08-Okt-2026 bersumber indihome_ordering_detail
        # (bukan dashboard_hourly_sales) -> footer pakai source "ordering".
        render_source = "fmc" if data_source == "fmc" else ("raw" if data_source == "raw" else "ordering")
        fname_suffix  = "_fmc" if data_source == "fmc" else ("_raw" if data_source == "raw" else "")

        if data_source == "fmc":
            # Tidak ada cutoff "last update" yang bermakna dari FMC (data live
            # per-request, bukan tabel dengan timestamp ingest) — pakai waktu
            # generate laporan, sama seperti liveupdateutoip.
            cutoff_str = _get_cutoff_upload(upload_time)
        elif data_source == "raw":
            # ── Closing (raw): cutoff dari tabel indihome_ordering_detail sendiri ──
            try:
                info_cutoff = db.query_last_update_raw()
                last_update = info_cutoff.get("last_update")
                last_date   = info_cutoff.get("last_date")
                if last_update:
                    cutoff_str = last_update.strftime('%d-%m-%Y %H:%M')
                    if last_date and last_date < tgl_closing:
                        cutoff_str = (
                            f"⚠️ data {tgl_closing.strftime('%d-%m-%Y')} belum tersedia, "
                            f"pakai data terakhir {cutoff_str}"
                        )
                else:
                    cutoff_str = None
            except Exception as e:
                logger.warning(f"Gagal ambil info cutoff raw ordering_detail: {e}")
                cutoff_str = None
        else:
            # ── Closing: cutoff data DB (indihome_ordering_detail), ditempel di tiap gambar ──
            try:
                info_cutoff = db.query_last_update_raw()
                last_update = info_cutoff.get("last_update")
                last_date   = info_cutoff.get("last_date")
                if last_update:
                    cutoff_str = last_update.strftime('%d-%m-%Y %H:%M')
                    if last_date and last_date < tgl_closing:
                        cutoff_str = (
                            f"⚠️ data {tgl_closing.strftime('%d-%m-%Y')} belum tersedia, "
                            f"pakai data terakhir {cutoff_str}"
                        )
                else:
                    cutoff_str = None
            except Exception as e:
                logger.warning(f"Gagal ambil info cutoff data: {e}")
                cutoff_str = None

        # ── Closing: Monitoring RE closing ────────────────────────────────
        result_hourly = _convert_daily_to_hourly(result_daily)
        img_hourly    = renderer.render_tabel(result_hourly, source=render_source, cutoff=cutoff_str)
        caption_h     = _buat_caption_hourly_sql(result_daily, upload_time, mode,
                                                  data_source=data_source)

        fname_hourly = f"monitoring_re_closing{fname_suffix}.png"
        await _kirim_foto_retry(bot, chat_id, img_hourly, fname_hourly,
                                 caption=caption_h, label="closingsql_hourly")
        if reply_msg and reply_msg.chat.id != GROUP_ID:
            await _kirim_foto_retry(bot, GROUP_ID, img_hourly, fname_hourly,
                                     caption=caption_h, label="closingsql_hourly_grup")

        # ── Closing: Daily RE PS (WoW, MoM) ───────────────────────────────
        img_daily  = renderer_daily.render_daily(result_daily, source=render_source, cutoff=cutoff_str)
        caption_d  = _buat_caption_daily(result_daily, upload_time, source=render_source)

        fname_daily = f"daily_re_ps{fname_suffix}.png"
        await _kirim_foto_retry(bot, chat_id, img_daily, fname_daily,
                                 caption=caption_d, label="closingsql_daily")
        if reply_msg and reply_msg.chat.id != GROUP_ID:
            await _kirim_foto_retry(bot, GROUP_ID, img_daily, fname_daily,
                                     caption=caption_d, label="closingsql_daily_grup")

        # ── Closing: Daily Performance WOK level ──────────────────────────
        try:
            result_dp = calculator_daily.hitung_daily_performance(
                _target_monthly_df, tgl_closing, data_source=data_source
            )

            def _top_bottom(rows, field, name_field="name"):
                valid = [r for r in rows if r.get(field) is not None]
                if not valid: return "-", "-"
                top    = max(valid, key=lambda r: r[field])
                bottom = min(valid, key=lambda r: r[field])
                return top[name_field], bottom[name_field]

            br_top_re,  br_bot_re  = _top_bottom(result_dp["branches"], "re_ach")
            br_top_ps,  br_bot_ps  = _top_bottom(result_dp["branches"], "ps_ach")
            wok_top_re, wok_bot_re = _top_bottom(result_dp["woks"], "re_ach")
            wok_top_ps, wok_bot_ps = _top_bottom(result_dp["woks"], "ps_ach")

            caption_dp = (
                f"Performance MtD Sales IndiHome JATENG-DIY by WOK\n"
                f"Update {tgl_closing.strftime('%d-%m-%Y')}\n"
                f"\n"
                f"BRANCH\n"
                f"🥇 Top Ach RE - {br_top_re}\n"
                f"🏳️ Bottom Ach RE - {br_bot_re}\n"
                f"\n"
                f"🥇 Top Ach PS - {br_top_ps}\n"
                f"🏳️ Bottom Ach PS - {br_bot_ps}\n"
                f"\n"
                f"WOK\n"
                f"🥇 Top Ach RE - {wok_top_re}\n"
                f"🏳️ Bottom Ach RE - {wok_bot_re}\n"
                f"\n"
                f"🥇 Top Ach PS - {wok_top_ps}\n"
                f"🏳️ Bottom Ach PS - {wok_bot_ps}"
            )
            has_tgt_dp = any(r.get("re_tgt") is not None for r in result_dp.get("woks", []))
            if not has_tgt_dp:
                caption_dp += "\n\n⚠️ Target belum tersedia (Target & Ach ditampilkan -)"
            elif data_source == "fmc":
                caption_dp += "\n\n⚠️ Revenue/ARPU N/A (tidak ada di FMC)"
            elif data_source == "raw":
                caption_dp += "\n\n⚠️ Revenue/ARPU N/A (belum di-query dari raw ordering_detail)"

            img_dp = renderer_daily_performance.render_daily_performance(result_dp, cutoff=cutoff_str)
            fname_dp = f"daily_performance_wok{fname_suffix}.png"
            await _kirim_foto_retry(bot, chat_id, img_dp, fname_dp,
                                     caption=caption_dp, label="closingsql_dp")
            if reply_msg and reply_msg.chat.id != GROUP_ID:
                await _kirim_foto_retry(bot, GROUP_ID, img_dp, fname_dp,
                                         caption=caption_dp, label="closingsql_dp_grup")

            # ── Closing: Daily Performance City level ──────────────────────
            # Selalu dari DB — FMC tidak punya field kabupaten (lihat
            # calculator_daily.hitung_city_performance).
            result_city = calculator_daily.hitung_city_performance(
                _target_monthly_df, tgl_closing, target_city_df=_target_city_df
            )
            caption_city = (
                f"📊 Performance MtD Sales IndiHome JATENG-DIY by City\n"
                f"Update {tgl_closing.strftime('%d-%m-%Y')}"
            )
            has_tgt_city = any(r.get("re_tgt") is not None for r in result_city.get("cities", []))
            if not has_tgt_city:
                caption_city += "\n⚠️ Target belum tersedia (Target & Ach ditampilkan -)"
            elif data_source == "fmc":
                caption_city += "\n(sumber: DB indihome_ordering_detail — FMC tidak punya data kabupaten)"
            elif data_source == "raw":
                caption_city += "\n(sumber: DB indihome_ordering_detail)"
            img_city = renderer_city_performance.render_city_performance(result_city, cutoff=cutoff_str)
            await _kirim_dokumen_retry(bot, chat_id, img_city, "daily_performance_city.png",
                                        caption=caption_city, label="closingsql_city")
            if reply_msg and reply_msg.chat.id != GROUP_ID:
                await _kirim_dokumen_retry(bot, GROUP_ID, img_city, "daily_performance_city.png",
                                            caption=caption_city, label="closingsql_city_grup")
        except Exception as e:
            logger.warning(f"Daily Performance gagal: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Daily Performance tidak tersedia:\n`{e}`",
                parse_mode="Markdown"
            )

        # ── Closing: Export Raw CSV (ZIP) ──────────────────────────────────
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="⏳ Menyiapkan data raw CSV..."
            )
            zip_bytes, csv_filename = calculator_daily.export_raw_csv(tgl_closing, data_source=data_source)
            zip_filename = csv_filename.replace(".csv", ".zip")

            bl_label  = (tgl_closing - relativedelta(months=1)).strftime('%b %Y')
            mtd_label = tgl_closing.strftime('%d %b %Y')
            label_src = " (FMC, kolom native beda dari DB)" if data_source == "fmc" else ""

            await bot.send_document(
                chat_id=chat_id,
                document=InputFile(BytesIO(zip_bytes), filename=zip_filename),
                caption=f"📦 Data raw ordering detail JATENG-DIY{label_src}\n"
                        f"FM {bl_label} + MtD {mtd_label}\n"
                        f"Total: {len(zip_bytes):,} bytes (ZIP)"
            )
            if reply_msg and reply_msg.chat.id != GROUP_ID:
                await bot.send_document(
                    chat_id=GROUP_ID,
                    document=InputFile(BytesIO(zip_bytes), filename=zip_filename),
                    caption=f"📦 Data raw ordering detail JATENG-DIY{label_src}\n"
                            f"FM {bl_label} + MtD {mtd_label}"
                )
        except Exception as e:
            logger.warning(f"Export CSV gagal: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Export CSV gagal:\n`{e}`",
                parse_mode="Markdown"
            )

        # ── Closing: IO RE PS by Channel ──────────────────────────────────
        try:
            result_ch  = calculator_channel.hitung_channel(tgl_closing, data_source=data_source)
            img_ch     = renderer_channel.render_channel(result_ch, cutoff=cutoff_str)
            caption_ch = (
                f"📊 IO RE PS by Channel IndiHome Jateng-DIY\n"
                f"MtD {tgl_closing.strftime('%d-%m-%Y')}  |  "
                f"MoM vs {result_ch['bl_label']}"
            )
            fname_ch = f"channel_report{fname_suffix}.png"
            await _kirim_foto_retry(bot, chat_id, img_ch, fname_ch,
                                     caption=caption_ch, label="closingsql_channel")
            if reply_msg and reply_msg.chat.id != GROUP_ID:
                await _kirim_foto_retry(bot, GROUP_ID, img_ch, fname_ch,
                                         caption=caption_ch, label="closingsql_channel_grup")
        except Exception as e:
            logger.warning(f"Channel report gagal: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Channel report gagal:\n`{e}`",
                parse_mode="Markdown"
            )

        # Sales by Kategori Paket TIDAK lagi dikirim dari sini — dipisah jadi
        # command /kategoripaket (commands/kategori_paket.py).
        if data_source == "db":
            # ── Closing: Sales by Kategori Promo Paket ──
            try:
                result_kpr  = kategori_promo.hitung_kategori_promo(tgl_closing)
                img_kpr     = kategori_promo.render_kategori_promo(result_kpr, cutoff=cutoff_str)
                caption_kpr = kategori_promo.build_caption(result_kpr)
                fname_kpr   = f"kategori_promo_report{fname_suffix}.png"
                await _kirim_foto_retry(bot, chat_id, img_kpr, fname_kpr,
                                         caption=caption_kpr, label="closingsql_kategori_promo")
                if reply_msg and reply_msg.chat.id != GROUP_ID:
                    await _kirim_foto_retry(bot, GROUP_ID, img_kpr, fname_kpr,
                                             caption=caption_kpr, label="closingsql_kategori_promo_grup")
            except Exception as e:
                logger.warning(f"Kategori Promo report gagal: {e}")
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Kategori Promo report gagal:\n`{e}`",
                    parse_mode="Markdown"
                )

    else:
        # ── Liveupdate: Monitoring RE hourly ──────────────────────────────
        # renderer.py/renderer_simple.py cuma kenal source "sql"/"hadoop"/"fmc"/"raw",
        # sedangkan data_source di sini "db"/"fmc"/"raw" — mapping supaya footer sumber benar.
        if data_source == "fmc":
            render_source = "fmc"
            cutoff_str    = _get_cutoff_upload(upload_time)
        elif data_source == "raw":
            render_source = "raw"
            cutoff_str    = await _get_cutoff_raw()
        else:
            render_source = "sql"
            cutoff_str    = await _get_cutoff_db()

        result_hourly = _convert_daily_to_hourly(result_daily)
        img_hourly    = renderer.render_tabel(result_hourly, source=render_source, cutoff=cutoff_str)
        caption_h     = _buat_caption_hourly_sql(result_daily, upload_time, mode,
                                                  data_source=data_source)

        fname_hourly = (
            "monitoring_re_fmc.png" if data_source == "fmc" else
            "monitoring_re_raw.png" if data_source == "raw" else
            "monitoring_re_sql.png"
        )
        await _kirim_foto_retry(bot, chat_id, img_hourly, fname_hourly,
                                 caption=caption_h, label="liveupdate_hourly")
        if reply_msg and reply_msg.chat.id != GROUP_ID:
            await _kirim_foto_retry(bot, GROUP_ID, img_hourly, fname_hourly,
                                     caption=caption_h, label="liveupdate_hourly_grup")

        # ── Liveupdate: Monitoring RE PS hourly (simpel) ──────────────────
        img_simple   = renderer_simple.render_simple(result_daily, source=render_source, cutoff=cutoff_str)
        fname_simple = (
            "monitoring_re_ps_fmc.png" if data_source == "fmc" else
            "monitoring_re_ps_raw.png" if data_source == "raw" else
            "monitoring_re_ps_sql.png"
        )
        await _kirim_foto_retry(bot, chat_id, img_simple, fname_simple, label="liveupdate_simple")
        if reply_msg and reply_msg.chat.id != GROUP_ID:
            await _kirim_foto_retry(bot, GROUP_ID, img_simple, fname_simple, label="liveupdate_simple_grup")


def _convert_daily_to_hourly(result_daily: dict) -> dict:
    """
    Konversi output hitung_re_ps_sql() ke format yang diharapkan render_tabel().
    render_tabel() butuh field: target, d1_fd, d1_hourly, d, pct_hourly,
                                gap_hourly, pct_fd, gap_fd, pct_ach
    """
    def conv(r: dict) -> dict:
        d       = r.get("re_today", 0)
        d1fd    = r.get("re_d1_fd", 0) or 0
        d1h     = r.get("re_d1_hourly", 0) or 0
        d7fd    = r.get("re_d7_fd", 0) or 0
        d7h     = r.get("re_d7_hourly", 0) or 0
        return {
            "name"       : r["name"],
            "target"     : r.get("re_target"),
            "d1_fd"      : d1fd,
            "d1_hourly"  : d1h,
            "d"          : d,
            "pct_hourly" : _pct_diff(d, d1h),
            "gap_hourly" : (d - d1h) if d1h > 0 else None,
            "pct_fd"     : _pct_diff(d, d1fd),
            "gap_fd"     : (d - d1fd) if d1fd > 0 else None,
            "pct_ach"    : r.get("re_pct_ach"),
            "rank"       : r.get("rank"),
            "d7_fd"      : d7fd,
            "d7_hourly"  : d7h,
            "pct_d7_hourly": _pct_diff(d, d7h),
        }

    return {
        "upload_time" : result_daily["upload_time"],
        "hari_ini"    : result_daily["hari_ini"],
        "mode"        : result_daily["mode"],
        "region"      : conv(result_daily["region"]),
        "branches"    : [conv(b) for b in result_daily["branches"]],
        "woks"        : [conv(w) for w in result_daily["woks"]],
    }


def _pct_diff(d, d1):
    """Hitung % perubahan dari d1 ke d."""
    if d1 and d1 > 0:
        return round((d - d1) / d1 * 100, 1)
    return None


def _buat_caption_hourly_sql(result: dict, upload_time: datetime, mode: str,
                              data_source: str = "db") -> str:
    """Caption untuk laporan hourly RE dari SQL (atau FMC API jika backup)."""
    woks = [w for w in result["woks"] if w["re_pct_ach"] is not None]
    woks_sorted = sorted(woks, key=lambda w: w["re_pct_ach"], reverse=True)

    top5    = woks_sorted[:5]
    bottom5 = woks_sorted[-5:][::-1]

    if mode == "closing":
        label_tgl = f"{result['hari_ini'].strftime('%d-%m-%Y')} (Closing)"
        label_ach = "Closing"
    else:
        label_tgl = upload_time.strftime('%d-%m-%Y %H.%M')
        label_ach = "HI"

    label_src = (
        "Live FMC (backup)" if data_source == "fmc" else
        "Live Raw ordering_detail (backup)" if data_source == "raw" else
        "Live DB"
    )

    lines = [
        f"Semangat pagi! 🗄️ {label_src}",
        f"Checkpoint RE IndiHome {result['region']['name']}",
        f"Update {label_tgl}",
        "-------",
        "",
        f"Top 5 WOK Ach RE {label_ach}",
    ]
    for w in top5:
        lines.append(f"  {w['name']}  {w['re_pct_ach']:.0f}%")

    lines += ["", f"Bottom 5 WOK Ach RE {label_ach}"]
    for w in bottom5:
        lines.append(f"  {w['name']}  {w['re_pct_ach']:.0f}%")

    return "\n".join(lines)


async def cmd_dbinfo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/dbinfo — cek update terakhir data di DB."""
    await update.message.reply_text("⏳ Mengecek update terakhir database...")
    try:
        info = db.query_last_update()
        last_update = info["last_update"]
        last_date   = info["last_date"]
        last_hour   = info["last_hour"]
        total_rows  = info["total_rows"]

        if last_update is None:
            await update.message.reply_text(
                f"⚠️ Tidak ada data di tabel `{info['tabel']}`",
                parse_mode="Markdown"
            )
            return

        # Hitung delay dari sekarang
        now   = datetime.now()
        delta = now - last_update
        menit = int(delta.total_seconds() // 60)
        if menit < 60:
            delay_str = f"{menit} menit yang lalu"
        else:
            jam  = menit // 60
            sisa = menit % 60
            delay_str = f"{jam} jam {sisa} menit yang lalu"

        await update.message.reply_text(
            f"🗄️ *Info Database*\n\n"
            f"Tabel: `{info['tabel']}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🕐 *Update terakhir:*\n"
            f"   `{last_update.strftime('%d-%m-%Y %H:%M:%S')}`\n"
            f"   _{delay_str}_\n\n"
            f"📅 Tanggal terakhir: `{last_date.strftime('%d-%m-%Y') if last_date else '-'}`\n"
            f"⏰ Jam terakhir: `{last_hour:02d}:00`\n"
            f"📊 Total baris (region): `{total_rows:,}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Error /dbinfo")
        await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")



async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /menu — Tampilkan daftar command secara ringkas dari tabel SQLite `bot_commands`.
    Gunakan `/menu help <command>` atau `/<command> help` untuk melihat detail lengkap.
    """
    from telegram.constants import ParseMode
    from utils.command_registry import (
        build_command_help_text,
        build_concise_menu_text,
        get_command_from_db,
    )

    raw_args = [a.strip() for a in (ctx.args or []) if a.strip()]
    teks = ""
    if not raw_args:
        teks = build_concise_menu_text()
    else:
        first = raw_args[0].lower().lstrip("/")
        if first in ("help", "?", "--help", "-h"):
            if len(raw_args) >= 2:
                target_cmd = raw_args[1].lower().lstrip("/")
                teks = build_command_help_text(target_cmd)
            else:
                teks = build_command_help_text("menu")
        elif len(raw_args) >= 2 and raw_args[1].lower() in ("help", "?", "--help", "-h"):
            teks = build_command_help_text(first)
        elif get_command_from_db(first) is not None:
            teks = build_command_help_text(first)
        else:
            teks = build_concise_menu_text(category_filter=first)

    LIMIT = 4096
    if len(teks) <= LIMIT:
        await update.message.reply_text(teks, parse_mode=ParseMode.HTML)
        return

    sisa = teks
    while sisa:
        if len(sisa) <= LIMIT:
            await update.message.reply_text(sisa, parse_mode=ParseMode.HTML)
            break
        batas = sisa.rfind("\n\n", 0, LIMIT)
        if batas <= 0:
            batas = sisa.rfind("\n", 0, LIMIT)
        if batas <= 0:
            batas = LIMIT
        await update.message.reply_text(sisa[:batas], parse_mode=ParseMode.HTML)
        sisa = sisa[batas:].lstrip("\n")


async def job_kirim_terjadwal(context: ContextTypes.DEFAULT_TYPE):
    """Job yang dipanggil scheduler tiap jam terjadwal."""
    upload_time = datetime.now()
    logger.info(f"[SCHEDULER] Kirim laporan otomatis jam {upload_time.strftime('%H:%M')}")

    try:
        await _kirim_laporan_sql(context.bot, GROUP_ID, upload_time, mode="hourly")
        logger.info("[SCHEDULER] Laporan berhasil dikirim.")
    except Exception as e:
        logger.exception("[SCHEDULER] Gagal kirim laporan otomatis")
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"⚠️ Laporan otomatis gagal:\n`{e}`",
            parse_mode="Markdown"
        )


async def job_kirim_dod_terjadwal(context: ContextTypes.DEFAULT_TYPE):
    """Job scheduler harian: kirim laporan %DoD otomatis (setara /dod) untuk tanggal H-1."""
    tgl_closing = date.today() - relativedelta(days=1)
    logger.info(f"[SCHEDULER] Kirim laporan DoD otomatis untuk {tgl_closing.strftime('%d-%m-%Y')}")

    try:
        cutoff_str = await _get_cutoff_tabel("ordering detail")
        result = calculator_dod.hitung_dod(tgl_closing)
        periode = f"{result['bulan_label']} — s/d {tgl_closing.strftime('%d-%m-%Y')}"

        img_count = renderer_dod.render_dod_count(result, cutoff=cutoff_str)
        img_count.seek(0)
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            photo=InputFile(img_count, filename="dod_count_report.png"),
            caption=f"📊 *PS Harian IndiHome JATENG-DIY*\n{periode}",
            parse_mode="Markdown"
        )

        img_pct = renderer_dod.render_dod_pct(result, cutoff=cutoff_str)
        img_pct.seek(0)
        await context.bot.send_photo(
            chat_id=GROUP_ID,
            photo=InputFile(img_pct, filename="dod_pct_report.png"),
            caption=f"📊 *%DoD (Day over Day) PS IndiHome JATENG-DIY*\n{periode}",
            parse_mode="Markdown"
        )
        # Report 3 (DoD Performance FMC City) SEMENTARA DI-HOLD — tidak dikirim.
        logger.info("[SCHEDULER] Laporan DoD berhasil dikirim.")
    except Exception as e:
        logger.exception("[SCHEDULER] Gagal kirim laporan DoD otomatis")
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"⚠️ Laporan DoD otomatis gagal:\n`{e}`",
            parse_mode="Markdown"
        )


# ── Command Handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    teks = (
        "👋 *Bot Monitoring RE Jateng-DIY*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📦 *Sumber Data KPRO*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ *Upload file Target* (sekali di awal bulan)\n"
        "   Nama file harus mengandung kata *target*\n"
        "   Kolom wajib: `WOK` | `TARGET_IO` | `TARGET_RE` | `TARGET_PS`\n\n"
        "2️⃣ *Upload file KPRO* — generate laporan hourly\n\n"
        "3️⃣ */closing DD-MM-YYYY* — laporan closing KPRO\n"
        "   Contoh: `/closing 03-05-2026`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🗄️ *Sumber Data Hadoop*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "4️⃣ *Upload file* `ordering_detail_*.csv`\n"
        "5️⃣ */closinghadoop DD-MM-YYYY*\n"
        "6️⃣ */dailyreps* — ulang laporan daily RE+PS\n"
        "7️⃣ */closingdaily DD-MM-YYYY*\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔴 *Sumber Data Live (MySQL DB)*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "8️⃣ */liveupdate* — generate laporan dari DB sekarang (dashboard\\_hourly\\_sales, WOK baru)\n"
        "8️⃣🅱️ */liveupdateutoip* — backup /liveupdate, sumber FMC API\n"
        "8️⃣🇨 */liveupdatebk* — backup /liveupdate, dihitung ulang dari raw `ordering_detail`\n"
        "9️⃣ */closingsql DD-MM-YYYY* — closing dari DB\n"
        "   Contoh: `/closingsql 03-05-2026`\n"
        "9️⃣🅱️ */closingutoip DD-MM-YYYY* — backup /closingsql, sumber FMC API\n"
        "   Contoh: `/closingutoip 03-05-2026`\n"
        "9️⃣🇨 */closingbk DD-MM-YYYY* — backup /closingsql, dihitung ulang dari raw `ordering_detail`\n"
        "   Contoh: `/closingbk 03-05-2026`\n"
        "🔟 */dailyre DD/MM/YYYY* — Monitoring Daily RE (target base + gap kemarin, sumber hourly)\n"
        "   Contoh: `/dailyre 09/09/2026`\n\n"
        "⏰ *Laporan otomatis* dikirim tiap jam:\n"
        "   07:30 | 08:30 | 09:30 | ... | 20:30\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 *Perintah lain:*\n"
        "/status — cek status bot\n"
        "/dbstatus — cek koneksi database\n"
        "/dbinfo — cek update terakhir data DB\n"
        "/target — lihat target tersimpan"
    )
    await update.message.reply_text(teks, parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    target_info = (
        f"✅ Target tersimpan: {len(_target_df)} WOK"
        if _target_df is not None else "⚠️ Belum ada file target"
    )
    kpro_info = (
        f"✅ Data KPRO tersimpan: {len(_last_kpro):,} baris"
        if _last_kpro is not None else "⚠️ Belum ada data KPRO"
    )
    hadoop_info = (
        f"✅ Data Hadoop tersimpan: {len(_last_hadoop):,} baris"
        if _last_hadoop is not None else "⚠️ Belum ada data Hadoop"
    )
    db_ok = db.test_connection()
    db_info = "✅ Koneksi DB aktif" if db_ok else "❌ Koneksi DB gagal"

    await update.message.reply_text(
        f"🟢 Bot aktif\n{target_info}\n{kpro_info}\n{hadoop_info}\n{db_info}\n"
        f"🕐 Server time: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )


async def cmd_dbstatus(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cek koneksi dan status tabel-tabel sumber data bot."""
    await update.message.reply_text("⏳ Mengecek koneksi dan status tabel...")

    try:
        ok = await asyncio.wait_for(asyncio.to_thread(db.test_connection), timeout=15)
    except asyncio.TimeoutError:
        await update.message.reply_text(
            "❌ *Timeout koneksi database* (>15 detik).\n"
            "Kemungkinan VPN/jaringan ke DB bermasalah.",
            parse_mode="Markdown"
        )
        return

    if not ok:
        await update.message.reply_text(
            "❌ *Koneksi database gagal!*\n"
            "Periksa konfigurasi DB di config.py",
            parse_mode="Markdown"
        )
        return

    try:
        statuses  = await asyncio.to_thread(db.query_all_table_status)
        bulan_ini = date.today()
        lines = [
            "✅ *Koneksi database OK*",
            "",
            f"📅 *Status Tabel Bulan {bulan_ini.strftime('%B').upper()} {bulan_ini.year}*",
            "━━━━━━━━━━━━━━━━━━",
        ]
        for s in statuses:
            lines.append("")
            lines.append(s["label"])
            lines.append(f"`{s['tabel']}`")
            if s["error"]:
                lines.append(f"⚠️ Error: `{s['error']}`")
            elif s.get("info"):
                lines.append(s["info"])
            elif s["last_update"]:
                lines.append(f"🕐 Last update: *{s['last_update'].strftime('%d-%m-%Y %H:%M')}*")
            else:
                lines.append("🕐 Last update: _tidak ada data_")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.exception("Error /dbstatus")
        await update.message.reply_text(
            f"✅ Koneksi OK tapi cek status tabel gagal:\n`{e}`",
            parse_mode="Markdown"
        )


async def cmd_gp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/gp — cek status & coba nyambungin GlobalProtect VPN di server."""
    await update.message.reply_text("⏳ Mengecek status GlobalProtect...")

    try:
        status = await asyncio.wait_for(asyncio.to_thread(gp_control.get_status), timeout=20)
    except asyncio.TimeoutError:
        await update.message.reply_text("❌ Timeout cek status GlobalProtect.")
        return
    except Exception as e:
        logger.exception("Error /gp saat cek status")
        await update.message.reply_text(f"❌ Gagal cek status GlobalProtect:\n`{e}`", parse_mode="Markdown")
        return

    if status["connected"]:
        await update.message.reply_text(
            f"✅ GlobalProtect sudah *connect* (portal `{status['portal']}`)\n"
            f"Log terakhir: `{status['last_event']}`",
            parse_mode="Markdown"
        )
        return

    if not status["pangpa"]:
        await update.message.reply_text("⚠️ Proses PanGPA tidak jalan, mencoba menyalakan ulang...")

    await update.message.reply_text("🔄 Belum connect, mencoba menyambungkan GlobalProtect...")
    try:
        await asyncio.wait_for(asyncio.to_thread(gp_control.reconnect), timeout=20)
    except Exception as e:
        logger.exception("Error /gp saat reconnect")
        await update.message.reply_text(f"❌ Gagal menyambungkan GlobalProtect:\n`{e}`", parse_mode="Markdown")
        return

    # Poll berkala (bukan nunggu tetap lalu cek sekali) — tunnel creation
    # ke gateway biasa butuh 15-20+ detik, jadi dicek tiap 5 detik sampai
    # maksimal 40 detik supaya tidak keburu melapor "belum connect" padahal
    # prosesnya masih jalan (last_event masih "Trying to create tunnel").
    status2 = {"connected": False, "last_event": "-"}
    for _ in range(8):
        await asyncio.sleep(5)
        try:
            status2 = await asyncio.wait_for(asyncio.to_thread(gp_control.get_status), timeout=20)
        except Exception:
            continue
        if status2["connected"]:
            break

    if status2["connected"]:
        await update.message.reply_text(
            f"✅ GlobalProtect berhasil *connect* (portal `{status['portal']}`)\n"
            f"Log terakhir: `{status2['last_event']}`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "⚠️ GlobalProtect masih belum connect setelah dicoba otomatis.\n"
            f"Log terakhir: `{status2['last_event']}`\n"
            "Kemungkinan sesi login sudah expired dan butuh login SSO manual "
            "(bot tidak bisa isi kredensial/2FA) — cek layar server via RDP/console.",
            parse_mode="Markdown"
        )


async def cmd_target(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if _target_df is None or _target_df.empty:
        await update.message.reply_text(
            "⚠️ Belum ada file target.\n"
            "Kirim file Excel dengan nama mengandung kata *target*.",
            parse_mode="Markdown"
        )
        return

    df = _target_df.copy()
    df.columns = df.columns.str.upper()
    lines = ["🎯 *Target RE per WOK:*\n"]
    total = 0
    for _, row in df.iterrows():
        wok = str(row.get("WOK", "-"))
        tgt = int(row.get("TARGET_RE", 0) or 0)
        lines.append(f"• {wok}: *{tgt:,}*")
        total += tgt
    lines.append(f"\n📊 *Total Target: {total:,}*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── SQL, DailyRE, KPRO & Hadoop Commands (direfactor ke BaseReport) ──────────
async def _get_target_region():
    """Sheet TARGET_REGION untuk /nasional (commands/nasional.py): hasil upload /target dulu,
    fallback file template_target_2026_bot*.xlsx terbaru."""
    if _target_region_df is not None:
        return _target_region_df
    path = _find_latest_target_file()
    if not path:
        return None
    try:
        return await asyncio.to_thread(pd.read_excel, path, sheet_name="TARGET_REGION")
    except Exception as e:
        logger.warning(f"[nasional] Gagal baca sheet TARGET_REGION dari {path}: {e}")
        return None


async def _kirim_laporan_sql_proxy(*args, **kwargs):
    return await _kirim_laporan_sql(*args, **kwargs)


async def _kirim_laporan_proxy(*args, **kwargs):
    return await _kirim_laporan(*args, **kwargs)


async def _kirim_laporan_daily_proxy(*args, **kwargs):
    return await _kirim_laporan_daily(*args, **kwargs)


async def _kirim_foto_retry_proxy(*args, **kwargs):
    return await _kirim_foto_retry(*args, **kwargs)


cmd_liveupdate = closing.ReportLiveUpdate(kirim_laporan_sql_fn=_kirim_laporan_sql_proxy).handle
cmd_liveupdateutoip = closing.ReportLiveUpdateUtoip(kirim_laporan_sql_fn=_kirim_laporan_sql_proxy).handle
cmd_liveupdatebk = closing.ReportLiveUpdateBK(kirim_laporan_sql_fn=_kirim_laporan_sql_proxy).handle
cmd_dailyre = dailyre.ReportDailyRE(kirim_foto_fn=_kirim_foto_retry_proxy).handle
cmd_closing_sql = closing.ReportClosingSQL(kirim_laporan_sql_fn=_kirim_laporan_sql_proxy).handle
cmd_closing_utoip = closing.ReportClosingUtoip(kirim_laporan_sql_fn=_kirim_laporan_sql_proxy).handle
cmd_closingbk = closing.ReportClosingBK(kirim_laporan_sql_fn=_kirim_laporan_sql_proxy).handle
cmd_closing = closing.ReportClosingKPRO(
    get_kpro_fn=lambda: (_last_kpro, _last_kpro_upload_time),
    kirim_laporan_fn=_kirim_laporan_proxy,
    get_cutoff_upload_fn=_get_cutoff_upload,
).handle
cmd_daily = closing.ReportDailyREPS(
    get_hadoop_fn=lambda: (_last_hadoop, _last_hadoop_upload_time),
    kirim_laporan_daily_fn=_kirim_laporan_daily_proxy,
    get_cutoff_upload_fn=_get_cutoff_upload,
).handle
cmd_closing_daily = closing.ReportClosingDaily(
    get_hadoop_fn=lambda: (_last_hadoop, _last_hadoop_upload_time),
    kirim_laporan_daily_fn=_kirim_laporan_daily_proxy,
    get_cutoff_upload_fn=_get_cutoff_upload,
).handle
cmd_closing_hadoop = closing.ReportClosingHadoop(
    get_hadoop_fn=lambda: (_last_hadoop, _last_hadoop_upload_time),
    kirim_laporan_fn=_kirim_laporan_proxy,
    get_cutoff_upload_fn=_get_cutoff_upload,
).handle

# ── File Handler ──────────────────────────────────────────────────────────────
async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global _target_df, _last_kpro

    doc = update.message.document
    if not doc:
        return

    if _is_stock_ont_report(update.message):
        await _proses_stock_ont_alert(update, ctx, doc)
        return

    if _is_program_tracking_upload(update.message):
        await _proses_program_tracking(update, ctx, doc)
        return

    if (doc.file_name or "").lower().endswith(".html"):
        await _handle_performance_html_upload(update, ctx, doc)
        return

    if _is_performance_upload(update, ctx):
        await _handle_performance_upload(update, ctx, doc)
        return

    if childps_bot.is_childps_upload(update.message):
        await childps_bot.handle_childps_upload(update, ctx, doc)
        return

    if _is_klaim_upload(update):
        await _handle_klaim_upload(update, ctx, doc)
        return

    fname = (doc.file_name or "").lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".xls") or fname.endswith(".csv")):
        await update.message.reply_text(
            "⚠️ Format tidak didukung. Kirim file *.xlsx* atau *.csv*",
            parse_mode="Markdown"
        )
        return

    # File dikirim dgn caption "/djpprio [DD-MM-YYYY]" -> approve-tugas utk
    # report DJP ODP Priority. Dicek LEBIH DULU (sebelum sniffing nama file di
    # bawah) supaya tidak ketuker sama _proses_djp_csv ("djp" di nama file
    # approve-tugas kemungkinan besar juga mengandung kata "djp").
    caption = (update.message.caption or "").strip().lower()
    if caption.startswith("/djpprio"):
        await _proses_djpprio(update, ctx, doc, update.message.caption or "")
        return

    try:
        tg_file    = await doc.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        df_raw     = _parse_excel_csv(file_bytes, fname)
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal membaca file:\n`{e}`",
                                        parse_mode="Markdown")
        return

    if "target" in fname:
        df_raw.columns = df_raw.columns.str.strip().str.upper()
        await _proses_target(update, df_raw)
    elif "djp" in fname:
        df_raw.columns = df_raw.columns.str.strip().str.upper()
        await _proses_djp_csv(update, df_raw)
    elif "ordering detail" in fname or "ordering_detail" in fname:
        await _proses_hadoop(update, ctx, df_raw)
    else:
        df_raw.columns = df_raw.columns.str.strip().str.upper()
        await _proses_kpro(update, ctx, df_raw)


# ── /performance — SF Performance Tracking (Section 0-6) + Report SAPA ────────
# Jalan dari HTML asli (performance_browser.py, headless Chromium) — lihat
# modul itu utk detail arsitektur. Bagian di bawah ini cuma urusan Telegram-nya:
# buffering album, klasifikasi jenis file per-upload, & pengiriman hasil.
# Metode upload: user pilih 2-3 file SEKALIGUS di Telegram (multi-select/album —
# "media group"), 1 caption `/performance [DD-MM-YYYY]` menempel di salah satu
# item saja (batasan Bot API: caption cuma bisa di 1 item per album). Jenis tiap
# file dideteksi dari ISI kolom (bukan nama file/urutan), sama seperti auto-detect
# di resources/performance/SF_Performance_Report_22.html — lihat calculator_performance.detect_file_kind.
#
# ASUMSI (lihat plan): item BERCAPTION diasumsikan sampai duluan/hampir bersamaan
# dengan item lain di album yang sama (perilaku umum Telegram bot, dipakai bot lain
# juga) — kalau item tanpa caption kebetulan sampai LEBIH DULU dari item ber-caption
# (belum ada batch aktif utk media_group_id itu), item itu diabaikan diam-diam
# (bukan salah proses ke handler lain) & PENUH RISIKO ke-drop kalau captionnya tidak
# pernah menyusul — dianggap cukup jarang utk Phase 1.
_PERFORMANCE_KIND_LABEL = {
    "ps": "Sumber Data 1 — PS (apple-to-apple)",
    "tugas": "Sumber Data 2 — approve-tugas",
    "sf_master": "Data SF Master",
    "sapa_assign": "SAPA 1 — Assignment",
    "sapa_survey": "SAPA 2 — Survey",
    "sapa_prospect": "SAPA 3 — Prospect Homepass",
}


async def _handle_performance_html_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    """Kirim file .html apapun ke bot -> MENIMPA resources/performance/SF_Performance_Report_22.html
    (nama file TETAP/fixed, TERLEPAS dari nama file yang diupload — performance_browser.py
    selalu baca dari path itu) supaya "timpa" beneran berlaku tanpa user perlu
    menyamakan nama file persis. Versi lama di-backup ke .bak dulu (bukan
    langsung hilang) supaya diff masih bisa dicek manual kalau perlu.

    BEDA dari versi lama (sebelum pivot ke performance_browser.py/Playwright):
    dulu file ini cuma "referensi" yang perlu di-re-port manual ke
    calculator_performance.py/renderer_performance.py tiap ada perubahan.
    SEKARANG /performance MENJALANKAN file ini langsung di headless Chromium —
    jadi begitu file baru ditimpa di sini, generate berikutnya OTOMATIS pakai
    versi baru, TANPA perlu re-port apa pun (kecuali kalau ada dropzone/section
    BARU yang bot.py belum tahu cara routing-nya — itu tetap perlu update kode)."""
    message = update.message
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
        await message.reply_text(
            f"❌ File HTML *{doc.file_name}* ({doc.file_size / 1048576:.1f} MB) melebihi batas 20 MB.",
            parse_mode="Markdown"
        )
        return
    try:
        tg_file = await doc.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await message.reply_text(f"❌ Gagal mengunduh file HTML:\n`{e}`", parse_mode="Markdown")
        return

    septian_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "performance")
    os.makedirs(septian_dir, exist_ok=True)
    dest_path = performance_browser.HTML_PATH
    backup_note = ""
    if os.path.exists(dest_path):
        try:
            shutil.copyfile(dest_path, dest_path + ".bak")
            backup_note = " (versi lama disalin ke `.bak`)"
        except Exception:
            logger.exception("[/performance] gagal backup HTML lama")
    with open(dest_path, "wb") as f:
        f.write(file_bytes)

    await message.reply_text(
        f"✅ HTML referensi ditimpa: `resources/performance/{os.path.basename(dest_path)}` "
        f"(dari file yang kamu kirim: `{doc.file_name}`){backup_note}\n"
        f"ℹ️ /performance generate berikutnya OTOMATIS pakai versi ini — tidak perlu re-sync "
        f"kode apa pun (kecuali ada dropzone/section BARU yang belum dikenal bot).",
        parse_mode="Markdown"
    )


def _is_klaim_upload(update: Update) -> bool:
    """Kirim file .xlsx dgn nama mengandung 'klaim' (mis. 'Rekap Data Pelanggan
    Klaim (2).xlsx'), ATAU caption diawali '/klaim' -> nimpa sumber data /klaim
    (resources/klaim/Rekap Data Pelanggan Klaim.xlsx), TANPA perlu copy-paste file manual
    ke folder resources/klaim/."""
    message = update.message
    doc = message.document
    fname = (doc.file_name or "").lower()
    caption = (message.caption or "").strip().lower()
    if caption.startswith("/klaim"):
        return True
    return "klaim" in fname and fname.endswith((".xlsx", ".xls"))


async def _handle_klaim_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    """Timpa resources/klaim/Rekap Data Pelanggan Klaim.xlsx dgn file yg dikirim ke bot
    (versi lama di-backup ke .bak dulu, sama pola dgn upload HTML /performance).
    Sanity-check dulu: harus ada sheet 'All Klaim' dgn kolom minimal (Nomor
    Internet, Nama Program, WOK) SEBELUM file lama ditimpa, supaya file yg salah
    kirim tidak merusak sumber data yg sudah jalan. Setelah ditimpa, /klaim
    berikutnya OTOMATIS pakai data baru — user tetap ketik /klaim sendiri utk
    lihat reportnya (tidak auto-generate di sini)."""
    message = update.message
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
        await message.reply_text(
            f"❌ File *{doc.file_name}* ({doc.file_size / 1048576:.1f} MB) melebihi batas 20 MB.",
            parse_mode="Markdown"
        )
        return
    try:
        tg_file = await doc.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await message.reply_text(f"❌ Gagal mengunduh file:\n`{e}`", parse_mode="Markdown")
        return

    try:
        xls = pd.ExcelFile(BytesIO(file_bytes))
        if "All Klaim" not in xls.sheet_names:
            await message.reply_text(
                f"❌ File `{doc.file_name}` tidak punya sheet 'All Klaim' "
                f"(sheet yg ada: {', '.join(xls.sheet_names)}) — tidak ditimpa.",
                parse_mode="Markdown"
            )
            return
        df_check = pd.read_excel(xls, sheet_name="All Klaim", nrows=5)
        df_check.columns = df_check.columns.str.strip()
        required = {"Nomor Internet", "Nama Program", "WOK"}
        missing = required - set(df_check.columns)
        if missing:
            await message.reply_text(
                f"❌ File `{doc.file_name}` sheet 'All Klaim' kurang kolom: "
                f"{', '.join(sorted(missing))} — tidak ditimpa.",
                parse_mode="Markdown"
            )
            return
    except Exception as e:
        await message.reply_text(
            f"❌ Gagal baca file `{doc.file_name}` sbg Excel:\n`{e}`", parse_mode="Markdown"
        )
        return

    dest_path = calculator_klaim.KLAIM_XLSX_PATH
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    backup_note = ""
    if os.path.exists(dest_path):
        try:
            shutil.copyfile(dest_path, dest_path + ".bak")
            backup_note = " (versi lama disalin ke `.bak`)"
        except Exception:
            logger.exception("[/klaim] gagal backup file lama")
    with open(dest_path, "wb") as f:
        f.write(file_bytes)

    await message.reply_text(
        f"✅ Sumber data /klaim ditimpa: `resources/klaim/{os.path.basename(dest_path)}` "
        f"(dari file yang kamu kirim: `{doc.file_name}`){backup_note}\n"
        f"ℹ️ Ketik /klaim buat lihat report dgn data baru ini.",
        parse_mode="Markdown"
    )


def _is_performance_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.message
    caption = (message.caption or "").strip().lower()
    if caption.startswith("/performance"):
        return True
    pending = ctx.chat_data.get("performance_pending")
    mgid = message.media_group_id
    return bool(pending and mgid and pending.get("media_group_id") == mgid)


def _classify_performance_file(fname: str, file_bytes: bytes):
    """Return (kind, DataFrame) atau (None, None) kalau tidak dikenali. Sync —
    dipanggil lewat asyncio.to_thread dari _handle_performance_upload."""
    fname_l = (fname or "").lower()
    if fname_l.endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(BytesIO(file_bytes))
        sheet = calculator_performance.pick_sf_master_sheet(xls.sheet_names)
        df = pd.read_excel(xls, sheet_name=sheet)
        df.columns = df.columns.str.strip()
        return calculator_performance.detect_file_kind(fname, df), df
    df = _parse_excel_csv(file_bytes, fname)
    return calculator_performance.detect_file_kind(fname, df), df


async def _handle_performance_upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    message = update.message
    chat_id = update.effective_chat.id
    caption = (message.caption or "").strip()
    mgid = message.media_group_id

    pending = ctx.chat_data.get("performance_pending")
    if caption.lower().startswith("/performance"):
        cutoff_override = None
        parts = caption.split()
        if len(parts) > 1:
            try:
                cutoff_override = datetime.strptime(parts[1], "%d-%m-%Y").date()
            except ValueError:
                await message.reply_text(
                    "❌ Format tanggal salah. Gunakan `DD-MM-YYYY`\nContoh: `/performance 11-08-2026`",
                    parse_mode="Markdown"
                )
                return
        pending = {
            "media_group_id": mgid,
            "cutoff_override": cutoff_override,
            "files": {},
            "requester_chat": chat_id,
            "requester_thread": getattr(message, "message_thread_id", None),
        }
        ctx.chat_data["performance_pending"] = pending
    elif not pending or (mgid and pending.get("media_group_id") != mgid):
        return

    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
        await message.reply_text(
            f"❌ File *{doc.file_name}* ({doc.file_size / 1048576:.1f} MB) melebihi batas "
            f"download Bot API (maks 20 MB) — dilewati.",
            parse_mode="Markdown"
        )
    else:
        read_failed = False
        try:
            tg_file = await doc.get_file()
            file_bytes = bytes(await tg_file.download_as_bytearray())
            kind, df = await asyncio.to_thread(_classify_performance_file, doc.file_name or "", file_bytes)
        except Exception as e:
            logger.exception(f"[/performance] gagal baca file {doc.file_name}")
            await message.reply_text(f"⚠️ Gagal membaca `{doc.file_name}`:\n`{e}`", parse_mode="Markdown")
            kind, df, read_failed = None, None, True
        if kind:
            # Simpan BYTES mentah (bukan DataFrame) — performance_browser.py
            # butuh file aslinya utk di-upload lagi ke input HTML di headless
            # Chromium (jalankan HTML asli, bukan reimplementasi Python).
            pending["files"][kind] = (doc.file_name, file_bytes)
            await message.reply_text(
                f"✅ Terdeteksi: *{_PERFORMANCE_KIND_LABEL[kind]}* ({doc.file_name})",
                parse_mode="Markdown"
            )
        elif not read_failed:
            await message.reply_text(
                f"⚠️ `{doc.file_name}` tidak dikenali sebagai salah satu file /performance "
                f"(PS apple-to-apple / approve-tugas / Data SF Master) — dilewati.",
                parse_mode="Markdown"
            )

    job_queue = ctx.application.job_queue
    job_name = f"performance_batch_{chat_id}"
    for j in job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()
    job_queue.run_once(_performance_run_batch_job, when=2.5, chat_id=chat_id, name=job_name)


def _split_for_telegram(text: str, limit: int = 3500) -> list:
    """Pecah teks panjang jadi beberapa pesan (batas Telegram 4096 char/pesan),
    potong di batas baris supaya tidak motong kata/markdown di tengah."""
    lines = text.split("\n")
    chunks, cur = [], ""
    for line in lines:
        trial = (cur + "\n" + line) if cur else line
        if len(trial) > limit and cur:
            chunks.append(cur)
            cur = line
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    return chunks or [text]


async def _send_png_bundle(context: ContextTypes.DEFAULT_TYPE, targets: list, sections: list, out_suffix: str, label_prefix: str):
    """Kirim list [(base_name, BytesIO PNG), ...] ke semua targets [(chat,thread),...]
    — upload sekali ke tujuan pertama, tujuan berikutnya reuse file_id (dedup, sama
    pola dgn _proses_djpprio bot.py:~1872-1893)."""
    for base_name, buf in sections:
        fname = f"{base_name}_{out_suffix}.png"
        file_id = None
        for chat, thread_t in targets:
            if file_id is None:
                buf.seek(0)

                async def _send1(chat=chat, thread_t=thread_t):
                    return await context.bot.send_document(
                        chat_id=chat, message_thread_id=thread_t,
                        document=InputFile(buf, filename=fname),
                        write_timeout=180, read_timeout=120,
                    )
                msg = await _kirim_dgn_retry(_send1, label=f"{label_prefix}_{base_name}")
                file_id = msg.document.file_id
            else:
                async def _send2(chat=chat, thread_t=thread_t, file_id=file_id):
                    return await context.bot.send_document(
                        chat_id=chat, message_thread_id=thread_t, document=file_id)
                await _kirim_dgn_retry(_send2, label=f"{label_prefix}_{base_name}_dup")


async def _send_caption_text(context: ContextTypes.DEFAULT_TYPE, targets: list, caption_txt: str, label: str):
    for chunk in _split_for_telegram(caption_txt):
        for chat, thread_t in targets:
            async def _send_caption(chat=chat, thread_t=thread_t, chunk=chunk):
                return await context.bot.send_message(
                    chat_id=chat, message_thread_id=thread_t, text=chunk, parse_mode="Markdown")
            await _kirim_dgn_retry(_send_caption, label=label)


async def _performance_run_batch_job(context: ContextTypes.DEFAULT_TYPE):
    """Generate & kirim SEMUA bagian yang datanya lengkap dari 1 batch upload:
    report utama (Section 0-4, butuh ps+tugas [+opsional sf_master]) DAN/ATAU
    Report SAPA (butuh sapa_assign+sapa_survey+sapa_prospect) — user bisa kirim
    ke-6 file sekaligus dalam 1 album, atau cuma sebagian (mis. cuma 3 file SAPA)."""
    chat_id = context.job.chat_id
    pending = context.chat_data.get("performance_pending")
    if not pending:
        return
    context.chat_data["performance_pending"] = None
    thread = pending["requester_thread"]
    files = pending["files"]

    main_ready = "ps" in files and "tugas" in files
    sapa_ready = all(k in files for k in ("sapa_assign", "sapa_survey", "sapa_prospect"))
    if not main_ready and not sapa_ready:
        missing_main = [m for k, m in (("ps", "Sumber Data 1 — PS (apple-to-apple)"),
                                        ("tugas", "Sumber Data 2 — approve-tugas")) if k not in files]
        missing_sapa = [m for k, m in (("sapa_assign", "SAPA 1 — Assignment"),
                                        ("sapa_survey", "SAPA 2 — Survey"),
                                        ("sapa_prospect", "SAPA 3 — Prospect Homepass")) if k not in files]
        text = "❌ /performance belum lengkap.\n"
        text += "Utk report utama, masih kurang:\n" + "\n".join(f"• {m}" for m in missing_main) + "\n"
        text += "ATAU utk Report SAPA, masih kurang:\n" + "\n".join(f"• {m}" for m in missing_sapa)
        await context.bot.send_message(chat_id=chat_id, message_thread_id=thread, text=text)
        return

    requester_chat, requester_thread = pending["requester_chat"], pending["requester_thread"]
    targets = [(requester_chat, requester_thread)]
    if GROUP_ID != requester_chat:
        targets.append((GROUP_ID, None))

    await context.bot.send_message(
        chat_id=chat_id, message_thread_id=thread,
        text="⏳ Generating SF Performance Tracking via HTML asli (headless browser)..."
    )

    cutoff_str = pending["cutoff_override"].strftime("%Y-%m-%d") if pending["cutoff_override"] else None
    try:
        result = await performance_browser.run_performance_report(files, cutoff_override=cutoff_str)
    except Exception as e:
        logger.exception("[/performance] gagal generate report (browser)")
        await context.bot.send_message(
            chat_id=chat_id, message_thread_id=thread,
            text=f"❌ Gagal generate report:\n`{str(e)[:600]}`", parse_mode="Markdown"
        )
        return

    notes = []

    if result["main"]:
        m = result["main"]
        sections = [(name, BytesIO(png)) for name, png in m["sections"]]
        await _send_png_bundle(context, targets, sections, m["cutoff_date"], "performance")
        await _send_caption_text(context, targets, m["caption"], "performance_caption")
        sf_reg_note = "Data SF Master" if m["sf_reg_source"] == "master" else "estimasi dari approve-tugas"
        notes.append(f"✅ Section 0-6 berhasil ✓ · SF REG: {sf_reg_note}")

    if result["sapa"]:
        s = result["sapa"]
        sections = [(name, BytesIO(png)) for name, png in s["sections"]]
        out_suffix = cutoff_str or (result["main"]["cutoff_date"] if result["main"] else date.today().strftime("%Y-%m-%d"))
        await _send_png_bundle(context, targets, sections, out_suffix, "performance_sapa")
        await _send_caption_text(context, targets, s["caption"], "performance_sapa_caption")
        notes.append("✅ Report SAPA berhasil ✓")

    if notes:
        notes.append("ℹ️ Jalan dari HTML asli (pixel-perfect, headless browser) — All Parameter "
                      "WOW/MoM, PDF gabungan, & Excel drill-down menyusul di update berikutnya.")
        await context.bot.send_message(chat_id=chat_id, message_thread_id=thread, text="\n".join(notes))


# ── /performance & /leads (direfactor ke BaseReport) ─────────────────────────
cmd_performance = performance.ReportPerformance().handle
cmd_leads = leads.ReportLeads().handle

async def _proses_stock_ont_alert(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    """
    Baca PDF "Stock_ONT_Report*.pdf" (Stock Paradise) yang diupload ke topic
    Partnership, lalu balas dengan gambar Stock Alert berisi SEMUA WH SO
    berstatus SHORTAGE (ONT Dual Band / ONT Premium / STB / Orbit / Kartu
    Perdana), diurutkan dari stock days paling kritis per kategori.

    Balasan otomatis ke chat + topic yang sama (reply_photo mengikuti
    message_thread_id pesan asal) — lihat pengecualian di _tolak_chat_diblokir.
    """
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
        await update.message.reply_text(
            f"❌ File *{doc.file_size / 1048576:.1f} MB* — melebihi batas download "
            f"Bot API Telegram (maks 20 MB).",
            parse_mode="Markdown"
        )
        return

    try:
        tg_file   = await doc.get_file()
        pdf_bytes = bytes(await tg_file.download_as_bytearray())
        data      = calculator_stock_alert.parse_stock_ont_report(pdf_bytes)
    except Exception as e:
        logger.exception("[STOCK_ALERT] Gagal membaca Stock ONT Report")
        await update.message.reply_text(f"❌ Gagal membaca file:\n`{e}`",
                                        parse_mode="Markdown")
        return

    for pesan in calculator_stock_alert.format_stock_alert_messages(data):
        await update.message.reply_text(pesan)


def _is_program_tracking_upload(msg) -> bool:
    """PDF apapun dengan nama file mengandung "program tracking" (case-
    insensitive) -> auto-extract via program_tracking.py. Tidak hardcode nama
    bulan/minggu supaya tetap kedeteksi bulan berikutnya (mis. "Program
    Tracking W3 September 2026.pdf")."""
    doc = msg.document if msg else None
    if not doc:
        return False
    fname = (doc.file_name or "").lower()
    return "program tracking" in fname and fname.endswith(".pdf")


async def _kirim_album_program_tracking(chat_id, thread_id, files):
    """Kirim 1 grup program (>1 halaman) sbg album document via HTTP API
    Telegram LANGSUNG (httpx), BUKAN ctx.bot.send_media_group.

    Alasan: ctx.bot.send_media_group (python-telegram-bot) gagal dgn error
    Telegram "Can't parse inputmedia: media not found" saat InputMediaDocument
    dibungkus InputFile(BytesIO(...)) — sudah kejadian di produksi (server,
    PTB versi terpasang di sana). Root cause persis belum jelas (dugaan bug/
    versi PTB), tapi kirim langsung via HTTP multipart (persis pola yg dipakai
    & terbukti reliable saat pengetesan manual sebelum fitur ini di-wire ke
    bot.py) menghindari lapisan InputFile/attach PTB itu sama sekali."""
    media = []
    upload_files = {}
    for idx, (fname, png, caption) in enumerate(files):
        key = f"file{idx}"
        upload_files[key] = (fname, png, "image/png")
        media.append({"type": "document", "media": f"attach://{key}", "caption": caption})

    data = {"chat_id": chat_id, "media": json.dumps(media)}
    if thread_id is not None:
        data["message_thread_id"] = thread_id

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup",
            data=data, files=upload_files,
        )
    resp.raise_for_status()
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"sendMediaGroup gagal: {result}")


async def _proses_program_tracking(update: Update, ctx: ContextTypes.DEFAULT_TYPE, doc):
    """Upload PDF "Program Tracking ..." (GTM) -> tiap halaman program
    di-render jadi gambar, dikelompokkan OTOMATIS per nama program (lihat
    program_tracking.build_send_plan — grouping berdasarkan judul halaman,
    BUKAN hardcode nomor halaman, supaya tetap jalan walau struktur PDF bulan
    depan berubah), lalu dikirim balik ke chat yang sama tempat file diupload
    (requester) sbg document PNG (bukan photo, biar tidak dikompres/pecah) —
    program multi-halaman dikirim sbg 1 album, program 1 halaman dikirim
    tunggal.

    Parsing PDF + render halaman DIJALANKAN di asyncio.to_thread supaya tidak
    mem-blok event loop (lihat memory concurrency-model-bot-re-jateng).
    """
    message = update.message
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > MAX_DOWNLOAD_BYTES:
        await message.reply_text(
            f"❌ File *{doc.file_name}* ({doc.file_size / 1048576:.1f} MB) melebihi batas 20 MB.",
            parse_mode="Markdown"
        )
        return

    try:
        tg_file = await doc.get_file()
        pdf_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        await message.reply_text(f"❌ Gagal mengunduh file:\n`{e}`", parse_mode="Markdown")
        return

    await message.reply_text("⏳ Membaca PDF Program Tracking, mohon tunggu...")

    try:
        plan = await asyncio.to_thread(program_tracking.build_send_plan, pdf_bytes)
    except Exception as e:
        logger.exception("[PROGRAM_TRACKING] Gagal ekstrak PDF")
        await message.reply_text(f"❌ Gagal mengekstrak PDF:\n`{e}`", parse_mode="Markdown")
        return

    if not plan:
        await message.reply_text("⚠️ Tidak ada halaman program yang terdeteksi di PDF ini.")
        return

    chat_id   = message.chat_id
    thread_id = message.message_thread_id
    for item in plan:
        files = item["files"]
        if len(files) == 1:
            fname, png, caption = files[0]
            await ctx.bot.send_document(
                chat_id=chat_id, message_thread_id=thread_id,
                document=InputFile(BytesIO(png), filename=fname), caption=caption,
            )
        else:
            await _kirim_album_program_tracking(chat_id, thread_id, files)

    await message.reply_text(
        f"✅ Selesai — {len(plan)} program terkirim dari PDF *{doc.file_name}*.",
        parse_mode="Markdown"
    )


# ── /djpprio (direfactor ke reports/djpprio/ menggunakan BaseReport) ──────────
_djpprio_report = djpprio.ReportDJPPrio(
    parse_excel_csv_fn=_parse_excel_csv,
    kirim_file_dedup_fn=lambda *a, **kw: _kirim_file_dedup(*a, **kw),
    write_raw_csv_gz_fn=agresif_native.write_raw_csv_gz,
    unwrap_bot_fn=lambda b: b._bot if isinstance(b, _BotKeTopic) else b,
)
cmd_djpprio = _djpprio_report.handle
_proses_djpprio = _djpprio_report.process_document

async def _proses_target(update: Update, df: pd.DataFrame):
    global _target_df, _target_monthly_df, _target_city_df, _sf_aktif_df, _target_caps_df, _target_addon_dfs
    global _target_agresif_kec_df, _target_fmc_city_df, _target_wireless_df, _target_region_df

    # Coba baca per sheet
    try:
        tg_file    = await update.message.document.get_file()
        file_bytes = bytes(await tg_file.download_as_bytearray())
        try:
            df_daily = pd.read_excel(BytesIO(file_bytes), sheet_name="TARGET_DAILY")
            df_daily.columns = df_daily.columns.str.strip().str.upper()
        except Exception:
            df_daily = None
        try:
            df_monthly = pd.read_excel(BytesIO(file_bytes), sheet_name="TARGET_MONTHLY")
            df_monthly.columns = df_monthly.columns.str.strip().str.upper()
        except Exception:
            df_monthly = None
        try:
            df_city = pd.read_excel(BytesIO(file_bytes), sheet_name="TARGET_CITY")
            df_city.columns = df_city.columns.str.strip().str.upper()
        except Exception:
            df_city = None
        try:
            df_sf = pd.read_excel(BytesIO(file_bytes), sheet_name="SF_AKTIF")
            df_sf.columns = df_sf.columns.str.strip().str.upper()
        except Exception:
            df_sf = None
        try:
            df_caps = pd.read_excel(BytesIO(file_bytes), sheet_name="TARGET_CAPS")
            df_caps.columns = df_caps.columns.str.strip().str.upper()
        except Exception:
            df_caps = None
        try:
            df_agresif_kec = pd.read_excel(BytesIO(file_bytes), sheet_name=SHEET_TARGET_AGRESIF_KEC)
            df_agresif_kec.columns = df_agresif_kec.columns.str.strip().str.upper()
        except Exception:
            df_agresif_kec = None
        try:
            df_fmc_city = pd.read_excel(BytesIO(file_bytes), sheet_name=SHEET_TARGET_FMC_CITY)
            df_fmc_city.columns = df_fmc_city.columns.str.strip().str.upper()
        except Exception:
            df_fmc_city = None
        try:
            df_wireless = pd.read_excel(BytesIO(file_bytes), sheet_name=SHEET_TARGET_WIRELESS)
            df_wireless.columns = df_wireless.columns.str.strip().str.upper()
        except Exception:
            df_wireless = None
        try:
            df_region = pd.read_excel(BytesIO(file_bytes), sheet_name="TARGET_REGION")
            df_region.columns = df_region.columns.str.strip().str.upper()
        except Exception:
            df_region = None
        df_addon_sheets = {}
        for prod, sheet_name in [("FTTR", "TARGET_MONTHLY_FTTR"),
                                  ("IP_CAM", "TARGET_MONTHLY_IN CAMERA"),
                                  ("MESH_WIFI", "TARGET_MONTHLY_MESH_WIFI")]:
            try:
                d = pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name)
                d.columns = d.columns.str.strip().str.upper()
                df_addon_sheets[prod] = d
            except Exception:
                pass
    except Exception:
        df_daily   = df
        df_monthly = None
        df_city    = None
        df_sf      = None
        df_caps    = None
        df_agresif_kec = None
        df_fmc_city    = None
        df_wireless    = None
        df_region      = None
        df_addon_sheets = {}

    lines = []

    # ── Proses TARGET_DAILY ───────────────────────────────────────────────
    if df_daily is not None and not df_daily.empty:
        if "WOK" in df_daily.columns and "TARGET_RE" in df_daily.columns:
            _target_df = df_daily
            if "BULAN" in df_daily.columns:
                bulan_list = sorted(df_daily["BULAN"].dropna().unique().tolist())
                total_io   = int(df_daily["TARGET_IO"].sum()) if "TARGET_IO" in df_daily.columns else 0
                total_re   = int(df_daily["TARGET_RE"].sum())
                total_ps   = int(df_daily["TARGET_PS"].sum()) if "TARGET_PS" in df_daily.columns else 0
                io_note = "" if "TARGET_IO" in df_daily.columns else " ⚠️ (kolom TARGET_IO belum ada, IO dianggap 0)"
                lines.append(
                    f"✅ *TARGET_DAILY tersimpan*\n"
                    f"   Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                    f"   Total IO: *{total_io:,}* | RE: *{total_re:,}* | PS: *{total_ps:,}*{io_note}"
                )
            else:
                lines.append("✅ *TARGET_DAILY tersimpan* (format lama)")
        else:
            lines.append("⚠️ Sheet TARGET_DAILY: kolom tidak lengkap")
    elif df_daily is None and df is not None and "WOK" in df.columns and "TARGET_RE" in df.columns:
        _target_df = df
        lines.append("✅ *Target tersimpan* (format lama)")

    # ── Proses TARGET_MONTHLY ─────────────────────────────────────────────
    if df_monthly is not None and not df_monthly.empty:
        required = {"BULAN", "WOK", "TARGET_IO", "TARGET_RE", "TARGET_PS"}
        missing  = required - set(df_monthly.columns)
        if not missing:
            _target_monthly_df = df_monthly
            bulan_list = sorted(df_monthly["BULAN"].dropna().unique().tolist())
            total_io = int(df_monthly["TARGET_IO"].sum())
            total_re = int(df_monthly["TARGET_RE"].sum())
            total_ps = int(df_monthly["TARGET_PS"].sum())
            lines.append(
                f"✅ *TARGET_MONTHLY tersimpan*\n"
                f"   Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total IO: *{total_io:,}* | RE: *{total_re:,}* | PS: *{total_ps:,}*"
            )
        else:
            lines.append(f"⚠️ Sheet TARGET_MONTHLY: kolom kurang `{', '.join(missing)}`")

    # ── Proses TARGET_CITY ────────────────────────────────────────────────
    if df_city is not None and not df_city.empty:
        required = {"BULAN", "WOK", "CITY", "TARGET_IO", "TARGET_RE", "TARGET_PS"}
        missing  = required - set(df_city.columns)
        if not missing:
            _target_city_df = df_city
            bulan_list = sorted(df_city["BULAN"].dropna().unique().tolist())
            total_io = int(df_city["TARGET_IO"].sum())
            total_re = int(df_city["TARGET_RE"].sum())
            total_ps = int(df_city["TARGET_PS"].sum())
            lines.append(
                f"✅ *TARGET_CITY tersimpan*\n"
                f"   Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total IO: *{total_io:,}* | RE: *{total_re:,}* | PS: *{total_ps:,}*"
            )
        else:
            lines.append(f"⚠️ Sheet TARGET_CITY: kolom kurang `{', '.join(missing)}`")

    # ── Proses SF_AKTIF ───────────────────────────────────────────────────
    if df_sf is not None and not df_sf.empty:
        required_sf = {"WOK", "BRANCH"}
        missing_sf  = required_sf - set(df_sf.columns)
        # Cek minimal ada 1 kolom bulan (format 2026-XX)
        month_cols  = [c for c in df_sf.columns if str(c).startswith("20") and "-" in str(c)]
        if not missing_sf and month_cols:
            _sf_aktif_df = df_sf
            # Hitung total SF dari semua bulan yang terisi
            total_sf = int(df_sf[month_cols].replace(0, None).stack().count())
            n_wok    = len(df_sf)
            bulan_terisi = [m for m in month_cols if df_sf[m].sum() > 0]
            lines.append(
                f"✅ *SF_AKTIF tersimpan*\n"
                f"   {n_wok} WOK  |  Bulan terisi: {', '.join(bulan_terisi) if bulan_terisi else 'belum ada'}"
            )
        else:
            if missing_sf:
                lines.append(f"⚠️ Sheet SF_AKTIF: kolom kurang `{', '.join(missing_sf)}`")
            else:
                lines.append("⚠️ Sheet SF_AKTIF: tidak ada kolom bulan (format: 2026-01)")

    # ── Proses TARGET_CAPS ────────────────────────────────────────────────
    if df_caps is not None and not df_caps.empty:
        required = {"BULAN", "WOK", "TARGET_CAPS"}
        missing  = required - set(df_caps.columns)
        if not missing:
            _target_caps_df = df_caps
            bulan_list  = sorted(df_caps["BULAN"].dropna().unique().tolist())
            total_caps  = int(df_caps["TARGET_CAPS"].sum())
            lines.append(
                f"✅ *TARGET_CAPS tersimpan*\n"
                f"   Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total Target CAPS: *{total_caps:,}*"
            )
        else:
            lines.append(f"⚠️ Sheet TARGET_CAPS: kolom kurang `{', '.join(missing)}`")

    # ── Proses TARGET_KEC AGRESIF (target /agresif report 1 & 2, per kecamatan) ──
    if df_agresif_kec is not None and not df_agresif_kec.empty:
        required = {"BULAN", "CITY", "KEC", "TARGET_PS_LOW", "TARGET_PS_MIDHIGH"}
        missing  = required - set(df_agresif_kec.columns)
        if not missing:
            _target_agresif_kec_df = df_agresif_kec
            bulan_list = sorted(df_agresif_kec["BULAN"].dropna().unique().tolist())
            total_low  = int(df_agresif_kec["TARGET_PS_LOW"].sum())
            total_mid  = int(df_agresif_kec["TARGET_PS_MIDHIGH"].sum())
            lines.append(
                f"OK {SHEET_TARGET_AGRESIF_KEC} tersimpan\n"
                f"   {len(df_agresif_kec)} kecamatan | Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total Target PS Low: {total_low:,} | Mid: {total_mid:,}"
            )
        else:
            lines.append(f"[!] Sheet {SHEET_TARGET_AGRESIF_KEC}: kolom kurang {', '.join(missing)}")

    # ── Proses TARGET_CITY FMC (target /agresif report 3, per FMC city) ──────
    if df_fmc_city is not None and not df_fmc_city.empty:
        required = {"BULAN", "CITY", "TARGET_PS_LOW", "TARGET_PS_MIDHIGH"}
        missing  = required - set(df_fmc_city.columns)
        if not missing:
            _target_fmc_city_df = df_fmc_city
            bulan_list = sorted(df_fmc_city["BULAN"].dropna().unique().tolist())
            total_low  = int(df_fmc_city["TARGET_PS_LOW"].sum())
            total_mid  = int(df_fmc_city["TARGET_PS_MIDHIGH"].sum())
            lines.append(
                f"OK {SHEET_TARGET_FMC_CITY} tersimpan\n"
                f"   {len(df_fmc_city)} city | Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total Target PS Low: {total_low:,} | Mid: {total_mid:,}"
            )
        else:
            lines.append(f"[!] Sheet {SHEET_TARGET_FMC_CITY}: kolom kurang {', '.join(missing)}")

    # ── Proses TARGET_WIRELESS (target /wireless, per WOK) ────────────────────
    if df_wireless is not None and not df_wireless.empty:
        required = {"BULAN", "WOK", "TARGET_IO", "TARGET_RE", "TARGET_PS"}
        missing  = required - set(df_wireless.columns)
        if not missing:
            _target_wireless_df = df_wireless
            bulan_list = sorted(df_wireless["BULAN"].dropna().unique().tolist())
            lines.append(
                f"OK {SHEET_TARGET_WIRELESS} tersimpan\n"
                f"   Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total IO: {int(df_wireless['TARGET_IO'].sum()):,} | "
                f"RE: {int(df_wireless['TARGET_RE'].sum()):,} | "
                f"PS: {int(df_wireless['TARGET_PS'].sum()):,}"
            )
        else:
            lines.append(f"[!] Sheet {SHEET_TARGET_WIRELESS}: kolom kurang {', '.join(missing)}")

    # ── Proses TARGET_REGION (target BULANAN /nasional, per region) ───────────
    if df_region is not None and not df_region.empty:
        required = {"BULAN", "REGION", "TARGET_IO", "TARGET_RE", "TARGET_PS"}
        missing  = required - set(df_region.columns)
        if not missing:
            _target_region_df = df_region
            bulan_list = sorted(df_region["BULAN"].dropna().unique().tolist())
            lines.append(
                f"✅ *TARGET_REGION tersimpan*\n"
                f"   Bulan: {bulan_list[0]} s/d {bulan_list[-1]}\n"
                f"   Total IO: *{int(df_region['TARGET_IO'].sum()):,}* | "
                f"RE: *{int(df_region['TARGET_RE'].sum()):,}* | "
                f"PS: *{int(df_region['TARGET_PS'].sum()):,}*"
            )
        else:
            lines.append(f"⚠️ Sheet TARGET_REGION: kolom kurang `{', '.join(missing)}`")

    # ── Proses target Addon (3 sheet terpisah: FTTR / IN CAMERA / MESH_WIFI) ──
    if df_addon_sheets:
        required = {"BULAN", "WOK", "TARGET_PS"}
        addon_lines = []
        for prod, sheet_name in [("FTTR", "TARGET_MONTHLY_FTTR"),
                                  ("IP_CAM", "TARGET_MONTHLY_IN CAMERA"),
                                  ("MESH_WIFI", "TARGET_MONTHLY_MESH_WIFI")]:
            d = df_addon_sheets.get(prod)
            if d is None or d.empty:
                continue
            missing = required - set(d.columns)
            if missing:
                lines.append(f"⚠️ Sheet {sheet_name}: kolom kurang `{', '.join(missing)}`")
                continue
            _target_addon_dfs[prod] = d
            bulan_list = sorted(d["BULAN"].dropna().unique().tolist())
            total = int(d["TARGET_PS"].sum())
            addon_lines.append(
                f"   {sheet_name}: bulan {bulan_list[0]} s/d {bulan_list[-1]}, total *{total:,}*"
            )
        if addon_lines:
            lines.append("✅ *Target Addon (FTTR/IP Camera/Mesh Wifi) tersimpan*\n" + "\n".join(addon_lines))

    if not lines:
        await update.message.reply_text(
            "❌ File target tidak bisa dibaca.\n"
            "Pastikan ada sheet `TARGET_DAILY`, `TARGET_MONTHLY`, dan/atau `TARGET_CITY`.",
            parse_mode="Markdown"
        )
        return

    _save_target_state()

    lines.append("\nTarget otomatis sesuai bulan laporan.")
    # Kirim TANPA parse_mode (plain text) — pesan ini gabungan banyak blok dinamis
    # (nama sheet & data upload user), rawan bikin Markdown legacy Telegram gagal
    # parse kalau total tanda * atau _ di seluruh pesan gabungan jadi ganjil
    # (mis. nama sheet "TARGET_MONTHLY_MESH_WIFI" = 3 underscore) -> error
    # "Can't parse entities". Plain text kebal dari masalah ini.
    await update.message.reply_text("\n\n".join(lines))


async def _proses_kpro(update: Update, ctx: ContextTypes.DEFAULT_TYPE, df: pd.DataFrame):
    global _last_kpro, _last_kpro_upload_time
    missing = _validasi_kpro(df)
    if missing:
        await update.message.reply_text(
            f"❌ Kolom tidak ditemukan:\n`{', '.join(missing)}`",
            parse_mode="Markdown"
        )
        return

    _last_kpro  = df
    upload_time = datetime.now()
    _last_kpro_upload_time = upload_time
    await update.message.reply_text("⏳ Memproses data, mohon tunggu...")
    wok_asing = sorted(
        w for w in df["WOK"].dropna().astype(str).str.strip().str.upper().unique()
        if w not in wilayah.WOK_ORDER
    )
    if wok_asing:
        await update.message.reply_text(
            "⚠️ File KPRO tidak punya kolom kabupaten, jadi WOK memakai nama dari file "
            f"(struktur lama). WOK di luar struktur baru: {', '.join(wok_asing[:8])}"
        )

    try:
        await _kirim_laporan(update, ctx, df, upload_time, mode="hourly",
                             cutoff=_get_cutoff_upload(upload_time))
    except Exception as e:
        logger.exception("Error saat memproses KPRO")
        await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


async def _proses_hadoop(update: Update, ctx: ContextTypes.DEFAULT_TYPE, df: pd.DataFrame):
    global _last_hadoop, _last_hadoop_upload_time
    missing = _validasi_hadoop(df)
    if missing:
        await update.message.reply_text(
            f"❌ Kolom tidak ditemukan di file Hadoop:\n`{', '.join(missing)}`",
            parse_mode="Markdown"
        )
        return

    df = df.rename(columns={
        "re_ts"  : "DATECREATED",
        "wok"    : "WOK",
        "branch" : "BRANCH",
        "region" : "REGION",
    })
    df.columns = df.columns.str.upper()
    df["DATECREATED"] = pd.to_datetime(df["DATECREATED"], errors="coerce")
    df = df[df["DATECREATED"].notna()]

    # WOK/BRANCH baru dipetakan dari kabupaten (wilayah.py); baris yang
    # kabupatennya kosong/NAN/luar JATENG-DIY dibuang dari perhitungan.
    if "KABUPATEN" in df.columns:
        sebelum = len(df)
        df = wilayah.petakan_df(df, "KABUPATEN", "WOK", "BRANCH")
        logger.info(f"[HADOOP] pemetaan WOK baru: {len(df):,}/{sebelum:,} baris terpetakan")
    else:
        await update.message.reply_text(
            "⚠️ File Hadoop tidak punya kolom `kabupaten` — WOK/BRANCH tidak bisa "
            "dipetakan ke struktur WOK baru, laporan memakai WOK bawaan file.",
            parse_mode="Markdown"
        )

    rename_map = {}
    for col in df.columns:
        if col.lower() == "ps_ts":
            rename_map[col] = "ps_ts"
    if rename_map:
        df = df.rename(columns=rename_map)

    _last_hadoop = df
    upload_time  = datetime.now()
    _last_hadoop_upload_time = upload_time
    await update.message.reply_text("⏳ Memproses data Hadoop, mohon tunggu...")

    try:
        cutoff_str = _get_cutoff_upload(upload_time)
        await _kirim_laporan(update, ctx, df, upload_time, mode="hourly", source="hadoop",
                             cutoff=cutoff_str)
        await _kirim_laporan_daily(update, ctx, df, upload_time, cutoff=cutoff_str)
    except Exception as e:
        logger.exception("Error saat memproses Hadoop")
        await update.message.reply_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")


async def _proses_djp_csv(update: Update, df: pd.DataFrame):
    """Proses upload CSV — simpan DJP dan MB sekaligus ke memori."""
    global _djp_csv_df, _mb_csv_df, _last_djpcsv_upload_time

    # Validasi kolom
    missing = _validasi_djp(df)
    if missing:
        await update.message.reply_text(
            f"❌ Kolom tidak lengkap di CSV:\n`{', '.join(missing)}`",
            parse_mode="Markdown"
        )
        return

    # Filter JATENG-DIY + APPROVED dulu
    df_base = df[
        (df["STATUS"].str.strip().str.upper() == "APPROVED") &
        (df["REGION"].str.strip().str.upper() == "JATENG-DIY")
    ].copy()

    # Split DJP dan MB
    df_djp = df_base[df_base["SCHEDULE CATEGORY"].str.strip().str.upper() == "DJP"].copy()
    df_mb  = df_base[df_base["SCHEDULE CATEGORY"].str.strip().str.upper() == "BRIEFING"].copy()

    if df_djp.empty and df_mb.empty:
        await update.message.reply_text(
            "⚠️ Tidak ada data DJP atau BRIEFING APPROVED di file ini."
        )
        return

    # Parse tanggal untuk keduanya
    for df_x in [df_djp, df_mb]:
        df_x["TUGAS DATE"] = pd.to_datetime(
            df_x["TUGAS DATE"], errors="coerce"
        ).dt.date

    df_djp = df_djp.dropna(subset=["TUGAS DATE"])
    df_mb  = df_mb.dropna(subset=["TUGAS DATE"])

    def _append_replace(existing_df, new_df):
        """Append new_df ke existing_df, replace per bulan."""
        if new_df.empty:
            return existing_df
        bulan_baru = {d.strftime("%Y-%m") for d in new_df["TUGAS DATE"]}
        if existing_df is not None and not existing_df.empty:
            bulan_label = existing_df["TUGAS DATE"].apply(lambda d: d.strftime("%Y-%m"))
            existing_df = existing_df[~bulan_label.isin(bulan_baru)]
            return pd.concat([existing_df, new_df], ignore_index=True)
        return new_df.copy()

    _djp_csv_df = _append_replace(_djp_csv_df, df_djp)
    _mb_csv_df  = _append_replace(_mb_csv_df,  df_mb)
    _last_djpcsv_upload_time = datetime.now()

    # ── Ringkasan ─────────────────────────────────────────────────────────
    lines = ["✅ *CSV tersimpan*\n"]

    for label, dff, total_df in [
        ("DJP",      df_djp, _djp_csv_df),
        ("BRIEFING", df_mb,  _mb_csv_df),
    ]:
        if dff.empty:
            lines.append(f"⚠️ {label}: tidak ada data di file ini")
            continue
        tgl_min   = dff["TUGAS DATE"].min()
        tgl_max   = dff["TUGAS DATE"].max()
        bln_baru  = sorted({d.strftime("%Y-%m") for d in dff["TUGAS DATE"]})
        bln_total = sorted({d.strftime("%Y-%m") for d in total_df["TUGAS DATE"]})
        lines.append(
            f"*{label}*\n"
            f"  File ini : {tgl_min.strftime('%d-%m-%Y')} s/d {tgl_max.strftime('%d-%m-%Y')}\n"
            f"  Bulan    : {', '.join(bln_baru)} (replace jika ada)\n"
            f"  Row baru : *{len(dff):,}*  |  SF unik: *{dff['USER CODE'].nunique():,}*\n"
            f"  Total tersimpan: bulan {', '.join(bln_total)} ({len(total_df):,} rows)"
        )

    lines.append("\nGunakan `/djpcsv` atau `/mbcsv` + tanggal untuk generate laporan.")
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


# ── /djpcsv, /mbcsv, /c3mr, /payment, /c3mr10s (direfactor ke BaseReport) ────
_top_bottom_djp = djp_mb_sf.top_bottom_djp
_build_djp_caption = djp_mb_sf.build_djp_caption
_build_sf_caption = djp_mb_sf.build_sf_caption

cmd_djpcsv = djp_mb_sf.ReportDJPCSV(
    get_djp_csv_fn=lambda: _djp_csv_df,
    get_sf_aktif_fn=lambda: _sf_aktif_df,
    get_upload_cutoff_fn=lambda: _get_cutoff_upload(_last_djpcsv_upload_time),
).handle
cmd_mbcsv = djp_mb_sf.ReportMBCSV(
    get_mb_csv_fn=lambda: _mb_csv_df,
    get_sf_aktif_fn=lambda: _sf_aktif_df,
    get_upload_cutoff_fn=lambda: _get_cutoff_upload(_last_djpcsv_upload_time),
).handle
cmd_c3mr = c3mr.ReportC3MR(get_cutoff_fn=_get_cutoff_tabel).handle
cmd_payment = c3mr.ReportPayment().handle
cmd_c3mr10s = c3mr.ReportC3MR10S(get_cutoff_fn=_get_cutoff_tabel).handle

async def _kirim_dgn_retry(kirim_fn, *, maks: int = 3, jeda_detik: float = 5.0, label: str = "kirim"):
    """
    Jalankan kirim_fn() (biasanya reply_photo/send_photo). Kalau gagal karena
    telegram.error.TimedOut/NetworkError — balasan Telegram tidak sampai dalam
    batas waktu, PALING SERING karena file-nya besar & koneksi lambat, BUKAN
    berarti pengirimannya gagal — coba ulang sampai `maks` kali dengan jeda.

    CATATAN RISIKO (sengaja diterima untuk /c3mrnew): kalau TimedOut kejadian
    SETELAH Telegram sebenarnya sudah memproses file itu (cuma respons ACK-nya
    yang telat), retry ini BISA membuat foto yang sama terkirim dua kali.
    _RetryRequest (di atas) sengaja TIDAK meng-cover kasus ini karena alasan
    yang sama. Di sini trade-off-nya dibalik: laporan C3MR New Sales berat
    (query bisa lama) jadi user lebih diuntungkan drpd harus /c3mrnew ulang
    dari nol; risiko duplikat kecil & gampang dihapus manual kalau kejadian.
    """
    from telegram.error import TimedOut, NetworkError
    percobaan = 0
    while True:
        try:
            return await kirim_fn()
        except (TimedOut, NetworkError) as e:
            percobaan += 1
            if percobaan >= maks:
                logger.warning(f"[{label}] gagal kirim setelah {maks}x percobaan: {e}")
                raise
            logger.warning(
                f"[{label}] {type(e).__name__} (percobaan {percobaan}/{maks - 1}) "
                f"— retry dalam {jeda_detik}s..."
            )
            await asyncio.sleep(jeda_detik)


async def _kirim_foto_retry(bot, chat_id: int, img, filename: str,
                             caption: str = None, label: str = "foto",
                             parse_mode: str = None):
    """
    send_photo dengan retry ringan (maks 2x percobaan, jeda pendek) supaya
    ReadError/TimedOut sesaat tidak menggagalkan SISA laporan yang belum
    terkirim (sebelumnya: 1 send_photo gagal -> exception naik -> seluruh
    _kirim_laporan_sql berhenti, gambar2 berikutnya ikut tidak terkirim).

    img di-seek(0) ulang tiap percobaan karena posisi buffer maju setelah
    upaya kirim sebelumnya (baik sukses maupun gagal).

    Retry cuma 1x (maks=2) — bukan 3x seperti /c3mrnew — supaya risiko foto
    kekirim dobel (kalau ReadError kejadian SETELAH Telegram sebenarnya sudah
    terima filenya) tetap kecil.
    """
    async def _kirim():
        img.seek(0)
        return await bot.send_photo(
            chat_id=chat_id, photo=InputFile(img, filename=filename), caption=caption,
            parse_mode=parse_mode
        )
    return await _kirim_dgn_retry(_kirim, maks=2, jeda_detik=3.0, label=label)


async def _kirim_dokumen_retry(bot, chat_id: int, doc, filename: str,
                               caption: str = None, label: str = "dokumen",
                               parse_mode: str = None):
    """
    send_document dengan retry ringan (maks 2x percobaan, jeda pendek).
    doc di-seek(0) ulang tiap percobaan.
    """
    async def _kirim():
        if hasattr(doc, "seek"):
            doc.seek(0)
        return await bot.send_document(
            chat_id=chat_id, document=InputFile(doc, filename=filename), caption=caption,
            parse_mode=parse_mode
        )
    return await _kirim_dgn_retry(_kirim, maks=2, jeda_detik=3.0, label=label)


# ── /c3mrnew, /djp, /sf, /caps, /pranpc* (direfactor ke BaseReport) ──────────
cmd_c3mrnew = c3mr.ReportC3MRNew(
    get_cutoff_fn=_get_cutoff_tabel,
    kirim_retry_fn=_kirim_dgn_retry,
).handle
cmd_djp = djp_mb_sf.ReportDJP(
    get_cutoff_fn=_get_cutoff_tabel,
    get_sf_aktif_fn=lambda: _sf_aktif_df,
).handle
cmd_sf = djp_mb_sf.ReportSF(
    get_cutoff_fn=_get_cutoff_tabel,
    get_sf_aktif_fn=lambda: _sf_aktif_df,
).handle
cmd_caps = caps.ReportCaps(
    get_cutoff_fn=_get_cutoff_tabel,
    get_target_fn=lambda: _target_caps_df,
).handle
cmd_pranpcall = pranpc.ReportPranpcAll().handle
cmd_pranpcagent = pranpc.ReportPranpcAgent().handle
cmd_moretensi = pranpc.ReportMoRetensi().handle
cmd_pranpcsp = pranpc.ReportPranpcSP().handle
cmd_pranpcprio = pranpc.ReportPranpcPrio().handle

async def _kirim_file_dedup(ctx: ContextTypes.DEFAULT_TYPE, targets: list,
                             path: str, filename: str, caption: str, persist_name: str,
                             bot=None):
    """Kirim 1 file ke semua `targets` [(chat,thread),...] — upload SEKALI ke
    tujuan pertama, tujuan berikutnya pakai file_id (cepat, tak re-upload).
    Dipakai /agresif & /djpprio utk kirim file raw/report.

    Kalau >49MB (limit Bot API 50MB): JANGAN kirim, copy dulu ke folder
    PERMANEN `agresif_raw_exports/` (nama TETAP `persist_name`, ditimpa tiap
    kali biar tidak menumpuk) SEBELUM out_dir sementara (tempfile.mkdtemp)
    dihapus oleh pemanggil — supaya "disimpan di server" itu beneran benar,
    bukan file yang sudah lenyap begitu pesannya dibaca.

    `bot` opsional: kalau diisi, pakai bot ini LANGSUNG (bypass _BotKeTopic)
    supaya chat_id tidak di-override ke REPORT_GROUP_ID. Dipakai utk kirim
    file raw yang sengaja TIDAK boleh masuk topic.
    """
    size_mb = os.path.getsize(path) / 1048576
    if size_mb > 49:
        persist_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agresif_raw_exports")
        os.makedirs(persist_dir, exist_ok=True)
        persist_path = os.path.join(persist_dir, persist_name)
        shutil.copyfile(path, persist_path)
        _bot = bot or ctx.bot
        for chat, thread in targets:
            await _bot.send_message(
                chat_id=chat, message_thread_id=thread,
                text=(f"⚠️ {filename} ({size_mb:.1f} MB) "
                      f"melebihi batas kirim Bot API (50 MB) — tidak dikirim otomatis.\n"
                      f"Disimpan di server (ditimpa tiap kali): `{persist_path}`"),
                parse_mode="Markdown"
            )
        return
    _bot = bot or ctx.bot
    file_id = None
    for chat, thread in targets:
        if file_id is None:
            with open(path, "rb") as fh:
                msg = await _bot.send_document(
                    chat_id=chat, message_thread_id=thread,
                    document=InputFile(fh, filename=filename), caption=caption,
                    write_timeout=600, read_timeout=180,
                )
            file_id = msg.document.file_id
        else:
            await _bot.send_document(
                chat_id=chat, message_thread_id=thread,
                document=file_id, caption=caption,
            )


# ── /agresif, /5so, /7so, /wireless, /dod, /promo, /pdd, /addon, /klaim ──────
async def _get_agresif_targets():
    df_kec = _target_agresif_kec_df
    df_fmc = _target_fmc_city_df
    if df_kec is None and df_fmc is None:
        df_kec, df_fmc = await asyncio.to_thread(_load_agresif_target_from_local_file)
    return df_kec, df_fmc


async def _get_wireless_target():
    df_target = _target_wireless_df
    if df_target is None:
        df_target = await asyncio.to_thread(_load_wireless_target_from_local_file)
    return df_target


cmd_agresif_full = agresif.ReportAgresifFull(
    get_targets_fn=_get_agresif_targets,
    is_terjadwal_fn=lambda b: isinstance(b, _BotKeTopic),
    unwrap_bot_fn=lambda b: b._bot if isinstance(b, _BotKeTopic) else b,
    kirim_file_dedup_fn=_kirim_file_dedup,
).handle
cmd_agresif = agresif.ReportAgresif(
    get_targets_fn=_get_agresif_targets,
    is_terjadwal_fn=lambda b: isinstance(b, _BotKeTopic),
).handle
cmd_5so = sf_momentum.Report5SO(get_cutoff_fn=_get_cutoff_tabel).handle
cmd_7so = sf_momentum.Report7SO(get_cutoff_fn=_get_cutoff_tabel).handle
cmd_wireless = wireless.ReportWireless(
    get_target_fn=_get_wireless_target,
    get_cutoff_raw_fn=lambda: _get_cutoff_raw(),
    kirim_foto_retry_fn=_kirim_foto_retry,
).handle
cmd_dod = dod.ReportDoD(get_cutoff_fn=_get_cutoff_tabel).handle
cmd_promo = promo.ReportPromo(get_cutoff_fn=_get_cutoff_tabel).handle
cmd_pdd = pdd.ReportPDD(get_cutoff_fn=_get_cutoff_tabel).handle
_buat_caption_addon = addon.build_caption_addon
cmd_addon = addon.ReportAddon(
    get_cutoff_fn=_get_cutoff_tabel,
    get_target_fn=lambda: _target_addon_dfs or _load_addon_target_from_local_file(),
    kirim_retry_fn=_kirim_dgn_retry,
).handle
cmd_klaim = klaim.ReportKlaim().handle

# ── Laporan terjadwal ke grup topic ───────────────────────────────────────────
# Handler /perintah dibuat untuk dipanggil user (butuh `update` & `ctx`). Supaya
# tidak perlu menulis ulang 10+ alur laporan, scheduler memakai adapter di bawah:
# objek tiruan `update` yang membelokkan semua balasan ke chat+topic tujuan.
class _PesanKeTopic:
    """
    Tiruan `update.message` — reply_* diarahkan ke REPORT_GROUP_ID + topic.

    chat.id sengaja diisi GROUP_ID (bukan chat tujuan) karena tiap handler punya
    pola `if update.effective_chat.id != GROUP_ID: <forward ke GROUP_ID>`. Kalau
    diisi id asli, tiap laporan terkirim DUA kali (ke topic + ke grup lama).
    Dengan GROUP_ID, cabang forward itu dilewati.
    """

    def __init__(self, bot, chat_id: int, thread_id: int, label: str):
        self._bot       = bot
        self._chat_id   = chat_id
        self._thread_id = thread_id
        self._label     = label
        self.chat = SimpleNamespace(id=GROUP_ID)

    async def reply_text(self, text, **kw):
        # Pesan progres ("⏳ Memproses...") tidak perlu muncul di grup laporan.
        if str(text).lstrip().startswith("⏳"):
            logger.info(f"[JADWAL:{self._label}] (progres dilewati) {str(text)[:60]}")
            return None
        return await self._bot.send_message(
            chat_id=self._chat_id, message_thread_id=self._thread_id, text=text, **kw
        )

    async def reply_photo(self, photo, **kw):
        return await self._bot.send_photo(
            chat_id=self._chat_id, message_thread_id=self._thread_id, photo=photo, **kw
        )

    async def reply_document(self, document, **kw):
        return await self._bot.send_document(
            chat_id=self._chat_id, message_thread_id=self._thread_id, document=document, **kw
        )


class _UpdateKeTopic:
    """Tiruan `update` seperlunya: .message, .effective_chat, .effective_message."""

    def __init__(self, message: _PesanKeTopic):
        self.message           = message
        self.effective_message = message
        self.effective_chat    = SimpleNamespace(id=GROUP_ID)


def _tujuan_terjadwal(thread_id):
    """
    Tujuan laporan terjadwal -> (chat_id, thread_id, salin_ke).
    JADWAL_KIRIM_KE_GRUP_REPORT=True : topic di grup report + salinan ke GROUP_ID.
    False                            : HANYA grup koordinasi (GROUP_ID), tanpa topic.
    """
    if JADWAL_KIRIM_KE_GRUP_REPORT:
        return REPORT_GROUP_ID, thread_id, GROUP_ID
    return GROUP_ID, None, None


def _salin_media(kw: dict) -> dict:
    """
    Bikin salinan kwargs yang aman dikirim ULANG.

    Objek InputFile/stream hanya bisa dibaca sekali — kalau kw yang sama dipakai
    dua kali, kiriman kedua bakal kosong/gagal. Di sini isinya dibaca lalu
    dibungkus ulang jadi InputFile baru.
    """
    baru = dict(kw)
    for kunci in ("photo", "document", "video", "audio"):
        nilai = baru.get(kunci)
        if isinstance(nilai, InputFile):
            baru[kunci] = InputFile(
                BytesIO(nilai.input_file_content), filename=nilai.filename
            )
        elif hasattr(nilai, "read"):
            try:
                nilai.seek(0)
                baru[kunci] = InputFile(BytesIO(nilai.read()), filename="report.png")
                nilai.seek(0)
            except Exception:
                pass
    return baru


# Antrean Lock Global Khusus Pengiriman (Telegram & WhatsApp):
# Proses kalkulasi/query DB/fetch API tetap berjalan asynchronous dan boleh paralel,
# tetapi aksi pengiriman pesan/media ke chat/grup dikunci berurutan agar pesan tidak pernah tumpang tindih.
_send_delivery_lock = asyncio.Lock()


class _BotKeTopic:
    """
    Pembungkus objek Bot: SEMUA send_* dikirim ke DUA tujuan —
      1. REPORT_GROUP_ID + topic-nya (laporan untuk manajemen)
      2. GROUP_ID / grup koordinasi (buat memantau semua laporan di satu tempat)

    Perlu karena tidak semua handler mengirim lewat `update.message.reply_*`.
    /liveupdate & /closingsql misalnya memanggil _kirim_laporan_sql(ctx.bot,
    update.effective_chat.id, ...) yang mengirim langsung via bot.send_photo —
    lewat jalur itu adapter pesan tidak kepakai. Dengan membungkus bot-nya,
    semua jalur pengiriman ikut terarah dengan benar, termasuk yang tak terduga.

    Kegagalan kirim ke grup koordinasi TIDAK menggagalkan laporannya — cukup
    dicatat di log, karena tujuan utamanya tetap topic.
    """

    def __init__(self, bot, chat_id: int, thread_id: int, salin_ke: int = None,
                 status: "_StatusLaporan" = None, kirim_ke_wa: bool = False):
        self._bot       = bot
        self._chat_id   = chat_id
        self._thread_id = thread_id
        self._salin_ke  = salin_ke
        # Penanda hasil (opsional) — dicatat tiap kali laporan mengirim media,
        # dipakai job penjadwal untuk membedakan laporan BERHASIL vs gagal.
        self._status    = status
        self._kirim_ke_wa = kirim_ke_wa

    def __getattr__(self, nama):
        asli = getattr(self._bot, nama)
        if not nama.startswith("send_"):
            return asli

        async def _kirim(*args, **kw):
            kw["chat_id"] = self._chat_id
            if self._thread_id is None:
                # Tujuan = grup koordinasi (tanpa topic): buang thread eksplisit dari
                # pemanggil (mis. /agresif memakai topic SALES) supaya tidak "thread not found".
                kw["message_thread_id"] = None
            else:
                kw.setdefault("message_thread_id", self._thread_id)
            salinan = _salin_media(kw) if self._salin_ke else None

            # Antre pengiriman agar pesan/media keluar secara berurutan dan tidak tumpang tindih
            async with _send_delivery_lock:
                hasil = await asli(*args, **kw)

                # Catat kalau laporan sudah mengeluarkan OUTPUT nyata (gambar/CSV/dsb).
                # Begitu ada output, job penjadwal tak akan mengulang laporan ini —
                # jaminan laporan tidak pernah terkirim dobel walau ada error menyusul.
                if self._status is not None and nama in (
                    "send_photo", "send_document", "send_video", "send_audio"
                ):
                    self._status.media_terkirim += 1

                if self._salin_ke:
                    salinan["chat_id"] = self._salin_ke
                    salinan.pop("message_thread_id", None)  # grup koordinasi tanpa topic
                    try:
                        await asli(*args, **salinan)
                    except Exception:
                        logger.exception(
                            f"[JADWAL] Salinan ke grup koordinasi {self._salin_ke} gagal ({nama})"
                        )

                if self._kirim_ke_wa and WA_JADWAL_OTOMATIS_AKTIF and WAHA_TARGET_CHAT_ID:
                    try:
                        from whatsapp.client import get_waha_client
                        from whatsapp.adapter import WahaBotAdapter
                        adapter = WahaBotAdapter(get_waha_client(), WAHA_TARGET_CHAT_ID, send_images=WAHA_SEND_IMAGES)
                        wa_kw = _salin_media(kw) if not self._salin_ke else _salin_media(salinan)
                        if nama == "send_photo":
                            await adapter.send_photo(photo=wa_kw.get("photo"), caption=wa_kw.get("caption"))
                        elif nama == "send_document":
                            await adapter.send_document(document=wa_kw.get("document"), caption=wa_kw.get("caption"))
                        elif nama == "send_message":
                            await adapter.send_message(text=wa_kw.get("text"))
                    except Exception:
                        logger.exception(f"[JADWAL] Pengiriman otomatis ke WhatsApp {WAHA_TARGET_CHAT_ID} gagal ({nama})")

                return hasil

        return _kirim


def _dengan_batas_waktu(handler, menit: float = None):
    """
    Bungkus sebuah command handler dengan PENANGKAL TIMEOUT.

    Kalau handler tidak selesai dalam `menit` menit (default REPORT_TIMEOUT_MENIT),
    prosesnya dibatalkan dan pengguna diberi tahu — supaya satu perintah yang
    nyangkut (mis. VPN putus tapi TCP masih setengah nyambung sehingga query
    menggantung dan tak pernah balik) tidak menggantung tanpa kabar.

    Berkat concurrent_updates, perintah lain tetap jalan walau ada yang macet;
    timeout ini memastikan yang macet pun akhirnya menutup diri dan melapor.

    Catatan teknis: pembatalan menghentikan ALUR handler (coroutine-nya), tapi
    thread query DB yang terlanjur jalan tidak bisa dipaksa mati oleh Python — ia
    berhenti sendiri saat query balik/gagal. Yang penting bot tetap responsif dan
    memberi kabar, bukan diam menggantung.
    """
    batas = (menit if menit is not None else REPORT_TIMEOUT_MENIT) * 60

    async def _wrapped(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        nama = "Perintah"
        try:
            teks = update.effective_message.text if update and update.effective_message else None
            if teks:
                nama = teks.split()[0]  # mis. "/c3mrnew"
        except Exception:
            pass
        try:
            await asyncio.wait_for(handler(update, ctx), timeout=batas)
        except asyncio.TimeoutError:
            logger.error(f"[TIMEOUT] {nama} dibatalkan — melebihi {batas/60:.0f} menit")
            try:
                await update.effective_message.reply_text(
                    f"⏱️ {nama} dibatalkan otomatis — proses melebihi "
                    f"{batas/60:.0f} menit (kemungkinan koneksi DB/VPN nyangkut). "
                    f"Coba lagi setelah koneksi stabil."
                )
            except Exception:
                logger.exception("[TIMEOUT] Notifikasi timeout gagal dikirim")

    return _wrapped


def _daftar_perintah_terjadwal() -> dict:
    """Nama perintah di JADWAL_LAPORAN -> fungsi handler-nya."""
    return {
        "liveupdate":   cmd_liveupdate,
        "closingsql":   cmd_closing_sql,
        "dailyre":      cmd_dailyre,
        "dod":          cmd_dod,
        "promo":        cmd_promo,
        "addon":        cmd_addon,
        "homepass":     cmd_homepass,
        "pdd":          cmd_pdd,
        "salahtagging": cmd_salahtagging,
        "homepass_wok_old":     cmd_homepass_wok_old,
        "salahtagging_wok_old": cmd_salahtagging_wok_old,
        "caps":         cmd_caps,
        "c3mr":         cmd_c3mr,
        "c3mrnew":      cmd_c3mrnew,
        "c3mr10s":      cmd_c3mr10s,
        "klaim":        cmd_klaim,
        "agresif":      cmd_agresif,
        "wireless":     cmd_wireless,
        "wirelesschannel": cmd_wireless_channel,
        "wireless2":    cmd_wireless2,
        "wirelesschannel2": cmd_wirelesschannel2,
        "clockin_sf_teritory": cmd_clockin_sf_teritory,
        "clockin_sf_all": cmd_clockin_sf_all,
        "homepass_raw": cmd_homepass_raw,
        "murmer":       cmd_murmer,
        "5so":          cmd_5so,
        "7so":          cmd_7so,
        "c3mrnewch":    cmd_c3mrnewch,
        "c3mrsvp":      cmd_c3mrsvp,
        "leads":        cmd_leads,
        "nasional":     cmd_nasional,
        "pranpcall":    cmd_pranpcall,
        "pranpcagent":  cmd_pranpcagent,
        "moretensi":    cmd_moretensi,
        "pranpcsp":     cmd_pranpcsp,
        "pranpcprio":   cmd_pranpcprio,
        "ms":           cmd_ms,
        "msbranch":     cmd_msbranch,
        "childps":      childps_bot.cmd_childps,
    }


# Laporan yang TIDAK butuh MySQL internal (rajawalidb1) / VPN GlobalProtect —
# sumbernya web publik biasa (leads_browser.py -> jatenggayeng.id). Dipakai
# job_laporan_topic supaya laporan ini TIDAK ikut menunggu/dianggap gagal
# gara2 _tunggu_db_siap (yg ngecek MySQL internal, bukan internet biasa).
# PraNPC (/pranpc*, /moretensi) memakai DB Indiana (server publik terpisah, config DB2_*), bukan VPN.
_LAPORAN_TANPA_DB = {"leads", "pranpcall", "pranpcagent", "moretensi", "pranpcsp", "pranpcprio"}


async def _tunggu_db_siap(context: ContextTypes.DEFAULT_TYPE, label: str) -> bool:
    """
    Pastikan DB terjangkau sebelum laporan terjadwal dijalankan.

    Kalau VPN/GlobalProtect putus, laporan TIDAK dilewatkan begitu saja — bot
    memantau koneksi tiap JADWAL_CEK_DETIK detik selama maks JADWAL_TUNGGU_MENIT
    menit. Begitu VPN nyambung, laporan LANGSUNG lanjut (hitungan detik), bukan
    menunggu jeda panjang.

    Pemantauannya ringan: cuma tes buka port TCP (db.port_terbuka). Login MySQL
    penuh (db.test_connection) baru dijalankan setelah port-nya kebuka, untuk
    memastikan servernya benar-benar siap melayani — port kebuka belum tentu
    MySQL-nya sudah menerima login.

    Return True kalau DB siap, False kalau menyerah sampai batas waktu.
    """
    async def _kabari(teks):
        try:
            await context.bot.send_message(chat_id=GROUP_ID, text=teks)
        except Exception:
            logger.exception("[JADWAL] Notifikasi status DB gagal dikirim")

    async def _siap() -> bool:
        if not await asyncio.to_thread(db.port_terbuka):
            return False
        return await asyncio.to_thread(db.test_connection)

    # Percobaan pertama: kalau langsung siap, tidak usah bikin notif apa pun.
    try:
        if await _siap():
            return True
    except Exception as e:
        logger.warning(f"[JADWAL:{label}] Cek koneksi DB error: {e}")

    mulai = datetime.now()
    batas = JADWAL_TUNGGU_MENIT * 60
    logger.warning(f"[JADWAL:{label}] DB tidak terjangkau — mulai memantau tiap {JADWAL_CEK_DETIK} detik")

    # Coba auto-reconnect GlobalProtect duluan (best-effort, tanpa nunggu hasil
    # lama-lama). Ini cuma bisa berhasil kalau sesi SSO-nya masih dalam masa
    # berlaku (~7 jam) — begitu putus TCP-nya tapi sesinya masih valid, GP
    # bisa nyambung lagi sendiri tanpa approval 2FA. Kalau sesinya sudah
    # expired, ini tidak akan berhasil dan tetap butuh login manual.
    gp_dicoba = False
    try:
        gp_status = await asyncio.wait_for(asyncio.to_thread(gp_control.get_status), timeout=15)
        if not gp_status["connected"]:
            gp_dicoba = True
            await asyncio.wait_for(asyncio.to_thread(gp_control.reconnect), timeout=15)
    except Exception as e:
        logger.warning(f"[JADWAL:{label}] Auto-reconnect GlobalProtect gagal dicoba: {e}")

    await _kabari(
        f"⚠️ Laporan terjadwal {label} DITUNDA — database tidak terjangkau "
        f"(kemungkinan VPN/GlobalProtect putus).\n"
        + ("🔄 Sudah dicoba auto-reconnect GlobalProtect.\n" if gp_dicoba else "")
        + f"Bot memantau tiap {JADWAL_CEK_DETIK} detik dan akan LANGSUNG lanjut "
        f"begitu koneksi pulih (maks tunggu {JADWAL_TUNGGU_MENIT} menit).\n"
        f"Kalau sesi SSO GlobalProtect sudah lewat 7 jam, auto-reconnect TIDAK akan "
        f"berhasil — perlu login manual (SSO+2FA) via RDP/console ke server."
    )

    while (datetime.now() - mulai).total_seconds() < batas:
        await asyncio.sleep(JADWAL_CEK_DETIK)
        try:
            if await _siap():
                tertunda = int((datetime.now() - mulai).total_seconds())
                menit, detik = divmod(tertunda, 60)
                logger.info(f"[JADWAL:{label}] DB pulih setelah {menit}m {detik}d — lanjut")
                await _kabari(
                    f"✅ Koneksi DB pulih. Laporan terjadwal {label} dilanjutkan "
                    f"(tertunda {menit} menit {detik} detik)."
                )
                return True
        except Exception as e:
            logger.warning(f"[JADWAL:{label}] Cek koneksi DB error: {e}")

    await _kabari(
        f"❌ Laporan terjadwal {label} BATAL — database tetap tidak terjangkau "
        f"setelah menunggu {JADWAL_TUNGGU_MENIT} menit.\n"
        f"Cek VPN/GlobalProtect, lalu jalankan perintahnya manual."
    )
    return False


class _StatusLaporan:
    """
    Penanda hasil satu laporan terjadwal, diisi oleh _BotKeTopic saat mengirim.

    media_terkirim > 0 berarti laporan sudah mengeluarkan output (gambar/CSV).
    Job penjadwal memakainya untuk memutuskan sebuah laporan BERHASIL (tak boleh
    diulang, supaya tidak dobel) vs gagal SEBELUM mengeluarkan output (boleh
    diulang kalau ternyata gagal karena DB/GP putus di tengah query).
    """
    def __init__(self):
        self.media_terkirim = 0


# Batas percobaan per laporan kalau DB/GP putus di TENGAH query yang panjang.
# _tunggu_db_siap sudah menunggu GP pulih SEBELUM tiap laporan; batas ini untuk
# kasus GP putus lagi saat query sedang jalan (mis. c3mrnew), supaya laporan itu
# diulang otomatis dari awal — bukan gagal permanen dan menyeret laporan lain.
JADWAL_MAKS_PERCOBAAN = 3


async def _retry_laporan_background(context: ContextTypes.DEFAULT_TYPE, nama: str, args: list,
                                     label: str, topic: str, thread_id: int):
    """
    Dipanggil kalau _tunggu_db_siap sudah menyerah (JADWAL_TUNGGU_MENIT lewat)
    dan laporan belum sempat jalan sama sekali (mis. sesi SSO GlobalProtect
    ~7 jam expired pas tidak ada yang sempat login manual).

    Jalan di BACKGROUND — tidak menahan laporan lain di slot yang sama — terus
    memantau DB/GP sampai maksimal JADWAL_RETRY_BACKGROUND_JAM jam. Begitu
    koneksi pulih (kapan pun itu, walau baru berjam-jam kemudian), laporan ini
    langsung dijalankan & dikirim seperti biasa, tanpa perlu dijalankan manual.
    """
    perintahs = _daftar_perintah_terjadwal()
    handler = perintahs.get(nama)
    if handler is None:
        logger.error(f"[JADWAL:{label}] Retry background: perintah '{nama}' tidak dikenal")
        return

    async def _siap() -> bool:
        if not await asyncio.to_thread(db.port_terbuka):
            return False
        return await asyncio.to_thread(db.test_connection)

    mulai = datetime.now()
    batas = JADWAL_RETRY_BACKGROUND_JAM * 3600
    logger.warning(f"[JADWAL:{label}] Retry background dimulai, maks {JADWAL_RETRY_BACKGROUND_JAM} jam")

    while (datetime.now() - mulai).total_seconds() < batas:
        await asyncio.sleep(JADWAL_CEK_DETIK)
        try:
            if await _siap():
                break
        except Exception as e:
            logger.warning(f"[JADWAL:{label}] Retry background cek DB error: {e}")
    else:
        logger.error(f"[JADWAL:{label}] Retry background menyerah setelah {JADWAL_RETRY_BACKGROUND_JAM} jam")
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=(f"❌ Laporan terjadwal /{nama} ({topic}) BATAL PERMANEN — database tetap "
                      f"tidak terjangkau setelah {JADWAL_RETRY_BACKGROUND_JAM} jam retry background. "
                      f"Jalankan manual setelah GP/GlobalProtect stabil.")
            )
        except Exception:
            logger.exception(f"[JADWAL:{label}] Notifikasi retry background gagal final tidak terkirim")
        return

    tertunda = int((datetime.now() - mulai).total_seconds())
    menit_total, detik = divmod(tertunda, 60)
    jam, menit = divmod(menit_total, 60)
    logger.info(f"[JADWAL:{label}] DB pulih (retry background) setelah {jam}j {menit}m — laporan dijalankan")
    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=(f"✅ Koneksi DB pulih (retry background, tertunda {jam} jam {menit} menit). "
                  f"Laporan terjadwal /{nama} ({topic}) dijalankan sekarang.")
        )
    except Exception:
        logger.exception(f"[JADWAL:{label}] Notifikasi retry background pulih tidak terkirim")

    status = _StatusLaporan()
    try:
        tujuan_chat, tujuan_thread, salin = _tujuan_terjadwal(thread_id)
        bot_topic = _BotKeTopic(context.bot, tujuan_chat, tujuan_thread,
                                salin_ke=salin, status=status)
        pesan     = _PesanKeTopic(bot_topic, tujuan_chat, tujuan_thread, label)
        await asyncio.wait_for(
            handler(_UpdateKeTopic(pesan), SimpleNamespace(args=args, bot=bot_topic)),
            timeout=REPORT_TIMEOUT_MENIT * 60,
        )
        logger.info(f"[JADWAL:{label}] Retry background selesai")
    except asyncio.TimeoutError:
        logger.error(f"[JADWAL:{label}] Retry background TIMEOUT setelah {REPORT_TIMEOUT_MENIT} menit")
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=(f"⏱️ Laporan terjadwal /{nama} ({topic}) (retry background) dibatalkan — "
                      f"melebihi {REPORT_TIMEOUT_MENIT} menit.")
            )
        except Exception:
            logger.exception(f"[JADWAL:{label}] Notifikasi timeout retry background tidak terkirim")
    except Exception:
        logger.exception(f"[JADWAL:{label}] Retry background GAGAL")
        try:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                text=f"❌ Laporan terjadwal /{nama} ({topic}) (retry background) gagal dijalankan."
            )
        except Exception:
            logger.exception(f"[JADWAL:{label}] Notifikasi gagal retry background tidak terkirim")


# ── Mode query: langsung (MySQL/VPN) atau lewat SQL Console Rajawali Dashboard ──
# Lihat mode_query.py. Jalur Rajawali menjalankan rajawali_auto.py sebagai subprocess (otomasi UI
# Prisma: query -> export -> report -> kirim), satu per satu (lock), hasil export hari itu dipakai ulang
# antar slot (--pakai-ada) supaya query tidak diulang.
RAJAWALI_TIMEOUT_MENIT = getattr(_config, "RAJAWALI_TIMEOUT_MENIT", 60)
RAJAWALI_BLOK_INPUT    = getattr(_config, "RAJAWALI_BLOK_INPUT", False)   # True = blok mouse/keyboard (butuh admin)
_rajawali_lock = asyncio.Lock()


_rajawali_mulai = {"t": 0.0}


def _bukti_rajawali_terbaru():
    """Tangkapan layar kegagalan terbaru dari run Rajawali terakhir (storage/logs/screenshots/), atau None."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "logs", "screenshots")
    fs = [p for p in glob.glob(os.path.join(d, "rajawali_gagal_*.png")) if os.path.getmtime(p) >= _rajawali_mulai["t"]]
    return max(fs, key=os.path.getmtime) if fs else None


async def _jalankan_rajawali(nama_laporan, tgl, topic=None, kirim=True, chat=None):
    """Jalankan rajawali_auto.py untuk laporan `nama_laporan` tanggal `tgl`.
    Return (berhasil, ringkasan_log). Ringkasan hanya baris log runner '[..]' & 'GAGAL' (tanpa log HTTP)."""
    cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "utils", "rajawali_auto.py"),
           "--tanggal", tgl.strftime("%d-%m-%Y"), "--only", ",".join(nama_laporan), "--pakai-ada"]
    if kirim:
        cmd.append("--kirim")
    if chat:
        cmd += ["--chat", str(chat)]
    elif topic:
        cmd += ["--topic", topic]
    if not RAJAWALI_BLOK_INPUT:
        cmd.append("--tanpa-blok")
    async with _rajawali_lock:
        _rajawali_mulai["t"] = datetime.now().timestamp()
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            # RAJAWALI_DARI_BOT: runner tidak mengirim notifikasi gagal sendiri (bot yang mengabari, supaya tidak dobel)
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "RAJAWALI_DARI_BOT": "1"})
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=RAJAWALI_TIMEOUT_MENIT * 60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, f"timeout {RAJAWALI_TIMEOUT_MENIT} menit"
    teks = out.decode("utf-8", "replace")
    ringkas = "\n".join(b for b in teks.splitlines() if b.startswith("[") or "GAGAL" in b)
    return mode_query.runner_berhasil(proc.returncode, teks), ringkas[-1500:]


async def _slot_lewat_rajawali(context, slot, topic):
    """Bila mode query menyuruh lewat Rajawali: jalankan laporan slot yang didukung lewat rajawali_auto.py.
    Return daftar (nama, offset) yang masih harus dijalankan lewat jalur langsung (MySQL)."""
    laporan = list(slot["laporan"])
    mode = mode_query.ambil()
    if mode == "langsung":
        return laporan
    db_ok = mode == "auto" and await asyncio.to_thread(db.port_terbuka)
    if not mode_query.pakai_rajawali(db_ok):
        return laporan
    lewat = [(n, o) for n, o in laporan if n in mode_query.DIDUKUNG_RAJAWALI]
    sisa = [(n, o) for n, o in laporan if n not in mode_query.DIDUKUNG_RAJAWALI]
    per_tgl = {}
    for n, o in lewat:
        hari = 0 if n == "liveupdate" else (o or 1)      # liveupdate = data jam berjalan hari ini
        per_tgl.setdefault(date.today() - timedelta(days=hari), []).append(n)
    for tgl, nama in per_tgl.items():
        label = f"{topic}/rajawali:{','.join(nama)}"
        logger.info(f"[JADWAL:{label}] Mode {mode} -> lewat Rajawali Dashboard, tanggal {tgl:%d-%m-%Y}")
        ok, ringkas = await _jalankan_rajawali(nama, tgl, topic)
        if ok:
            logger.info(f"[JADWAL:{label}] Selesai")
            # Teruskan hasil mode Rajawali ke WhatsApp bila laporan ini ditandai kirim ke WA
            if WA_JADWAL_OTOMATIS_AKTIF and WAHA_TARGET_CHAT_ID:
                for nm in nama:
                    if slot.get("wa") or nm in ("liveupdate", "closingsql", "agresif"):
                        try:
                            from whatsapp.senders import _rajawali_ke_wa
                            await _rajawali_ke_wa(nm, tgl, WAHA_TARGET_CHAT_ID, WAHA_SEND_IMAGES, png_sebagai_gambar=(nm == "agresif"))
                            logger.info(f"[JADWAL:{label}] Berhasil diteruskan ke WhatsApp ({nm} -> {WAHA_TARGET_CHAT_ID})")
                        except Exception as wa_err:
                            logger.warning(f"[JADWAL:{label}] Gagal teruskan ke WhatsApp ({nm}): {wa_err}")
        else:
            logger.error(f"[JADWAL:{label}] GAGAL\n{ringkas}")
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=(f"❌ Laporan terjadwal {', '.join('/' + x for x in nama)} ({topic}) lewat Rajawali "
                          f"Dashboard gagal.\n\n{ringkas[-800:]}"))
                foto = _bukti_rajawali_terbaru()
                if foto:
                    with open(foto, "rb") as f:
                        await context.bot.send_photo(chat_id=GROUP_ID, photo=f, caption="Layar Prisma saat gagal")
            except Exception:
                logger.exception(f"[JADWAL:{label}] Notifikasi gagal tidak terkirim")
    if mode == "rajawali":
        # laporan yang memang tidak memakai MySQL (mis. leads) tetap jalan seperti biasa
        lewati = [(n, o) for n, o in sisa if n not in _LAPORAN_TANPA_DB]
        if lewati:
            logger.warning(f"[JADWAL:{topic}] Mode rajawali: {', '.join(n for n, _ in lewati)} belum didukung "
                           f"lewat Rajawali Dashboard -> dilewati")
        return [(n, o) for n, o in sisa if n in _LAPORAN_TANPA_DB]
    return sisa


async def cmd_modequery(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/modequery [langsung|rajawali|auto] — lihat / ganti sumber data laporan terjadwal."""
    if ctx.args:
        try:
            mode_query.atur(ctx.args[0])
        except ValueError as e:
            await update.message.reply_text(f"⚠️ {e}")
            return
    m = mode_query.ambil()
    ket = {"langsung": "query langsung ke MySQL (butuh VPN/GlobalProtect)",
           "rajawali": "lewat SQL Console Rajawali Dashboard (otomasi Prisma)",
           "auto": "langsung bila DB terjangkau, kalau tidak lewat Rajawali Dashboard"}
    await update.message.reply_text(
        f"🔀 Mode query: *{m}* — {ket[m]}\n\n"
        f"Didukung lewat Rajawali: {', '.join('`/' + x + '`' for x in sorted(mode_query.DIDUKUNG_RAJAWALI))}\n"
        f"Laporan lain: mode *auto* = tetap langsung; mode *rajawali* = dilewati.\n\n"
        f"Ganti: `/modequery langsung` · `/modequery rajawali` · `/modequery auto`",
        parse_mode="Markdown")


async def cmd_rajawali(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/rajawali [DD-MM-YYYY] [laporan,...] — jalankan laporan lewat Rajawali Dashboard sekarang
    (kirim ke grup koordinasi). Default: H-1, semua laporan yang didukung."""
    tgl, nama = date.today() - timedelta(days=1), sorted(mode_query.DIDUKUNG_RAJAWALI - {"liveupdate", "caps"})
    for a in ctx.args or []:
        try:
            tgl = datetime.strptime(a, "%d-%m-%Y").date()
        except ValueError:
            nama = [x.strip().lstrip("/") for x in a.split(",") if x.strip()]
    salah = [x for x in nama if x not in mode_query.DIDUKUNG_RAJAWALI]
    if nama == ["liveupdate"]:
        tgl = date.today()                         # data jam berjalan
    elif nama == ["caps"] and not any(re.fullmatch(r"\d{2}-\d{2}-\d{4}", a) for a in ctx.args or []):
        tgl = date.today() - timedelta(days=2)     # caps = H-2 (sama dgn jadwal)
    if salah:
        await update.message.reply_text(f"⚠️ Belum didukung lewat Rajawali: {', '.join(salah)}")
        return
    if _rajawali_lock.locked():
        await update.message.reply_text("⏳ Otomasi Rajawali sedang berjalan, permintaan ini menunggu giliran.")
    await update.message.reply_text(
        f"⏳ Menjalankan lewat Rajawali Dashboard: {', '.join('/' + x for x in nama)} "
        f"tanggal {tgl:%d-%m-%Y} (±15 menit)...")

    ctx.application.create_task(_rajawali_ke_chat(update, nama, tgl), name=f"rajawali-{tgl:%Y%m%d}")


async def _rajawali_ke_chat(update, nama, tgl):
    """Jalankan laporan lewat Rajawali, hasil ke chat pemanggil (laporan sendiri ikut menyalin ke GROUP_ID
    seperti command biasa). Balas ringkasan hanya bila gagal."""
    ok, ringkas = await _jalankan_rajawali(nama, tgl, chat=update.effective_chat.id)
    if not ok:
        await update.message.reply_text(f"❌ Lewat Rajawali Dashboard gagal.\n\n{ringkas[-800:]}")
        foto = _bukti_rajawali_terbaru()
        if foto:
            with open(foto, "rb") as f:
                await update.message.reply_photo(photo=f, caption="Layar Prisma saat gagal")


async def _cegat_mode_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Command manual laporan ikut /modequery: bila mode = rajawali (atau auto & DB tak terjangkau) dan
    laporannya didukung, jalankan lewat Rajawali Dashboard lalu HENTIKAN handler biasa (ApplicationHandlerStop).
    Mode langsung / laporan lain -> tidak melakukan apa pun, command jalan normal."""
    msg = update.effective_message
    if not msg or not msg.text or not msg.text.startswith("/"):
        return
    kata = msg.text.split()
    nama = kata[0][1:].split("@")[0].lower()
    if any(a.strip().lower() in ("help", "?", "--help", "-h", "list") for a in kata[1:]):
        return
    if nama not in mode_query.DIDUKUNG_RAJAWALI or mode_query.ambil() == "langsung":
        return
    if nama == "caps" and not any(re.fullmatch(r"\d{2}-\d{2}-\d{4}", a) for a in kata[1:]):
        return                                     # /caps wajib tanggal -> biar handler biasa yg menjelaskan format
    db_ok = mode_query.ambil() == "auto" and await asyncio.to_thread(db.port_terbuka)
    if not mode_query.pakai_rajawali(db_ok):
        return
    tgl, lain = (date.today() if nama == "liveupdate" else date.today() - timedelta(days=1)), []
    for a in kata[1:]:
        try:
            tgl = datetime.strptime(a, "%d-%m-%Y").date()
        except ValueError:
            lain.append(a)
    antre = " (menunggu otomasi lain selesai)" if _rajawali_lock.locked() else ""
    # nama command bisa mengandung "_" (/homepass_raw, /clockin_sf_teritory) -> di Markdown dibaca awal teks miring
    # tanpa penutup -> BadRequest "Can't parse entities". Escape nama & argumen.
    from telegram.helpers import escape_markdown as _esc
    await msg.reply_text(
        f"⏳ Mode query *{mode_query.ambil()}*: /{_esc(nama)} {tgl:%d-%m-%Y} diambil lewat Rajawali Dashboard"
        f"{antre}..." + (f"\n_Argumen diabaikan: {_esc(' '.join(lain))}_" if lain else ""),
        parse_mode="Markdown")
    ctx.application.create_task(_rajawali_ke_chat(update, [nama], tgl), name=f"rajawali-{nama}")
    raise ApplicationHandlerStop


async def job_laporan_topic(context: ContextTypes.DEFAULT_TYPE):
    """
    Jalankan 1 slot jadwal: semua laporan di dalamnya dieksekusi BERURUTAN
    (menunggu yang satu selesai sebelum lanjut) supaya query berat tidak
    menumpuk dan urutannya di topic tetap rapi.

    Ketahanan koneksi (VPN/GlobalProtect):
      • Sebelum SETIAP laporan, koneksi DB dipastikan siap lewat _tunggu_db_siap.
        Jadi kalau GP putus di tengah slot, laporan sisa TIDAK rontok beruntun —
        masing-masing menunggu GP pulih dulu.
      • Kalau GP putus di TENGAH query sebuah laporan (laporan gagal sebelum
        mengirim output apa pun DAN DB jadi tak terjangkau), laporan itu diulang
        dari awal setelah GP pulih, maks JADWAL_MAKS_PERCOBAAN kali.
      • Begitu laporan sudah mengirim output (media_terkirim > 0), laporan TIDAK
        pernah diulang — jaminan tidak dobel lebih diutamakan daripada retry.
    """
    slot       = context.job.data
    topic      = slot["topic"]
    thread_id  = TOPIC_IDS[topic]
    perintahs  = _daftar_perintah_terjadwal()

    # Slot yang jam-menitnya SAMA mulai bersamaan lalu antre Prisma/DB; urutan antrean dari penjadwal acak
    # (29-10: agresif terkirim sebelum closingsql). Jeda kecil sesuai urutan di JADWAL_LAPORAN supaya slot
    # yang ditulis lebih dulu di config juga mengantre lebih dulu.
    sejam = [s for s in JADWAL_LAPORAN if s.get("jam") == slot.get("jam") and s.get("menit") == slot.get("menit")]
    urut = next((i for i, s in enumerate(sejam) if s == slot), 0)
    if urut:
        await asyncio.sleep(2 * urut)

    # mode query rajawali/auto: laporan yang didukung dikerjakan lewat Rajawali Dashboard dulu
    laporan_langsung = await _slot_lewat_rajawali(context, slot, topic)

    for nama, offset in laporan_langsung:
        handler = perintahs.get(nama)
        if handler is None:
            logger.error(f"[JADWAL:{topic}] Perintah '{nama}' tidak dikenal, dilewati")
            continue

        args = []
        if offset is not None:
            tgl = date.today() - timedelta(days=offset)
            args = [tgl.strftime("%d-%m-%Y")]

        label = f"{topic}/{nama}"
        log_id = scheduler_db.record_log_start(
            job_id=slot.get("id"),
            report_name=nama,
            topic=topic,
            triggered_by=slot.get("_triggered_by", "SCHEDULER"),
        )
        laporan_sukses = False
        media_count = 0
        error_terakhir = None

        for percobaan in range(1, JADWAL_MAKS_PERCOBAAN + 1):
            # Pastikan DB siap SEBELUM laporan jalan. Kalau GP putus (sejak awal
            # slot atau putus lagi setelah laporan sebelumnya), bot menunggu
            # sampai pulih — query tidak dijalankan di atas koneksi mati.
            # Dilewati utk laporan yg tidak butuh MySQL internal (_LAPORAN_TANPA_DB).
            if nama not in _LAPORAN_TANPA_DB and not await _tunggu_db_siap(context, label):
                # GP tak pulih sampai batas waktu → laporan ini TIDAK dijalankan
                # sekarang (_tunggu_db_siap sudah mengirim notif BATAL-nya sendiri),
                # tapi dilanjutkan retry di BACKGROUND (tidak menahan laporan lain
                # di slot ini) — kalau nanti GP baru pulih (mis. baru sempat login
                # manual sejam kemudian), laporan ini tetap otomatis terkirim.
                context.application.create_task(
                    _retry_laporan_background(context, nama, args, label, topic, thread_id),
                    name=f"retry-bg-{label}",
                )
                error_terakhir = "DB / GlobalProtect tidak terjangkau"
                break

            logger.info(f"[JADWAL:{label}] Mulai (percobaan {percobaan}/{JADWAL_MAKS_PERCOBAAN}) "
                        f"— args={args or '(tanpa tanggal)'}")
            status = _StatusLaporan()
            try:
                # salin_ke=GROUP_ID: laporan terjadwal juga masuk grup koordinasi
                # supaya semua laporan bisa dipantau di satu tempat.
                tujuan_chat, tujuan_thread, salin = _tujuan_terjadwal(thread_id)
                # Cek apakah laporan / slot ini ditandai untuk dikirim ke WhatsApp
                kirim_wa = bool(slot.get("wa") or getattr(getattr(handler, "__self__", None), "send_wa", False) or (nama in ("liveupdate", "closingsql", "agresif")))
                bot_topic = _BotKeTopic(context.bot, tujuan_chat, tujuan_thread,
                                        salin_ke=salin, status=status, kirim_ke_wa=kirim_wa)
                pesan     = _PesanKeTopic(bot_topic, tujuan_chat, tujuan_thread, label)
                # Penangkal timeout: kalau laporan menggantung (mis. query nyangkut
                # karena VPN setengah putus), batalkan setelah REPORT_TIMEOUT_MENIT
                # menit supaya slot tidak macet selamanya dan laporan sisa tetap jalan.
                await asyncio.wait_for(
                    handler(_UpdateKeTopic(pesan), SimpleNamespace(args=args, bot=bot_topic)),
                    timeout=REPORT_TIMEOUT_MENIT * 60,
                )
            except asyncio.TimeoutError:
                error_terakhir = f"TIMEOUT melebihi {REPORT_TIMEOUT_MENIT} menit"
                logger.error(f"[JADWAL:{label}] TIMEOUT — melebihi {REPORT_TIMEOUT_MENIT} menit, dibatalkan")
                try:
                    await context.bot.send_message(
                        chat_id=GROUP_ID,
                        text=(f"⏱️ Laporan terjadwal /{nama} ({topic}) dibatalkan — "
                              f"melebihi {REPORT_TIMEOUT_MENIT} menit (kemungkinan query "
                              f"nyangkut karena DB/VPN). Jalankan manual setelah koneksi stabil.")
                    )
                except Exception:
                    logger.exception(f"[JADWAL:{label}] Notifikasi timeout tidak terkirim")
            except Exception as e:
                error_terakhir = str(e)
                logger.exception(f"[JADWAL:{label}] GAGAL (percobaan {percobaan})")

            # Laporan sudah mengeluarkan output → dianggap SELESAI. Tidak diulang
            # walau ada error menyusul, supaya laporan tidak pernah terkirim dobel.
            if status.media_terkirim > 0:
                laporan_sukses = True
                media_count = status.media_terkirim
                logger.info(f"[JADWAL:{label}] Selesai")
                break

            # Tidak ada output. Kalau DB masih hidup, kegagalannya BUKAN karena GP
            # (mis. data kosong / format salah) — handler sudah melapor sendiri,
            # tidak perlu diulang. Laporan _LAPORAN_TANPA_DB juga dianggap begini
            # LANGSUNG (gagalnya bukan krn DB/GP, cek db.port_terbuka tidak relevan).
            if nama in _LAPORAN_TANPA_DB or await asyncio.to_thread(db.port_terbuka):
                logger.warning(f"[JADWAL:{label}] Tidak menghasilkan output tapi DB hidup "
                               f"— kegagalan non-DB, tidak diulang")
                break

            # DB mati + belum ada output → kemungkinan besar GP putus di tengah query.
            if percobaan >= JADWAL_MAKS_PERCOBAAN:
                logger.error(f"[JADWAL:{label}] Menyerah setelah {JADWAL_MAKS_PERCOBAAN}x — DB tetap putus")
                try:
                    await context.bot.send_message(
                        chat_id=GROUP_ID,
                        text=(f"❌ Laporan terjadwal /{nama} ({topic}) tetap gagal setelah "
                              f"{JADWAL_MAKS_PERCOBAAN}x — database putus di tengah query. "
                              f"Jalankan manual setelah GP/GlobalProtect stabil.")
                    )
                except Exception:
                    logger.exception(f"[JADWAL:{label}] Notifikasi gagal final tidak terkirim")
                break

            logger.warning(f"[JADWAL:{label}] DB putus di tengah query — tunggu GP pulih "
                           f"lalu ulang (percobaan {percobaan}/{JADWAL_MAKS_PERCOBAAN})")
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=(f"🔄 Laporan terjadwal /{nama} ({topic}) terhenti — GP/GlobalProtect "
                          f"putus di tengah query. Menunggu koneksi pulih lalu diulang "
                          f"otomatis (percobaan {percobaan + 1}/{JADWAL_MAKS_PERCOBAAN}).")
                )
            except Exception:
                logger.exception(f"[JADWAL:{label}] Notifikasi retry tidak terkirim")
            # Lanjut iterasi → _tunggu_db_siap di atas akan menunggu GP pulih.

        status_str = "SUCCESS" if laporan_sukses else "FAILED"
        scheduler_db.record_log_finish(log_id, status=status_str, media_terkirim=media_count, error_message=error_terakhir)


def _is_stock_ont_report(msg) -> bool:
    """True kalau msg adalah PDF "Stock_ONT_Report*.pdf" (Stock Paradise) —
    satu-satunya jenis file yang boleh lolos dari chat BLOCKED (lihat
    _tolak_chat_diblokir), supaya bisa dibacakan otomatis jadi Stock Alert.

    Di-gate lewat STOCK_ALERT_ENABLED (config.py) — selama fitur di-HOLD,
    fungsi ini selalu False sehingga _tolak_chat_diblokir & handle_file
    kembali ke perilaku lama (chat blocked tetap diblokir total, PDF ini
    diperlakukan seperti file tak dikenal biasa)."""
    if not STOCK_ALERT_ENABLED:
        return False
    doc = msg.document if msg else None
    if not doc:
        return False
    fname = (doc.file_name or "").lower()
    return fname.startswith("stock_ont_report") and fname.endswith(".pdf")


async def _tolak_chat_diblokir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Buang total update dari chat di BLOCKED_CHAT_IDS — bot tidak boleh menanggapi
    APA PUN di sana (perintah, upload file, pesan biasa).

    Sengaja TIDAK membalas apa-apa (bahkan penolakan), karena membalas pun sudah
    termasuk "menanggapi". Cukup dicatat di log supaya tetap ketahuan kalau ada
    yang mencoba pakai bot dari grup itu.

    SATU pengecualian: PDF "Stock_ONT_Report*.pdf" yang diupload persis di topic
    STOCK_ALERT_TOPIC_ID (Partnership) — dibiarkan lanjut ke handle_file supaya
    otomatis dibacakan jadi Stock Alert (_proses_stock_ont_alert). Topic/file
    lain di chat ini tetap diblokir total seperti biasa.
    """
    chat = update.effective_chat
    if chat and chat.id in BLOCKED_CHAT_IDS:
        msg = update.effective_message
        thread_id = getattr(msg, "message_thread_id", None) if msg else None
        if thread_id == STOCK_ALERT_TOPIC_ID and _is_stock_ont_report(msg):
            logger.info(f"[BLOKIR] Pengecualian: Stock ONT Report dari chat {chat.id} "
                        f"topic {thread_id} diproses (bukan diabaikan)")
            return
        isi = ""
        if msg:
            if msg.text:
                isi = f" | teks: {msg.text[:60]!r}"
            elif msg.document:
                isi = f" | file: {msg.document.file_name!r}"
        logger.info(f"[BLOKIR] Update dari chat {chat.id} diabaikan{isi}")
        raise ApplicationHandlerStop


async def _blokir_perintah_di_topic(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Abaikan TOTAL perintah manual (/...) yang diketik DARI DALAM sebuah topic
    di grup forum — bot cuma boleh dijalankan dari chat requester (japri) atau
    grup koordinasi (permintaan user 27-Aug-2026). Sengaja TIDAK membalas
    apa pun (bahkan penolakan), cukup dicatat di log — sama pola dengan
    _tolak_chat_diblokir.

    `is_topic_message` HANYA True untuk pesan di topic forum non-"General"
    (pesan di General, grup biasa, atau chat pribadi → False), jadi command
    di grup koordinasi / japri tetap jalan normal. Laporan TERJADWAL tidak
    lewat sini (di-trigger job_queue, bukan Update dari pesan masuk).

    Dipasang di group=-2 (setelah _tolak_chat_diblokir). ApplicationHandlerStop
    mencegah CommandHandler di group 0 ikut jalan.
    """
    msg = update.effective_message
    if not msg or not msg.text or not msg.text.startswith("/"):
        return
    if not getattr(msg, "is_topic_message", False):
        return
    logger.info(f"[BLOKIR-TOPIC] Perintah {msg.text[:40]!r} dari chat {msg.chat_id} "
                f"topic {getattr(msg, 'message_thread_id', None)} diabaikan")
    raise ApplicationHandlerStop


# ── Main ──────────────────────────────────────────────────────────────────────
class _RetryRequest(HTTPXRequest):
    """
    HTTPXRequest yang mengulang HANYA error jaringan yang dijamin tidak bikin
    laporan dobel.

    Prinsipnya: cuma retry kalau kegagalan terjadi SEBELUM/SAAT request dikirim
    (ConnectError, WriteError, PoolTimeout, dst) — di titik itu Telegram pasti
    belum memproses apa-apa, jadi mengulang aman & tidak mungkin menggandakan.

    Error saat MEMBACA BALASAN (httpx.ReadError, ReadTimeout, RemoteProtocol,
    CloseError) SENGAJA TIDAK diulang: pada error jenis ini request bisa jadi
    sudah diterima Telegram, cuma balasannya yang gagal sampai — kalau diulang,
    laporannya berpotensi muncul dua kali. Error jenis ini dibiarkan naik ke
    handler dan memicu notifikasi "gagal" (bisa dikirim ulang manual), demi
    jaminan TIDAK PERNAH DOBEL.
    """

    # httpx pra-kirim yang aman diulang (tidak mungkin sudah diproses server).
    _AMAN_RETRY = (
        httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout,
        httpx.WriteError, httpx.WriteTimeout, httpx.LocalProtocolError,
    )
    _MAKS   = 5      # total percobaan (jeda 2+4+6+8 = 20 dtk: cukup utk putus koneksi sesaat)
    _JEDA_S = 2.0    # jeda dasar (dikali nomor percobaan)

    @classmethod
    def _aman_diulang(cls, e: BaseException) -> bool:
        """
        PTB 22 (HTTPXRequest.do_request) SUDAH membungkus error httpx menjadi telegram.error.NetworkError /
        TimedOut (`raise ... from err`), jadi `except httpx.ConnectError` langsung tidak pernah kena —
        sebelum 09-11-2026 retry ini praktis tidak jalan (error "httpx.ConnectError: All connection attempts
        failed" langsung menggagalkan laporan). Yang diperiksa sekarang rantai __cause__/__context__:
          - error httpx pertama di rantai harus termasuk _AMAN_RETRY (pra-kirim);
          - ssl.SSLError mentah berisi "ALERT" (mis. "sslv3 alert bad record mac") = server MENOLAK record
            TLS kita, jadi request tidak diproses -> aman diulang dengan koneksi baru. PTB melaporkannya
            sebagai "Unknown error in HTTP implementation: SSLError(...)".
        """
        import ssl
        c, n = e, 0
        while c is not None and n < 6:
            if isinstance(c, httpx.HTTPError):
                return isinstance(c, cls._AMAN_RETRY)
            if isinstance(c, ssl.SSLError):
                return "ALERT" in str(c).upper()
            c, n = (c.__cause__ or c.__context__), n + 1
        return False

    async def do_request(self, *args, **kwargs):
        import ssl
        from telegram.error import NetworkError
        for percobaan in range(1, self._MAKS + 1):
            try:
                return await super().do_request(*args, **kwargs)
            except (NetworkError, ssl.SSLError, *self._AMAN_RETRY) as e:   # TimedOut turunan NetworkError
                if not self._aman_diulang(e):
                    raise
                if percobaan >= self._MAKS:
                    logger.warning(f"[HTTP] menyerah setelah {self._MAKS}x: {type(e).__name__}: {e}")
                    raise
                logger.warning(
                    f"[HTTP] error pra-kirim {type(e).__name__}: {e} — retry "
                    f"{percobaan}/{self._MAKS - 1} (aman, tidak akan dobel)"
                )
                await asyncio.sleep(self._JEDA_S * percobaan)


# ── Kunci satu-instance (per MESIN) ─────────────────────────────────────────────
# Mencegah bot dijalankan dua kali di komputer yang SAMA (mis. lupa sudah ada
# yang jalan, lalu dobel-klik / buka terminal baru). Pakai file-lock eksklusif
# yang ditahan selama proses hidup; kalau lock gagal diambil, berarti sudah ada
# instance lain di mesin ini -> proses baru langsung berhenti.
#
# CATATAN: lock ini per-mesin, jadi TIDAK mendeteksi bentrok lintas mesin
# (mis. lokal vs server). Bentrok lintas mesin ditangani _error_handler
# (Conflict) di bawah, dibantu PRIMARY_HOST.
_lock_handle = None


def _acquire_single_instance_lock() -> bool:
    """True kalau lock berhasil diambil (aman lanjut); False kalau sudah ada
    instance lain di mesin ini."""
    global _lock_handle
    lock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, "bot.lock")
    try:
        _lock_handle = open(lock_path, "a+")
        if os.name == "nt":
            import msvcrt
            _lock_handle.seek(0)
            msvcrt.locking(_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Rekam PID pemegang lock (informasional saja).
        _lock_handle.seek(0)
        _lock_handle.truncate()
        _lock_handle.write(str(os.getpid()))
        _lock_handle.flush()
        return True
    except OSError:
        return False


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Satu-satunya penampung error PTB. Tanpa ini, tiap error (termasuk Conflict)
    dicetak sebagai traceback panjang "No error handlers are registered".

    Khusus telegram.error.Conflict (dua instance pakai token yang sama, saling
    rebut getUpdates): kalau mesin ini BUKAN PRIMARY_HOST, instance ini mundur
    & berhenti sendiri supaya bot utama di server tidak ikut terganggu.
    """
    from telegram.error import Conflict

    err = context.error
    if isinstance(err, Conflict):
        host = socket.gethostname()
        logger.error(
            "[CONFLICT] Ada instance bot LAIN aktif dengan token yang sama "
            "(getUpdates bentrok) — kemungkinan bot masih jalan di mesin lain."
        )
        if PRIMARY_HOST and host.upper() != PRIMARY_HOST.upper():
            logger.error(
                f"[CONFLICT] Mesin ini ('{host}') bukan PRIMARY_HOST "
                f"('{PRIMARY_HOST}') -> instance ini MUNDUR & berhenti supaya "
                f"bot utama tidak terganggu."
            )
            context.application.stop_running()
        else:
            logger.error(
                f"[CONFLICT] Mesin ini ('{host}') dianggap utama "
                f"(PRIMARY_HOST='{PRIMARY_HOST}') -> tetap jalan. Pastikan "
                f"instance di mesin lain dimatikan."
            )
        return
    logger.error("Exception tak tertangani saat proses update:", exc_info=err)


# Handler /c3mrnewch — diisi di main() dari c3mrnewch.register_handlers() (return
# value-nya), dideklarasikan global di sini supaya _daftar_perintah_terjadwal()
# (fungsi terpisah, dipanggil scheduler) bisa merujuknya.
cmd_c3mrnewch = None
cmd_wireless_channel = None   # diisi di main() dari wireless_channel.register_handlers()
cmd_wireless2 = None          # diisi di main() dari commands.wireless2.register_handlers()
cmd_wirelesschannel2 = None   # idem
cmd_clockin_sf_teritory = cmd_homepass_raw = None   # diisi di main() dari commands.clockin_sf_teritory.register_handlers()
cmd_clockin_sf_all = None     # diisi di main() dari commands.clockin_sf_all.register_handlers()
cmd_ms = cmd_msbranch = None   # diisi di main() dari commands.market_share.register_handlers()
cmd_murmer = None             # diisi di main() dari murmer.register_handlers()
cmd_c3mrsvp = None            # diisi di main() dari commands.c3mrsvp.register_handlers()
cmd_nasional = None           # diisi di main() dari commands.nasional.register_handlers()
cmd_homepass = cmd_homepass_wok_old = None            # diisi di main() dari commands.homepass(_wok_old).register_handlers()
cmd_salahtagging = cmd_salahtagging_wok_old = None    # diisi di main() dari commands.salahtagging(_wok_old).register_handlers()


def main():
    global cmd_c3mrnewch, cmd_wireless_channel, cmd_wireless2, cmd_wirelesschannel2, cmd_murmer, cmd_c3mrsvp, cmd_nasional
    global cmd_homepass, cmd_homepass_wok_old, cmd_salahtagging, cmd_salahtagging_wok_old
    global cmd_clockin_sf_teritory, cmd_homepass_raw, cmd_clockin_sf_all
    global cmd_ms, cmd_msbranch
    if not _acquire_single_instance_lock():
        logger.error(
            "[INSTANCE] Bot SUDAH jalan di mesin ini (lock bot.lock terpakai). "
            "Proses baru dibatalkan supaya tidak bentrok / laporan dobel."
        )
        sys.exit(1)

    _load_target_state()
    _load_target_state()

    # Default timeout PTB (5 detik) terlalu pendek untuk kirim beberapa foto
    # laporan berurutan (termasuk forward ke GROUP_ID) -> sering TimedOut
    # walau laporannya sendiri sebenarnya sudah berhasil terkirim.
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        # concurrent_updates(True): tiap update (perintah) diproses di task-nya
        # sendiri, TIDAK berurutan. Jadi selagi laporan berat (mis. /c3mrnew yang
        # bisa ~1 jam) masih jalan, perintah lain tetap bisa masuk & jalan bareng
        # tanpa harus menunggu yang pertama selesai.
        #   • Aman untuk query DB: tiap query buka koneksi sendiri lalu ditutup
        #     (db.get_connection), tidak ada koneksi global yang dipakai bersama.
        #   • Laporan TERJADWAL tetap berurutan di dalam satu slot (lihat
        #     job_laporan_topic) supaya urutan pesan di topic tetap rapi — ini
        #     terpisah dari concurrency perintah manual.
        .concurrent_updates(True)
        # Naikkan pool koneksi HTTP ke Telegram supaya banyak perintah yang jalan
        # bersamaan tidak antre saat kirim foto/dokumen (default tadi 8).
        .request(_RetryRequest(connection_pool_size=32, connect_timeout=30,
                               read_timeout=60, write_timeout=60, pool_timeout=60))
        .get_updates_request(_RetryRequest(connect_timeout=30, read_timeout=60,
                                           write_timeout=60, pool_timeout=30))
        .post_init(post_init_sync_commands)
        .build()
    )

    # Penampung error global (termasuk penanganan Conflict lintas mesin).
    CommandRegistry.clear()
    CommandRegistry.install_app_hook(app)
    app.add_error_handler(_error_handler)

    # ── Filter chat yang diblokir ──────────────────────────────────────────
    # Dipasang di group=-3 supaya jalan PALING AWAL, sebelum handler apa pun.
    # ApplicationHandlerStop menghentikan pemrosesan update sepenuhnya, jadi
    # bot benar-benar bungkam di chat tsb: perintah, file, maupun pesan biasa.
    # (PTB: tiap GROUP menjalankan handler pertama yang match — makanya guard
    #  di bawah ini dipisah ke group tersendiri, bukan ditumpuk di group sama.)
    app.add_handler(TypeHandler(Update, _tolak_chat_diblokir), group=-3)

    # Tolak perintah manual yang diketik dari dalam topic forum (output tidak
    # boleh nyasar ke topic) — jalan setelah filter chat blokir, sebelum
    # command handler (group 0).
    app.add_handler(TypeHandler(Update, _blokir_perintah_di_topic), group=-2)

    # Command laporan ikut /modequery (rajawali/auto -> lewat Rajawali Dashboard). Group sendiri karena
    # tiap group hanya menjalankan 1 handler yang cocok; jalan setelah 2 penjaga di atas.
    app.add_handler(TypeHandler(Update, _cegat_mode_query), group=-1)

    # ── Daftarkan command handlers ─────────────────────────────────────────
    # Perintah RINGAN (langsung balas, tanpa query berat) — tidak perlu penangkal
    # timeout.
    TelegramCommand("start", cmd_start, use_timeout=False).register(app)
    TelegramCommand("menu", cmd_menu, use_timeout=False).register(app)
    TelegramCommand("status", cmd_status, use_timeout=False).register(app)
    TelegramCommand("modequery", cmd_modequery, use_timeout=False).register(app)
    TelegramCommand("rajawali", cmd_rajawali, use_timeout=False).register(app)
    TelegramCommand("dbstatus", cmd_dbstatus, use_timeout=False).register(app)
    TelegramCommand("dbinfo", cmd_dbinfo, use_timeout=False).register(app)
    TelegramCommand("target", cmd_target, use_timeout=False).register(app)
    TelegramCommand("gp", cmd_gp, use_timeout=False).register(app)

    # Perintah BERAT (query DB + render, bisa lama) — dibungkus penangkal timeout
    # (_dengan_batas_waktu). Kalau prosesnya nyangkut (mis. VPN/DB setengah
    # putus), dibatalkan otomatis setelah REPORT_TIMEOUT_MENIT menit dan pengguna
    # diberi kabar, bukan menggantung diam. Berkat concurrent_updates, perintah
    # ini juga bisa jalan bersamaan tanpa saling menunggu.
    _T = _dengan_batas_waktu
    TelegramCommand("closing", cmd_closing).register(app, timeout_wrapper=_T)
    TelegramCommand("closinghadoop", cmd_closing_hadoop).register(app, timeout_wrapper=_T)
    TelegramCommand("dailyreps", cmd_daily).register(app, timeout_wrapper=_T)
    TelegramCommand("closingdaily", cmd_closing_daily).register(app, timeout_wrapper=_T)
    TelegramCommand("liveupdate", cmd_liveupdate).register(app, timeout_wrapper=_T)
    TelegramCommand("liveupdateutoip", cmd_liveupdateutoip).register(app, timeout_wrapper=_T)
    TelegramCommand("liveupdatebk", cmd_liveupdatebk).register(app, timeout_wrapper=_T)
    TelegramCommand("dailyre", cmd_dailyre).register(app, timeout_wrapper=_T)
    TelegramCommand("closingsql", cmd_closing_sql).register(app, timeout_wrapper=_T)
    TelegramCommand("closingutoip", cmd_closing_utoip).register(app, timeout_wrapper=_T)
    TelegramCommand("closingbk", cmd_closingbk).register(app, timeout_wrapper=_T)
    TelegramCommand("djp", cmd_djp).register(app, timeout_wrapper=_T)
    TelegramCommand("djpcsv", cmd_djpcsv).register(app, timeout_wrapper=_T)
    TelegramCommand("mbcsv", cmd_mbcsv).register(app, timeout_wrapper=_T)
    TelegramCommand("c3mr", cmd_c3mr).register(app, timeout_wrapper=_T)
    TelegramCommand("c3mr10s", cmd_c3mr10s).register(app, timeout_wrapper=_T)
    TelegramCommand("c3mrnew", cmd_c3mrnew).register(app, timeout_wrapper=_T)
    TelegramCommand("payment", cmd_payment).register(app, timeout_wrapper=_T)
    TelegramCommand("caps", cmd_caps).register(app, timeout_wrapper=_T)
    TelegramCommand("pranpcall", cmd_pranpcall).register(app, timeout_wrapper=_T)
    TelegramCommand("pranpcagent", cmd_pranpcagent).register(app, timeout_wrapper=_T)
    TelegramCommand("moretensi", cmd_moretensi).register(app, timeout_wrapper=_T)
    TelegramCommand("pranpcsp", cmd_pranpcsp).register(app, timeout_wrapper=_T)
    TelegramCommand("pranpcprio", cmd_pranpcprio).register(app, timeout_wrapper=_T)
    TelegramCommand("dod", cmd_dod).register(app, timeout_wrapper=_T)
    TelegramCommand("agresif", cmd_agresif).register(app, timeout_wrapper=_T)
    TelegramCommand("wireless", cmd_wireless).register(app, timeout_wrapper=_T)
    TelegramCommand("djpprio", cmd_djpprio).register(app, timeout_wrapper=_T)
    TelegramCommand("promo", cmd_promo).register(app, timeout_wrapper=_T)
    TelegramCommand("pdd", cmd_pdd).register(app, timeout_wrapper=_T)
    TelegramCommand("addon", cmd_addon).register(app, timeout_wrapper=_T)
    TelegramCommand("klaim", cmd_klaim).register(app, timeout_wrapper=_T)
    TelegramCommand("sf", cmd_sf).register(app, timeout_wrapper=_T)
    cmd_5so, cmd_7so = sf_momentum.register_handlers(app, _T, _get_cutoff_tabel)

    TelegramCommand("performance", cmd_performance).register(app, timeout_wrapper=_T)
    TelegramCommand("childps", childps_bot.cmd_childps).register(app, timeout_wrapper=_T)
    TelegramCommand("leads", cmd_leads).register(app, timeout_wrapper=_T)
    app.add_handler(MessageHandler(filters.Document.ALL, _T(handle_file)))

    #command kirim ke wa
    whatsapp.register_handlers(app, _kirim_laporan_sql, _T)

    cmd_murmer = murmer.register_handlers(app, _T)

    cmd_kategori_paket_mod.register_handlers(app, _T, _kirim_foto_retry)

    # /ms + kirim otomatis 10:00 ke topic MARKET_SHARE (commands/market_share.py).
    # Tujuan ikut setelan JADWAL_KIRIM_KE_GRUP_REPORT lewat _tujuan_terjadwal.
    def _bot_ms(bot, thread_id):
        tujuan_chat, tujuan_thread, salin = _tujuan_terjadwal(thread_id)
        return _BotKeTopic(bot, tujuan_chat, tujuan_thread, salin_ke=salin)
    cmd_ms, cmd_msbranch = cmd_market_share_mod.register_handlers(
        app, _T, _kirim_foto_retry, _tunggu_db_siap, _bot_ms)

    async def _get_target_wireless():
        # Sama dgn /wireless: target hasil upload /target, fallback file lokal terbaru.
        if _target_wireless_df is not None:
            return _target_wireless_df
        return await asyncio.to_thread(_load_wireless_target_from_local_file)

    cmd_wireless2, cmd_wirelesschannel2 = cmd_wireless2_mod.register_handlers(
        app, _T, _get_target_wireless, _get_cutoff_raw, _kirim_foto_retry)

    cmd_clockin_sf_teritory, cmd_homepass_raw = cmd_clockin_mod.register_handlers(app, _T)
    cmd_clockin_sf_all = cmd_clockin_all_mod.register_handlers(app, _T)

    cmd_jadwal_mod.register_handlers(app, _T)

    cmd_reports_schedule_mod.register_handlers(app, _T)

    cmd_c3mrnewch = c3mrnewch.register_handlers(app, _T, _get_cutoff_tabel)

    cmd_c3mrsvp = cmd_c3mrsvp_mod.register_handlers(app, _T, _get_cutoff_tabel)

    cmd_nasional = cmd_nasional_mod.register_handlers(
        app, _T, _get_target_region, _get_cutoff_db, _kirim_foto_retry)

    cmd_homepass = cmd_homepass_mod.register_handlers(app, _T)
    cmd_homepass_wok_old = cmd_homepass_wok_old_mod.register_handlers(app, _T)

    cmd_salahtagging = cmd_salahtagging_mod.register_handlers(app, _T, _get_cutoff_tabel)
    cmd_salahtagging_wok_old = cmd_salahtagging_wok_old_mod.register_handlers(app, _T, _get_cutoff_tabel)

    cmd_wireless_channel = wireless_channel.register_handlers(
        app, _T, _get_cutoff_raw, _kirim_foto_retry)

    # ── Setup scheduler dinamis (SQLite backed) ────────────────────────────
    # Mengambil jadwal aktif dari SQLite (storage/state/scheduler.db).
    # Jadwal dapat diaktifkan/dinonaktifkan dan diubah tanpa koding & tanpa restart.
    scheduler_db.seed_initial_jobs(JADWAL_LAPORAN)
    # Sinkronisasi deklaratif: otomatis daftarkan jadwal dari class report baru (BaseReport.schedule) jika belum ada di database
    scheduler_db.sync_declared_report_schedules()

    from datetime import time as dtime, timezone, timedelta as td
    WIB_TZ = timezone(td(hours=7))  # WIB = UTC+7

    # PTB 22.x: days 0-6 = Minggu-Sabtu (BUKAN Senin-Minggu).
    HARI_KE_ANGKA = {
        "MINGGU": 0, "SENIN": 1, "SELASA": 2, "RABU": 3,
        "KAMIS": 4, "JUMAT": 5, "SABTU": 6,
    }

    def _sinkronisasi_scheduler(aplikasi) -> int:
        """Hapus job lama dan daftarkan ulang job aktif dari SQLite secara dinamis."""
        jq: JobQueue = aplikasi.job_queue
        if jq is None:
            return 0
        for j in jq.jobs():
            if (j.name or "").startswith("jadwal_"):
                j.schedule_removal()

        active_jobs = scheduler_db.get_all_jobs(only_active=True)
        for slot in active_jobs:
            jam, menit = slot["jam"], slot["menit"]
            topic      = slot["topic"]
            hari       = slot.get("hari")

            if topic not in TOPIC_IDS:
                logger.error(f"[SCHEDULER] Topic '{topic}' tidak ada di TOPIC_IDS — slot #{slot['id']} dilewati")
                continue

            if hari is None:
                days = tuple(range(7))
                label_hari = "tiap hari"
            else:
                if hari.upper() not in HARI_KE_ANGKA:
                    logger.error(f"[SCHEDULER] Hari '{hari}' tidak dikenal — slot #{slot['id']} dilewati")
                    continue
                days = (HARI_KE_ANGKA[hari.upper()],)
                label_hari = f"tiap {hari.capitalize()}"

            daftar = ", ".join(f"/{n}" + (f" H-{o}" if o else "") for n, o in slot["laporan"])
            jq.run_daily(
                job_laporan_topic,
                time=dtime(jam, menit, 0, tzinfo=WIB_TZ),
                days=days,
                data=slot,
                name=f"jadwal_{topic}_{jam:02d}{menit:02d}_{slot['id']}",
                job_kwargs={
                    "misfire_grace_time": JADWAL_MISFIRE_GRACE_S,
                    "coalesce": True,
                },
            )
            logger.info(f"[SCHEDULER] #{slot['id']} {jam:02d}:{menit:02d} WIB {label_hari} -> topic {topic}: {daftar}")

        logger.info(f"[SCHEDULER] Total {len(active_jobs)} slot jadwal aktif terdaftar ke grup {REPORT_GROUP_ID}")
        return len(active_jobs)

    async def _trigger_job_manual(ctx, slot_data, triggered_by="MANUAL"):
        """Eksekutor manual ketika user mengetik /jobs_run <id>."""
        dummy_slot = dict(slot_data)
        dummy_slot["_triggered_by"] = triggered_by
        dummy_job = SimpleNamespace(data=dummy_slot)
        dummy_ctx = SimpleNamespace(bot=ctx.bot, application=ctx.application, job=dummy_job)
        await job_laporan_topic(dummy_ctx)

    # Daftarkan perintah manajemen jadwal SQLite (/jobs, /jobs_toggle, /jobs_edit, /jobs_run, /jobs_logs)
    cmd_jobs_manager_mod.register_handlers(
        app,
        _T,
        reload_jobs_fn=_sinkronisasi_scheduler,
        trigger_job_fn=_trigger_job_manual,
    )

    sync_commands_to_db()
    _sinkronisasi_scheduler(app)
    logger.info("Bot Monitoring RE Jateng-DIY aktif (+ SQLite dynamic scheduler)")
    app.run_polling()


if __name__ == "__main__":
    main()
