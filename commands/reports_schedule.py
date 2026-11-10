"""
commands/reports_schedule.py — Handler Telegram /reports_schedule: jadwal report otomatis
yang AKTIF dalam bentuk gambar, berisi 3 tabel yang disusun MENYAMPING (kiri ke kanan):
  1) Telegram — tiap hari
  2) WhatsApp
  3) Mingguan (tiap Senin)
Kolom command tidak ditampilkan; yang tampil daftar report yang dikirim per jam.

Sumbernya sama dengan /jadwal: job_queue yang benar-benar terdaftar di bot yang
sedang jalan (commands.jadwal._kumpulkan_jadwal), jadi yang tampil = yang memang
akan dikirim. Isi report per command diambil dari commands.jadwal.REPORT_PER_PERINTAH.
"""

import logging
import textwrap
from datetime import datetime, timedelta, timezone
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from telegram import InputFile
from telegram.ext import CommandHandler

from .jadwal import _kumpulkan_jadwal, REPORT_PER_PERINTAH

logger = logging.getLogger(__name__)

_WIB_TZ = timezone(timedelta(hours=7))

C_BG, C_DARK, C_MID = "white", "#1A1A1A", "#2C3E50"
C_SEP, C_ODD, C_EVEN = "#BDC3C7", "white", "#EAF0F8"
C_TELE, C_WA, C_WEEK = "#1B3A6B", "#1E8449", "#8B2500"

TW = 8.6        # lebar tiap tabel (inci); kolom ISI REPORT menyerap sisanya
GAPX = 0.45     # jarak horizontal antar tabel
CHAR_PER_INCH = 8.2   # perkiraan karakter muat per inci (font 10)
LH, PAD = 0.28, 0.26   # tinggi per baris teks, padding vertikal per baris tabel


def _fmt_data(offsets):
    uniq = sorted({o for o in offsets if o})
    return ", ".join(f"H-{o}" for o in uniq) if uniq else "-"


def _baris_slot(jam, menit, laporan, wrap, topic=None, hari=None):
    """Satu baris tabel = satu slot jam: semua report dari semua command di slot itu."""
    isi = []
    for nama, _offset in laporan:
        for rep in REPORT_PER_PERINTAH.get(nama, ["(isi report belum didaftarkan)"]):
            teks = textwrap.wrap(rep, wrap) or ["-"]
            isi.append(["•  " + teks[0]] + ["    " + t for t in teks[1:]])
    return {
        "jam": f"{jam:02d}:{menit:02d}", "topic": topic, "hari": hari,
        "isi": [ln for blok in isi for ln in blok],
        "data": _fmt_data(o for _n, o in laporan),
    }


