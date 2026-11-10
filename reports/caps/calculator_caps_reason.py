"""
calculator_caps_reason.py — Kalkulasi Top 5 Reason CAPS (DO) per Branch & Region

Report ke-4 dari perintah /caps.

Logic:
  - Sumber sama dgn calculator_caps_channel.py: retensi_dd_YYYYMM (nama tabel
    LITERAL mengikuti bulan closing), retention_category = 'DO',
    region_sales mengandung 'JATENG', cutoff MtD pakai deactivation_date.
  - Level yang ditampilkan: 6 Branch Jateng-DIY (MAGELANG, PEKALONGAN,
    PURWOKERTO, SEMARANG, SURAKARTA, YOGYAKARTA) + 1 baris Region JATENG-DIY.
    TIDAK sampai level WOK.
  - Tiap territory diambil TOP 5 reason berdasarkan MtD (terbanyak dulu).
  - MtD  = COUNT(DISTINCT bb_id) per reason
  - Cont.= MtD reason / MtD total CAPS territory tsb (SEMUA reason) * 100
  - M-1  = MtD reason yang sama di rentang tanggal yang sama bulan sebelumnya
  - MoM  = (MtD - M-1) / M-1 * 100  (churn naik = positif = jelek)
    Reason yang masuk Top 5 bulan ini tapi nol di M-1 -> MoM None ("-").

Catatan label:
  Kolom `reason` di DB berisi kode snake_case (mis. 'no_network_at_new_location').
  REASON_LABEL memetakannya ke label "Kategori - Sub Reason" seperti pada
  report CAPS korporat. Kode yang belum terdaftar otomatis di-prettify
  (underscore -> spasi, Title Case) supaya report tidak pernah kosong kalau
  sumber data menambah kode reason baru.
"""

import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar
import db
from config import BRANCH_ORDER, REGION_NAME
from calculator_caps_channel import cutoff_efektif

TOP_N = 5

# Kode reason (DB) -> "Kategori - Sub Reason"
REASON_LABEL = {
    # ── Pindah Alamat ────────────────────────────────────────────────────
    "no_network_at_new_location"                          : "Pindah Alamat - Tidak ada Jaringan di Lokasi baru",
    "pda_gagal_psb_indiHome_di_lokasi_baru"               : "Pindah Alamat - PDA gagal, PSB IndiHome di lokasi baru",
    "proses_pda_indiHome_gagal_system_sla_tidak_terpenuhi": "Pindah Alamat - Proses PDA gagal (SLA tidak terpenuhi)",
    "housing_renovation"                                  : "Pindah Alamat - Renovasi Rumah",

    # ── Pindah Provider ──────────────────────────────────────────────────
    "cukup_menggunakan_seluler"                           : "Pindah Provider - Cukup menggunakan Seluler",
    "provider_lainnya"                                    : "Pindah Provider - Provider Lainnya",
    "my_republic"                                         : "Pindah Provider - MyRepublic",
    "biznet"                                              : "Pindah Provider - Biznet",
    "internet_rakyat"                                     : "Pindah Provider - Internet Rakyat",
    "rtrw_net"                                            : "Pindah Provider - RT/RW Net",
    "xl_home"                                             : "Pindah Provider - XL Home",
    "iconnet"                                             : "Pindah Provider - Iconnet",
    "first_media"                                         : "Pindah Provider - First Media",
    "starlink"                                            : "Pindah Provider - Starlink",
    "indosat_hifi"                                        : "Pindah Provider - Indosat HiFi",
    "indihome"                                            : "Pindah Provider - IndiHome",
    "indiBiz"                                             : "Pindah Provider - IndiBiz",

    # ── Tidak Digunakan ──────────────────────────────────────────────────
    "no_internet_user_retired_deceased"                   : "Tidak Digunakan - Tidak ada pengguna internet (pensiun/meninggal)",

    # ── Faktor Ekonomi dan Produk ────────────────────────────────────────
    "Rumah_Usaha_Kantor_tutup_sewa_habis"                 : "Faktor Ekonomi dan Produk - Rumah/Usaha/Kantor tutup/sewa habis",
    "harga_terlalu_mahal"                                 : "Faktor Ekonomi dan Produk - Harga terlalu mahal",
    "mengurangi_jumlah_sambungan_indiHome_eksisting"       : "Faktor Ekonomi dan Produk - Mengurangi jml sambungan IndiHome eksisting",
    "contract_apc_ended"                                  : "Faktor Ekonomi dan Produk - Kontrak/APC berakhir",
    "merasa_ada_perubahan_struktur_paket_harga_sepihak"    : "Faktor Ekonomi dan Produk - Perubahan struktur paket/harga sepihak",
    "stopped_cannot_afford"                               : "Faktor Ekonomi dan Produk - Tidak mampu membayar",

    # ── Kualitas Produk/Layanan ──────────────────────────────────────────
    "sering_gangguan_penangganan_lama"                    : "Kualitas Produk/Layanan - Sering Gangguan/Penangganan Lama",
    "kualita_sinyal_internet_buruk"                       : "Kualitas Produk/Layanan - Kualitas sinyal internet buruk",
    "disappointing_service"                               : "Kualitas Produk/Layanan - Layanan mengecewakan",

    # ── Lainnya ──────────────────────────────────────────────────────────
    "force_majeure"                                       : "Lainnya - Force Majeure",
    "pengajuan_caps_dari_ctb_law_firm"                    : "Lainnya - Pengajuan CAPS dari CTB/Law Firm",
    "pengajuan_caps_bukan_dari_pemilik"                   : "Lainnya - Pengajuan CAPS bukan dari pemilik",
    "cabin_management"                                    : "Lainnya - Cabin Management",
    "cabut_karena_proses_modoroso_gagal"                  : "Lainnya - Cabut karena proses MoDoRoSo gagal",
}


