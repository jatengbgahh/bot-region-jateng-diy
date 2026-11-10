"""
reports/sf_momentum/calculator_5so.py — Report /5so: SF Momentum per Region / Branch / WOK (WOK baru, 14 WOK)

Metrics (M1 = MtD bulan lalu tgl 1..D, MTD = bulan ini tgl 1..D, MoM % = MTD vs M1):
  SF REGISTERED  = COUNT(DISTINCT kode) status ACTIVE di database_sf_YYYYMM,
                   snapshot event_date terakhir <= tgl D
                   (override bulan tertentu -> snapshot akhir bulan sumber, lihat
                   sf_rules.SF_SNAPSHOT_SOURCE_MONTH; Nov 2026 = akhir Okt 2026)
  SF dummy       = sf_rules.DUMMY_SF_CODES dibuang dari semua metrik (SF, PS/RE, DJP)
  SF AKTIF       = SF dengan PS >= 1 (channel AGENCY)
  SF PRODUKTIF   = SF dengan PS >= 10 (channel AGENCY)
  PRODUKTIVITAS  = total PS AGENCY / SF AKTIF
  SF AKTIF DJP   = COUNT(DISTINCT user_code) di djp_daily_user_detailed_YYYYMM
  ODP VISITED    = COUNT(DISTINCT odp_name) di djp_daily_user_detailed_YYYYMM
  MOMENTUM SKOR  = jumlah metrik (dari 6) dengan MoM > 0
  STATUS         = >=5 OUTPERFORM, 4 ON TRACK, 3 WATCH, <=2 CRITICAL
                   (umum: >=n-1, n-2, n-3, sisanya; n = jumlah metrik)

/7so (calculator_7so.py) memakai modul ini dengan basis RE (re_ts) dan 7 metrik,
termasuk DJP/SF/DAY = jumlah kunjungan DJP / SF AKTIF DJP / jumlah hari periode.

WOK tiap SF diambil dari kolom wok database_sf bulan berjalan (sudah WOK baru),
fallback ke database_sf bulan itu sendiri; jadi SF/PS/DJP M1 & MTD dipetakan
ke struktur WOK yang sama. PS tanpa sf_code terdaftar -> WOK dari kolom kabupaten.
PS: region JATENG%, NEW SALES, exclude wireless, AGENCY, dedup order_id.
"""
from datetime import date, timedelta
import pandas as pd
from dateutil.relativedelta import relativedelta
import db
from config import REGION_NAME
from . import sf_rules

# (BRANCH, WOK baru, [kabupaten]) — urutan = urutan tampil. Kabupaten dipakai sebagai
# fallback WOK untuk PS yang sf_code-nya tidak ada di database_sf.
MAP = [
    ("MAGELANG", "KEBUMEN", ["KEBUMEN", "PURWOREJO"]),
    ("MAGELANG", "MAGELANG TEMANGGUNG", ["KOTA MAGELANG", "MAGELANG", "TEMANGGUNG"]),
    ("PEKALONGAN", "BATANG", ["BATANG", "KOTA PEKALONGAN", "PEKALONGAN", "PEMALANG"]),
    ("PEKALONGAN", "TEGAL BREBES", ["BREBES", "KOTA TEGAL", "TEGAL"]),
    ("PURWOKERTO", "BANJARNEGARA", ["BANJARNEGARA", "PURBALINGGA", "WONOSOBO"]),
    ("PURWOKERTO", "CILACAP BANYUMAS", ["BANYUMAS", "CILACAP"]),
    ("SEMARANG", "DEMAK", ["DEMAK", "KOTA SALATIGA", "SEMARANG"]),
    ("SEMARANG", "JEPARA KUDUS", ["JEPARA", "KUDUS"]),
    ("SEMARANG", "PATI", ["PATI", "REMBANG"]),
    ("SEMARANG", "SEMARANG", ["KENDAL", "KOTA SEMARANG"]),
    ("SURAKARTA", "BOYOLALI", ["BOYOLALI", "KLATEN", "SUKOHARJO"]),
    ("SURAKARTA", "SRAGEN", ["BLORA", "GROBOGAN", "SRAGEN"]),
    ("SURAKARTA", "SURAKARTA", ["KARANGANYAR", "KOTA SURAKARTA", "WONOGIRI"]),
    ("YOGYAKARTA", "DAERAH ISTIMEWA YOGYAKARTA",
     ["BANTUL", "GUNUNG KIDUL", "GUNUNGKIDUL", "KOTA YOGYAKARTA", "KULON PROGO", "SLEMAN"]),
]
KAB2WOK = {k: w for _, w, ks in MAP for k in ks}

