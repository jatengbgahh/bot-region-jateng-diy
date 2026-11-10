"""
reports/nasional/calculator.py — Daily Tracking IndiHome Performance level REGION NASIONAL
(IO/RE/PS + Revenue + ARPU New Sales, per 12 region + Area 1-4 + National).

Periode: MtD s/d tgl_closing, dibanding tanggal yang sama bulan lalu (aturan hari_mtd
sama persis dengan calculator_daily._query_dashboard).

Sumber:
- indihome_ordering_detail_YYYYMM (semua region, NEW SALES non-WIRELESS) -> IO/RE/PS + revenue
  (SUM price_package order PS). dashboard_hourly_sales hanya berisi 3 region, jadi tidak dipakai.
- Target: sheet TARGET_REGION (target BULANAN penuh) di template_target_2026_bot*.xlsx terbaru.

Rumus (dicek terhadap contoh laporan):
  MoM = (bulan ini - bulan lalu) / bulan lalu ; Ach = MtD / target bulanan penuh (bukan DRR)
  PS to IO = PS / IO ; PS to RE = PS / RE ; ARPU = Revenue / PS (bukan rata-rata ARPU)
  Area & National = SUM base count region, rasio dihitung ulang.
"""

import calendar
import logging
from datetime import date, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta
from mysql.connector import Error

import db
from calculator_daily import get_connection, get_table

logger = logging.getLogger(__name__)

REGION_ORDER = [
    "SUMBAGUT", "SUMBAGTENG", "SUMBAGSEL",
    "JAKARTA BANTEN", "EASTERN JABOTABEK", "JABAR",
    "JATENG-DIY", "JATIM", "BALI NUSRA",
    "KALIMANTAN", "SULAWESI", "MALUKU DAN PAPUA",
]
UNMAPPED = "UNMAPPED"
AREA_OF = {
    "SUMBAGUT": "AREA 1", "SUMBAGTENG": "AREA 1", "SUMBAGSEL": "AREA 1",
    "JAKARTA BANTEN": "AREA 2", "EASTERN JABOTABEK": "AREA 2", "JABAR": "AREA 2",
    "JATENG-DIY": "AREA 3", "JATIM": "AREA 3", "BALI NUSRA": "AREA 3",
    "KALIMANTAN": "AREA 4", "SULAWESI": "AREA 4", "MALUKU DAN PAPUA": "AREA 4",
}
AREA_ORDER = ["AREA 1", "AREA 2", "AREA 3", "AREA 4"]

# (potongan teks di label DB, nama baris laporan) — dicek berurutan, label DB di-uppercase.
_ALIAS = [
    ("SUMBAGUT", "SUMBAGUT"), ("SUMBAGTENG", "SUMBAGTENG"), ("SUMBAGSEL", "SUMBAGSEL"),
    ("CENTRAL JABOTABEK", UNMAPPED), ("WESTERN JABOTABEK", UNMAPPED),   # label lama, jangan nyangkut ke Eastern
    ("JAKARTA", "JAKARTA BANTEN"), ("EASTERN", "EASTERN JABOTABEK"),
    ("JABOTABEK", "EASTERN JABOTABEK"), ("JABAR", "JABAR"),
    ("JATENG", "JATENG-DIY"), ("JATIM", "JATIM"), ("BALI", "BALI NUSRA"),
    ("KALIMANTAN", "KALIMANTAN"), ("SULAWESI", "SULAWESI"),
    ("MALUKU", "MALUKU DAN PAPUA"), ("PAPUA", "MALUKU DAN PAPUA"), ("PUMA", "MALUKU DAN PAPUA"),
]


def map_region(label) -> str:
    """Label region di DB (tidak konsisten antar bulan/tabel) -> nama baris laporan."""
    s = str(label or "").strip().upper()
    for kunci, nama in _ALIAS:
        if kunci in s:
            return nama
    return UNMAPPED


