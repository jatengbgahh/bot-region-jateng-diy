"""
calculator_performance.py — Kalkulasi report "SF Performance Tracking" (/performance),
native Python — reimplementasi dari logika JS di
Septian/SF_Performance_Report_22.html (dulu manual: buka HTML di browser, upload
file, klik Generate, screenshot/download per section).

PHASE 1 SCOPE (lihat plan): Section 0-4 (Tab 1) — Ringkasan Eksekutif,
Process Morning Briefing, Process DJP, Result, SF Tidak Lanjut MB/DJP/Active PS.
PHASE 3 SCOPE: Report SAPA (tab terpisah, 1 periode saja — TIDAK ada M/M-1,
lihat blok SAPA di bawah). Section 5-6 (Daily Monitoring, butuh breakdown
per-tanggal), All Parameter WOW/MoM, dan drill-down per-SF (butuh
sfActivityMap/sfIdentityMap + visits/entries mentah) BELUM diporting — menyusul
di fase berikutnya, lihat roadmap di plan.

Konsep inti (MTD apple-to-apple), identik dengan HTML:
  M   = tanggal 1 s/d cutoffDate bulan berjalan
  M-1 = tanggal 1 s/d hari-ke-N yang sama bulan sebelumnya (N dibatasi jumlah
        hari bulan sebelumnya kalau lebih pendek)
Semua rasio (%SF MB/DJP/Active PS) dibagi SF REG (dari Data SF Master kalau ada,
fallback estimasi dari SF unik di approve-tugas). MoM dihitung sebagai
pertumbuhan RELATIF ((M-M1)/M1), bukan selisih poin persentase — lihat
komentar fmtPctPt di HTML (html:1138-1155) untuk alasannya.
"""
import re
from datetime import date
from calendar import monthrange

import pandas as pd

import config
targets = None

# ==============================================================================
# KONSTANTA (urutan tabel, target kebijakan) — port verbatim dari HTML
# ==============================================================================

# WOK yang sengaja dikeluarkan dari report (proyek ekspansi terpisah, bukan
# tracking harian rutin) — html:369-370.
EXCLUDED_WOK = {"TEGAL BREBES GREENFIELD"}

# Urutan Branch di tabel — SAMA PERSIS dengan config.BRANCH_ORDER (dicek manual).
BRANCH_SORT_ORDER = list(config.BRANCH_ORDER)

# Urutan WOK di tabel report ini — CATATAN PENTING: urutan di dalam tiap Branch
# BERBEDA dari config.WOK_ORDER (yang dipakai /sf, /djp, dll.) — html:2090-2097
# eksplisit menomorkan urutan WOK per Branch mengikuti kebiasaan tabel "SF
# Performance Tracking" ini secara spesifik (dikonfirmasi user 2026-07-16),
# BUKAN salah ketik. JANGAN diganti ke config.WOK_ORDER — akan mismatch dengan
# reference PNG.
WOK_SORT_ORDER = [
    "KEBUMEN", "MAGELANG TEMANGGUNG",                          # Branch Magelang
    "PEMALANG PURBALINGGA", "BATANG", "TEGAL BREBES",          # Branch Pekalongan
    "CILACAP BANYUMAS", "WONOSOBO BANJARNEGARA",                # Branch Purwokerto
    "SEMARANG 2", "SEMARANG 1", "DEMAK", "JEPARA KUDUS - PATI",  # Branch Semarang
    "SRAGEN", "SURAKARTA", "BOYOLALI",                          # Branch Surakarta
    "YOGYA 2", "YOGYA 1",                                       # Branch Yogyakarta
]

REGION_NAME = config.REGION_NAME  # "JATENG-DIY" — dipakai sbg focus_region default

# Target kebijakan tetap (html:3412-3422) — bukan angka bulanan, jadi tidak
# lewat sf_performance_targets.py.
KPI_TARGET = {
    "mb_pct": 1.00,
    "djp_pct": 0.90,
    "djp_per_sf_day": 3,
    "ps_active_pct": 0.85,
    "ps_productivity": 8,
}
KPI_GAP_THRESHOLD_PCT = 0.05

# Target Section 4 (SF Tidak Lanjut) — html:1584.
CHURN_TARGET = {"MB": 0.0, "DJP": 0.0, "PS": 0.05}

WOK_STATUS_COLOR = {
    "Dorong MB": "#B71C1C", "Dorong DJP": "#E65100", "Naikkan Intensitas DJP": "#BF360C",
    "Dorong Closing PS": "#8B1E2E", "Naikkan Productivity": "#F2B705", "On Track": "#1B5E20",
}

INDO_MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
               "Agustus", "September", "Oktober", "November", "Desember"]
EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def _norm_region_key(s) -> str:
    return re.sub(r"[\s\-]+", "", str(s or "").strip().upper())


PS_TARGET_REGION_KEY = _norm_region_key("JATENG DIY")


# ==============================================================================
# DETEKSI JENIS FILE — port dari handleFile() html:964-990
# ==============================================================================
def detect_file_kind(filename: str, df: pd.DataFrame, sheet_name: str = None) -> str | None:
    """Return 'ps' | 'tugas' | 'sf_master' | None — dari ISI kolom, bukan nama file."""
    fname = (filename or "").lower()
    cols_lower = {str(c).strip().lower() for c in df.columns}

    if fname.endswith((".xlsx", ".xls")):
        has_status = any(c in cols_lower for c in ("status",))
        has_kode = any(c in cols_lower for c in ("kode",))
        has_region = any(c in cols_lower for c in ("region",))
        if has_status and has_kode and has_region:
            return "sf_master"
        return None

    if "total_order" in cols_lower and ("date_ps" in cols_lower or "year_month_ps" in cols_lower):
        return "ps"
    if any("tugas id" in c or "schedule category" in c for c in cols_lower):
        return "tugas"
    # ── Report SAPA (Phase 3) — 3 file tambahan opsional, sama pola auto-detect ──
    if "flag visit" in cols_lower and "flag approval" in cols_lower:
        return "sapa_survey"
    if "status cycle" in cols_lower and "jml follow up" in cols_lower:
        return "sapa_prospect"
    if "assignment date" in cols_lower and "odp name" in cols_lower:
        return "sapa_assign"
    return None


def pick_sf_master_sheet(sheet_names: list) -> str:
    for name in sheet_names:
        if "salesforce" in name.lower():
            return name
    return sheet_names[0]


# ==============================================================================
# NORMALISASI TANGGAL — port dateOnly() html:353-364. Header approve-tugas
# pernah kejadian CAMPUR format ISO & DD/MM/YYYY dalam 1 file yang sama (lihat
# komentar HTML html:339-352) — JANGAN shortcut pakai str[:10] tanpa deteksi.
# ==============================================================================
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")


def date_only(s) -> str | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    txt = str(s).strip()
    if not txt or txt.lower() == "nat":
        return None
    m = _ISO_RE.match(txt)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _SLASH_RE.match(txt)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    # Timestamp pandas (mis. dari xlsx tanggal asli) sudah berupa Timestamp,
    # bukan string — tangani lewat isoformat kalau ISO regex di atas tidak match.
    if hasattr(s, "strftime"):
        return s.strftime("%Y-%m-%d")
    return None


def _find_col(columns, candidates) -> str | None:
    norm = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand in norm:
            return norm[cand]
    for cand in candidates:
        for low, orig in norm.items():
            if cand in low:
                return orig
    return None


