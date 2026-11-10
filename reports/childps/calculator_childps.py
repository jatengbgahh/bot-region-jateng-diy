"""
calculator_childps.py — Child per PS Telkomsel One per WOK NEW (/childps).

Sumber: tabel tselone_to_msisdn_YYYYMM. Dua bentuk data diterima:
  (a) AGREGAT (kolom bln, city, cluster, ps, child) — dari childps_sql.py: query DB langsung atau export
      SQL Console Rajawali. Ini jalur terjadwal; tabel yang dibutuhkan hanya tselone_to_msisdn_YYYYMM.
  (b) MENTAH (1 baris = bb_id x msisdn_child) — upload file .csv/.zip ke bot (caption /childps).
Definisi:
  PS           = distinct bb_id, bulan dari activation_date_ih
  Child        = distinct msisdn_child (non-null, ≠ msisdn_parent)
  Child per PS = Child / PS (dihitung ulang dari jumlah di level branch/region)
Periode: MtD vs MtD bulan lalu tanggal yang sama (tgl 1 s.d. tgl cutoff);
cutoff = akhir bulan → full vs full.
Wilayah: kolom city → WOK NEW (calculator_sql_woknew.KAB2WOK); city kosong →
fallback kolom cluster (WOK lama).
"""

import calendar
import io
import zipfile
from datetime import date, datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

from calculator_sql_woknew import KAB2WOK, WOK_NEW_ORDER, WOK_NEW_TO_BRANCH

REGION_NAME = "JATENG-DIY"
BULAN = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
         7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"}
KOLOM_WAJIB = ["bb_id", "msisdn_parent", "msisdn_child", "activation_date_ih", "city"]

CLUSTER2WOK = {
    "KEBUMEN": "KEBUMEN", "MAGELANG TEMANGGUNG": "MAGELANG TEMANGGUNG",
    "BATANG": "BATANG", "TEGAL BREBES": "TEGAL BREBES",
    "WONOSOBO BANJARNEGARA": "BANJARNEGARA", "CILACAP BANYUMAS": "CILACAP BANYUMAS",
    "DEMAK": "DEMAK", "JEPARA KUDUS": "JEPARA KUDUS", "PATI": "PATI",
    "SEMARANG": "SEMARANG", "BOYOLALI": "BOYOLALI", "SRAGEN": "SRAGEN",
    "SURAKARTA": "SURAKARTA", "YOGYAKARTA": "DAERAH ISTIMEWA YOGYAKARTA",
}


# ── Baca data ────────────────────────────────────────────────────────────────

def _read_csv_bytes(b: bytes) -> pd.DataFrame:
    text = b.decode("utf-8-sig", errors="replace")
    first = text.split("\n", 1)[0].strip().lower()
    skip = 1 if first.startswith("sep=") else 0
    header = text.split("\n", skip + 1)[skip]
    sep = ";" if header.count(";") >= header.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, skiprows=skip, dtype=str)


def baca_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """File hasil SQL (.csv, atau .zip berisi .csv) → DataFrame mentah."""
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            csvs = [n for n in z.namelist() if n.lower().endswith(".csv") and not n.startswith("__MACOSX")]
            if not csvs:
                raise ValueError("Tidak ada file .csv di dalam zip")
            return pd.concat([_read_csv_bytes(z.read(n)) for n in csvs], ignore_index=True)
    if filename.lower().endswith(".csv"):
        return _read_csv_bytes(file_bytes)
    raise ValueError("Format file harus .csv atau .zip")


def query_db(tgl: date, sql_template: str = None) -> pd.DataFrame:
    """Query langsung ke MySQL. Default: SQL agregat childps_sql.buat_sql(tgl) (kolom bln, city, cluster, ps,
    child). sql_template (config_childps.CHILDPS_SQL) bila diisi = query mentah ala patch lama."""
    import db
    if sql_template:
        tgl_awal = (tgl.replace(day=1) - relativedelta(months=1))
        sql = sql_template.format(tgl_awal=tgl_awal.isoformat(), tgl_akhir=tgl.isoformat(),
                                  yyyymm=tgl.strftime("%Y%m"))
    else:
        import childps_sql
        sql = childps_sql.buat_sql(tgl)
    conn = db.get_connection()
    try:
        return pd.read_sql(sql, conn).astype(str).replace({"None": None, "nan": None})
    finally:
        conn.close()


# ── Hitung ───────────────────────────────────────────────────────────────────

def _agregat(df: pd.DataFrame) -> bool:
    kol = set(df.columns.str.strip().str.lower())
    return {"bln", "city", "ps", "child"} <= kol