def _susun_tabel(tele, wa):
    """Return list spec tabel: {judul, warna, kolom:[(judul, lebar, key)], baris:[...]}."""
    harian = [s for s in tele if s["hari"] is None]
    mingguan = [s for s in tele if s["hari"] is not None]
    urut = lambda s: (s["jam"], s["menit"])

    hari_mingguan = sorted({s["hari"].capitalize() for s in mingguan})
    pakai_hari = len(hari_mingguan) > 1     # kolom HARI hanya kalau harinya beda-beda
    judul3 = f"Tiap {hari_mingguan[0]}" if len(hari_mingguan) == 1 else "Mingguan"

    def kolom(pakai_topic, pakai_hari_):
        cols = [("JAM", 1.05, "jam")]
        if pakai_hari_:
            cols.append(("HARI", 1.05, "hari"))
        if pakai_topic:
            cols.append(("TUJUAN", 2.2, "topic"))
        cols.append(("DATA", 0.85, "data"))
        isi_w = TW - sum(c[1] for c in cols)
        cols.insert(len(cols) - 1, ("ISI REPORT", isi_w, "isi"))
        return cols

    def wrap_untuk(cols):
        isi_w = next(c[1] for c in cols if c[2] == "isi")
        return max(int((isi_w - 0.45) * CHAR_PER_INCH), 20)

    k1, k2, k3 = kolom(True, False), kolom(False, False), kolom(True, pakai_hari)
    w1, w2, w3 = wrap_untuk(k1), wrap_untuk(k2), wrap_untuk(k3)

    t1 = [_baris_slot(s["jam"], s["menit"], s["laporan"], w1, topic=f"Topic {s['topic']}")
          for s in sorted(harian, key=lambda s: (s["jam"], s["menit"], s["topic"]))]
    # Susun baris WhatsApp dari slot Telegram yang juga ditandai dikirim ke WA (+ fallback list wa)
    wa_slots = list(wa)
    if not wa_slots:
        for s in tele:
            for n, o in s["laporan"]:
                if s.get("wa") or n in ("liveupdate", "closingsql", "agresif"):
                    wa_slots.append({"jam": s["jam"], "menit": s["menit"], "laporan": n, "offset": o})

    t2 = [_baris_slot(s["jam"], s["menit"], [(s["laporan"], s["offset"])], w2)
          for s in sorted(wa_slots, key=urut)]
    t3 = [_baris_slot(s["jam"], s["menit"], s["laporan"], w3, topic=f"Topic {s['topic']}",
                      hari=s["hari"].capitalize())
          for s in sorted(mingguan, key=lambda s: (s["hari"], s["jam"], s["menit"], s["topic"]))]

    return [
        {"judul": "TELEGRAM - Tiap Hari", "warna": C_TELE, "kolom": k1, "baris": t1},
        {"judul": "WHATSAPP - Tiap Hari", "warna": C_WA,   "kolom": k2, "baris": t2},
        {"judul": f"TELEGRAM - {judul3}", "warna": C_WEEK, "kolom": k3, "baris": t3},
    ]


def _tinggi_baris(b):
    return max(len(b["isi"]), 1) * LH + PAD


def _tinggi_tabel(t, HH, TITLE_H):
    isi = sum(_tinggi_baris(b) for b in t["baris"]) if t["baris"] else 0.7
    return TITLE_H + HH + isi


