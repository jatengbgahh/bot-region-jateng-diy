"""
commands/jadwal.py — Handler Telegram /jadwal: daftar jadwal laporan otomatis yang AKTIF.

Sumbernya job_queue yang benar-benar terdaftar di bot yang sedang jalan (bukan
baca config), jadi yang tampil = yang memang akan dikirim. Ada dua jenis job:
  • jadwal_<TOPIC>_<HHMM>   → Telegram per-topic (dari config.JADWAL_LAPORAN)
  • jadwal_wa_<nama>_<HHMM> → WhatsApp via WAHA (dari config.JADWAL_LAPORAN_WA)
"""

import html
import logging
from datetime import datetime, timedelta, timezone

from telegram.constants import ParseMode
from telegram.ext import CommandHandler

logger = logging.getLogger(__name__)

_WIB_TZ = timezone(timedelta(hours=7))

# Nama perintah terjadwal -> report yang dikirim. Ubah di sini kalau isi report berubah.
REPORT_PER_PERINTAH = {
    "liveupdate": ["Monitoring RE (hourly)", "Monitoring RE PS (hourly)"],
    "closingsql": [
        "Monitoring RE Closing", "Daily RE PS (WoW, MoM)",
        "Daily Performance by WOK", "Daily Performance by City (file)",
        "Raw Data CSV (ZIP)", "IO RE PS by Channel",
        "Sales by Kategori Promo Paket",
    ],
    "dod": ["PS Harian (count) per Branch/WOK", "%DoD PS per Branch/WOK"],
    "dailyre": ["Monitoring Daily RE (target base vs realisasi)"],
    "nasional": ["Performance Nasional per Region (IO/RE/PS, Revenue, ARPU, Target)"],
    "agresif": ["New Sales Lokasi Agresif", "New Sales All FMC City"],
    "wireless": ["Performance MtD EZNet Wireless per WOK/Branch"],
    "wirelesschannel": ["PS EZNet Wireless by Channel"],
    "wireless2": ["Performance MtD EZNet Wireless per WOK/Branch (tanpa Murmer)"],
    "wirelesschannel2": ["PS EZNet Wireless by Channel (tanpa Murmer)"],
    "5so": ["5SO Scorecard Jateng-DIY (SF Momentum basis PS)"],
    "7so": ["7SO Scorecard Jateng-DIY (SF Momentum basis RE)", "SF Belum RE MTD (Excel, termasuk yang belum RE M1)",
            "5SO 7SO per SF + RAW (Excel, dengan Team Leader)"],
    "clockin_sf_all": ["Report Clock-In SF All Category (gambar + caption)", "Excel Clock-In SF All Category"],
    "murmer": ["EZNET Wireless Murmer (Daily/MTD/YTD per Region, %Ach YTD; Senin + data raw JATENG-DIY)"],
    "addon": ["Addon FTTR / IP Camera / Mesh Wifi per Branch/WOK"],
    "pdd": ["PDD per Branch/WOK (SF Active, TRX & Kontribusi per Channel)"],
    "childps": ["Child per PS Telkomsel One by WOK (MtD vs bulan lalu)"],
    "caps": ["CAPS per LOS", "CAPS per Customer Segment", "CAPS by Channel", "CAPS by Reason"],
    "c3mr": ["C3MR IndiHome Jateng-DIY per WOK", "C3MR IndiHome Jateng-DIY per City", "C3MR per LOS Group"],
    "c3mrnew": ["C3MR New Sales per BILL (BILL-1 s/d BILL-6)"],
    "c3mrnewch": ["C3MR LoS 0-6 Bulan (Total + BILL-1 s/d BILL-6)"],
    "c3mr10s": ["C3MR per Customer Segment"],
    "c3mrsvp": ["C3MR Fokus SVP (Pelanggan LOS <=24 Bulan) per WOK",
                "C3MR Fokus SVP (Pelanggan LOS <=24 Bulan) per City"],
    "homepass": ["Homepass Report per WOK/Branch"],
    "salahtagging": ["Monitoring RE Fallout Salah Tagging/Salah Homepass"],
    "homepass_wok_old": ["Homepass Report per WOK/Branch (WOK Lama)"],
    "salahtagging_wok_old": ["Monitoring RE Fallout Salah Tagging/Salah Homepass (WOK Lama)"],
    "klaim": ["Rekap Data Pelanggan Klaim per Nama Program"],
    "leads": ["Progress Caring Leads IO"],
    "ms": ["Market Share Per Branch Jateng-DIY", "Market Share Per City Jateng-DIY",
           "Market Share MOM Growth Per City Jateng-DIY"],
    "promo": ["PS Paket One Dynamic (Branch + WOK + City)"],
}


def _fmt_perintah(nama, offset):
    return f"/{nama}" + (f" (data H-{offset})" if offset else "")


def _fmt_baris_report(nama):
    reports = REPORT_PER_PERINTAH.get(nama)
    if not reports:
        return "      ↳ (isi report belum didaftarkan)"
    return "\n".join(f"      ↳ {html.escape(r)}" for r in reports)