def pretty_reason(code) -> str:
    """Label tampil untuk sebuah kode reason. Kode tak dikenal -> Title Case."""
    c = str(code or "").strip()
    if not c:
        return "Tidak Diisi"
    if c in REASON_LABEL:
        return REASON_LABEL[c]
    # lookup case-insensitive sebelum menyerah ke prettify generik
    for k, v in REASON_LABEL.items():
        if k.lower() == c.lower():
            return v
    return c.replace("_", " ").strip().title()


def _prep(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["branch"]            = df["branch"].fillna("").astype(str).str.strip().str.upper()
    df["bb_id"]             = df["bb_id"].astype(str).str.strip()
    df["deactivation_date"] = pd.to_datetime(df["deactivation_date"], errors="coerce")
    df["reason"]            = df["reason"].fillna("").astype(str).str.strip()
    return df


def _slice_mtd(df: pd.DataFrame, tgl_awal: date, tgl_akhir: date) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["deactivation_date"] >= pd.Timestamp(tgl_awal)) & \
           (df["deactivation_date"] <= pd.Timestamp(tgl_akhir))
    return df[mask]


def _counts(df: pd.DataFrame, branch: str | None) -> tuple[dict, int]:
    """
    Return ({reason_code: jml_distinct_bb_id}, total_distinct_bb_id).
    branch=None -> seluruh region.
    """
    if df.empty:
        return {}, 0
    sub = df if branch is None else df[df["branch"] == branch]
    if sub.empty:
        return {}, 0
    per_reason = sub.groupby("reason")["bb_id"].nunique().to_dict()
    return per_reason, int(sub["bb_id"].nunique())


def _mom(m, m1):
    if m1:
        return round((m - m1) / m1 * 100, 2)
    return None


def _top_rows(cnt_ini: dict, total_ini: int, cnt_lalu: dict) -> list[dict]:
    """Top-N reason by MtD; di-pad sampai TOP_N supaya tinggi blok seragam."""
    ranked = sorted(cnt_ini.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]

    rows = []
    for i, (code, jml) in enumerate(ranked, start=1):
        jml_l = int(cnt_lalu.get(code, 0))
        rows.append({
            "no"     : i,
            "code"   : code,
            "reason" : pretty_reason(code),
            "m1"     : jml_l,
            "mtd"    : int(jml),
            "cont"   : round(jml / total_ini * 100, 2) if total_ini else None,
            "mom"    : _mom(int(jml), jml_l),
        })

    for i in range(len(rows) + 1, TOP_N + 1):
        rows.append({"no": i, "code": None, "reason": "-",
                     "m1": None, "mtd": None, "cont": None, "mom": None})
    return rows


def hitung_caps_reason(tgl_closing: date) -> dict:
    bp_ini  = tgl_closing.replace(day=1)
    bp_lalu = bp_ini - relativedelta(months=1)

    tabel_ini  = f"retensi_dd_{bp_ini.strftime('%Y%m')}"
    tabel_lalu = f"retensi_dd_{bp_lalu.strftime('%Y%m')}"

    raw_ini  = _prep(db.query_retensi_do(tabel_ini))
    raw_lalu = _prep(db.query_retensi_do(tabel_lalu))

    # cutoff dipotong ke tanggal data terakhir yang ada (lihat penjelasan di
    # calculator_caps_channel.cutoff_efektif) — dipakai bareng supaya report
    # by Channel & by Reason selalu berhenti di tanggal yang sama
    tgl_efektif  = cutoff_efektif(raw_ini, tgl_closing)
    hari_max     = calendar.monthrange(bp_lalu.year, bp_lalu.month)[1]
    tgl_mtd_lalu = date(bp_lalu.year, bp_lalu.month, min(tgl_efektif.day, hari_max))

    df_ini  = _slice_mtd(raw_ini,  bp_ini,  tgl_efektif)
    df_lalu = _slice_mtd(raw_lalu, bp_lalu, tgl_mtd_lalu)

    # Branch yang ditampilkan: BRANCH_ORDER + branch tak terduga yang muncul di data
    extra = sorted(
        {b for b in (set(df_ini["branch"]) if not df_ini.empty else set())
         if b and b not in BRANCH_ORDER}
    )
    branch_names = BRANCH_ORDER + extra

    blocks = []
    for branch in branch_names:
        cnt_i, tot_i = _counts(df_ini,  branch)
        cnt_l, tot_l = _counts(df_lalu, branch)
        blocks.append({
            "level"  : "BRANCH",
            "name"   : branch,
            "total"  : tot_i,
            "total_l": tot_l,
            "mom"    : _mom(tot_i, tot_l),
            "rows"   : _top_rows(cnt_i, tot_i, cnt_l),
        })

    cnt_i, tot_i = _counts(df_ini,  None)
    cnt_l, tot_l = _counts(df_lalu, None)
    region_block = {
        "level"  : "REGION",
        "name"   : REGION_NAME,
        "total"  : tot_i,
        "total_l": tot_l,
        "mom"    : _mom(tot_i, tot_l),
        "rows"   : _top_rows(cnt_i, tot_i, cnt_l),
    }
    blocks.append(region_block)

    return {
        "tgl_closing": tgl_efektif,          # tanggal yang benar-benar dihitung
        "tgl_diminta": tgl_closing,          # tanggal di perintah /caps
        "tgl_mundur" : tgl_efektif < tgl_closing,
        "bi_label"   : bp_ini.strftime("%b %Y").upper(),
        "bl_label"   : bp_lalu.strftime("%b %Y").upper(),
        "blocks"     : blocks,
        "region"     : region_block,
        "top_n"      : TOP_N,
    }
