"""
whatsapp/senders.py — Logika inti "hasilkan laporan lalu kirim ke WhatsApp".

Dipakai bersama oleh command manual (commands.py) dan job terjadwal (scheduler.py).
Tiap fungsi mengembalikan jumlah pesan/media terkirim, dan raise Exception kalau gagal.

/liveupdate & /closingsql memakai _kirim_laporan_sql milik bot.py (diberikan sebagai
parameter, bukan diimpor, supaya tidak ada impor melingkar ke bot.py) sehingga format
laporan selalu sama dengan versi Telegram. /agresif memakai versi LITE (2 gambar).
"""

import asyncio
import glob
import logging
import os
import pickle
from datetime import date, datetime
from io import BytesIO

import pandas as pd

import db
from .adapter import WahaBotAdapter
from .client import get_waha_client

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _lewat_rajawali(nama: str) -> bool:
    """Ikut /modequery (mode_query.py): True bila laporan ini harus diambil lewat Rajawali Dashboard."""
    import mode_query
    m = mode_query.ambil()
    if m == "langsung" or nama not in mode_query.DIDUKUNG_RAJAWALI:
        return False
    db_ok = m == "auto" and await asyncio.to_thread(db.port_terbuka)
    return mode_query.pakai_rajawali(db_ok)


async def _rajawali_ke_wa(nama: str, tgl: date, target_chat_id: str, send_images: bool,
                          png_sebagai_gambar: bool = False) -> int:
    """Buat laporan lewat rajawali_auto.py (dry-run, handler bot yang sama) lalu kirim hasilnya ke WhatsApp
    lewat WahaBotAdapter dengan urutan, caption & dokumen yang sama (urutan.json)."""
    import json
    import sys
    import tempfile
    dl_dir = os.path.join(_BASE, "storage", "downloads")
    os.makedirs(dl_dir, exist_ok=True)
    out = tempfile.mkdtemp(prefix=f"wa_{nama}_", dir=dl_dir)
    cmd = [sys.executable, os.path.join(_BASE, "utils", "rajawali_auto.py"), "--tanggal", tgl.strftime("%d-%m-%Y"),
           "--only", nama, "--pakai-ada", "--tanpa-blok", "--out-dir", out]
    logger.info(f"[WA/{nama}] Mode query -> lewat Rajawali Dashboard ({tgl:%d-%m-%Y})")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        keluaran, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError("Otomasi Rajawali melebihi 60 menit")
    teks = keluaran.decode("utf-8", "replace")
    import mode_query
    if not mode_query.runner_berhasil(proc.returncode, teks):
        ringkas = "\n".join(b for b in teks.splitlines() if b.startswith("[") or "GAGAL" in b)
        ringkas = ringkas or teks.strip()       # mis. "can't open file ..." (tanpa baris log runner)
        raise RuntimeError(f"Lewat Rajawali Dashboard gagal:\n{ringkas[-600:]}")
    daftar = glob.glob(os.path.join(out, "*", "urutan.json"))
    if not daftar:
        raise RuntimeError("Hasil Rajawali tidak ditemukan (urutan.json)")
    folder = os.path.dirname(daftar[0])
    adapter = WahaBotAdapter(get_waha_client(), target_chat_id, send_images=send_images)
    for item in json.load(open(daftar[0], encoding="utf-8")):
        if item["jenis"] == "message":
            await adapter.send_message(chat_id=0, text=item["teks"])
            continue
        if not item["file"]:
            continue
        isi = BytesIO(open(os.path.join(folder, item["file"]), "rb").read())
        isi.filename = item["file"].split("_", 1)[1]          # buang nomor urut "NN_"
        if item["jenis"] == "photo" or (png_sebagai_gambar and item["file"].lower().endswith(".png")):
            await adapter.send_photo(chat_id=0, photo=isi, caption=item["caption"])
        else:
            await adapter.send_document(chat_id=0, document=isi, caption=item["caption"])
    import shutil
    shutil.rmtree(out, ignore_errors=True)       # folder hasil sementara (sudah terkirim)
    return adapter.sent_count