def _periode(tgl_closing: date):
    """Return (awal_ini, awal_lalu, akhir_lalu) — aturan MtD sama dgn calculator_daily."""
    bulan_lalu = tgl_closing - relativedelta(months=1)
    hari_max_lalu = calendar.monthrange(bulan_lalu.year, bulan_lalu.month)[1]
    hari_max_ini = calendar.monthrange(tgl_closing.year, tgl_closing.month)[1]
    hari_mtd = hari_max_lalu if tgl_closing.day == hari_max_ini else min(tgl_closing.day, hari_max_lalu)
    return (tgl_closing.replace(day=1), bulan_lalu.replace(day=1),
            date(bulan_lalu.year, bulan_lalu.month, hari_mtd))


# ── Query ───────────────────────────────────────────────────────────────────

def _query_hourly(tgl_dari: date, tgl_sampai: date) -> dict:
    """
    IO/RE/PS/revenue per region dari indihome_ordering_detail_YYYYMM (semua region).
    dashboard_hourly_sales HANYA berisi 3 region (Area 3), jadi tidak dipakai di sini.
    Filter: order_type='NEW SALES', tanpa produk WIRELESS (sama dgn db.query_ordering_detail).
      IO = COUNT io_ts, RE = COUNT re_ts, PS = COUNT ps_ts di periode (masing-masing timestamp
      sendiri); revenue = SUM(price_package) order yang ps_ts-nya di periode — terverifikasi
      sama persis dgn dashboard_hourly_sales.ps_rev utk Jateng.
    """
    tabel = f"indihome_ordering_detail_{tgl_dari:%Y%m}"
    akhir = tgl_sampai + timedelta(days=1)
    out = {}
    for m, col in (("io", "io_ts"), ("re", "re_ts"), ("ps", "ps_ts")):
        sql = f"""
            SELECT region, COUNT(*) AS n, SUM(price_package) AS rev
            FROM `{tabel}`
            WHERE order_type = 'NEW SALES'
              AND (product_commercial_name NOT LIKE '%%WIRELESS%%' OR product_commercial_name IS NULL)
              AND {col} IS NOT NULL AND {col} >= %s AND {col} < %s
            GROUP BY region
        """
        def _jalankan():
            conn = get_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute(sql, (tgl_dari, akhir))
            r = cur.fetchall()
            cur.close(); conn.close()
            return r
        try:
            rows = db._jalankan_dengan_retry(_jalankan, f"national_ordering {tabel}.{col}")
        except Error as e:
            logger.warning(f"national_ordering {tabel}.{col} gagal: {e}")
            rows = []
        for r in rows:
            k = map_region(r["region"])
            if k == UNMAPPED:
                logger.warning(f"[national] label region tidak dikenali -> UNMAPPED: {r['region']!r}")
            a = out.setdefault(k, {"io": 0, "re": 0, "ps": 0, "rev": 0.0})
            a[m] += int(r["n"] or 0)
            if m == "ps":
                a["rev"] += float(r["rev"] or 0)
    return out


def _target_region(target_df, tgl_closing: date) -> dict:
    """{region: (io, re, ps)} dari sheet TARGET_REGION untuk bulan closing."""
    out = {}
    if target_df is None or target_df.empty:
        return out
    t = target_df.copy()
    t.columns = t.columns.astype(str).str.strip().str.upper()
    if not {"BULAN", "REGION"} <= set(t.columns):
        return out
    t = t[t["BULAN"].astype(str).str.strip() == tgl_closing.strftime("%Y-%m")]
    for _, r in t.iterrows():
        k = map_region(r.get("REGION"))
        if k == UNMAPPED:
            continue
        v = [float(r.get(c, 0) or 0) for c in ("TARGET_IO", "TARGET_RE", "TARGET_PS")]
        a = out.setdefault(k, [0.0, 0.0, 0.0])
        for i in range(3):
            a[i] += v[i]
    return {k: tuple(v) for k, v in out.items()}


# ── Hitung ──────────────────────────────────────────────────────────────────

def _pct(a, b):
    return round(a / b * 100, 1) if b else None

def _mom(a, b):
    return round((a - b) / b * 100, 1) if b else None


