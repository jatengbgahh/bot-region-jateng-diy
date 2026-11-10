"""
csv_report_runner.py — Report pagi (closingsql, dod, agresif, wireless2, wirelesschannel2)
dari CSV indihome_ordering_detail, dipakai saat DB tidak bisa diakses.

Menjalankan handler bot ASLI (jalur terjadwal) dengan DB diganti csv_fake_db.

  python csv_report_runner.py --csv <file.csv> --tanggal 18-10-2026              # dry-run: simpan ke folder
  python csv_report_runner.py --csv <file.csv> --tanggal 18-10-2026 --kirim      # kirim ke GROUP_ID
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from types import SimpleNamespace

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument("--csv", nargs="+", help="CSV raw ordering_detail (mode raw / referensi untuk --rekam)")
for _o in ("sf-ini", "sf-lalu", "djp-ini", "djp-lalu"):
    ap.add_argument("--" + _o, help="export database_sf / djp_daily_user_detailed (5so/7so)")
ap.add_argument("--caps-export", help="export satu-query caps_sql.py (q;j) -> /caps 4 gambar (pakai --only caps)")
ap.add_argument("--childps-export", help="export agregat childps_sql.py (bln;city;cluster;ps;child) -> /childps (pakai --only childps)")
ap.add_argument("--ms-export", help="export satu-query ms_sql.py (q;j) -> /ms /msbranch (pakai --only ms,msbranch)")
ap.add_argument("--c3mr-export", help="export c3mr_sql.py --bagian C (q;j) -> /c3mr + /c3mrsvp (pakai --only c3mr,c3mrsvp)")
ap.add_argument("--hourly-export", help="export dashboard_hourly_sales (rajawali_auto.sql_hourly) -> /liveupdate "
                                         "(pakai --only liveupdate)")
ap.add_argument("--c3mr-unpaid", help="export c3mr_sql.py --bagian U (U_ini) -> lampiran CSV unpaid /c3mrnew")
ap.add_argument("--sfo-export", help="export satu-query sfo_sql.py (q;j) -> /5so /7so (pakai --only 5so,7so)")
ap.add_argument("--tanpa-raw-murmer", action="store_true", help="jangan kirim lampiran raw Excel murmer (hari Senin)")
ap.add_argument("--homepass-export", help="export homepass_sql.py (bln + homepass_sales) -> /homepass (pakai --csv iod_*)")
ap.add_argument("--homepass-file", help="detail-homepass_*.xlsx untuk /clockin_sf_teritory, /clockin_sf_all dan /homepass_raw")
ap.add_argument("--rekam", help="prefix output: rekam semua SQL laporan -> <prefix>.sql + <prefix>.manifest.json (tidak mengirim)")
ap.add_argument("--bagian", help="--rekam: nasional | murmer | murmer-awal | murmer-akhir (default semua yang direkam)")
ap.add_argument("--export", nargs="+", help="export agregat dari Console Rajawali (kolom q;j) — mode replay")
ap.add_argument("--manifest", help="manifest dari --rekam, pasangan --export")
ap.add_argument("--tanggal", required=True, help="DD-MM-YYYY (H-1)")
ap.add_argument("--out", default=os.path.join(BASE, "out_report_pagi"))
ap.add_argument("--kirim", action="store_true")
ap.add_argument("--chat", help="--kirim ke chat ini (CHAT_ID atau CHAT_ID:THREAD_ID), seperti command manual "
                               "yang diketik di chat itu; mengalahkan --topic")
ap.add_argument("--topic", help="--kirim ke tujuan laporan terjadwal topic ini (SALES, FUNDAMENTAL, ...), sama seperti "
                                "jadwal bot; default grup koordinasi (GROUP_ID)")
ap.add_argument("--only", default="closingsql,dod,nasional,agresif,wireless2,wirelesschannel2,murmer")
ap.add_argument("--alias-kosong", action="store_true", help="uji: bulan tabel yang tak ada = view ke bulan ada")
ap.add_argument("--skip-zip", action="store_true", help="jangan kirim ZIP raw CSV closing")
args = ap.parse_args()
if args.homepass_file:
    os.environ["CLOCKIN_HOMEPASS_FILE"] = args.homepass_file

import csv_fake_db
if args.csv:   # "path::YYYYMM" = partisi cadangan utk baris tanpa event_date
    args.csv = [tuple(x.rsplit("::", 1)) if "::" in x else x for x in args.csv]
GESER = False
if args.rekam and not args.csv:
    args.csv = os.path.join(BASE, "storage", "cache", "ref_ordering_20261018.csv.gz")   # data referensi; tanggal digeser
    GESER = True
if args.hourly_export:
    csv_fake_db.install_kosong()
    print("tabel hourly:", csv_fake_db.muat_hourly(args.hourly_export))
elif args.c3mr_export:
    csv_fake_db.install_kosong()
    print("c3mr:", csv_fake_db.muat_export_c3mr(args.c3mr_export, datetime.strptime(args.tanggal, "%d-%m-%Y").date()))
elif args.sfo_export:
    _t0 = datetime.strptime(args.tanggal, "%d-%m-%Y").date()
    if args.csv:     # ordering dari export iod_* (sudah diquery utk closingsql), SF & DJP M1 dari export sfo
        print("tabel:", csv_fake_db.install(args.csv, alias_kosong=args.alias_kosong))
    else:
        csv_fake_db.install_kosong()
    _lewati = ({"djp_ini"} if args.djp_ini else set()) | ({"djp_lalu"} if args.djp_lalu else set())
    print("tabel 5so/7so:", csv_fake_db.muat_export_sfo(args.sfo_export, _t0, _lewati))
    if args.djp_ini:   # DJP bulan ini dari file lain (mis. homepass) menggantikan tabel DJP yang belum terisi
        print("djp_ini (file lain):", csv_fake_db.muat_tabel(
            args.djp_ini, f"djp_daily_user_detailed_{_t0:%Y%m}", {"regional": "JATENG-DIY"}))
        os.environ["SFO_DJP_SUMBER_MTD"] = "SELA"
    if args.djp_lalu:  # DJP M1 dari file SELA bulan lalu (tabel DJP DB tidak diisi lagi sejak Okt 2026)
        from dateutil.relativedelta import relativedelta as _rd0
        print("djp_lalu (file lain):", csv_fake_db.muat_tabel(
            args.djp_lalu, f"djp_daily_user_detailed_{(_t0 - _rd0(months=1)):%Y%m}", {"regional": "JATENG-DIY"}))
        os.environ["SFO_DJP_SUMBER_M1"] = "SELA"
elif set(args.only.split(",")) <= {"homepass_raw", "clockin_sf_teritory", "clockin_sf_all"} and not args.csv and not args.export:
    csv_fake_db.install_kosong()             # tanpa DB: hanya kirim file homepass / report clock-in dari file
elif args.caps_export:
    csv_fake_db.install_kosong()
    print("tabel caps:", csv_fake_db.muat_export_caps(args.caps_export, datetime.strptime(args.tanggal, "%d-%m-%Y").date()))
elif args.childps_export:
    csv_fake_db.install_kosong()
    import childps_bot
    print("childps baris agregat:", childps_bot.pasang_export(args.childps_export))
elif args.ms_export:
    csv_fake_db.install_kosong()
    print("tabel market share:", csv_fake_db.muat_export_ms(args.ms_export, datetime.strptime(args.tanggal, "%d-%m-%Y").date()))
elif args.export and not args.csv:
    print("replay query:", csv_fake_db.install_replay(args.export[0], args.manifest))
else:
    print("tabel:", csv_fake_db.install(args.csv, alias_kosong=args.alias_kosong))
    _t = datetime.strptime(args.tanggal, "%d-%m-%Y").date()
    if args.homepass_export:
        print("homepass_sales:", csv_fake_db.muat_export_homepass(args.homepass_export, _t))
    from dateutil.relativedelta import relativedelta as _rd
    for _opt, _awalan, _bulan in (("sf_ini", "database_sf_", _t), ("sf_lalu", "database_sf_", _t - _rd(months=1)),
                                  ("djp_ini", "djp_daily_user_detailed_", _t), ("djp_lalu", "djp_daily_user_detailed_", _t - _rd(months=1))):
        _f = getattr(args, _opt)
        if _f:
            _tbl = f"{_awalan}{_bulan:%Y%m}"
            _tambah = ({"region": "JATENG-DIY", "status": "ACTIVE", "event_date": _bulan.replace(day=1).strftime("%Y-%m-%d")}
                       if "sf" in _opt else {"regional": "JATENG-DIY"})
            print(_tbl, csv_fake_db.muat_tabel(_f, _tbl, _tambah), "baris")
    if args.export:   # hibrid: raw Jateng dari CSV + nasional/murmer dari hasil query
        print("query dari export agregat:", csv_fake_db.pasang_extra(args.export, args.manifest))
    if args.rekam:
        csv_fake_db.mulai_rekam()
        if GESER:
            _t = datetime.strptime(args.tanggal, "%d-%m-%Y").date()
            csv_fake_db.set_shift(_t)
            import db as _db
            _db.query_tanggal_tersedia = lambda *a, **k: [_t]

import bot  # noqa: E402  (setelah DB palsu terpasang)
from telegram import Bot  # noqa: E402
from config import TOKEN, GROUP_ID  # noqa: E402

bot._load_target_state()

if args.c3mr_export:
    # Mode agregat: df_unpaid (lampiran CSV c3mrnew) akan berisi baris sintetis tanpa bb_id -> JANGAN dikirim.
    _asli_new = bot.calculator_c3mrnew.hitung_c3mrnew

    _df_unpaid = csv_fake_db.df_unpaid_c3mrnew(args.c3mr_unpaid) if args.c3mr_unpaid else None
    if _df_unpaid is not None:
        print("unpaid c3mrnew (lampiran CSV):", len(_df_unpaid), "pelanggan")

    def _tanpa_csv(tgl, *a, **k):
        r = _asli_new(tgl, *a, **k)
        r["df_unpaid"] = _df_unpaid        # None (tanpa lampiran) bila export bagian U tidak ada
        return r
    bot.calculator_c3mrnew.hitung_c3mrnew = _tanpa_csv

    # ...dan blokir pesan "Tidak ada data unpaid" yang menyesatkan (datanya hanya tak tersedia dari export agregat).
    _asli_reply = bot._PesanKeTopic.reply_text

    async def _reply_tanpa_unpaid(self, text, **kw):
        if _df_unpaid is None and "Tidak ada data unpaid" in str(text):
            return None
        return await _asli_reply(self, text, **kw)
    bot._PesanKeTopic.reply_text = _reply_tanpa_unpaid


class _App:
    def add_handler(self, *a, **k):
        pass


async def _get_target_wireless():
    if bot._target_wireless_df is not None:
        return bot._target_wireless_df
    return await asyncio.to_thread(bot._load_wireless_target_from_local_file)


bot.cmd_wireless2, bot.cmd_wirelesschannel2 = bot.cmd_wireless2_mod.register_handlers(
    _App(), bot._dengan_batas_waktu, _get_target_wireless, bot._get_cutoff_raw, bot._kirim_foto_retry)


async def _get_target_region():
    return await bot._get_target_region()


bot.cmd_nasional = bot.cmd_nasional_mod.register_handlers(
    _App(), bot._dengan_batas_waktu, _get_target_region, bot._get_cutoff_raw, bot._kirim_foto_retry)
bot.cmd_murmer = bot.murmer.register_handlers(_App(), bot._dengan_batas_waktu)
bot.cmd_c3mrsvp = bot.cmd_c3mrsvp_mod.register_handlers(_App(), bot._dengan_batas_waktu, bot._get_cutoff_tabel)
bot.cmd_c3mrnewch = bot.c3mrnewch.register_handlers(_App(), bot._dengan_batas_waktu, bot._get_cutoff_tabel)
import importlib
_ck = importlib.import_module("commands.clockin_sf_teritory")
bot.cmd_clockin_sf_teritory, bot.cmd_homepass_raw = _ck.register_handlers(_App(), bot._dengan_batas_waktu)
bot.cmd_clockin_sf_all = importlib.import_module("commands.clockin_sf_all").register_handlers(_App(), bot._dengan_batas_waktu)
bot.cmd_ms, bot.cmd_msbranch = bot.cmd_market_share_mod.register_handlers(
    _App(), bot._dengan_batas_waktu, bot._kirim_foto_retry)
for _nm in ("homepass", "homepass_wok_old"):
    setattr(bot, "cmd_" + _nm, importlib.import_module("commands." + _nm).register_handlers(_App(), bot._dengan_batas_waktu))
for _nm in ("salahtagging", "salahtagging_wok_old"):
    setattr(bot, "cmd_" + _nm, importlib.import_module("commands." + _nm).register_handlers(
        _App(), bot._dengan_batas_waktu, bot._get_cutoff_tabel))


class CatatKiriman:
    """Bungkus Bot asli: catat (chat_id, message_id) tiap send_* supaya kiriman salah bisa dihapus
    otomatis (hapus_kiriman.py). Disimpan di storage/sql_packets/terkirim_<waktu>.json."""
    def __init__(self, bot):
        self._bot, self.ids = bot, []
        self.path = os.path.join(BASE, "storage", "sql_packets", f"terkirim_{datetime.now():%Y%m%d_%H%M%S}.json")

    def __getattr__(self, nama):
        asli = getattr(self._bot, nama)
        if not nama.startswith("send_"):
            return asli

        async def _kirim(*a, **kw):
            # timeout panjang supaya gambar besar (City, ZIP) tidak timeout -> tidak retry/ketinggalan urutan
            for _k, _v in (("write_timeout", 900), ("read_timeout", 900), ("connect_timeout", 60), ("pool_timeout", 120)):
                kw.setdefault(_k, _v)
            if args.tanpa_raw_murmer and nama == "send_document":
                _fn = getattr(kw.get("document"), "filename", "") or ""
                if _fn.startswith("eznet_murmer_raw"):
                    print("[lewati] lampiran raw murmer tidak dikirim:", _fn)
                    return SimpleNamespace(message_id=None, document=SimpleNamespace(file_id="x"))
            hasil = await asli(*a, **kw)
            mid = getattr(hasil, "message_id", None)
            if mid:
                self.ids.append({"chat_id": kw.get("chat_id", getattr(hasil, "chat_id", None)), "message_id": mid})
                import json
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                json.dump({"tanggal_laporan": args.tanggal, "pesan": self.ids}, open(self.path, "w"))
            return hasil
        return _kirim


class FakeBot:
    """Tangkap semua kiriman ke folder lokal (dry-run)."""
    def __init__(self, out):
        self.out, self.n = out, 0
        os.makedirs(out, exist_ok=True)
        self.urutan = []         # urutan.json: dipakai mengirim ulang hasil dry-run apa adanya (mis. ke WhatsApp)

    def _catat(self, jenis, p=None, caption=None, teks=None):
        self.urutan.append({"jenis": jenis, "file": os.path.basename(p) if p else None,
                            "caption": caption, "teks": teks})
        with open(os.path.join(self.out, "urutan.json"), "w", encoding="utf-8") as f:
            json.dump(self.urutan, f, ensure_ascii=False, indent=1)

    def _simpan(self, obj, default):
        self.n += 1
        if isinstance(obj, str):
            return None
        name = getattr(obj, "filename", None) or default
        data = getattr(obj, "input_file_content", None)
        if data is None:
            obj.seek(0)
            data = obj.read()
        p = os.path.join(self.out, f"{self.n:02d}_{name}")
        with open(p, "wb") as f:
            f.write(data)
        return p

    async def send_photo(self, chat_id=None, photo=None, caption=None, **kw):
        p = self._simpan(photo, "photo.png")
        self._cap(p, caption)
        self._catat("photo", p, caption)
        return SimpleNamespace(photo=[SimpleNamespace(file_id="x")])

    async def send_document(self, chat_id=None, document=None, caption=None, **kw):
        p = self._simpan(document, "doc.bin")
        self._cap(p, caption)
        self._catat("document", p, caption)
        return SimpleNamespace(document=SimpleNamespace(file_id="x"))

    async def send_message(self, chat_id=None, text=None, **kw):
        self.n += 1
        with open(os.path.join(self.out, f"{self.n:02d}_pesan.txt"), "w", encoding="utf-8") as f:
            f.write(str(text))
        self._catat("message", teks=str(text))
        return SimpleNamespace()

    def _cap(self, p, caption):
        if p and caption:
            with open(p + ".caption.txt", "w", encoding="utf-8") as f:
                f.write(caption)


async def main():
    tgl = datetime.strptime(args.tanggal, "%d-%m-%Y").date()
    if args.kirim:
        # _RetryRequest (bot.py): ulang otomatis error koneksi pra-kirim (ConnectError "All connection attempts
        # failed", SSL alert) yang dijamin tidak membuat kiriman dobel — dulu HTTPXRequest polos: 1 putus koneksi
        # sesaat = seluruh laporan terjadwal gagal (liveupdate 15:15, 08-11-2026).
        real = Bot(TOKEN, request=bot._RetryRequest(connect_timeout=30, read_timeout=180, write_timeout=300,
                                                   pool_timeout=60))
        await real.initialize()
        real = CatatKiriman(real)
    else:
        real = FakeBot(args.out)

    perintahs = bot._daftar_perintah_terjadwal()
    perintahs.setdefault("clockin_sf_teritory", bot.cmd_clockin_sf_teritory)
    perintahs.setdefault("clockin_sf_all", bot.cmd_clockin_sf_all)
    perintahs.setdefault("homepass_raw", bot.cmd_homepass_raw)
    perintahs.setdefault("ms", bot.cmd_ms)
    perintahs.setdefault("msbranch", bot.cmd_msbranch)
    perintahs.setdefault("childps", bot.childps_bot.cmd_childps)
    if args.chat and args.kirim:
        _c, _, _t = args.chat.partition(":")
        chat, thread, salin = int(_c), (int(_t) if _t else None), None
    elif args.topic and args.kirim:
        chat, thread, salin = bot._tujuan_terjadwal(bot.TOPIC_IDS[args.topic])
    else:
        chat, thread, salin = GROUP_ID, None, None
    for nama in args.only.split(","):
        status = bot._StatusLaporan()
        bot_topic = bot._BotKeTopic(real, chat, thread, salin_ke=salin, status=status)
        if args.skip_zip:
            orig = bot_topic.send_document

        pesan = bot._PesanKeTopic(bot_topic, chat, thread, f"{args.topic or 'SALES'}/{nama}")
        print(f"=== /{nama} {args.tanggal}")
        try:
            await perintahs[nama](bot._UpdateKeTopic(pesan),
                                  SimpleNamespace(args=[tgl.strftime("%d-%m-%Y")], bot=bot_topic))
            print(f"    selesai, media terkirim/tersimpan: {status.media_terkirim}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"    GAGAL {nama}: {e}")
    if args.kirim:
        print("ID pesan tercatat:", real.path)
        await real._bot.shutdown()
    if args.rekam:
        n, lewat = csv_fake_db.buat_paket(args.rekam + ".sql", args.rekam + ".manifest.json",
                                          meta={"tanggal": args.tanggal}, bagian=args.bagian)
        print(f"[rekam] {n} query dipaket -> {args.rekam}.sql")
        for k, r in lewat.items():
            print(f"[rekam] DILEWATI {k}: {r} | {csv_fake_db.RECORD[k]['sql'][:90]!r}")
        if not GESER:
            m = csv_fake_db.jalankan_paket_lokal(args.rekam + ".sql", args.rekam + ".export.csv")
            print(f"[rekam] simulasi export lokal: {m} baris -> {args.rekam}.export.csv")


asyncio.run(main())