def load_agresif_targets() -> tuple:
    """Muat target kecamatan & FMC city dari saved_target.pkl atau template Excel terbaru."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_state_file = os.path.join(base_dir, "storage", "state", "saved_target.pkl")
    df_kec = df_fmc = None

    if os.path.exists(target_state_file):
        try:
            with open(target_state_file, "rb") as f:
                state = pickle.load(f)
                if isinstance(state, dict):
                    df_kec = state.get("target_agresif_kec_df")
                    df_fmc = state.get("target_fmc_city_df")
        except Exception as e:
            logger.warning(f"[WAHA] Gagal baca saved_target.pkl: {e}")

    if df_kec is None or df_fmc is None:
        files = glob.glob(os.path.join(base_dir, "storage", "state", "targets", "template_target_2026_bot*.xlsx"))
        files += glob.glob(os.path.join(base_dir, "template_target_2026_bot*.xlsx"))
        if files:
            latest = max(files, key=os.path.getmtime)
            try:
                if df_kec is None:
                    d = pd.read_excel(latest, sheet_name="TARGET_KEC AGRESIF")
                    d.columns = d.columns.str.strip().str.upper()
                    if {"BULAN", "CITY", "KEC", "TARGET_PS_LOW", "TARGET_PS_MIDHIGH"} <= set(d.columns):
                        df_kec = d
            except Exception as e:
                logger.warning(f"[WAHA] Gagal baca TARGET_KEC AGRESIF dari {latest}: {e}")
            try:
                if df_fmc is None:
                    d = pd.read_excel(latest, sheet_name="TARGET_CITY FMC")
                    d.columns = d.columns.str.strip().str.upper()
                    if {"BULAN", "CITY", "TARGET_PS_LOW", "TARGET_PS_MIDHIGH"} <= set(d.columns):
                        df_fmc = d
            except Exception as e:
                logger.warning(f"[WAHA] Gagal baca TARGET_CITY FMC dari {latest}: {e}")

    return df_kec, df_fmc


async def core_liveupdate_wa(kirim_laporan_sql_func, target_chat_id: str, send_images: bool) -> int:
    """Logika inti /liveupdate_wa, dipakai command manual maupun job terjadwal.
    Return jumlah pesan/media terkirim; raise Exception kalau gagal."""
    if await _lewat_rajawali("liveupdate"):
        return await _rajawali_ke_wa("liveupdate", date.today(), target_chat_id, send_images)
    waha_client = get_waha_client()
    adapter = WahaBotAdapter(waha_client, target_chat_id, send_images=send_images)
    upload_time = datetime.now()
    await kirim_laporan_sql_func(
        adapter, 0, upload_time, mode="hourly",
        reply_msg=None, data_source="db"
    )
    return adapter.sent_count


async def core_closingsql_wa(kirim_laporan_sql_func, tgl_closing: date,
                              target_chat_id: str, send_images: bool) -> int:
    """Logika inti /closingsql_wa, dipakai command manual maupun job terjadwal.
    Raise RuntimeError kalau data tanggal itu belum tersedia di DB."""
    if await _lewat_rajawali("closingsql"):
        return await _rajawali_ke_wa("closingsql", tgl_closing, target_chat_id, send_images)
    tanggal_tersedia = await asyncio.to_thread(db.query_tanggal_tersedia, tgl_closing)
    if tgl_closing not in tanggal_tersedia:
        tgl_str = ", ".join(t.strftime("%d-%m-%Y") for t in sorted(tanggal_tersedia)[-5:])
        raise RuntimeError(
            f"Data tanggal {tgl_closing.strftime('%d-%m-%Y')} belum tersedia di database. "
            f"Tanggal tersedia (5 terakhir): {tgl_str}"
        )

    waha_client = get_waha_client()
    adapter = WahaBotAdapter(waha_client, target_chat_id, send_images=send_images)
    upload_time = datetime.now()
    await kirim_laporan_sql_func(
        adapter, 0, upload_time, mode="closing",
        tgl_closing=tgl_closing, reply_msg=None, data_source="db"
    )
    return adapter.sent_count


async def core_agresif_wa(tgl: date, target_chat_id: str, send_images: bool) -> int:
    """Logika inti /agresif_wa versi LITE (sama dengan cmd_agresif di bot.py):
    2 gambar (Lokasi Agresif + All FMC City), tanpa xlsx/raw csv.
    Return jumlah pesan/media terkirim; raise Exception kalau gagal."""
    if await _lewat_rajawali("agresif"):
        # /agresif_wa asli mengirim 2 PNG sebagai gambar (bukan dokumen seperti versi Telegram)
        return await _rajawali_ke_wa("agresif", tgl, target_chat_id, send_images, png_sebagai_gambar=True)
    import agresif_data
    import agresif_native
    import agresif_lite
    import calculator_agresif
    import renderer_agresif_lite

    df_kec, df_fmc = await asyncio.to_thread(load_agresif_targets)

    def _compute():
        df_raw = agresif_data.build_raw(tgl)
        if df_raw.empty:
            raise RuntimeError(
                "Data RAW kosong untuk cutoff ini — cek koneksi DB/VPN "
                "atau apakah tabel indihome_ordering_detail bulan terkait ada isinya."
            )
        df_calc = agresif_native.prepare_calc_df(df_raw)
        last_update_max = pd.to_datetime(df_raw["last_update"], errors="coerce").max()
        cutoff_str = last_update_max.strftime("%d-%m-%Y %H:%M") if pd.notna(last_update_max) else None

        r_lok = agresif_lite.hitung_lite_lokasi(tgl, df_calc, df_kec)
        r_fmc = agresif_lite.hitung_lite_fmc(tgl, df_calc, df_fmc)

        # Caption dari kalkulator PENUH (butuh %-metric & ranking), sama seperti Telegram.
        r_ps_full  = calculator_agresif.hitung_agresif_ps(tgl, df_calc, df_kec)
        r_fmc_full = calculator_agresif.hitung_agresif_fmc(tgl, df_calc, df_fmc)
        cap_lok, cap_fmc = agresif_lite.build_lite_captions(tgl, r_ps_full, r_fmc_full)
        return cutoff_str, r_lok, r_fmc, cap_lok, cap_fmc

    cutoff_str, r_lok, r_fmc, caption1, caption2 = await asyncio.to_thread(_compute)

    # Render PNG — sinkron sesuai invariant matplotlib
    png1_buf = renderer_agresif_lite.render_lite_lokasi(r_lok, cutoff=cutoff_str)
    png2_buf = renderer_agresif_lite.render_lite_fmc(r_fmc, cutoff=cutoff_str)

    out_suffix = tgl.strftime("%d%m%Y")
    laporan = [
        (png1_buf, caption1, f"01_NEW_SALES_LOKASI_AGRESIF_{out_suffix}.png"),
        (png2_buf, caption2, f"02_NEW_SALES_ALL_FMC_CITY_{out_suffix}.png"),
    ]

    waha_client = get_waha_client()
    terkirim = 0
    for buf, cap, fname in laporan:
        if send_images:
            await asyncio.to_thread(
                waha_client.send_image, target_chat_id, buf.getvalue(), fname, caption=cap
            )
        else:
            await asyncio.to_thread(waha_client.send_text, target_chat_id, cap)
        terkirim += 1
    return terkirim