def _row(name, base, tgt):
    """base = dict io/re/ps/rev untuk 'now' & 'prev' (jumlah, bukan rasio)."""
    n, p = base["now"], base["prev"]
    arpu_n = round(n["rev"] / n["ps"]) if n["ps"] else None
    arpu_p = round(p["rev"] / p["ps"]) if p["ps"] else None
    row = {"name": name,
           "ps_to_io": _pct(n["ps"], n["io"]), "ps_to_re": _pct(n["ps"], n["re"]),
           "rev_prev": round(p["rev"]), "rev_now": round(n["rev"]),
           "mom_rev": _mom(n["rev"], p["rev"]),
           "arpu_prev": arpu_p, "arpu_now": arpu_n,
           "mom_arpu": _mom(arpu_n, arpu_p) if arpu_n is not None and arpu_p else None}
    for i, m in enumerate(("io", "re", "ps")):
        row[f"{m}_tgt"] = round(tgt[i])
        row[f"{m}_prev"] = p[m]; row[f"{m}_now"] = n[m]
        row[f"{m}_mom"] = _mom(n[m], p[m])
        row[f"{m}_ach"] = _pct(n[m], tgt[i])
    return row


def _kosong():
    return {"io": 0, "re": 0, "ps": 0, "rev": 0.0}


def hitung_national(target_df, tgl_closing: date) -> dict:
    awal_ini, awal_lalu, akhir_lalu = _periode(tgl_closing)
    h_now = _query_hourly(awal_ini, tgl_closing)
    h_prev = _query_hourly(awal_lalu, akhir_lalu)
    targets = _target_region(target_df, tgl_closing)

    def base_of(k):
        out = {}
        for tag, h in (("now", h_now), ("prev", h_prev)):
            out[tag] = dict(_kosong(), **{x: h.get(k, {}).get(x, 0) for x in ("io", "re", "ps", "rev")})
        return out

    def tambah(a, b):
        r = {}
        for tag in ("now", "prev"):
            r[tag] = {x: a[tag][x] + b[tag][x] for x in ("io", "re", "ps", "rev")}
        return r

    def tgt_sum(keys):
        t = [0.0, 0.0, 0.0]
        for k in keys:
            for i, v in enumerate(targets.get(k, (0, 0, 0))):
                t[i] += v
        return t

    bases = {k: base_of(k) for k in REGION_ORDER + [UNMAPPED]}
    regions = [_row(k, bases[k], targets.get(k, (0, 0, 0))) for k in REGION_ORDER]
    regions.append(_row(UNMAPPED, bases[UNMAPPED], (0, 0, 0)))

    areas = []
    for ar in AREA_ORDER:
        ks = [k for k in REGION_ORDER if AREA_OF[k] == ar]
        b = bases[ks[0]]
        for k in ks[1:]:
            b = tambah(b, bases[k])
        areas.append(_row(ar, b, tgt_sum(ks)))
    areas.append(_row(UNMAPPED, bases[UNMAPPED], (0, 0, 0)))

    semua = bases[REGION_ORDER[0]]
    for k in REGION_ORDER[1:] + [UNMAPPED]:
        semua = tambah(semua, bases[k])
    national = _row("NATIONAL", semua, tgt_sum(REGION_ORDER))

    if not targets:
        logger.warning("[national] sheet TARGET_REGION kosong / bulan ini belum ada -> target 0, Ach '-'")
    return {
        "tgl_closing": tgl_closing, "bulan_lalu": awal_lalu, "akhir_lalu": akhir_lalu,
        "regions": regions, "areas": areas, "national": national,
        "target_ada": bool(targets),
    }


if __name__ == "__main__":
    # Diagnostik (butuh VPN): label region & kolom yang benar-benar ada di DB.
    import sys
    tgl = date.today()
    if len(sys.argv) > 1:
        from datetime import datetime
        tgl = datetime.strptime(sys.argv[1], "%d-%m-%Y").date()
    conn = get_connection(); cur = conn.cursor()
    tabel = get_table(tgl)
    cur.execute(f"SHOW COLUMNS FROM `{tabel}`")
    print("Kolom", tabel, [r[0] for r in cur.fetchall()])
    cur.execute(f"SELECT region, COUNT(*) FROM `{tabel}` GROUP BY region")
    for reg, n in cur.fetchall():
        print(f"{reg!r:30} -> {map_region(reg):20} ({n} baris)")
    cur.close(); conn.close()
