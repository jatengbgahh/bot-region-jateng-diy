"""Script migrasi file, state, dan cache dari folder Bot Lama & Scraping SELA Lama
ke struktur folder Bot Baru (storage/ dan resources/).

Cara pakai (interaktif):
    python -m utils.migrate_from_legacy

Cara pakai (lewat argumen CLI):
    python -m utils.migrate_from_legacy --old-bot "D:\\Path\\Bot_Lama" --old-sela "D:\\Path\\Scraping_SELA_Lama"
    python -m utils.migrate_from_legacy --old-bot "D:\\Path\\Bot_Lama" --old-sela "D:\\Path\\Scraping_SELA_Lama" --dry-run
    python -m utils.migrate_from_legacy --old-bot "D:\\Path\\Bot_Lama" --old-sela "D:\\Path\\Scraping_SELA_Lama" --force
"""
import argparse
import json
import os
import re
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# File lock sementara Chrome/Playwright yang tidak perlu disalin
IGNORE_PATTERNS = {
    "SingletonLock", "SingletonCookie", "SingletonSocket",
    "lockfile", "bot.lock", "rajawali_auto.lock", "__pycache__"
}

# Pemetaan path lama di .env ke path baru di resources/
ENV_PATH_REPLACEMENTS = [
    (r"Willy[\\/]+REKAPITULASI ODP PRIORITAS\.xlsx", "resources/djp_priority/REKAPITULASI ODP PRIORITAS.xlsx"),
    (r"Meta[\\/]+Target PS All Channel 2026 - Update\.xlsx", "resources/klaim/Target PS All Channel 2026 - Update.xlsx"),
    (r"Septian[\\/]+Format Report Daily RE\.xlsx", "resources/dailyre/Format Report Daily RE.xlsx"),
    (r"tika[\\/]+", "resources/geo/"),
]

# Pemetaan folder referensi statis lama -> folder resources/ baru
LEGACY_RESOURCE_MAP = [
    ("Willy/DJP ODP Priority - September 2026.xlsx", "resources/djp_priority/DJP ODP Priority - September 2026.xlsx"),
    ("Willy/REKAPITULASI ODP PRIORITAS.xlsx", "resources/djp_priority/REKAPITULASI ODP PRIORITAS.xlsx"),
    ("Meta/Rekap Data Pelanggan Klaim.xlsx", "resources/klaim/Rekap Data Pelanggan Klaim.xlsx"),
    ("Meta/Target PS All Channel 2026 - Update.xlsx", "resources/klaim/Target PS All Channel 2026 - Update.xlsx"),
    ("Septian/TEMPLATE REPORT TARGET RE BARU - fixed.xlsx", "resources/dailyre/TEMPLATE REPORT TARGET RE BARU - fixed.xlsx"),
    ("Septian/Format Report Daily RE.xlsx", "resources/dailyre/Format Report Daily RE.xlsx"),
    ("tika/SF_Performance_Report_22.html", "resources/performance/SF_Performance_Report_22.html"),
    ("tika/update team leader sales force.xlsx", "resources/team_leader/update team leader sales force.xlsx"),
    ("tika/GeocodingJatengDIY_1.zip", "resources/geo/GeocodingJatengDIY_1.zip"),
]


class MigrationStats:
    def __init__(self):
        self.copied = 0
        self.skipped = 0
        self.errors = 0
        self.bytes_copied = 0


def _should_copy(src: str, dst: str, force: bool) -> bool:
    if not os.path.exists(dst):
        return True
    if force:
        return True
    try:
        # Salin jika file sumber lebih baru (> 1 detik) atau ukuran berbeda dan sumber tidak kosong
        src_stat = os.stat(src)
        dst_stat = os.stat(dst)
        if src_stat.st_size == 0:
            return False
        return src_stat.st_mtime > dst_stat.st_mtime + 1.0
    except OSError:
        return True