def _siapkan(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()
    if _agregat(df):
        if "cluster" not in df.columns:
            df["cluster"] = None
        city = df["city"].fillna("").str.strip().str.upper()
        df["wok"] = city.map(KAB2WOK).fillna(df["cluster"].fillna("").str.strip().str.upper().map(CLUSTER2WOK))
        df["branch"] = df["wok"].map(WOK_NEW_TO_BRANCH)
        df["bln"] = df["bln"].astype(str).str.strip().str[:7]
        df["ps"] = pd.to_numeric(df["ps"], errors="coerce").fillna(0)
        df["child"] = pd.to_numeric(df["child"], errors="coerce").fillna(0)
        return df
    kurang = [k for k in KOLOM_WAJIB if k not in df.columns]
    if kurang:
        raise ValueError(f"Kolom tidak ada: {', '.join(kurang)}")
    if "cluster" not in df.columns:
        df["cluster"] = None
    city = df["city"].fillna("").str.strip().str.upper()
    df["wok"] = city.map(KAB2WOK).fillna(df["cluster"].fillna("").str.strip().str.upper().map(CLUSTER2WOK))
    df["branch"] = df["wok"].map(WOK_NEW_TO_BRANCH)
    tgl = pd.to_datetime(df["activation_date_ih"].str[:10], errors="coerce")
    df["bln"] = tgl.dt.strftime("%Y-%m")
    df["hari"] = tgl.dt.day
    return df


def _cutoff_default(df: pd.DataFrame) -> date:
    if "event_date" in df.columns and df["event_date"].notna().any():
        return pd.to_datetime(df["event_date"].dropna().max()).date()
    return pd.to_datetime(df["activation_date_ih"].str[:10], errors="coerce").max().date()


def _metrics(d):
    if "ps" in d.columns and "child" in d.columns and "bb_id" not in d.columns:   # data agregat: jumlahkan
        ps, child = int(d["ps"].sum()), int(d["child"].sum())
        member = ps + child   # All Member = PS (1 parent per PS) + Child
        return dict(ps=ps, member=member, mpp=member / ps if ps else None,
                    child=child, cpp=child / ps if ps else None)
    ch = d[d["msisdn_child"].notna() & (d["msisdn_child"] != "") & (d["msisdn_child"] != d["msisdn_parent"])]
    ps = d["bb_id"].nunique()
    child = ch["msisdn_child"].nunique()
    member = ps + child   # All Member = PS (1 parent per PS) + Child
    return dict(ps=ps, member=member, mpp=member / ps if ps else None,
                child=child, cpp=child / ps if ps else None)


def hitung_childps(df_raw: pd.DataFrame, tgl: date = None) -> dict:
    """df_raw = data mentah (kolom asli SQL). tgl = cutoff (default: event_date terakhir)."""
    agregat = _agregat(df_raw)
    df = _siapkan(df_raw)
    if tgl is None:
        if agregat:
            raise ValueError("Data agregat butuh tanggal cutoff (DD-MM-YYYY)")
        tgl = _cutoff_default(df_raw.rename(columns=str.lower))
    lalu = tgl - relativedelta(months=1)
    akhir_bulan = tgl.day == calendar.monthrange(tgl.year, tgl.month)[1]
    hari_lalu = calendar.monthrange(lalu.year, lalu.month)[1] if akhir_bulan else tgl.day
    m_ini, m_lalu = tgl.strftime("%Y-%m"), lalu.strftime("%Y-%m")

    if agregat:   # batas hari sudah diterapkan di SQL (childps_sql.periode)
        d_ini, d_lalu = df[df.bln == m_ini], df[df.bln == m_lalu]
    else:
        d_ini = df[(df.bln == m_ini) & (df.hari <= tgl.day)]
        d_lalu = df[(df.bln == m_lalu) & (df.hari <= hari_lalu)]

    def row(mask_fn, **lbl):
        a, b = _metrics(mask_fn(d_lalu)), _metrics(mask_fn(d_ini))
        r = dict(lbl)
        for k in a:
            r[f"{k}_l"], r[f"{k}_i"] = a[k], b[k]
        r["cpp_d"] = None if a["cpp"] is None or b["cpp"] is None else b["cpp"] - a["cpp"]
        r["mpp_d"] = None if a["mpp"] is None or b["mpp"] is None else b["mpp"] - a["mpp"]
        return r

    woks = [row(lambda d, w=w: d[d.wok == w], _t="wok", branch=WOK_NEW_TO_BRANCH[w], name=w)
            for w in WOK_NEW_ORDER]
    branches = [row(lambda d, b=b: d[d.branch == b], _t="br", name=b)
                for b in dict.fromkeys(WOK_NEW_TO_BRANCH.values())]
    region = row(lambda d: d[d.wok.notna()], _t="reg", name=REGION_NAME)

    return dict(
        tgl=tgl, bl=BULAN[lalu.month], bi=BULAN[tgl.month],
        full_month=akhir_bulan,
        rows=woks + branches + [region], woks=woks, region=region,
        tanpa_wok=(int(df[df.wok.isna() & df.bln.isin([m_ini, m_lalu])]["ps"].sum()) if agregat
                   else int(df[df.wok.isna() & df.bln.isin([m_ini, m_lalu])]["bb_id"].nunique())),
    )


# ── Caption ──────────────────────────────────────────────────────────────────

def _nama(r):
    return "DIY" if r["name"] == "DAERAH ISTIMEWA YOGYAKARTA" else r["name"].title()


def _f(v, fmt):
    return "-" if v is None else format(v, fmt)


def buat_caption(res: dict) -> str:
    bl, bi, tgl = res["bl"], res["bi"], res["tgl"]
    periode = (f"FM {bi} vs {bl}" if res["full_month"] else f"MtD 1–{tgl.day} {bi} vs {bl}")

    def item(i, r):
        return f"{i}. {_nama(r)} : {_f(r['cpp_i'], '.2f')} ({r['child_i']:,} child / {r['ps_i']:,} PS)"

    reg = res["region"]
    woks = sorted([r for r in res["woks"] if r["cpp_i"] is not None],
                  key=lambda r: (r["cpp_i"], r["child_i"]), reverse=True)
    lines = [
        "📊 Child per PS Telkomsel One JATENG-DIY by WOK",
        periode,
        f"{REGION_NAME} : {_f(reg['cpp_i'], '.2f')} ({reg['child_i']:,} child / {reg['ps_i']:,} PS)",
        "", "📈 Top 3 WOK Child per PS",
    ]
    lines += [item(i, r) for i, r in enumerate(woks[:3], 1)]
    lines += ["", "📉 Bottom 3 WOK Child per PS"]
    lines += [item(i, r) for i, r in enumerate(list(reversed(woks))[:3], 1)]
    return "\n".join(lines)