WOK2BR = {w: b for b, w, _ in MAP}
WOKS = [w for _, w, _ in MAP]
BRANCHES = list(dict.fromkeys(b for b, _, _ in MAP))

# Sisa nama WOK lama di database_sf/DJP -> WOK baru (fallback kalau kode SF tidak ketemu)
OLD2NEW = {
    "YOGYA 1": "DAERAH ISTIMEWA YOGYAKARTA", "YOGYA 2": "DAERAH ISTIMEWA YOGYAKARTA",
    "SEMARANG 1": "SEMARANG", "SEMARANG 2": "SEMARANG",
    "JEPARA KUDUS - PATI": "JEPARA KUDUS", "PEMALANG PURBALINGGA": "BATANG",
    "WONOSOBO BANJARNEGARA": "BANJARNEGARA", "TEGAL BREBES GREENFIELD": "TEGAL BREBES",
}
METRICS = ["sf_reg", "sf_aktif", "sf_prod", "prod", "sf_djp", "odp"]
PROD_MIN_TRX = 10
TS_COL = {"PS": "ps_ts", "RE": "re_ts"}


def _norm_wok(w) -> str:
    w = str(w or "").strip().upper()
    w = OLD2NEW.get(w, w)
    return w if w in WOK2BR else None


def _q(sql: str, params: tuple, label: str) -> pd.DataFrame:
    def _run():
        conn = db.get_connection()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close(); conn.close()
    try:
        return pd.DataFrame(db._jalankan_dengan_retry(_run, label))
    except db.Error as e:          # tabel bulan itu belum ada, dsb.
        db.logger.warning(f"{label} gagal: {e}")
        return pd.DataFrame()


def _dari_export() -> bool:
    """True when the DB is replaced by csv_fake_db (Rajawali export / CSV mode). The export
    query (report.buat_sql) already applies SF_SNAPSHOT_SOURCE_MONTH, so the database_sf_<ym>
    table loaded from the export must be read as-is (no second redirect)."""
    return getattr(db.get_connection, "__module__", "") == "csv_fake_db"


def sf_snapshot(kolom: str, ym: str, tgl: date, label: str) -> pd.DataFrame:
    """
    Snapshot SF ACTIVE JATENG-DIY di database_sf_<ym>, event_date terakhir <= tgl.
    FALLBACK: kalau tabel bulan itu belum ada / belum berisi (mis. awal bulan,
    database_sf_YYYYMM belum dibuat), pakai snapshot TERAKHIR di database_sf bulan
    sebelumnya. Dipakai /5so (_sf_master) dan /7so (_sf_master_lengkap).

    SF Registered override (sf_rules.SF_SNAPSHOT_SOURCE_MONTH): for a report month whose
    database_sf table is only a copy of the previous month (Nov 2026), read the source month
    table instead. tgl is later than every event_date of that table, so the query returns its
    LAST snapshot (end of the source month). Skipped in export mode (see _dari_export).
    Dummy SF (sf_rules.DUMMY_SF_CODES) are always removed. `kolom` must return a `kode` column.
    """
    src = ym if _dari_export() else sf_rules.sf_source_month(ym)
    if src != ym:
        db.logger.info(f"{label}: SF snapshot {ym} -> snapshot terakhir database_sf_{src} (override)")
    bulan = date(int(src[:4]), int(src[4:6]), 1)
    for i, b in enumerate((bulan, bulan - relativedelta(months=1))):
        t = f"database_sf_{b:%Y%m}"
        df = _q(f"""SELECT {kolom} FROM `{t}`
                    WHERE region = 'JATENG-DIY' AND status = 'ACTIVE'
                      AND event_date = (SELECT MAX(event_date) FROM `{t}` WHERE event_date <= %s)""",
                (tgl,), f"{label} {t}")
        if not df.empty:
            if i:
                db.logger.warning(f"{label}: database_sf_{src} belum ada/kosong -> fallback "
                                  f"snapshot terakhir {t}")
            return sf_rules.drop_dummy(df, "kode")
    return pd.DataFrame()