def copy_single_file(src: str, dst: str, label: str, stats: MigrationStats, dry_run: bool = False, force: bool = False):
    if not os.path.isfile(src):
        return False
    if not _should_copy(src, dst, force):
        stats.skipped += 1
        print(f"  [SKIP] {label} (sudah ada & tidak lebih baru)")
        return False
    size = os.path.getsize(src)
    if dry_run:
        print(f"  [DRY-RUN] Akan menyalin {label} ({size / 1024:,.1f} KB)")
        stats.copied += 1
        stats.bytes_copied += size
        return True
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        stats.copied += 1
        stats.bytes_copied += size
        print(f"  [OK] Disalin: {label} ({size / 1024:,.1f} KB)")
        return True
    except Exception as e:
        stats.errors += 1
        print(f"  [!] Gagal menyalin {label}: {e}")
        return False


def copy_directory_tree(
    src_dir: str,
    dst_dir: str,
    label: str,
    stats: MigrationStats,
    dry_run: bool = False,
    force: bool = False,
    file_filter=None,
):
    if not os.path.isdir(src_dir):
        print(f"  [i] Folder {label} tidak ditemukan di sumber ({src_dir}) -> dilewati.")
        return
    copied_in_dir = 0
    skipped_in_dir = 0
    bytes_in_dir = 0
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_PATTERNS and not d.endswith(".tmp")]
        rel_root = os.path.relpath(root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)

        for fname in files:
            if fname in IGNORE_PATTERNS or fname.endswith(".tmp") or fname.endswith(".lock"):
                continue
            if file_filter and not file_filter(fname):
                continue
            src_file = os.path.join(root, fname)
            dst_file = os.path.join(target_root, fname)
            if not _should_copy(src_file, dst_file, force):
                skipped_in_dir += 1
                stats.skipped += 1
                continue
            try:
                fsize = os.path.getsize(src_file)
                if not dry_run:
                    os.makedirs(target_root, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                copied_in_dir += 1
                bytes_in_dir += fsize
                stats.copied += 1
                stats.bytes_copied += fsize
            except Exception as e:
                stats.errors += 1
                print(f"  [!] Gagal menyalin {src_file}: {e}")

    tag = "DRY-RUN" if dry_run else "OK"
    print(f"  [{tag}] Folder {label}: {copied_in_dir:,} file disalin ({bytes_in_dir / (1024 * 1024):,.1f} MB), "
          f"{skipped_in_dir:,} file dilewati.")


def migrate_env_file(src_env: str, dst_env: str, stats: MigrationStats, dry_run: bool = False, force: bool = False):
    """Salin .env dari bot lama sekaligus perbarui path Willy/Meta/tika/Septian ke resources/."""
    if not os.path.isfile(src_env):
        return
    if not _should_copy(src_env, dst_env, force):
        stats.skipped += 1
        print("  [SKIP] .env (sudah ada & tidak lebih baru; gunakan --force untuk menimpa)")
        return
    try:
        with open(src_env, "r", encoding="utf-8-sig") as f:
            content = f.read()
        for pat, repl in ENV_PATH_REPLACEMENTS:
            content = re.sub(pat, repl, content)
        size = len(content.encode("utf-8"))
        if dry_run:
            print(f"  [DRY-RUN] Akan menyalin & menyesuaikan path di .env ({size / 1024:,.1f} KB)")
        else:
            with open(dst_env, "w", encoding="utf-8") as f:
                f.write(content)
            print("  [OK] .env disalin & path referensi disesuaikan ke folder resources/.")
        stats.copied += 1
        stats.bytes_copied += size
    except Exception as e:
        stats.errors += 1
        print(f"  [!] Gagal memproses .env: {e}")


def migrate_rajawali_json(src_json: str, dst_json: str, stats: MigrationStats, dry_run: bool = False, force: bool = False):
    """Salin rajawali_auto.json dan hapus kunci folder_scraping lama agar memakai storage/sela bawaan."""
    if not os.path.isfile(src_json):
        return
    if not _should_copy(src_json, dst_json, force):
        stats.skipped += 1
        print("  [SKIP] storage/state/rajawali_auto.json (sudah ada & tidak lebih baru)")
        return
    try:
        with open(src_json, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        # Jika masih ada kunci folder_scraping lama, hapus supaya otomatis memakai storage/sela di bot baru
        if "folder_scraping" in data:
            old_val = data.pop("folder_scraping")
            print(f"  [i] Menghapus 'folder_scraping' lama ({old_val}) dari rajawali_auto.json -> pakai storage/sela")
        raw_out = json.dumps(data, ensure_ascii=False, indent=2)
        if dry_run:
            print("  [DRY-RUN] Akan menyalin storage/state/rajawali_auto.json")
        else:
            os.makedirs(os.path.dirname(dst_json), exist_ok=True)
            with open(dst_json, "w", encoding="utf-8") as f:
                f.write(raw_out)
            print("  [OK] Disalin: storage/state/rajawali_auto.json")
        stats.copied += 1
        stats.bytes_copied += len(raw_out.encode("utf-8"))
    except Exception as e:
        stats.errors += 1
        print(f"  [!] Gagal memproses rajawali_auto.json: {e}")


def migrate_from_old_bot(old_bot: str, stats: MigrationStats, dry_run: bool = False, force: bool = False):
    print(f"\n=== [1] MIGRASI DARI FOLDER BOT LAMA: {old_bot} ===")
    if not os.path.isdir(old_bot):
        print(f"  [!] Folder bot lama tidak ditemukan: {old_bot}")
        return

    # 1. File .env
    migrate_env_file(os.path.join(old_bot, ".env"), os.path.join(PROJECT_ROOT, ".env"), stats, dry_run, force)

    # 2. File state (cari di root bot lama maupun di storage/state/ bot lama)
    def find_old_state(rel_new, rel_old_root):
        cand1 = os.path.join(old_bot, rel_new)
        cand2 = os.path.join(old_bot, rel_old_root)
        if os.path.isfile(cand1):
            return cand1
        return cand2

    migrate_rajawali_json(
        find_old_state(os.path.join("storage", "state", "rajawali_auto.json"), "rajawali_auto.json"),
        os.path.join(PROJECT_ROOT, "storage", "state", "rajawali_auto.json"),
        stats, dry_run, force
    )

    single_files = [
        (find_old_state(os.path.join("storage", "state", "saved_target.pkl"), "saved_target.pkl"),
         os.path.join(PROJECT_ROOT, "storage", "state", "saved_target.pkl"),
         "storage/state/saved_target.pkl"),
        (find_old_state(os.path.join("storage", "state", "mode_query.json"), "mode_query.json"),
         os.path.join(PROJECT_ROOT, "storage", "state", "mode_query.json"),
         "storage/state/mode_query.json"),
        (find_old_state(os.path.join("storage", "state", "market_share_last_sent.json"), "market_share_last_sent.json"),
         os.path.join(PROJECT_ROOT, "storage", "state", "market_share_last_sent.json"),
         "storage/state/market_share_last_sent.json"),
        (find_old_state(os.path.join("storage", "state", "targets", "template_target_2026_bot_v8.xlsx"), "template_target_2026_bot_v8.xlsx"),
         os.path.join(PROJECT_ROOT, "storage", "state", "targets", "template_target_2026_bot_v8.xlsx"),
         "storage/state/targets/template_target_2026_bot_v8.xlsx"),
        (find_old_state(os.path.join("storage", "cache", "ref_ordering_20261018.csv.gz"), "ref_ordering_20261018.csv.gz"),
         os.path.join(PROJECT_ROOT, "storage", "cache", "ref_ordering_20261018.csv.gz"),
         "storage/cache/ref_ordering_20261018.csv.gz"),
        (find_old_state(
            os.path.join("storage", "cache", "sf_teritory_jateng_cache.xlsx"),
            os.path.join("reports", "clockin_sf_teritory", "sf_teritory_jateng_cache.xlsx")
         ),
         os.path.join(PROJECT_ROOT, "storage", "cache", "sf_teritory_jateng_cache.xlsx"),
         "storage/cache/sf_teritory_jateng_cache.xlsx"),
    ]
    for src, dst, label in single_files:
        copy_single_file(src, dst, label, stats, dry_run, force)

    # 3. File resources (Willy, Meta, tika, Septian -> resources/)
    for old_rel, new_rel in LEGACY_RESOURCE_MAP:
        src = os.path.join(old_bot, *old_rel.split("/"))
        if not os.path.isfile(src):
            src = os.path.join(old_bot, *new_rel.split("/"))
        dst = os.path.join(PROJECT_ROOT, *new_rel.split("/"))
        if os.path.isfile(src):
            copy_single_file(src, dst, new_rel, stats, dry_run, force)

    # 4. Folder pagi_paket -> storage/sql_packets
    old_pagi = os.path.join(old_bot, "storage", "sql_packets")
    if not os.path.isdir(old_pagi):
        old_pagi = os.path.join(old_bot, "pagi_paket")
    copy_directory_tree(
        old_pagi,
        os.path.join(PROJECT_ROOT, "storage", "sql_packets"),
        "pagi_paket -> storage/sql_packets",
        stats, dry_run, force
    )

    # 5. Folder unduhan_rajawali -> storage/downloads
    old_dl = os.path.join(old_bot, "storage", "downloads")
    if not os.path.isdir(old_dl):
        old_dl = os.path.join(old_bot, "unduhan_rajawali")
    copy_directory_tree(
        old_dl,
        os.path.join(PROJECT_ROOT, "storage", "downloads"),
        "unduhan_rajawali -> storage/downloads",
        stats, dry_run, force
    )

    # 6. Cache homepass_djp (jika ada)
    old_hp_cache = os.path.join(old_bot, "storage", "cache", "homepass_djp")
    if not os.path.isdir(old_hp_cache):
        old_hp_cache = os.path.join(old_bot, "unduhan_rajawali", "_cache_homepass_djp")
    if os.path.isdir(old_hp_cache):
        copy_directory_tree(
            old_hp_cache,
            os.path.join(PROJECT_ROOT, "storage", "cache", "homepass_djp"),
            "cache homepass_djp -> storage/cache/homepass_djp",
            stats, dry_run, force
        )


def migrate_from_old_sela(old_sela: str, stats: MigrationStats, dry_run: bool = False, force: bool = False):
    print(f"\n=== [2] MIGRASI DARI FOLDER SCRAPING SELA LAMA: {old_sela} ===")
    if not os.path.isdir(old_sela):
        print(f"  [!] Folder scraping SELA lama tidak ditemukan: {old_sela}")
        return

    sela_dst = os.path.join(PROJECT_ROOT, "storage", "sela")

    # 1. Kunci AES sesi (config/digipos_sf_indihome.json)
    copy_single_file(
        os.path.join(old_sela, "config", "digipos_sf_indihome.json"),
        os.path.join(sela_dst, "config", "digipos_sf_indihome.json"),
        "storage/sela/config/digipos_sf_indihome.json",
        stats, dry_run, force
    )

    # 2. Browser profile (data/browser_profile)
    copy_directory_tree(
        os.path.join(old_sela, "data", "browser_profile"),
        os.path.join(sela_dst, "data", "browser_profile"),
        "data/browser_profile -> storage/sela/data/browser_profile",
        stats, dry_run, force
    )

    # 3. Cache jadwal & assignment mingguan SF (data/cache_detail_sf)
    copy_directory_tree(
        os.path.join(old_sela, "data", "cache_detail_sf"),
        os.path.join(sela_dst, "data", "cache_detail_sf"),
        "data/cache_detail_sf -> storage/sela/data/cache_detail_sf",
        stats, dry_run, force
    )

    # 4. Cache riwayat kunjungan SF (data/cache_sf_visits)
    copy_directory_tree(
        os.path.join(old_sela, "data", "cache_sf_visits"),
        os.path.join(sela_dst, "data", "cache_sf_visits"),
        "data/cache_sf_visits -> storage/sela/data/cache_sf_visits",
        stats, dry_run, force
    )

    # 5. Hasil Excel khusus SELA (detail-homepass_*.xlsx, detail-sf-indihome_*.xlsx, List SF Teritory*.xlsx)
    def _is_sela_result(fname: str) -> bool:
        low = fname.lower()
        return low.endswith(".xlsx") and (
            low.startswith("detail-homepass_")
            or low.startswith("detail-sf-indihome_")
            or low.startswith("jadwal-sf-indihome")
            or low.startswith("list sf teritory")
        )

    copy_directory_tree(
        os.path.join(old_sela, "data", "results"),
        os.path.join(sela_dst, "data", "results"),
        "data/results (khusus SELA .xlsx) -> storage/sela/data/results",
        stats, dry_run, force,
        file_filter=_is_sela_result,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Migrasi file konfigurasi, state, dan cache dari Bot Lama & Scraping SELA Lama ke Bot Baru."
    )
    parser.add_argument("--old-bot", type=str, default=None,
                        help="Path folder bot lama (mis. D:\\Kerjaan\\Project\\bot_re_jateng_lama)")
    parser.add_argument("--old-sela", type=str, default=None,
                        help="Path folder scraping SELA lama (mis. D:\\Kerjaan\\hasil gabungan data)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulasi saja (tampilkan daftar file yang akan disalin tanpa menulis ke disk)")
    parser.add_argument("--force", action="store_true",
                        help="Timpa semua file tujuan walaupun file di tujuan lebih baru")
    args = parser.parse_args()

    print("=" * 65)
    print("  MIGRASI DATA & CACHE KE BOT BARU")
    print(f"  Folder Bot Baru (Tujuan): {PROJECT_ROOT}")
    print("=" * 65)

    old_bot = args.old_bot
    old_sela = args.old_sela

    if old_bot is None and old_sela is None:
        print("\nMasukkan path sumber (kosongkan/tekan Enter jika ingin melewati salah satu):")
        try:
            old_bot = input("  1. Lokasi Folder Bot Lama          : ").strip().strip('"').strip("'")
            old_sela = input("  2. Lokasi Folder Scraping SELA Lama: ").strip().strip('"').strip("'")
        except EOFError:
            pass

    if not old_bot and not old_sela:
        print("\n[!] Tidak ada lokasi folder sumber yang dimasukkan. Migrasi dibatalkan.")
        return 1

    stats = MigrationStats()

    if old_bot:
        if os.path.normcase(os.path.abspath(old_bot)) == os.path.normcase(PROJECT_ROOT):
            print("\n[!] Lokasi folder bot lama sama dengan folder bot baru! Dilewati.")
        else:
            migrate_from_old_bot(os.path.abspath(old_bot), stats, dry_run=args.dry_run, force=args.force)

    if old_sela:
        migrate_from_old_sela(os.path.abspath(old_sela), stats, dry_run=args.dry_run, force=args.force)

    print("\n" + "=" * 65)
    print("  RINGKASAN MIGRASI" + (" (DRY-RUN / SIMULASI)" if args.dry_run else ""))
    print("=" * 65)
    print(f"  File disalin  : {stats.copied:,} file ({stats.bytes_copied / (1024 * 1024):,.2f} MB)")
    print(f"  File dilewati : {stats.skipped:,} file (sudah ada & terbaru)")
    print(f"  Gagal/Error   : {stats.errors:,} file")
    print("=" * 65)
    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