def _kumpulkan_jadwal(job_queue):
    """Return (slot_telegram, slot_wa): dua list dict {jam, menit, hari, ...}."""
    tele, wa = [], []
    for job in job_queue.jobs():
        data = job.data
        if not isinstance(data, dict) or not (job.name or "").startswith("jadwal_"):
            continue
        if "target_chat_id" in data:  # job WA
            try:
                hhmm = job.name.rsplit("_", 1)[1]
                jam, menit = int(hhmm[:2]), int(hhmm[2:])
            except (IndexError, ValueError):
                continue
            wa.append({"jam": jam, "menit": menit, "laporan": data["laporan"],
                       "offset": data.get("offset_hari"), "next_t": job.next_t})
        elif "topic" in data:  # job Telegram per-topic
            tele.append({"jam": data["jam"], "menit": data["menit"], "hari": data.get("hari"),
                         "topic": data["topic"], "laporan": data["laporan"],
                         "next_t": job.next_t})
    return tele, wa


def _fmt_next(next_t):
    if not next_t:
        return "-"
    return next_t.astimezone(_WIB_TZ).strftime("%a %d-%m %H:%M")


def _bangun_teks(tele, wa):
    baris = ["📅 <b>Jadwal Laporan Aktif</b> (WIB)"]

    if not tele and not wa:
        return "\n".join(baris + ["", "⚠️ Tidak ada jadwal yang aktif."])

    # ── Telegram per topic ──────────────────────────────────────────────
    topics = []
    for s in tele:
        if s["topic"] not in topics:
            topics.append(s["topic"])
    for topic in topics:
        baris += ["", f"━━━━━━━━━━━━━━━━━━", f"📌 <b>Topic {html.escape(topic)}</b>"]
        slots = sorted((s for s in tele if s["topic"] == topic),
                       key=lambda s: (s["jam"], s["menit"]))
        for s in slots:
            hari = "tiap hari" if s["hari"] is None else f"tiap {s['hari'].capitalize()}"
            baris.append(f"\n⏰ <b>{s['jam']:02d}:{s['menit']:02d}</b> — {hari}")
            for nama, offset in s["laporan"]:
                wa_badge = " 🟢<i>+WA</i>" if (s.get("wa") or nama in ("liveupdate", "closingsql", "agresif")) else ""
                baris.append(f"   • <code>{html.escape(_fmt_perintah(nama, offset))}</code>{wa_badge}")
                baris.append(_fmt_baris_report(nama))

    # ── WhatsApp ────────────────────────────────────────────────────────
    if wa:
        baris += ["", "━━━━━━━━━━━━━━━━━━", "💬 <b>WhatsApp (WAHA)</b>"]
        for s in sorted(wa, key=lambda s: (s["jam"], s["menit"])):
            baris.append(f"\n⏰ <b>{s['jam']:02d}:{s['menit']:02d}</b> — tiap hari")
            baris.append(f"   • <code>{html.escape(_fmt_perintah(s['laporan'], s['offset']))}_wa</code>")
            baris.append(_fmt_baris_report(s["laporan"]))

    # ── Berikutnya ──────────────────────────────────────────────────────
    semua = [(s["next_t"], f"{s['jam']:02d}:{s['menit']:02d} topic {s['topic']}") for s in tele if s["next_t"]]
    semua += [(s["next_t"], f"{s['jam']:02d}:{s['menit']:02d} WhatsApp") for s in wa if s["next_t"]]
    if semua:
        t, ket = min(semua, key=lambda x: x[0])
        baris += ["", f"⏭ Jadwal berikutnya: <b>{_fmt_next(t)}</b> ({html.escape(ket)})"]

    baris.append(f"\nTotal: {len(tele)} slot Telegram, {len(wa)} slot WhatsApp")
    return "\n".join(baris)


def _potong(teks, batas=4000):
    """Pecah teks per baris supaya tiap pesan di bawah batas 4096 karakter Telegram."""
    bagian, cur = [], ""
    for baris in teks.split("\n"):
        if cur and len(cur) + len(baris) + 1 > batas:
            bagian.append(cur)
            cur = ""
        cur = f"{cur}\n{baris}" if cur else baris
    if cur:
        bagian.append(cur)
    return bagian


def register_handlers(app, timeout_wrapper=None):
    """Daftarkan command /jadwal ke aplikasi Telegram."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_jadwal(update, ctx):
        """/jadwal — daftar jadwal laporan otomatis yang aktif + report yang dikirim."""
        try:
            job_queue = ctx.application.job_queue
            if job_queue is None:
                await update.message.reply_text("⚠️ job_queue tidak tersedia — tidak ada jadwal aktif.")
                return
            tele, wa = _kumpulkan_jadwal(job_queue)
            for bagian in _potong(_bangun_teks(tele, wa)):
                await update.message.reply_text(bagian, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Error /jadwal")
            await update.message.reply_text(f"❌ Error:\n{html.escape(str(e))[:600]}")

    app.add_handler(CommandHandler("jadwal", _T(cmd_jadwal)))