def _s(v) -> str:
    """Konversi nilai sel (bisa NaN pandas untuk kolom kosong) jadi string aman.
    PENTING: JANGAN pakai idiom `str(v or "")` — pandas NaN (float) itu TRUTHY
    di Python (`bool(float('nan')) is True`), jadi `v or ""` tidak pernah jatuh
    ke fallback "" utk sel kosong, hasilnya malah string literal "nan" yang lolos
    filter `if not sf`. Bug nyata: baris PS non-SF (GRAPARI/WEB&APP/B2B2C, sf_code
    kosong) kebaca sf="nan" (truthy) alih-alih di-skip, Total PS jadi ~17% kegedean
    saat divalidasi vs Septian/SF_Performance_Result_2026-08-11.png (2026-08-12)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _is_excluded_wok(wok: str) -> bool:
    return str(wok or "").strip().upper() in EXCLUDED_WOK


# ==============================================================================
# NORMALISASI BARIS — port normPsRows/normTugasRows/normSfMasterRows html:372-443
# ==============================================================================
def norm_ps_rows(df: pd.DataFrame) -> list:
    cols = df.columns
    c_region = _find_col(cols, ["region"])
    c_branch = _find_col(cols, ["branch"])
    c_wok = _find_col(cols, ["wok"])
    c_sf = _find_col(cols, ["sf_code"])
    c_order = _find_col(cols, ["total_order"])
    c_date = _find_col(cols, ["date_ps", "year_month_ps"])
    out = []
    for _, row in df.iterrows():
        region = _s(row.get(c_region))
        branch = _s(row.get(c_branch))
        wok = _s(row.get(c_wok))
        sf = _s(row.get(c_sf))
        order = pd.to_numeric(row.get(c_order, 0), errors="coerce")
        order = 0 if pd.isna(order) else float(order)
        dt = date_only(row.get(c_date))
        if not region or not dt or not sf:
            continue
        if _is_excluded_wok(wok):
            continue
        out.append({"region": region, "branch": branch, "wok": wok, "sf": sf,
                     "order": order, "date": dt})
    return out


def norm_tugas_rows(df: pd.DataFrame) -> list:
    cols = df.columns
    c_status = _find_col(cols, ["status"])
    c_region = _find_col(cols, ["region"])
    c_branch = _find_col(cols, ["branch"])
    c_wok = _find_col(cols, ["wok"])
    c_sf = _find_col(cols, ["user code"])
    c_sf_name = _find_col(cols, ["user name"])
    c_category = _find_col(cols, ["schedule category"])
    c_date = _find_col(cols, ["tugas date"])
    c_odp = _find_col(cols, ["odp"])
    out = []
    for _, row in df.iterrows():
        if _s(row.get(c_status)).upper() != "APPROVED":
            continue
        region = _s(row.get(c_region))
        branch = _s(row.get(c_branch))
        wok = _s(row.get(c_wok))
        sf = _s(row.get(c_sf))
        sf_name = _s(row.get(c_sf_name))
        category = _s(row.get(c_category)).upper()
        dt = date_only(row.get(c_date))
        odp = _s(row.get(c_odp))
        if not region or not sf or not dt:
            continue
        if _is_excluded_wok(wok):
            continue
        out.append({"region": region, "branch": branch, "wok": wok, "sf": sf,
                     "sf_name": sf_name, "category": category, "date": dt, "odp": odp})
    return out


def norm_sf_master_rows(df: pd.DataFrame) -> list:
    cols = df.columns
    c_status = _find_col(cols, ["status"])
    c_region = _find_col(cols, ["region"])
    c_branch = _find_col(cols, ["branch"])
    c_wok = _find_col(cols, ["wok"])
    c_kode = _find_col(cols, ["kode"])
    c_nama = _find_col(cols, ["nama"])
    c_agency = _find_col(cols, ["agency"])
    c_tl_nama = _find_col(cols, ["team leader"])
    c_tl_kode = _find_col(cols, ["kode team leader"])
    out = []
    for _, row in df.iterrows():
        status = _s(row.get(c_status)).upper()
        if status != "ACTIVE":
            continue
        region = _s(row.get(c_region))
        kode = _s(row.get(c_kode))
        if not region or not kode:
            continue
        wok = _s(row.get(c_wok))
        if _is_excluded_wok(wok):
            continue
        out.append({
            "region": region, "branch": _s(row.get(c_branch)),
            "wok": wok, "sf": kode,
            "nama": _s(row.get(c_nama)),
            "agency": _s(row.get(c_agency)),
            "tl_nama": _s(row.get(c_tl_nama)),
            "tl_kode": _s(row.get(c_tl_kode)),
        })
    return out


# ==============================================================================
# RENTANG MTD APPLE-TO-APPLE — port computeRanges() html:661-672
# ==============================================================================
def compute_ranges(cutoff_date: date) -> dict:
    y, m, d = cutoff_date.year, cutoff_date.month, cutoff_date.day
    m_start = f"{y:04d}-{m:02d}-01"
    m_end = cutoff_date.strftime("%Y-%m-%d")
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    days_in_prev_month = monthrange(py, pm)[1]
    n_days_m1 = min(d, days_in_prev_month)
    pm_start = f"{py:04d}-{pm:02d}-01"
    pm_end = f"{py:04d}-{pm:02d}-{n_days_m1:02d}"
    return {"mStart": m_start, "mEnd": m_end, "pmStart": pm_start, "pmEnd": pm_end,
            "nDaysM": d, "nDaysM1": n_days_m1}


def _in_range(dt: str, start: str, end: str) -> bool:
    return start <= dt <= end


# ==============================================================================
# LEVEL KEY / URUTAN — port levelKey/levelKeysFromAll/customOrderCompare
# html:608-642, 2098-2107
# ==============================================================================
def level_key(level: str, row: dict) -> str:
    if level == "region":
        return row["region"]
    if level == "branch":
        return f"{row['region']}|{row['branch']}"
    return f"{row['region']}|{row['branch']}|{row['wok']}"


def _custom_order_compare_key(order_list):
    def keyfn(value: str):
        v = str(value or "").strip().upper()
        idx = order_list.index(v) if v in order_list else None
        return (0, idx) if idx is not None else (1, v)
    return keyfn


def level_keys_from_all(row_lists: list, level: str, focus_region: str) -> list:
    keys = set()
    for rows in row_lists:
        if not rows:
            continue
        for row in rows:
            if level == "region":
                if row["region"]:
                    keys.add(row["region"])
            elif level == "branch":
                if row["region"] == focus_region and row["branch"]:
                    keys.add(level_key("branch", row))
            elif level == "wok":
                if row["region"] == focus_region and row["branch"] and row["wok"]:
                    keys.add(level_key("wok", row))
    keys = list(keys)
    if level == "branch":
        keys.sort(key=lambda k: _custom_order_compare_key(BRANCH_SORT_ORDER)(k.split("|")[1]))
    elif level == "wok":
        keys.sort(key=lambda k: (
            _custom_order_compare_key(BRANCH_SORT_ORDER)(k.split("|")[1]),
            _custom_order_compare_key(WOK_SORT_ORDER)(k.split("|")[2]),
        ))
    else:
        keys.sort()
    return keys


# ==============================================================================
# SF REG SETS — port buildSfRegSets() html:645-656
# ==============================================================================
def build_sf_reg_sets(sf_master_rows: list, tugas_rows: list, level: str, focus_region: str) -> dict:
    sets = {}
    source = sf_master_rows if sf_master_rows else tugas_rows
    for row in source:
        if level != "region" and row["region"] != focus_region:
            continue
        key = level_key(level, row)
        sets.setdefault(key, set()).add(row["sf"])
    return sets


# ==============================================================================
# AGGREGASI PER LEVEL — port buildLevelAgg()/buildRows() html:675-804
# ==============================================================================
def _pct(n, d):
    return (n / d) if d > 0 else 0.0


def build_level_agg(tugas_rows: list, ps_rows: list, level: str, focus_region: str,
                     ranges: dict, sf_reg_sets: dict) -> dict:
    m_start, m_end = ranges["mStart"], ranges["mEnd"]
    pm_start, pm_end = ranges["pmStart"], ranges["pmEnd"]
    mb, djp, ps = {}, {}, {}

    def ensure(d, key, factory):
        if key not in d:
            d[key] = factory()
        return d[key]

    for row in tugas_rows:
        if level != "region" and row["region"] != focus_region:
            continue
        key = level_key(level, row)
        in_m = _in_range(row["date"], m_start, m_end)
        in_m1 = _in_range(row["date"], pm_start, pm_end)
        if not in_m and not in_m1:
            continue
        if row["category"] == "BRIEFING":
            rec = ensure(mb, key, lambda: {"m": set(), "m1": set()})
            if in_m:
                rec["m"].add(row["sf"])
            if in_m1:
                rec["m1"].add(row["sf"])
        elif row["category"] == "DJP":
            rec = ensure(djp, key, lambda: {"m": set(), "m1": set(), "countM": 0, "countM1": 0})
            if in_m:
                rec["m"].add(row["sf"])
                rec["countM"] += 1
            if in_m1:
                rec["m1"].add(row["sf"])
                rec["countM1"] += 1

    for row in ps_rows:
        if level != "region" and row["region"] != focus_region:
            continue
        key = level_key(level, row)
        in_m = _in_range(row["date"], m_start, m_end)
        in_m1 = _in_range(row["date"], pm_start, pm_end)
        if not in_m and not in_m1:
            continue
        rec = ensure(ps, key, lambda: {"m": set(), "m1": set(), "totalM": 0.0, "totalM1": 0.0})
        if in_m:
            rec["totalM"] += row["order"]
            if row["order"] > 0 and row["sf"]:
                rec["m"].add(row["sf"])
        if in_m1:
            rec["totalM1"] += row["order"]
            if row["order"] > 0 and row["sf"]:
                rec["m1"].add(row["sf"])

    return {"sfRegSets": sf_reg_sets, "mb": mb, "djp": djp, "ps": ps}


def build_rows(agg: dict, keys: list, n_days_m: int, n_days_m1: int) -> list:
    rows = []
    for key in keys:
        sf_reg_set = agg["sfRegSets"].get(key, set())
        sf_reg = len(sf_reg_set)
        in_reg = lambda sf: sf in sf_reg_set

        mb_rec = agg["mb"].get(key)
        mb_m_list = [sf for sf in (mb_rec["m"] if mb_rec else set()) if in_reg(sf)]
        mb_m1_list = list(mb_rec["m1"]) if mb_rec else []
        mb_m, mb_m1 = len(mb_m_list), len(mb_m1_list)

        djp_rec = agg["djp"].get(key)
        djp_sf_m_list = [sf for sf in (djp_rec["m"] if djp_rec else set()) if in_reg(sf)]
        djp_sf_m1_list = list(djp_rec["m1"]) if djp_rec else []
        djp_sf_m, djp_sf_m1 = len(djp_sf_m_list), len(djp_sf_m1_list)
        djp_total_m = djp_rec["countM"] if djp_rec else 0
        djp_total_m1 = djp_rec["countM1"] if djp_rec else 0

        ps_rec = agg["ps"].get(key)
        ps_sf_m_list = [sf for sf in (ps_rec["m"] if ps_rec else set()) if in_reg(sf)]
        ps_sf_m1_list = list(ps_rec["m1"]) if ps_rec else []
        ps_sf_m, ps_sf_m1 = len(ps_sf_m_list), len(ps_sf_m1_list)
        ps_total_m = ps_rec["totalM"] if ps_rec else 0.0
        ps_total_m1 = ps_rec["totalM1"] if ps_rec else 0.0

        rows.append({
            "key": key, "sfReg": sf_reg, "sfRegList": list(sf_reg_set),
            "mb": {"m1": mb_m1, "m": mb_m, "pctM1": _pct(mb_m1, sf_reg), "pctM": _pct(mb_m, sf_reg),
                   "m1List": mb_m1_list, "mList": mb_m_list},
            "djp": {"sfM1": djp_sf_m1, "sfM": djp_sf_m, "pctM1": _pct(djp_sf_m1, sf_reg), "pctM": _pct(djp_sf_m, sf_reg),
                    "totalM1": djp_total_m1, "totalM": djp_total_m,
                    "perSfDayM1": (djp_total_m1 / djp_sf_m1 / n_days_m1) if djp_sf_m1 > 0 else 0.0,
                    "perSfDayM": (djp_total_m / djp_sf_m / n_days_m) if djp_sf_m > 0 else 0.0,
                    "sfM1List": djp_sf_m1_list, "sfMList": djp_sf_m_list},
            "ps": {"sfM1": ps_sf_m1, "sfM": ps_sf_m, "pctM1": _pct(ps_sf_m1, sf_reg), "pctM": _pct(ps_sf_m, sf_reg),
                   "totalM1": ps_total_m1, "totalM": ps_total_m,
                   "prodM1": (ps_total_m1 / sf_reg) if sf_reg > 0 else 0.0,
                   "prodM": (ps_total_m / sf_reg) if sf_reg > 0 else 0.0,
                   "sfM1List": ps_sf_m1_list, "sfMList": ps_sf_m_list},
        })
    return rows


def compute_total_row(rows: list, n_days_m: int, n_days_m1: int) -> dict | None:
    """Port computeTotalRow() html:1177-1223 (versi ringkas Phase 1, tanpa daily/visits/entries).
    Dipanggil per tabel (region/branch/wok) dengan rows list tabel itu sendiri —
    TOTAL Region Benchmark = jumlah SEMUA region, TOTAL Detail Branch/WOK = jumlah
    branch/wok di focus_region saja (sama seperti HTML)."""
    if not rows:
        return None
    sf_reg = sum(r["sfReg"] for r in rows)

    def union_list(fn):
        s = set()
        for r in rows:
            s.update(fn(r) or [])
        return list(s)

    mb_m1, mb_m = sum(r["mb"]["m1"] for r in rows), sum(r["mb"]["m"] for r in rows)
    djp_sf_m1, djp_sf_m = sum(r["djp"]["sfM1"] for r in rows), sum(r["djp"]["sfM"] for r in rows)
    djp_total_m1, djp_total_m = sum(r["djp"]["totalM1"] for r in rows), sum(r["djp"]["totalM"] for r in rows)
    ps_sf_m1, ps_sf_m = sum(r["ps"]["sfM1"] for r in rows), sum(r["ps"]["sfM"] for r in rows)
    ps_total_m1, ps_total_m = sum(r["ps"]["totalM1"] for r in rows), sum(r["ps"]["totalM"] for r in rows)

    return {
        "key": "TOTAL", "sfReg": sf_reg, "sfRegList": union_list(lambda r: r["sfRegList"]),
        "mb": {"m1": mb_m1, "m": mb_m, "pctM1": _pct(mb_m1, sf_reg), "pctM": _pct(mb_m, sf_reg),
               "m1List": union_list(lambda r: r["mb"]["m1List"]), "mList": union_list(lambda r: r["mb"]["mList"])},
        "djp": {"sfM1": djp_sf_m1, "sfM": djp_sf_m, "pctM1": _pct(djp_sf_m1, sf_reg), "pctM": _pct(djp_sf_m, sf_reg),
                "totalM1": djp_total_m1, "totalM": djp_total_m,
                "perSfDayM1": (djp_total_m1 / djp_sf_m1 / n_days_m1) if djp_sf_m1 > 0 else 0.0,
                "perSfDayM": (djp_total_m / djp_sf_m / n_days_m) if djp_sf_m > 0 else 0.0,
                "sfM1List": union_list(lambda r: r["djp"]["sfM1List"]), "sfMList": union_list(lambda r: r["djp"]["sfMList"])},
        "ps": {"sfM1": ps_sf_m1, "sfM": ps_sf_m, "pctM1": _pct(ps_sf_m1, sf_reg), "pctM": _pct(ps_sf_m, sf_reg),
               "totalM1": ps_total_m1, "totalM": ps_total_m,
               "prodM1": (ps_total_m1 / sf_reg) if sf_reg > 0 else 0.0,
               "prodM": (ps_total_m / sf_reg) if sf_reg > 0 else 0.0,
               "sfM1List": union_list(lambda r: r["ps"]["sfM1List"]), "sfMList": union_list(lambda r: r["ps"]["sfMList"])},
    }


# ==============================================================================
# RANKING — port denseRankDesc/attachAllRanks html:1241-1274
# ==============================================================================
def _dense_rank_desc(values: list) -> list:
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    ranks = [0] * len(values)
    rank, prev = 0, None
    for idx, i in enumerate(order):
        v = values[i]
        if prev is None or v != prev:
            rank = idx + 1
            prev = v
        ranks[i] = rank
    return ranks


def ps_mom_total(r) -> float:
    return ((r["ps"]["totalM"] - r["ps"]["totalM1"]) / r["ps"]["totalM1"]) if r["ps"]["totalM1"] > 0 else float("-inf")


def ps_ach_to_target(r, total_region_ctx, target_month: str):
    t = ps_target_for_row(r, total_region_ctx, target_month)
    return (r["ps"]["totalM"] / t) if (isinstance(t, (int, float)) and t > 0) else None


def attach_all_ranks(rows: list, total_region_ctx, target_month: str):
    r_mb = _dense_rank_desc([r["mb"]["pctM"] for r in rows])
    r_djp = _dense_rank_desc([r["djp"]["pctM"] for r in rows])
    r_ps_active = _dense_rank_desc([r["ps"]["pctM"] for r in rows])
    for i, r in enumerate(rows):
        r["rankMb"], r["rankDjp"], r["rankPsActive"] = r_mb[i], r_djp[i], r_ps_active[i]

    with_target = [(i, ps_ach_to_target(r, total_region_ctx, target_month)) for i, r in enumerate(rows)]
    with_target = [(i, ach) for i, ach in with_target if ach is not None]
    ach_ranks = _dense_rank_desc([ach for _, ach in with_target])
    for r in rows:
        r.pop("rankPsAch", None)
    for (i, _), rank in zip(with_target, ach_ranks):
        rows[i]["rankPsAch"] = rank


# ==============================================================================
# TARGET KPI (PS_TARGET_BY_MONTH) — port psTargetForRow/psTargetSumForWoks
# html:1457-1509
# ==============================================================================
def ps_target_sum_for_woks(woks: list, target_month: str):
    active_wok = targets.PS_TARGET_BY_MONTH.get(target_month)
    if not active_wok:
        return None
    total, any_found = 0, False
    for wok in woks:
        rec = active_wok.get(wok)
        if rec and isinstance(rec.get("t"), (int, float)):
            total += rec["t"]
            any_found = True
    return total if any_found else None


def ps_target_for_row(r, total_region_ctx, target_month: str):
    """total_region_ctx: nama region yang direpresentasikan baris TOTAL (isi
    focus_region utk tabel Branch/WOK, None utk tabel Region Benchmark)."""
    key = r["key"]
    if key == "TOTAL":
        region = total_region_ctx
    elif "|" not in key:
        region = key
    else:
        region = key.split("|")[0]

    if _norm_region_key(region) != PS_TARGET_REGION_KEY:
        return None
    active_wok = targets.PS_TARGET_BY_MONTH.get(target_month)
    if not active_wok:
        return None

    if key == "TOTAL" or "|" not in key:
        return ps_target_sum_for_woks(list(active_wok.keys()), target_month)
    parts = key.split("|")
    if len(parts) == 2:
        branch = parts[1].strip().upper()
        woks = [w for w, rec in active_wok.items() if rec["branch"] == branch]
        return ps_target_sum_for_woks(woks, target_month)
    wok = parts[2].strip().upper()
    return ps_target_sum_for_woks([wok], target_month)


# ==============================================================================
# BUILD REPORT — port computeReport() html:877-928 (versi Phase 1, tanpa daily
# breakdown & sfActivityMap/sfIdentityMap)
# ==============================================================================
def build_report(df_ps: pd.DataFrame, df_tugas: pd.DataFrame, df_sf_master: pd.DataFrame | None,
                  focus_region: str, cutoff_date: date) -> dict:
    """df_ps/df_tugas: DataFrame mentah hasil parse file (belum dinormalisasi).
    df_sf_master: DataFrame sheet 'List Salesforce User', atau None kalau opsional
    tidak diupload (SF REG fallback ke estimasi dari approve-tugas)."""
    target_month = cutoff_date.strftime("%Y-%m")
    tugas_rows = norm_tugas_rows(df_tugas)
    ps_rows = norm_ps_rows(df_ps)
    sf_master_rows = norm_sf_master_rows(df_sf_master) if df_sf_master is not None else None
    sf_reg_source = "master" if sf_master_rows else "estimasi"
    ranges = compute_ranges(cutoff_date)

    region_keys = level_keys_from_all([tugas_rows, ps_rows, sf_master_rows], "region", focus_region)
    branch_keys = level_keys_from_all([tugas_rows, ps_rows, sf_master_rows], "branch", focus_region)
    wok_keys = level_keys_from_all([tugas_rows, ps_rows, sf_master_rows], "wok", focus_region)

    region_sf_reg = build_sf_reg_sets(sf_master_rows, tugas_rows, "region", focus_region)
    branch_sf_reg = build_sf_reg_sets(sf_master_rows, tugas_rows, "branch", focus_region)
    wok_sf_reg = build_sf_reg_sets(sf_master_rows, tugas_rows, "wok", focus_region)

    region_agg = build_level_agg(tugas_rows, ps_rows, "region", focus_region, ranges, region_sf_reg)
    branch_agg = build_level_agg(tugas_rows, ps_rows, "branch", focus_region, ranges, branch_sf_reg)
    wok_agg = build_level_agg(tugas_rows, ps_rows, "wok", focus_region, ranges, wok_sf_reg)

    region_rows = build_rows(region_agg, region_keys, ranges["nDaysM"], ranges["nDaysM1"])
    branch_rows = build_rows(branch_agg, branch_keys, ranges["nDaysM"], ranges["nDaysM1"])
    wok_rows = build_rows(wok_agg, wok_keys, ranges["nDaysM"], ranges["nDaysM1"])

    attach_all_ranks(region_rows, None, target_month)
    attach_all_ranks(branch_rows, focus_region, target_month)
    attach_all_ranks(wok_rows, focus_region, target_month)

    all_regions = sorted({r["region"] for r in tugas_rows})

    return {
        "regionRows": region_rows, "branchRows": branch_rows, "wokRows": wok_rows,
        "allRegions": all_regions, "focusRegion": focus_region,
        "cutoffDate": cutoff_date.strftime("%Y-%m-%d"), "targetMonth": target_month,
        "ranges": ranges, "sfRegSource": sf_reg_source,
    }


# ==============================================================================
# CHURN (SF Tidak Lanjut) — port computeChurnList html:1573-1576
# ==============================================================================
def compute_churn_list(m1_list: list, m_list: list) -> list:
    m_set = set(m_list or [])
    return [sf for sf in (m1_list or []) if sf not in m_set]


# ==============================================================================
# FORMAT HELPERS — port fmtPct/fmtPctPt/fmtNum/fmtDec/titleCase/labelOf
# html:1134-1163
# ==============================================================================
def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def fmt_target_pct(x: float) -> str:
    return f"{round(x * 100)}%"


def fmt_pct_pt(m1: float, m: float) -> dict:
    """MoM relatif (bukan selisih poin) — html:1138-1155."""
    if not (m1 > 0):
        return {"txt": "n/a", "pos": None}
    v = (m - m1) / m1
    sign = "+" if v >= 0 else ""
    return {"txt": f"{sign}{v * 100:.1f}%", "pos": v >= 0}


def fmt_num(x: float) -> str:
    return f"{round(x):,}".replace(",", ".")


def fmt_dec(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


def title_case(s: str) -> str:
    return re.sub(r"\w\S*", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), str(s))


def label_of(key: str) -> str:
    return key.split("|")[-1]


def row_label_path(r: dict) -> str:
    if r["key"] == "TOTAL":
        return "TOTAL"
    return " - ".join(title_case(p) for p in r["key"].split("|"))


def period_label(report: dict) -> str:
    r = report["ranges"]
    return f"MTD {r['mStart']} s/d {r['mEnd']} vs MTD {r['pmStart']} s/d {r['pmEnd']}"


def format_indo_date(date_str: str) -> str:
    y, m, d = (int(x) for x in date_str.split("-"))
    return f"{d:02d} {INDO_MONTHS[m - 1]} {y}"


def format_en_date(date_str: str) -> str:
    y, m, d = (int(x) for x in date_str.split("-"))
    return f"{d:02d} {EN_MONTHS[m - 1]} {y}"


def active_target_month_label(target_month: str) -> str:
    try:
        y, m = target_month.split("-")
        return f"{INDO_MONTHS[int(m) - 1]} {y}"
    except Exception:
        return target_month


# ==============================================================================
# WOK STATUS — port computeWokStatus() html:3438-3487
# ==============================================================================
def compute_wok_status(r: dict, total_region_ctx, target_month: str) -> dict:
    gap_mb = KPI_TARGET["mb_pct"] - r["mb"]["pctM"]
    gap_djp = KPI_TARGET["djp_pct"] - r["djp"]["pctM"]
    gap_intensity = KPI_TARGET["djp_per_sf_day"] - r["djp"]["perSfDayM"]
    gap_intensity_rel = gap_intensity / KPI_TARGET["djp_per_sf_day"]
    gap_ps_active = KPI_TARGET["ps_active_pct"] - r["ps"]["pctM"]
    gap_prod = KPI_TARGET["ps_productivity"] - r["ps"]["prodM"]
    gap_prod_rel = gap_prod / KPI_TARGET["ps_productivity"]

    process_candidates = [
        {"tag": "Dorong MB", "gap": gap_mb,
         "detail": f"SF MB {fmt_pct(r['mb']['pctM'])}, GAP {fmt_pct(gap_mb)} dr target {fmt_target_pct(KPI_TARGET['mb_pct'])}",
         "action": "TL pastikan SEMUA SF briefing tiap pagi — cek kehadiran & kualitas arahan."},
        {"tag": "Dorong DJP", "gap": gap_djp,
         "detail": f"SF DJP {fmt_pct(r['djp']['pctM'])}, GAP {fmt_pct(gap_djp)} dr target {fmt_target_pct(KPI_TARGET['djp_pct'])}",
         "action": "MB sudah jalan, dorong SEMUA SF bergerak DJP ke ODP prioritas pilihan TL/SPV."},
        {"tag": "Naikkan Intensitas DJP", "gap": gap_intensity_rel,
         "detail": f"DJP/SF/Day {fmt_dec(r['djp']['perSfDayM'], 1)}, GAP {fmt_dec(max(0, gap_intensity), 1)} dr target min {KPI_TARGET['djp_per_sf_day']}/hari",
         "action": "SF sudah jalan DJP tapi kunjungan per hari kurang — pastikan tiap SF minimal 3 ODP prioritas/hari."},
    ]
    result_candidates = [
        {"tag": "Dorong Closing PS", "gap": gap_ps_active,
         "detail": f"SF Aktif PS {fmt_pct(r['ps']['pctM'])}, GAP {fmt_pct(gap_ps_active)} dr target {fmt_target_pct(KPI_TARGET['ps_active_pct'])}",
         "action": "DJP sudah jalan tapi belum closing — evaluasi kualitas kunjungan & coaching SF."},
        {"tag": "Naikkan Productivity", "gap": gap_prod_rel,
         "detail": f"SF Reg Productivity {fmt_dec(r['ps']['prodM'], 2)} SSL/SF Reg, GAP {fmt_dec(gap_prod, 2)} dr target {KPI_TARGET['ps_productivity']}",
         "action": "Proses & closing sudah oke — perbanyak prospek calon pelanggan melalui door2door, TMW, dll."},
    ]

    significant_process = [c for c in process_candidates if c["gap"] > KPI_GAP_THRESHOLD_PCT]
    if significant_process:
        top = max(significant_process, key=lambda c: c["gap"])
        return {"tag": top["tag"], "detail": top["detail"], "action": top["action"]}

    significant_result = [c for c in result_candidates if c["gap"] > KPI_GAP_THRESHOLD_PCT]
    if significant_result:
        top = max(significant_result, key=lambda c: c["gap"])
        return {"tag": top["tag"], "detail": top["detail"], "action": top["action"]}

    return {
        "tag": "On Track",
        "detail": (f"MB {fmt_pct(r['mb']['pctM'])}, DJP {fmt_pct(r['djp']['pctM'])}, "
                   f"{fmt_dec(r['djp']['perSfDayM'], 1)}/hari, PS {fmt_pct(r['ps']['pctM'])}, "
                   f"Prod {fmt_dec(r['ps']['prodM'], 2)}"),
        "action": "Semua indikator sudah capai/mendekati target — pertahankan momentum.",
    }


# ==============================================================================
# TAKEAWAY BULLETS — port bullet()/bulletPlain() + computeTakeawayMB/DJP/PS/Churn
# html:3106-3382
# ==============================================================================
def bullet(label: str, value: str) -> dict:
    return {"plain": f"• {label}: {value}.", "md": f"• {label}: **{value}**."}


def bullet_plain(text: str) -> dict:
    return {"plain": f"• {text}", "md": f"• {text}"}


def compute_takeaway_mb(report: dict) -> dict:
    wok_rows = report["wokRows"]
    wok_by_pct = sorted(wok_rows, key=lambda r: r["mb"]["pctM"], reverse=True)
    wok_by_mom = sorted(wok_rows, key=lambda r: r["mb"]["pctM"] - r["mb"]["pctM1"], reverse=True)
    branch_by_pct = sorted(report["branchRows"], key=lambda r: r["mb"]["pctM"], reverse=True)
    top = next((r for r in report["regionRows"] if r["key"] == report["focusRegion"]), None)

    key_bullets = []
    if top:
        gap_mb = KPI_TARGET["mb_pct"] - top["mb"]["pctM"]
        if gap_mb > 0.005:
            key_bullets.append(bullet_plain(f"%SF MB region {fmt_pct(top['mb']['pctM'])} — GAP {fmt_pct(gap_mb)} dari target 100%"))
        else:
            key_bullets.append(bullet_plain(f"%SF MB region {fmt_pct(top['mb']['pctM'])} — target 100% tercapai"))
    if wok_by_pct:
        r = wok_by_pct[0]
        key_bullets.append(bullet("WOK %SF MB tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(r['mb']['pctM'])})"))
    if wok_by_mom:
        r = wok_by_mom[0]
        key_bullets.append(bullet("Best MoM %SF MB (WOK)", f"{title_case(label_of(r['key']))} ({fmt_pct_pt(r['mb']['pctM1'], r['mb']['pctM'])['txt']})"))
    if branch_by_pct:
        r = branch_by_pct[0]
        key_bullets.append(bullet("Branch %SF MB tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(r['mb']['pctM'])})"))

    attention_bullets = []
    if wok_by_pct:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_pct(r['mb']['pctM'])})" for r in wok_by_pct[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 %SF Morning Briefing: {bottom3}"))
    return {"keyBullets": key_bullets, "attentionBullets": attention_bullets}


def compute_takeaway_djp(report: dict) -> dict:
    wok_rows = report["wokRows"]
    wok_by_pct = sorted(wok_rows, key=lambda r: r["djp"]["pctM"], reverse=True)
    wok_by_mom_pct = sorted(wok_rows, key=lambda r: r["djp"]["pctM"] - r["djp"]["pctM1"], reverse=True)

    def mom_per_day(r):
        return ((r["djp"]["perSfDayM"] - r["djp"]["perSfDayM1"]) / r["djp"]["perSfDayM1"]) if r["djp"]["perSfDayM1"] > 0 else -999
    wok_by_mom_per_day = sorted(wok_rows, key=mom_per_day, reverse=True)
    branch_by_pct = sorted(report["branchRows"], key=lambda r: r["djp"]["pctM"], reverse=True)
    top = next((r for r in report["regionRows"] if r["key"] == report["focusRegion"]), None)

    key_bullets = []
    if top:
        gap_djp = KPI_TARGET["djp_pct"] - top["djp"]["pctM"]
        if gap_djp > 0.005:
            key_bullets.append(bullet_plain(
                f"%SF DJP region {fmt_pct(top['djp']['pctM'])} — GAP {fmt_pct(gap_djp)} dari target 90%; "
                f"DJP/SF/Day {fmt_dec(top['djp']['perSfDayM'], 1)} (target min 3/hari)"))
        else:
            key_bullets.append(bullet_plain(
                f"%SF DJP region {fmt_pct(top['djp']['pctM'])} — target 90% tercapai; "
                f"DJP/SF/Day {fmt_dec(top['djp']['perSfDayM'], 1)} (target min 3/hari)"))
    if wok_by_pct:
        r = wok_by_pct[0]
        key_bullets.append(bullet("WOK %SF DJP tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(r['djp']['pctM'])})"))
    if wok_by_mom_pct:
        r = wok_by_mom_pct[0]
        key_bullets.append(bullet("Best MoM %SF DJP (WOK)", f"{title_case(label_of(r['key']))} ({fmt_pct_pt(r['djp']['pctM1'], r['djp']['pctM'])['txt']})"))
    if wok_by_mom_per_day:
        r = wok_by_mom_per_day[0]
        key_bullets.append(bullet("Best MoM DJP/SF/Day (WOK)", f"{title_case(label_of(r['key']))} ({fmt_pct_pt(r['djp']['perSfDayM1'], r['djp']['perSfDayM'])['txt']})"))
    if branch_by_pct:
        r = branch_by_pct[0]
        key_bullets.append(bullet("Branch %SF DJP tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(r['djp']['pctM'])})"))

    wok_by_per_day = sorted(wok_rows, key=lambda r: r["djp"]["perSfDayM"], reverse=True)
    attention_bullets = []
    if wok_by_pct:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_pct(r['djp']['pctM'])})" for r in wok_by_pct[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 SF DJP (Aktif): {bottom3}"))
    if wok_by_per_day:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_dec(r['djp']['perSfDayM'])})" for r in wok_by_per_day[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 DJP/SF/Day: {bottom3}"))
    return {"keyBullets": key_bullets, "attentionBullets": attention_bullets}


def compute_takeaway_ps(report: dict) -> dict:
    wok_rows = report["wokRows"]
    target_month = report["targetMonth"]
    wok_by_active = sorted(wok_rows, key=lambda r: r["ps"]["pctM"], reverse=True)
    wok_by_mom_active = sorted(wok_rows, key=lambda r: r["ps"]["pctM"] - r["ps"]["pctM1"], reverse=True)

    def mom_prod(r):
        return ((r["ps"]["prodM"] - r["ps"]["prodM1"]) / r["ps"]["prodM1"]) if r["ps"]["prodM1"] > 0 else -999
    wok_by_mom_prod = sorted(wok_rows, key=mom_prod, reverse=True)
    branch_by_active = sorted(report["branchRows"], key=lambda r: r["ps"]["pctM"], reverse=True)
    top = next((r for r in report["regionRows"] if r["key"] == report["focusRegion"]), None)

    key_bullets = []
    if top:
        t = ps_target_for_row(top, None, target_month)
        if isinstance(t, (int, float)) and t > 0:
            gap_ssl = round(t - top["ps"]["totalM"])
            if gap_ssl > 0:
                key_bullets.append(bullet_plain(
                    f"Total PS region {fmt_num(top['ps']['totalM'])} SSL = {fmt_pct(top['ps']['totalM'] / t)} "
                    f"dari Target KPI {fmt_num(t)} SSL (kurang {fmt_num(gap_ssl)} SSL)"))
            else:
                key_bullets.append(bullet_plain(
                    f"Total PS region {fmt_num(top['ps']['totalM'])} SSL — Target KPI {fmt_num(t)} SSL "
                    f"tercapai ({fmt_pct(top['ps']['totalM'] / t)})"))
        else:
            key_bullets.append(bullet_plain(
                f"Total PS region {fmt_num(top['ps']['totalM'])} SSL ({fmt_pct_pt(top['ps']['totalM1'], top['ps']['totalM'])['txt']} MoM)"))

    wok_by_ach = sorted(
        ((r, ps_ach_to_target(r, None, target_month)) for r in wok_rows),
        key=lambda x: (x[1] is not None, x[1] if x[1] is not None else -1), reverse=True)
    wok_by_ach = [(r, a) for r, a in wok_by_ach if a is not None]
    if wok_by_ach:
        r, ach = wok_by_ach[0]
        key_bullets.append(bullet("WOK Pencapaian Sales (Ach% Target KPI) tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(ach)})"))
    if wok_by_active:
        r = wok_by_active[0]
        key_bullets.append(bullet("WOK SF Active PS Ratio tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(r['ps']['pctM'])})"))
    if wok_by_mom_active:
        r = wok_by_mom_active[0]
        key_bullets.append(bullet("Best MoM Active PS (WOK)", f"{title_case(label_of(r['key']))} ({fmt_pct_pt(r['ps']['pctM1'], r['ps']['pctM'])['txt']})"))
    if wok_by_mom_prod:
        r = wok_by_mom_prod[0]
        key_bullets.append(bullet("Best MoM SF Reg Productivity (WOK)", f"{title_case(label_of(r['key']))} ({fmt_pct_pt(r['ps']['prodM1'], r['ps']['prodM'])['txt']})"))
    if branch_by_active:
        r = branch_by_active[0]
        key_bullets.append(bullet("Branch SF Active PS Ratio tertinggi", f"{title_case(label_of(r['key']))} ({fmt_pct(r['ps']['pctM'])})"))

    wok_by_total = sorted(wok_rows, key=lambda r: r["ps"]["totalM"], reverse=True)
    wok_by_prod = sorted(wok_rows, key=lambda r: r["ps"]["prodM"], reverse=True)
    attention_bullets = []
    if wok_by_ach:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_pct(a)})" for r, a in wok_by_ach[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 Pencapaian Sales (Ach% Target KPI): {bottom3}"))
    if wok_by_active:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_pct(r['ps']['pctM'])})" for r in wok_by_active[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 SF Active PS: {bottom3}"))
    if wok_by_total:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_num(r['ps']['totalM'])})" for r in wok_by_total[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 Total PS: {bottom3}"))
    if wok_by_prod:
        bottom3 = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_dec(r['ps']['prodM'], 2)})" for r in wok_by_prod[-3:][::-1])
        attention_bullets.append(bullet_plain(f"WOK bottom 3 SF Reg Productivity: {bottom3}"))
    return {"keyBullets": key_bullets, "attentionBullets": attention_bullets}


def compute_takeaway_churn(report: dict) -> dict:
    focus_row = next((r for r in report["regionRows"] if r["key"] == report["focusRegion"]), None)

    def churn_cnt(r, m1_key_path, m_key_path):
        m1 = r[m1_key_path[0]][m1_key_path[1]]
        m = r[m_key_path[0]][m_key_path[1]]
        return len(compute_churn_list(m1, m))

    mb_churn = lambda r: churn_cnt(r, ("mb", "m1List"), ("mb", "mList"))
    djp_churn = lambda r: churn_cnt(r, ("djp", "sfM1List"), ("djp", "sfMList"))
    ps_churn = lambda r: churn_cnt(r, ("ps", "sfM1List"), ("ps", "sfMList"))

    def pct_churn(r, ch_fn, base_key_path):
        base = len(r[base_key_path[0]][base_key_path[1]] or [])
        return (ch_fn(r) / base) if base > 0 else 0.0

    pct_mb_churn = lambda r: pct_churn(r, mb_churn, ("mb", "m1List"))
    pct_djp_churn = lambda r: pct_churn(r, djp_churn, ("djp", "sfM1List"))
    pct_ps_churn = lambda r: pct_churn(r, ps_churn, ("ps", "sfM1List"))

    total_churn_mb = mb_churn(focus_row) if focus_row else 0
    total_churn_djp = djp_churn(focus_row) if focus_row else 0
    total_churn_ps = ps_churn(focus_row) if focus_row else 0

    wok_rows = report["wokRows"]
    wok_by_mb_asc = sorted(wok_rows, key=pct_mb_churn)
    wok_by_djp_asc = sorted(wok_rows, key=pct_djp_churn)
    wok_by_ps_asc = sorted(wok_rows, key=pct_ps_churn)

    def base_txt_short(w, ch_fn, base_key_path):
        base = len(w[base_key_path[0]][base_key_path[1]] or [])
        return f"{fmt_num(ch_fn(w))} dari {fmt_num(base)}"

    key_bullets = [bullet(
        f"Total Tidak Lanjut MB/DJP/PS Region {report['focusRegion']}",
        f"{fmt_num(total_churn_mb)} / {fmt_num(total_churn_djp)} / {fmt_num(total_churn_ps)} SF")]
    if wok_by_mb_asc:
        w = wok_by_mb_asc[0]
        key_bullets.append(bullet("Retensi Terbaik MB", f"{title_case(label_of(w['key']))} ({fmt_pct(pct_mb_churn(w))}, {base_txt_short(w, mb_churn, ('mb', 'm1List'))})"))
    if wok_by_djp_asc:
        w = wok_by_djp_asc[0]
        key_bullets.append(bullet("Retensi Terbaik DJP", f"{title_case(label_of(w['key']))} ({fmt_pct(pct_djp_churn(w))}, {base_txt_short(w, djp_churn, ('djp', 'sfM1List'))})"))
    if wok_by_ps_asc:
        w = wok_by_ps_asc[0]
        key_bullets.append(bullet("Retensi Terbaik PS", f"{title_case(label_of(w['key']))} ({fmt_pct(pct_ps_churn(w))}, {base_txt_short(w, ps_churn, ('ps', 'sfM1List'))})"))

    attention_bullets = []
    if wok_by_mb_asc:
        w = wok_by_mb_asc[-1]
        attention_bullets.append(bullet("Perlu Perhatian MB", f"{title_case(label_of(w['key']))} ({fmt_pct(pct_mb_churn(w))}, {base_txt_short(w, mb_churn, ('mb', 'm1List'))})"))
    if wok_by_djp_asc:
        w = wok_by_djp_asc[-1]
        attention_bullets.append(bullet("Perlu Perhatian DJP", f"{title_case(label_of(w['key']))} ({fmt_pct(pct_djp_churn(w))}, {base_txt_short(w, djp_churn, ('djp', 'sfM1List'))})"))
    if wok_by_ps_asc:
        w = wok_by_ps_asc[-1]
        attention_bullets.append(bullet("Perlu Perhatian PS", f"{title_case(label_of(w['key']))} ({fmt_pct(pct_ps_churn(w))}, {base_txt_short(w, ps_churn, ('ps', 'sfM1List'))})"))
    return {"keyBullets": key_bullets, "attentionBullets": attention_bullets}


# ==============================================================================
# NARASI EKSEKUTIF — port computeExecutiveNarrative() html:3609-3674
# Return list of (plain_line, md_line) pairs — plain dipakai renderer PNG (tanpa
# bold), md dipakai caption Telegram (dengan **bold**).
# ==============================================================================
def compute_executive_narrative(report: dict) -> dict:
    top = next((r for r in report["regionRows"] if r["key"] == report["focusRegion"]), None)
    if not top:
        return {"plain": [], "md": []}
    target_month = report["targetMonth"]
    gap_djp = KPI_TARGET["djp_pct"] - top["djp"]["pctM"]
    gap_mb = KPI_TARGET["mb_pct"] - top["mb"]["pctM"]
    gap_ps_active = KPI_TARGET["ps_active_pct"] - top["ps"]["pctM"]
    gap_intensity = KPI_TARGET["djp_per_sf_day"] - top["djp"]["perSfDayM"]

    result_lines_plain, result_lines_md = [], []
    target = ps_target_for_row(top, None, target_month)
    if isinstance(target, (int, float)) and target > 0:
        ach = top["ps"]["totalM"] / target
        gap_ssl = round(target - top["ps"]["totalM"])
        if gap_ssl > 0:
            per_sf_need = (gap_ssl / top["ps"]["sfM"]) if top["ps"]["sfM"] > 0 else 0
            result_lines_plain.append(f"Total PS {fmt_num(top['ps']['totalM'])} SSL = {fmt_pct(ach)} dari Target KPI {fmt_num(target)} SSL — kurang {fmt_num(gap_ssl)} SSL.")
            result_lines_md.append(f"Total PS **{fmt_num(top['ps']['totalM'])}** SSL = **{fmt_pct(ach)}** dari Target KPI {fmt_num(target)} SSL — kurang **{fmt_num(gap_ssl)} SSL**.")
            tail = (f", sambil mengaktifkan SF yang belum jualan (SF Aktif PS baru {fmt_pct(top['ps']['pctM'])}, target {fmt_target_pct(KPI_TARGET['ps_active_pct'])})."
                    if gap_ps_active > 0.005 else ".")
            result_lines_plain.append(f"SF Reg Productivity saat ini {fmt_dec(top['ps']['prodM'], 2)} SSL/SF Reg (target 8): untuk menutup gap, tiap SF aktif ({fmt_num(top['ps']['sfM'])} SF) perlu menambah rata-rata {fmt_dec(per_sf_need, 1)} SSL lagi{tail}")
            result_lines_md.append(f"SF Reg Productivity saat ini {fmt_dec(top['ps']['prodM'], 2)} SSL/SF Reg (target 8): untuk menutup gap, tiap SF aktif ({fmt_num(top['ps']['sfM'])} SF) perlu menambah rata-rata **{fmt_dec(per_sf_need, 1)} SSL** lagi{tail}")
        else:
            result_lines_plain.append(f"Total PS {fmt_num(top['ps']['totalM'])} SSL — Target KPI {fmt_num(target)} SSL tercapai ({fmt_pct(ach)}). Jaga run-rate.")
            result_lines_md.append(f"Total PS **{fmt_num(top['ps']['totalM'])}** SSL — **Target KPI {fmt_num(target)} SSL tercapai ({fmt_pct(ach)})**. Jaga run-rate.")
            result_lines_plain.append(f"SF Reg Productivity {fmt_dec(top['ps']['prodM'], 2)} SSL/SF Reg (target 8), SF Aktif PS {fmt_pct(top['ps']['pctM'])} (target {fmt_target_pct(KPI_TARGET['ps_active_pct'])}).")
            result_lines_md.append(result_lines_plain[-1])
    else:
        line = f"Total PS {fmt_num(top['ps']['totalM'])} SSL ({fmt_pct_pt(top['ps']['totalM1'], top['ps']['totalM'])['txt']} MoM), SF Reg Productivity {fmt_dec(top['ps']['prodM'], 2)} SSL/SF Reg, SF Aktif PS {fmt_pct(top['ps']['pctM'])}."
        result_lines_plain.append(line)
        result_lines_md.append(f"Total PS **{fmt_num(top['ps']['totalM'])}** SSL ({fmt_pct_pt(top['ps']['totalM1'], top['ps']['totalM'])['txt']} MoM), SF Reg Productivity {fmt_dec(top['ps']['prodM'], 2)} SSL/SF Reg, SF Aktif PS {fmt_pct(top['ps']['pctM'])}.")

    if gap_intensity > 0.05:
        intensity_txt_p = f"DJP/SF/Day baru {fmt_dec(top['djp']['perSfDayM'], 1)} dari target min 3 ODP/SF/hari"
        intensity_txt_md = f"DJP/SF/Day baru **{fmt_dec(top['djp']['perSfDayM'], 1)}** dari target min 3 ODP/SF/hari"
    else:
        intensity_txt_p = f"DJP/SF/Day {fmt_dec(top['djp']['perSfDayM'], 1)} — sudah capai min 3/hari"
        intensity_txt_md = f"DJP/SF/Day **{fmt_dec(top['djp']['perSfDayM'], 1)}** — sudah capai min 3/hari"
    if gap_djp > 0.005:
        djp_cov_txt = f"%SF DJP {fmt_pct(top['djp']['pctM'])} ({fmt_pct_pt(top['djp']['pctM1'], top['djp']['pctM'])['txt']} MoM, GAP {fmt_pct(gap_djp)} dari {fmt_target_pct(KPI_TARGET['djp_pct'])})"
    else:
        djp_cov_txt = f"%SF DJP {fmt_pct(top['djp']['pctM'])} — capai target"
    if gap_mb > 0.005:
        mb_txt = f"MB {fmt_pct(top['mb']['pctM'])} ({fmt_pct_pt(top['mb']['pctM1'], top['mb']['pctM'])['txt']} MoM, GAP {fmt_pct(gap_mb)} dari {fmt_target_pct(KPI_TARGET['mb_pct'])})"
    else:
        mb_txt = f"MB {fmt_pct(top['mb']['pctM'])} — capai target"
    process_lines_plain = [f"{intensity_txt_p} ;", f"{djp_cov_txt};", f"{mb_txt}."]
    process_lines_md = [f"{intensity_txt_md} ;", f"{djp_cov_txt};", f"{mb_txt}."]

    churn_mb = len(compute_churn_list(top["mb"]["m1List"], top["mb"]["mList"]))
    churn_djp = len(compute_churn_list(top["djp"]["sfM1List"], top["djp"]["sfMList"]))
    churn_ps = len(compute_churn_list(top["ps"]["sfM1List"], top["ps"]["sfMList"]))
    base_ps = len(top["ps"]["sfM1List"] or [])
    churn_ps_pct = (churn_ps / base_ps) if base_ps > 0 else 0.0
    churn_target_txt = f"maks {fmt_target_pct(CHURN_TARGET['PS'])}"
    issues_plain, issues_md = [], []
    if churn_mb > 0:
        issues_plain.append(f"{fmt_num(churn_mb)} SF Tidak Lanjut MB")
        issues_md.append(f"**{fmt_num(churn_mb)} SF** Tidak Lanjut MB")
    if churn_djp > 0:
        issues_plain.append(f"{fmt_num(churn_djp)} SF Tidak Lanjut DJP")
        issues_md.append(f"**{fmt_num(churn_djp)} SF** Tidak Lanjut DJP")
    if churn_ps_pct > CHURN_TARGET["PS"]:
        issues_plain.append(f"Tidak Lanjut SF Active PS {fmt_pct(churn_ps_pct)} ({churn_target_txt})")
        issues_md.append(f"Tidak Lanjut SF Active PS **{fmt_pct(churn_ps_pct)}** ({churn_target_txt})")
    if issues_plain:
        retensi_line_plain = ", ".join(issues_plain) + "."
        retensi_line_md = ", ".join(issues_md) + "."
    else:
        retensi_line_plain = f"Aman — tidak ada SF Tidak Lanjut MB/DJP, Tidak Lanjut SF Active PS {fmt_pct(churn_ps_pct)} ({churn_target_txt})."
        retensi_line_md = retensi_line_plain

    plain = ["Result:"] + [f"• {t}" for t in result_lines_plain] + ["Proses:"] + [f"• {t}" for t in process_lines_plain] + ["Retensi SF:", f"• {retensi_line_plain}"]
    md = ["**Result**:"] + [f"• {t}" for t in result_lines_md] + ["**Proses**:"] + [f"• {t}" for t in process_lines_md] + ["**Retensi SF**:", f"• {retensi_line_md}"]
    return {"plain": plain, "md": md}


# ==============================================================================
# CAPTION TELEGRAM — port buildCaption() html:4723-4787
# ==============================================================================
def build_caption(report: dict) -> str:
    top = next((r for r in report["regionRows"] if r["key"] == report["focusRegion"]), None)
    tw_mb = compute_takeaway_mb(report)
    tw_djp = compute_takeaway_djp(report)
    tw_ps = compute_takeaway_ps(report)
    narrative = compute_executive_narrative(report)

    lines = [
        f"📊 **SF PERFORMANCE TRACKING** — Region **{report['focusRegion']}**",
        f"MTD {format_en_date(report['cutoffDate'])}",
        "",
        "**RINGKASAN EKSEKUTIF — PROCESS & RESULT**",
        "",
        "\n".join(narrative["md"]),
        "",
        "====================================================",
        "",
        "**PROCESS — MORNING BRIEFING**",
        "",
        f"• SF Morning Briefing: **{fmt_pct(top['mb']['pctM'])}** ({fmt_pct_pt(top['mb']['pctM1'], top['mb']['pctM'])['txt']} MoM)",
        "",
        "Key Takeaway:",
        *[b["md"] for b in tw_mb["keyBullets"]],
        "",
        "Need Attention:",
        *[b["md"] for b in tw_mb["attentionBullets"]],
        "",
        "====================================================",
        "",
        "**PROCESS — DJP**",
        "",
        f"• SF Aktif DJP: **{fmt_pct(top['djp']['pctM'])}** ({fmt_pct_pt(top['djp']['pctM1'], top['djp']['pctM'])['txt']} MoM)",
        f"• Total DJP: **{fmt_num(top['djp']['totalM'])}** kunjungan ({fmt_pct_pt(top['djp']['totalM1'], top['djp']['totalM'])['txt']} MoM)",
        f"• Produktivitas: **{fmt_dec(top['djp']['perSfDayM'])}** DJP/SF/hari ({fmt_pct_pt(top['djp']['perSfDayM1'], top['djp']['perSfDayM'])['txt']} MoM)",
        "",
        "Key Takeaway:",
        *[b["md"] for b in tw_djp["keyBullets"]],
        "",
        "Need Attention:",
        *[b["md"] for b in tw_djp["attentionBullets"]],
        "",
        "====================================================",
        "",
        "**RESULT**",
        "",
        f"• SF Active PS: **{fmt_pct(top['ps']['pctM'])}** ({fmt_pct_pt(top['ps']['pctM1'], top['ps']['pctM'])['txt']} MoM)",
        f"• Total PS: **{fmt_num(top['ps']['totalM'])}** SSL ({fmt_pct_pt(top['ps']['totalM1'], top['ps']['totalM'])['txt']} MoM)",
        f"• SF Reg Productivity: **{fmt_dec(top['ps']['prodM'], 2)}** SSL/SF Reg ({fmt_pct_pt(top['ps']['prodM1'], top['ps']['prodM'])['txt']} MoM)",
        "",
        "Key Takeaway:",
        *[b["md"] for b in tw_ps["keyBullets"]],
        "",
        "Need Attention:",
        *[b["md"] for b in tw_ps["attentionBullets"]],
    ]
    return "\n".join(lines)


# ==============================================================================
# REPORT SAPA (Phase 3) — port html:445-513, 3988-4317. BEDA dari report utama:
# HANYA 1 periode (rentang tanggal sudah difilter user sendiri saat export
# CSV-nya) — TIDAK ADA perbandingan M vs M-1, jadi tidak ada kolom MoM.
# Region TIDAK ADA di ketiga file SAPA (cuma Branch/WOK) — di-set manual ke
# focus_region, sama seperti HTML (html:446-450).
# ==============================================================================
def norm_assignment_rows(df: pd.DataFrame, focus_region: str) -> list:
    cols = df.columns
    c_branch = _find_col(cols, ["branch"])
    c_wok = _find_col(cols, ["wok"])
    c_sf_name = _find_col(cols, ["sales force name"])
    c_sf_code = _find_col(cols, ["sales code"])
    c_odp = _find_col(cols, ["odp name"])
    c_date = _find_col(cols, ["assignment date"])
    out = []
    for _, row in df.iterrows():
        branch = _s(row.get(c_branch)).upper()
        wok = _s(row.get(c_wok)).upper()
        if not wok or not branch:
            continue
        if _is_excluded_wok(wok):
            continue
        out.append({
            "region": focus_region, "branch": branch, "wok": wok,
            "sfName": _s(row.get(c_sf_name)),
            "sfCode": _s(row.get(c_sf_code)),
            "odp": _s(row.get(c_odp)),
            "assignDate": _s(row.get(c_date)),
        })
    return out


def norm_survey_rows(df: pd.DataFrame, focus_region: str) -> list:
    cols = df.columns
    c_branch = _find_col(cols, ["branch"])
    c_wok = _find_col(cols, ["wok"])
    c_sf = _find_col(cols, ["sales"])
    c_hh = _find_col(cols, ["household id"])
    c_odp = _find_col(cols, ["odp"])
    c_flag_visit = _find_col(cols, ["flag visit"])
    c_flag_appr = _find_col(cols, ["flag approval"])
    c_created = _find_col(cols, ["created at"])
    out = []
    for _, row in df.iterrows():
        branch = _s(row.get(c_branch)).upper()
        wok = _s(row.get(c_wok)).upper()
        if not wok or not branch:
            continue
        if _is_excluded_wok(wok):
            continue
        out.append({
            "region": focus_region, "branch": branch, "wok": wok,
            "sfCode": _s(row.get(c_sf)),
            "householdId": _s(row.get(c_hh)),
            "odp": _s(row.get(c_odp)),
            "flagVisit": _s(row.get(c_flag_visit)),
            "flagApproval": _s(row.get(c_flag_appr)),
            "createdAt": _s(row.get(c_created)),
        })
    return out


def norm_prospect_rows(df: pd.DataFrame, focus_region: str) -> list:
    cols = df.columns
    c_branch = _find_col(cols, ["branch"])
    c_wok = _find_col(cols, ["wok"])
    c_hh = _find_col(cols, ["household id"])
    c_odp = _find_col(cols, ["odp"])
    c_sf = _find_col(cols, ["sales code"])
    out = []
    for _, row in df.iterrows():
        branch = _s(row.get(c_branch)).upper()
        wok = _s(row.get(c_wok)).upper()
        if not wok or not branch:
            continue
        if _is_excluded_wok(wok):
            continue
        out.append({
            "region": focus_region, "branch": branch, "wok": wok,
            "householdId": _s(row.get(c_hh)),
            "odp": _s(row.get(c_odp)),
            "sfCode": _s(row.get(c_sf)),
        })
    return out


def _build_gf_agg(level: str, focus_region: str) -> dict:
    """Roster SF GF (targets.SF_GF_WOK) diagregasi ke level region/branch/wok yang
    sama dengan 3 source data SAPA — port buildGfAgg() html:4101-4112."""
    m = {}
    for wok, g in targets.SF_GF_WOK.items():
        fake_row = {"region": focus_region, "branch": g["branch"], "wok": wok}
        if level != "region" and fake_row["region"] != focus_region:
            continue
        key = level_key(level, fake_row)
        m.setdefault(key, set()).update(g["ids"])
    return m


def build_sapa_rows_for_level(keys: list, level: str, focus_region: str,
                               assign_rows: list, survey_rows: list, prospect_rows: list,
                               gf_map: dict) -> list:
    """Port buildSapaRowsForLevel() html:4117-4177."""
    def level_filter(row):
        return True if level == "region" else row["region"] == focus_region

    def rows_for_key(rows, key):
        return [r for r in rows if level_filter(r) and level_key(level, r) == key]

    out = []
    for key in keys:
        assign_here = rows_for_key(assign_rows, key)
        survey_here = rows_for_key(survey_rows, key)
        prospect_here = rows_for_key(prospect_rows, key)
        gf_ids = gf_map.get(key, set())

        sf_assign_set = {r["sfCode"] for r in assign_here if r["sfCode"] and r["sfCode"] in gf_ids}

        odp_sf_map = {}
        for r in assign_here:
            if not r["odp"] or not r["sfCode"]:
                continue
            pk = f"{r['odp']}||{r['sfCode']}"
            p = odp_sf_map.get(pk)
            if not p:
                p = {"odp": r["odp"], "sfCode": r["sfCode"], "region": r["region"], "branch": r["branch"],
                     "wok": r["wok"], "count": 0, "dateMin": "", "dateMax": ""}
                odp_sf_map[pk] = p
            p["count"] += 1
            if r["assignDate"]:
                if not p["dateMin"] or r["assignDate"] < p["dateMin"]:
                    p["dateMin"] = r["assignDate"]
                if not p["dateMax"] or r["assignDate"] > p["dateMax"]:
                    p["dateMax"] = r["assignDate"]
        odp_sf_pairs = list(odp_sf_map.values())
        distinct_odp_assigned = {p["odp"] for p in odp_sf_pairs}

        odp_survey_set = {r["odp"] for r in survey_here if r["odp"]}
        contacted_household_rows = [r for r in survey_here if r["flagVisit"] == "Contacted"]
        visited_household_rows = [r for r in survey_here if r["flagVisit"] in ("Visited", "Contacted")]

        out.append({
            "key": key,
            "gf": {"count": len(gf_ids), "ids": list(gf_ids)},
            "assign": {
                "sfCount": len(sf_assign_set), "sfList": list(sf_assign_set),
                "pct": _pct(len(sf_assign_set), len(gf_ids)),
                "totalByOdp": len(distinct_odp_assigned), "odpSfPairs": odp_sf_pairs,
            },
            "survey": {
                "visitedOdp": len(odp_survey_set), "odpList": list(odp_survey_set), "surveyRowsAll": survey_here,
                "pctVisitedOdp": _pct(len(odp_survey_set), len(distinct_odp_assigned)),
                "visitedHousehold": len(visited_household_rows), "visitedHouseholdRows": visited_household_rows,
                "contactedHousehold": len(contacted_household_rows), "contactedHouseholdRows": contacted_household_rows,
            },
            "prospect": {"count": len(prospect_here), "rows": prospect_here},
        })
    return out


def compute_sapa_total_row(rows: list) -> dict | None:
    """Port computeSapaTotalRow() html:4182-4203."""
    if not rows:
        return None

    def union(fn):
        s = set()
        for r in rows:
            s.update(fn(r) or [])
        return s

    gf_ids = union(lambda r: r["gf"]["ids"])
    assign_sf = union(lambda r: r["assign"]["sfList"])
    odp_sf_pairs = [p for r in rows for p in (r["assign"]["odpSfPairs"] or [])]
    assign_odp = {p["odp"] for p in odp_sf_pairs}
    odp_set = union(lambda r: r["survey"]["odpList"])
    survey_rows_all = [x for r in rows for x in (r["survey"]["surveyRowsAll"] or [])]
    visited_hh_rows = [x for r in rows for x in (r["survey"]["visitedHouseholdRows"] or [])]
    contacted_hh_rows = [x for r in rows for x in (r["survey"]["contactedHouseholdRows"] or [])]
    prospect_rows = [x for r in rows for x in (r["prospect"]["rows"] or [])]

    return {
        "key": "TOTAL",
        "gf": {"count": len(gf_ids), "ids": list(gf_ids)},
        "assign": {"sfCount": len(assign_sf), "sfList": list(assign_sf), "pct": _pct(len(assign_sf), len(gf_ids)),
                   "totalByOdp": len(assign_odp), "odpSfPairs": odp_sf_pairs},
        "survey": {"visitedOdp": len(odp_set), "odpList": list(odp_set), "surveyRowsAll": survey_rows_all,
                   "pctVisitedOdp": _pct(len(odp_set), len(assign_odp)),
                   "visitedHousehold": len(visited_hh_rows), "visitedHouseholdRows": visited_hh_rows,
                   "contactedHousehold": len(contacted_hh_rows), "contactedHouseholdRows": contacted_hh_rows},
        "prospect": {"count": len(prospect_rows), "rows": prospect_rows},
    }


def compute_sapa_report(df_assign: pd.DataFrame, df_survey: pd.DataFrame, df_prospect: pd.DataFrame,
                         focus_region: str) -> dict:
    """Port computeSapaReport() html:4211-4234."""
    assign_rows = norm_assignment_rows(df_assign, focus_region)
    survey_rows = norm_survey_rows(df_survey, focus_region)
    prospect_rows = norm_prospect_rows(df_prospect, focus_region)

    region_keys = level_keys_from_all([assign_rows, survey_rows, prospect_rows], "region", focus_region)
    branch_keys = level_keys_from_all([assign_rows, survey_rows, prospect_rows], "branch", focus_region)
    # WOK: gabungkan juga WOK dari roster SF GF yang mungkin belum muncul di 3 source
    # data sama sekali — supaya WOK yang belum jalan SAPA-nya tetap kelihatan (0),
    # bukan hilang dari tabel (html:4219-4223).
    gf_fake_rows = [{"region": focus_region, "branch": g["branch"], "wok": wok}
                     for wok, g in targets.SF_GF_WOK.items()]
    wok_keys = level_keys_from_all([assign_rows, survey_rows, prospect_rows, gf_fake_rows], "wok", focus_region)

    gf_region = _build_gf_agg("region", focus_region)
    gf_branch = _build_gf_agg("branch", focus_region)
    gf_wok = _build_gf_agg("wok", focus_region)

    region_rows = build_sapa_rows_for_level(region_keys, "region", focus_region, assign_rows, survey_rows, prospect_rows, gf_region)
    branch_rows = build_sapa_rows_for_level(branch_keys, "branch", focus_region, assign_rows, survey_rows, prospect_rows, gf_branch)
    wok_rows = build_sapa_rows_for_level(wok_keys, "wok", focus_region, assign_rows, survey_rows, prospect_rows, gf_wok)

    return {"regionRows": region_rows, "branchRows": branch_rows, "wokRows": wok_rows, "focusRegion": focus_region}


def compute_takeaway_sapa(sapa_report: dict) -> dict:
    """Port computeTakeawaySapa() html:4266-4287."""
    focus_row = next((r for r in sapa_report["regionRows"] if r["key"] == sapa_report["focusRegion"]), None)
    wok_with_gf = [r for r in sapa_report["wokRows"] if r["gf"]["count"] > 0]
    at_100 = [r for r in wok_with_gf if r["assign"]["pct"] >= 0.999]
    not_yet = sorted((r for r in wok_with_gf if r["assign"]["pct"] < 0.999), key=lambda r: r["assign"]["pct"])

    key_bullets = [bullet(
        f"%SF Assign SAPA Region {sapa_report['focusRegion']}",
        f"{fmt_pct(focus_row['assign']['pct'] if focus_row else 0)} "
        f"({fmt_num(focus_row['assign']['sfCount'] if focus_row else 0)} dari "
        f"{fmt_num(focus_row['gf']['count'] if focus_row else 0)} SF GF)")]
    if at_100:
        names = ", ".join(title_case(label_of(r["key"])) for r in at_100)
        key_bullets.append(bullet_plain(f"WOK sudah 100% SF Assign SAPA ({len(at_100)} dari {len(wok_with_gf)}): {names}"))

    attention_bullets = []
    if not_yet:
        parts = ", ".join(f"{title_case(label_of(r['key']))} ({fmt_pct(r['assign']['pct'])})" for r in not_yet)
        attention_bullets.append(bullet_plain(f"WOK belum 100% SF Assign SAPA ({len(not_yet)} dari {len(wok_with_gf)}): {parts}"))
    elif wok_with_gf:
        attention_bullets.append(bullet_plain("Semua WOK sudah 100% SF Assign SAPA — jaga konsistensi."))
    return {"keyBullets": key_bullets, "attentionBullets": attention_bullets}


def build_caption_sapa(sapa_report: dict) -> str:
    """Port buildCaptionSapaCore()/buildCaptionSapa() html:4293-4315 (versi Telegram)."""
    top = next((r for r in sapa_report["regionRows"] if r["key"] == sapa_report["focusRegion"]), None)
    tw = compute_takeaway_sapa(sapa_report)
    lines = [
        f"📊 **REPORT SALES ACTIVITY & PROSPECTING APP (SAPA)** — Region **{sapa_report['focusRegion']}**",
        "",
        "**Ringkasan**:",
        f"• Jumlah SF GF: **{fmt_num(top['gf']['count'])}**",
        f"• SF Assign SAPA: **{fmt_num(top['assign']['sfCount'])}** ({fmt_pct(top['assign']['pct'])})",
        f"• Assignment ODP SAPA: **{fmt_num(top['assign']['totalByOdp'])}**",
        f"• Visited ODP SAPA: **{fmt_num(top['survey']['visitedOdp'])}** ({fmt_pct(top['survey']['pctVisitedOdp'])})",
        f"• Visited Household: **{fmt_num(top['survey']['visitedHousehold'])}**",
        f"• Contacted Household: **{fmt_num(top['survey']['contactedHousehold'])}**",
        f"• Prospect Household: **{fmt_num(top['prospect']['count'])}**",
        "",
        "Key Takeaway:",
        *[b["md"] for b in tw["keyBullets"]],
        "",
        "Need Attention:",
        *[b["md"] for b in tw["attentionBullets"]],
    ]
    return "\n".join(lines)