def render_reports_schedule(tele, wa) -> BytesIO:
    tabel = _susun_tabel(tele, wa)

    MG, TH, HH, TITLE_H = 0.30, 1.05, 0.50, 0.55
    n = len(tabel)
    tinggi_maks = max(_tinggi_tabel(t, HH, TITLE_H) for t in tabel)
    FW = n * TW + (n - 1) * GAPX + MG * 2
    FH = TH + tinggi_maks + 0.55 + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor(C_BG)

    jml_slot = sum(len(t["baris"]) for t in tabel)
    ax.text(MG, FH - MG, "Jadwal Report Otomatis Bot RE JTG-DIY", ha="left", va="top",
            fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - MG - 0.48,
            f"{jml_slot} slot jadwal  |  Dibuat {datetime.now(_WIB_TZ).strftime('%d-%m-%Y %H:%M')} WIB",
            ha="left", va="top", fontsize=12, color="#7F8C8D")

    y_awal = FH - MG - TH
    for ti, t in enumerate(tabel):
        x0 = MG + ti * (TW + GAPX)
        warna, kolom = t["warna"], t["kolom"]
        xs = [x0]
        for _j, w, _k in kolom:
            xs.append(xs[-1] + w)

        # judul tabel
        ax.text(x0, y_awal - TITLE_H / 2, t["judul"], ha="left", va="center",
                fontsize=15, fontweight="bold", color=warna)
        y = y_awal - TITLE_H

        # header
        ax.add_patch(plt.Rectangle((x0, y - HH), TW, HH, facecolor=warna, edgecolor="none", zorder=2))
        for i, (judul, _w, k) in enumerate(kolom):
            ax.text((xs[i] + xs[i + 1]) / 2 if k != "isi" else xs[i] + 0.12, y - HH / 2, judul,
                    ha="center" if k != "isi" else "left", va="center",
                    fontsize=11, fontweight="bold", color="white", zorder=3)
        y_head_bawah = y - HH
        y = y_head_bawah

        if not t["baris"]:
            ax.text(x0 + TW / 2, y - 0.35, "Tidak ada jadwal", ha="center", va="center",
                    fontsize=12, color="#7F8C8D", style="italic")
            y -= 0.7
        for bi, b in enumerate(t["baris"]):
            h = _tinggi_baris(b)
            ax.add_patch(plt.Rectangle((x0, y - h), TW, h,
                                       facecolor=C_ODD if bi % 2 == 0 else C_EVEN,
                                       edgecolor="none", zorder=1))
            cy = y - h / 2
            for i, (_j, w, key) in enumerate(kolom):
                cx = (xs[i] + xs[i + 1]) / 2
                if key == "jam":
                    ax.text(cx, cy, b["jam"], ha="center", va="center", fontsize=14,
                            fontweight="bold", color=C_DARK, zorder=3)
                elif key == "hari":
                    ax.text(cx, cy, b["hari"], ha="center", va="center", fontsize=10.5,
                            color=C_DARK, zorder=3)
                elif key == "topic":
                    ax.add_patch(plt.Rectangle((xs[i] + 0.1, cy - 0.17), w - 0.2, 0.34,
                                               facecolor=warna, edgecolor="none", zorder=2))
                    ax.text(cx, cy, b["topic"], ha="center", va="center", fontsize=10,
                            fontweight="bold", color="white", zorder=3)
                elif key == "data":
                    ax.text(cx, cy, b["data"], ha="center", va="center", fontsize=10.5,
                            color=C_DARK, zorder=3)
                else:  # isi
                    ax.text(xs[i] + 0.12, cy, "\n".join(b["isi"]) or "-", ha="left", va="center",
                            fontsize=10, color=C_DARK, linespacing=1.25, zorder=3)
            y -= h
            ax.plot([x0, x0 + TW], [y, y], color=C_SEP, lw=0.6, zorder=2)

        for x in xs[1:-1]:
            ax.plot([x, x], [y, y_head_bawah], color=C_SEP, lw=0.4, zorder=2)
        ax.add_patch(plt.Rectangle((x0, y), TW, (y_head_bawah - y) + HH, fill=False,
                                   edgecolor="#7F8C8D", lw=0.9, zorder=4))

    ax.text(MG, y_awal - tinggi_maks - 0.12,
            "DATA H-1 = laporan memakai data kemarin  |  Sumber: jadwal aktif di bot "
            "(config.JADWAL_LAPORAN & JADWAL_LAPORAN_WA)",
            fontsize=8, color="#95A5A6", va="top", style="italic")

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf


def register_handlers(app, timeout_wrapper=None):
    """Daftarkan command /reports_schedule ke aplikasi Telegram."""
    _T = timeout_wrapper if timeout_wrapper is not None else (lambda f: f)

    async def cmd_reports_schedule(update, ctx):
        """/reports_schedule — gambar 3 tabel jadwal report otomatis yang aktif."""
        try:
            job_queue = ctx.application.job_queue
            if job_queue is None:
                await update.message.reply_text("⚠️ job_queue tidak tersedia — tidak ada jadwal aktif.")
                return
            tele, wa = _kumpulkan_jadwal(job_queue)
            if not tele and not wa:
                await update.message.reply_text("⚠️ Tidak ada jadwal yang aktif.")
                return
            # Render PNG SINKRON di event loop (invariant matplotlib di bot ini).
            img = render_reports_schedule(tele, wa)
            await update.message.reply_photo(
                photo=InputFile(img, filename="jadwal_report_otomatis.png"),
                caption="📅 Jadwal report otomatis yang aktif (WIB)",
            )
        except Exception as e:
            logger.exception("Error /reports_schedule")
            await update.message.reply_text(f"❌ Error:\n{str(e)[:600]}")

    app.add_handler(CommandHandler("reports_schedule", _T(cmd_reports_schedule)))