def _sf_master(ym: str, tgl: date) -> pd.DataFrame:
    """Snapshot SF ACTIVE JATENG-DIY per event_date terakhir <= tgl. Kolom: kode, wok.
    Fallback ke database_sf bulan sebelumnya bila tabel bulan ym belum ada (sf_snapshot)."""
    df = sf_snapshot("UPPER(TRIM(kode)) kode, wok", ym, tgl, "5so")
    if df.empty:
        return pd.DataFrame(columns=["kode", "wok"])
    df["wok"] = df["wok"].map(_norm_wok)
    return df.drop_duplicates("kode")


def _trx(a: date, b: date, basis: str) -> pd.DataFrame:
    """PS/RE AGENCY tgl a..b (inklusif), basis 'PS' (ps_ts) / 'RE' (re_ts). Kolom: sf, kab."""
    ts = TS_COL[basis]
    df = _q(f"""SELECT order_id, sf_code, sf_name, kabupaten, event_date
                FROM indihome_ordering_detail_{a.strftime('%Y%m')}
                WHERE region LIKE 'JATENG%%' AND order_type = 'NEW SALES'
                  AND UPPER(TRIM(channel_group)) = 'AGENCY'
                  AND (product_commercial_name NOT LIKE '%%WIRELESS%%' OR product_commercial_name IS NULL)
                  AND {ts} >= %s AND {ts} < %s""",
            (a, b + timedelta(days=1)), f"5so {basis} {a:%Y%m}")
    if df.empty:
        return pd.DataFrame(columns=["sf", "kab", "nama"])
    df = sf_rules.drop_dummy(df, "sf_code")            # dummy / test SF are not real sales
    df = df.sort_values("event_date").drop_duplicates("order_id", keep="last")
    df["sf"] = df["sf_code"].fillna("").astype(str).str.strip().str.upper()
    df["kab"] = df["kabupaten"].fillna("").astype(str).str.strip().str.upper()
    df["nama"] = df["sf_name"].fillna("").astype(str).str.strip()
    return df[["sf", "kab", "nama"]]


def _djp(a: date, b: date) -> pd.DataFrame:
    df = _q(f"""SELECT UPPER(TRIM(user_code)) sf, wok, odp_name
                FROM djp_daily_user_detailed_{a.strftime('%Y%m')}
                WHERE regional LIKE 'JATENG%%' AND tugas_date BETWEEN %s AND %s""",
            (a, b), f"5so djp {a:%Y%m}")
    if df.empty:
        return pd.DataFrame(columns=["sf", "wok", "odp_name"])
    return sf_rules.drop_dummy(df, "sf")               # dummy / test SF are not real DJP visits


def _hitung_periode(a: date, b: date, kode2wok: dict, basis: str) -> dict:
    """Return {key: {metric: value}} untuk key = WOK, 'BR:<branch>', REGION_NAME."""
    sfm = _sf_master(a.strftime("%Y%m"), b)
    own = dict(zip(sfm["kode"], sfm["wok"]))
    wok_of = lambda k: kode2wok.get(k) or own.get(k)

    sfm["w"] = sfm["kode"].map(wok_of)

    ps = _trx(a, b, basis)
    ps["w"] = [wok_of(s) if s else None for s in ps["sf"]]
    ps["w"] = ps["w"].fillna(ps["kab"].map(KAB2WOK))
    per_sf = ps[ps.sf != ""].groupby("sf").agg(n=("sf", "size"), w=("w", "first"),
                                              nama=("nama", "last")).reset_index()

    dj = _djp(a, b)
    dj["w"] = [wok_of(s) or _norm_wok(w) for s, w in zip(dj["sf"], dj["wok"])]

    groups = {w: [w] for w in WOKS}
    groups.update({f"BR:{br}": [w for w in WOKS if WOK2BR[w] == br] for br in BRANCHES})
    n_hari = (b - a).days + 1
    out = {}
    for key, ws in groups.items():
        out[key] = _agg(sfm[sfm.w.isin(ws)], ps[ps.w.isin(ws)],
                        per_sf[per_sf.w.isin(ws)], dj[dj.w.isin(ws)], n_hari)
    out[REGION_NAME] = _agg(sfm, ps, per_sf, dj, n_hari)
    # Detail per SF (untuk Excel SF tidak aktif /7so)
    out["_sf"] = per_sf[["sf", "n", "w", "nama"]]
    return out


def _agg(sfm, trx, per_sf, dj, n_hari) -> dict:
    sf_aktif = len(per_sf)
    sf_djp = dj["sf"].nunique()
    return {
        "sf_reg": sfm["kode"].nunique(),
        "sf_aktif": sf_aktif,
        "sf_prod": int((per_sf["n"] >= PROD_MIN_TRX).sum()),
        "trx": len(trx),
        "prod": round(len(trx) / sf_aktif, 1) if sf_aktif else None,
        "sf_djp": sf_djp,
        "odp": dj["odp_name"].dropna().nunique(),
        "visit": len(dj),
        "djp_sf_day": round(len(dj) / sf_djp / n_hari, 1) if sf_djp else None,
    }


def _mom(cur, prev):
    if cur is None or not prev:
        return None
    return round((cur - prev) / prev * 100, 2)


def _status(skor: int, n: int) -> str:
    if skor >= n - 1: return "OUTPERFORM"
    if skor == n - 2: return "ON TRACK"
    if skor == n - 3: return "WATCH"
    return "CRITICAL"


def hitung_5so(tgl: date, basis: str = "PS", metrics: list = METRICS,
               title: str = "5SO Scorecard") -> dict:
    awal = tgl.replace(day=1)
    lm_awal = awal - relativedelta(months=1)
    lm_akhir = min(lm_awal + relativedelta(day=tgl.day), awal - timedelta(days=1))

    master_ini = _sf_master(awal.strftime("%Y%m"), tgl)
    kode2wok = {k: w for k, w in zip(master_ini["kode"], master_ini["wok"]) if w}

    mtd = _hitung_periode(awal, tgl, kode2wok, basis)
    m1 = _hitung_periode(lm_awal, lm_akhir, kode2wok, basis)

    def _row(key, name, kind, branch=""):
        r = {"name": name, "kind": kind, "branch": branch}
        skor = 0
        for m in metrics:
            c, p = mtd[key][m], m1[key][m]
            mom = _mom(c, p)
            r[f"{m}_m1"], r[f"{m}_mtd"], r[f"{m}_mom"] = p, c, mom
            skor += int(mom is not None and mom > 0)
        r["trx_m1"], r["trx_mtd"] = m1[key]["trx"], mtd[key]["trx"]
        r["skor"], r["status"] = skor, _status(skor, len(metrics))
        return r

    rows = ([_row(REGION_NAME, REGION_NAME, "reg")]
            + [_row(f"BR:{br}", br, "br") for br in BRANCHES]
            + [_row(w, w, "wok", WOK2BR[w]) for w in WOKS])

    djp_last = _q(f"SELECT MAX(tugas_date) d FROM djp_daily_user_detailed_{awal:%Y%m} "
                  f"WHERE regional LIKE 'JATENG%%'", (), "5so djp last")
    djp_last = djp_last["d"].iloc[0] if not djp_last.empty else None

    return {"tgl": tgl, "awal": awal, "lm_awal": lm_awal, "lm_akhir": lm_akhir,
            "rows": rows, "metrics": metrics, "n_metrics": len(metrics),
            "basis": basis, "title": title, "djp_last": djp_last,
            "sf_note": sf_rules.sf_override_note(f"{awal:%Y%m}"),
            "sf_mtd": mtd["_sf"], "sf_m1": m1["_sf"]}
