"""
csv_fake_db.py — DB "palsu" berbasis SQLite untuk menjalankan kode laporan bot
ketika MySQL tidak bisa diakses.

Sumber: CSV export manual tabel indihome_ordering_detail (bulan 09 & 10, filter
NEW SALES + region JATENG). Satu baris CSV masuk ke tabel bulan sesuai kolom
event_date (kolom itu = partisi bulan tabel sumber; satu order bisa muncul di
kedua bulan, sama seperti di DB asli).

Semua query SQL di db.py / reports/* / calculator_* dipakai APA ADANYA — shim ini
cuma menerjemahkan dialek MySQL -> SQLite (placeholder %s, fungsi DATE/HOUR/
CONCAT/LPAD, collation case-insensitive) dan mengembalikan tipe date/datetime
seperti mysql.connector.

Pemakaian:  csv_fake_db.install(path_csv)   # sebelum import bot / jalankan laporan
"""
import hashlib
import json
import re
import sqlite3
import threading
from datetime import date, datetime

import pandas as pd
import reports as _reports_aliases  # noqa: F401 — aktifkan alias modul lama di sys.meta_path
from mysql.connector import Error as MySQLError

_RE_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$")
_RE_D = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUM_COLS = {"longitude", "latitude", "hp_longitude", "hp_latitude",
             "price_total", "price_package", "fee_psb", "speed_product"}

_con = None
_tables = {}
_LOCK = threading.RLock()   # murmer query paralel (thread) -> satu koneksi SQLite harus diserialkan
EXTRA = None    # mode hibrid: query tertentu dijawab dari export agregat, sisanya dari SQLite raw
RECORD = None   # dict key -> info, diisi saat mode rekam
REPLAY = None   # dict key -> {"cols":[...], "rows":[...]} saat mode replay (tanpa tabel sama sekali)
META = {}


SHIFT = None    # mode rekam dgn data referensi: {"delta": timedelta, "bulan": {"YYYYMM": "YYYYMM_ref"}}


def set_shift(tanggal_target, tanggal_ref=date(2026, 10, 18)):
    """Rekam untuk tanggal_target memakai data referensi: tanggal & nama tabel digeser ke jendela referensi."""
    global SHIFT
    from datetime import timedelta
    from dateutil.relativedelta import relativedelta
    t0, t1 = tanggal_target.replace(day=1), tanggal_target.replace(day=1) - relativedelta(months=1)
    SHIFT = {"delta": tanggal_target - tanggal_ref,
             "bulan": {t0.strftime("%Y%m"): tanggal_ref.strftime("%Y%m"),
                       t1.strftime("%Y%m"): (tanggal_ref.replace(day=1) - relativedelta(months=1)).strftime("%Y%m")},
             "lain": (tanggal_ref.replace(day=1) - relativedelta(months=1)).strftime("%Y%m")}


def _geser(sql, params):
    d = SHIFT["delta"]

    def tabel(m):
        return m.group(1) + SHIFT["bulan"].get(m.group(2), SHIFT["lain"])
    sql2 = re.sub(r"(indihome_ordering_detail_)(\d{6})", tabel, sql)

    def p(v):
        if isinstance(v, str):
            if _RE_DT.match(v):
                return (datetime.strptime(v[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S") - d).strftime("%Y-%m-%d %H:%M:%S")
            if _RE_D.match(v):
                return (datetime.strptime(v, "%Y-%m-%d") - d).strftime("%Y-%m-%d")
        return v
    return sql2, tuple(p(v) for v in params)


_RE_DH = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}$")


def _geser_balik(v):
    """Hasil query (tanggal referensi) -> tanggal target, supaya filter Python di kode laporan lolos."""
    if isinstance(v, str) and v[:4].isdigit() and not v.startswith("0000"):
        d = SHIFT["delta"]
        try:
            if _RE_DT.match(v):
                return (datetime.strptime(v[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S") + d).strftime("%Y-%m-%d %H:%M:%S")
            if _RE_D.match(v):
                return (datetime.strptime(v, "%Y-%m-%d") + d).strftime("%Y-%m-%d")
            if _RE_DH.match(v):
                return (datetime.strptime(v[:10], "%Y-%m-%d") + d).strftime("%Y-%m-%d") + v[10:]
        except ValueError:
            pass
    return v


def _norm(sql):
    return " ".join(sql.split())


def _key(sql, params):
    return hashlib.sha1((_norm(sql) + "|" + repr(params)).encode()).hexdigest()[:12]


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "''") + "'"


def _inline(sql, params):
    it = iter(params)
    return re.sub(r"%s", lambda m: _lit(next(it)), sql).replace("%%", "%")


def _load(path, bulan=None):
    """Baca 1 CSV (boleh .gz) per potongan, simpan HANYA order_type NEW SALES (semua laporan
    memfilter itu) supaya file raw 250MB+ berisi MODIFICATION tidak menghabiskan memori.
    bulan 'YYYYMM' = cadangan partisi tabel untuk baris tanpa event_date."""
    import gzip
    buka = gzip.open if str(path).endswith(".gz") else open
    with buka(path, "rt", encoding="utf-8-sig") as f:
        baris1 = f.readline()
    skip = 1 if baris1.lower().startswith("sep=") else 0
    sep = ";" if (baris1.count(";") > baris1.count(",") or skip) else ","
    bagian = []
    for ch in pd.read_csv(path, sep=sep, skiprows=skip, dtype=str, keep_default_na=False,
                          encoding="utf-8-sig", chunksize=50_000):
        bagian.append(ch[ch["order_type"].str.strip().str.upper() == "NEW SALES"])
    df = pd.concat(bagian, ignore_index=True)
    df = df.replace({"": None})
    for c in df.columns:
        s = df[c]
        if s.dropna().str.match(r"^0000-00-00").any():
            df[c] = s.where(~s.fillna("").str.startswith("0000-00-00"), None)
    for c in _NUM_COLS & set(df.columns):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["_bln"] = df["event_date"].str[:7].str.replace("-", "", regex=False)
    if bulan:
        df["_bln"] = df["_bln"].fillna(bulan)
    elif "io_ts" in df.columns:   # baris tanpa event_date (jarang): partisi dari bulan io_ts
        df["_bln"] = df["_bln"].fillna(df["io_ts"].fillna("").str[:7].str.replace("-", "", regex=False).replace("", None))
    return df.dropna(subset=["_bln"])


def _udf_date(v):
    if v is None:
        return None
    v = str(v)[:10]
    return v if _RE_D.match(v) and not v.startswith("0000") else None


def _udf_hour(v):
    if v is None:
        return None
    try:
        return int(str(v)[11:13])
    except ValueError:
        return None


def _udf_concat(*a):
    return None if any(x is None for x in a) else "".join(str(x) for x in a)


def _udf_lpad(s, n, pad):
    return None if s is None else str(s).rjust(int(n), str(pad))[-int(n):]


def _udf_year(v):
    return int(str(v)[:4]) if v and str(v)[:4].isdigit() else None


def _udf_month(v):
    return int(str(v)[5:7]) if v and len(str(v)) >= 7 else None


def _udf_day(v):
    return int(str(v)[8:10]) if v and len(str(v)) >= 10 else None


def _udf_datediff(a, b):
    try:
        return (datetime.strptime(str(a)[:10], "%Y-%m-%d") - datetime.strptime(str(b)[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def _conv_param(p):
    if isinstance(p, datetime):
        return p.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(p, date):
        return p.strftime("%Y-%m-%d")
    return p


def _conv_val(v):
    if isinstance(v, str):
        if v.startswith("0000-00-00"):          # tanggal nol MySQL -> None (seperti mysql.connector)
            return None
        if _RE_DT.match(v):
            return datetime.strptime(v[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        if _RE_D.match(v):
            return datetime.strptime(v, "%Y-%m-%d").date()
    return v


def _translate(sql):
    sql = re.sub(r"%s", "?", sql)
    return sql.replace("%%", "%")


class _Cursor:
    def __init__(self, con, dictionary=False, **_):
        self._c = con.cursor() if con is not None else None   # mode replay: tanpa SQLite
        self._dict = dictionary
        self._rows = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        params = tuple(_conv_param(p) for p in (params or ()))
        k = _key(sql, params)
        s_up = _norm(sql).upper()
        if s_up == "SELECT DATABASE()":                       # murmer._tabel_ada
            self._cols, self._rows, self.rowcount = ["DATABASE()"], [("rajawalidb1",)], 1
            return
        if "INFORMATION_SCHEMA.TABLES" in s_up:               # anggap semua tabel kandidat ada
            self._cols, self._rows = ["table_name"], [(t,) for t in params[1:]]
            self.rowcount = len(self._rows)
            return
        sumber = REPLAY if REPLAY is not None else (EXTRA if EXTRA and k in EXTRA else None)
        if sumber is not None:
            q = sumber.get(k)
            if q is None:
                raise MySQLError(msg=f"[replay] query tidak ada di export: {_norm(sql)[:140]}")
            self._cols, self._rows = q["cols"], [tuple(r) for r in q["rows"]]
            self.rowcount = len(self._rows)
            return
        sql_x, params_x = (_geser(sql, params) if SHIFT else (sql, params))
        with _LOCK:
            try:
                self._c.execute(_translate(sql_x), params_x)
            except sqlite3.OperationalError as e:
                raise MySQLError(msg=str(e)) from e
            cols = [d[0] for d in (self._c.description or [])]
            self._cols = cols
            self._rows = self._c.fetchall()
        if SHIFT:
            self._rows = [tuple(_geser_balik(v) for v in r) for r in self._rows]
        self.rowcount = len(self._rows)
        if RECORD is not None and cols:
            RECORD[k] = {"cols": cols, "sql": _inline(sql, params), "nrows": len(self._rows)}

    def _wrap(self, r):
        vals = [_conv_val(v) for v in r]
        return dict(zip(self._cols, vals)) if self._dict else tuple(vals)

    def fetchall(self):
        out = [self._wrap(r) for r in self._rows]
        self._rows = []
        return out

    def fetchone(self):
        if not self._rows:
            return None
        return self._wrap(self._rows.pop(0))

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        pass


class _Conn:
    def __init__(self, con):
        self._con = con

    def cursor(self, dictionary=False, **kw):
        return _Cursor(self._con, dictionary=dictionary)

    def close(self):
        pass

    def is_connected(self):
        return True

    def commit(self):
        pass

    def set_converter_class(self, cls):
        pass


def get_connection(*_a, **_k):
    return _Conn(_con)


def install(path_csv, alias_kosong=False):
    """Muat CSV -> SQLite in-memory, lalu timpa semua jalur koneksi DB di modul bot."""
    global _con
    paths = [path_csv] if isinstance(path_csv, (str, tuple)) else list(path_csv)   # terbaru dulu
    frames = [_load(*(x if isinstance(x, tuple) else (x,))) for x in paths]
    df = pd.concat(frames, ignore_index=True)
    if len(frames) > 1:        # satu order sama di file lama & baru: pakai yang terbaru (urutan pertama)
        df = df.drop_duplicates(subset=["order_id", "_bln"], keep="first")
    _con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, fn, n in [("DATE", _udf_date, 1), ("HOUR", _udf_hour, 1), ("CONCAT", _udf_concat, -1),
                        ("LPAD", _udf_lpad, 3), ("YEAR", _udf_year, 1), ("MONTH", _udf_month, 1),
                        ("DAY", _udf_day, 1), ("DATEDIFF", _udf_datediff, 2)]:
        _con.create_function(name, n, fn)

    for bln, part in df.groupby("_bln"):
        part = part.drop(columns="_bln")
        tabel = f"indihome_ordering_detail_{bln}"
        cols = ", ".join(
            f'"{c}" REAL' if c in _NUM_COLS else f'"{c}" TEXT COLLATE NOCASE' for c in part.columns
        )
        _con.execute(f'CREATE TABLE "{tabel}" ({cols})')
        ph = ",".join("?" * len(part.columns))
        _con.executemany(
            f'INSERT INTO "{tabel}" VALUES ({ph})',
            [tuple(None if pd.isna(v) else v for v in row) for row in part.itertuples(index=False, name=None)],
        )
        _tables[tabel] = len(part)
    if alias_kosong:   # HANYA untuk uji: bulan yang tidak ada dibuat view ke bulan terdekat yang ada
        ada = sorted(_tables)
        for m in range(1, 13):
            t = f"indihome_ordering_detail_2026{m:02d}"
            if t not in _tables:
                _con.execute(f'CREATE VIEW "{t}" AS SELECT * FROM "{ada[0]}"')
    _con.commit()

    import db
    import calculator_daily
    db.get_connection = get_connection
    db.port_terbuka = lambda *a, **k: True
    db.test_connection = lambda *a, **k: True
    calculator_daily.get_connection = get_connection

    def _tgl_tersedia(tgl_closing=None):
        _ord = [t for t in _tables if t.startswith("indihome_ordering_detail_")]   # SF/DJP/churn tak punya io_ts
        r = _con.execute("SELECT DISTINCT substr(io_ts,1,10) FROM " + ' UNION ALL SELECT DISTINCT substr(io_ts,1,10) FROM '.join(
            f'"{t}"' for t in _ord)).fetchall() if _ord else []
        return sorted({datetime.strptime(x[0], "%Y-%m-%d").date() for x in r if x[0]}, reverse=True)
    db.query_tanggal_tersedia = _tgl_tersedia
    return dict(_tables)


# ── Mode rekam -> SQL gabungan -> replay ──────────────────────────────────────
MAKS_KOLOM = 30
MAKS_BARIS = 200_000
MURMER_KOLOM = ["order_id", "event_date", "region", "io_ts", "re_ts", "ps_ts"]
MAKS_KOLOM_RAW = 80     # query raw yang memang dibutuhkan laporan (agresif: 75 kolom per order)
MAKS_BARIS_RAW = 60_000


def mulai_rekam():
    global RECORD
    RECORD = {}


def _bagian_dari(v):
    """Kelompok query untuk pemecahan run: nasional | murmer | lain."""
    c = v["cols"]
    if c == ["region", "n", "rev"] or c == ["last_update", "total_rows"]:
        return "nasional"
    if c == MURMER_KOLOM:
        return "murmer"
    return "lain"


_RE_RENTANG = re.compile(r"(io|re|ps)_ts >= '([^']+)' AND (?:io|re|ps)_ts < '([^']+)'")
_RE_TABEL = re.compile(r"FROM `(indihome_ordering_detail_\d+)`")


def _gabung_nasional(items):
    """Query nasional io/re/ps per bulan (3 scan tabel) -> 1 scan per bulan lewat CTE.
    items: {key: info}. Return (sql_bagian_list, key_terpakai)."""
    per_tabel, pakai = {}, set()
    for k, v in items.items():
        if v["cols"] != ["region", "n", "rev"]:
            continue
        m, t = _RE_RENTANG.search(v["sql"]), _RE_TABEL.search(v["sql"])
        if not (m and t) or "GROUP BY region" not in v["sql"]:
            continue
        per_tabel.setdefault(t.group(1), {})[m.group(1)] = (k, m.group(2), m.group(3))
    cte, sel = [], []
    for i, (tabel, d) in enumerate(per_tabel.items()):
        if set(d) != {"io", "re", "ps"}:
            continue
        agg, filt = [], []
        for met in ("io", "re", "ps"):
            k, a_, b_ = d[met]
            cond = f"{met}_ts >= '{a_}' AND {met}_ts < '{b_}'"
            agg.append(f"COUNT(CASE WHEN {cond} THEN 1 END) AS {met}_n, "
                       f"SUM(CASE WHEN {cond} THEN price_package END) AS {met}_rev")
            filt.append(f"({cond})")
        cte.append(f"x{i} AS (SELECT region, {', '.join(agg)} FROM `{tabel}` "
                   f"WHERE order_type = 'NEW SALES' AND (product_commercial_name NOT LIKE '%WIRELESS%' "
                   f"OR product_commercial_name IS NULL) AND ({' OR '.join(filt)}) GROUP BY region)")
        for met in ("io", "re", "ps"):
            k = d[met][0]
            pakai.add(k)
            sel.append(f"SELECT '{k}' AS q, JSON_ARRAY(region, {met}_n, {met}_rev) AS j FROM x{i} WHERE {met}_n > 0")
    return cte, sel, pakai


def buat_paket(path_sql, path_manifest, meta=None, bagian=None):
    """Tulis SQL gabungan (1 statement UNION ALL) + manifest.
    bagian: None (semua) atau 'nasional' / 'murmer' / 'murmer-awal' / 'murmer-akhir' -> hanya sebagian query.
    Tiap query ikut menulis 1 baris penanda (q, NULL) supaya replay tahu query itu SUDAH dijalankan
    (bedakan 'hasil kosong' dari 'belum di-run')."""
    ok, lewat = {}, {}
    for k, v in RECORD.items():
        if _norm(v["sql"]).upper().startswith("SELECT *,"):
            lewat[k] = "SELECT * (ZIP raw closing, tidak dipaket)"
        elif _norm(v["sql"]).upper().startswith("SELECT * FROM"):
            # murmer: kode hanya memakai kolom ini -> ambil subset saja (bukan 77 kolom)
            v["cols"] = [c for c in MURMER_KOLOM if c in v["cols"]]
            v["sql"] = re.sub(r"(?i)^\s*SELECT \*", "SELECT " + ", ".join(v["cols"]), v["sql"], count=1)
            ok[k] = v
        elif len(v["cols"]) > MAKS_KOLOM_RAW or v["nrows"] > MAKS_BARIS_RAW:
            lewat[k] = "terlalu besar/lebar"
        elif (len(v["cols"]) > MAKS_KOLOM or v["nrows"] > MAKS_BARIS) and not v["sql"].lstrip().upper().startswith("SELECT BB_ID"):
            lewat[k] = "terlalu besar/lebar (butuh raw)"
        elif not all(re.fullmatch(r"\w+", c) for c in v["cols"]):
            lewat[k] = "kolom tanpa alias"
        else:
            ok[k] = v

    if bagian:
        murmer = sorted((k for k, v in ok.items() if _bagian_dari(v) == "murmer"),
                        key=lambda k: _RE_TABEL_ANY.search(ok[k]["sql"]).group(1))
        sep = len(murmer) // 2
        pilih = {"nasional": [k for k, v in ok.items() if _bagian_dari(v) == "nasional"],
                 "murmer": murmer, "murmer-awal": murmer[:sep], "murmer-akhir": murmer[sep:]}[bagian]
        ok = {k: ok[k] for k in pilih}

    cte, bagian_sql, terpakai = _gabung_nasional(ok)
    for k, v in ok.items():
        if k in terpakai:
            continue
        bagian_sql.append(
            f"SELECT '{k}' AS q, JSON_ARRAY({', '.join('`' + c + '`' for c in v['cols'])}) AS j "
            f"FROM ({v['sql'].strip().rstrip(';')}) AS t")
    bagian_sql += [f"SELECT '{k}' AS q, NULL AS j" for k in ok]      # penanda "query ini sudah jalan"
    teks = ("WITH " + ",\n".join(cte) + "\n" if cte else "") + "\nUNION ALL\n".join(bagian_sql)
    with open(path_sql, "w", encoding="utf-8") as f:
        f.write(teks)
    with open(path_manifest, "w", encoding="utf-8") as f:
        json.dump({"meta": meta or {},
                   "queries": {k: {"cols": v["cols"], "sql": v["sql"][:300]} for k, v in RECORD.items()
                               if k not in lewat},    # manifest SELALU lengkap; SQL boleh sebagian (--bagian)
                   "dilewati": {k: {"alasan": r, "sql": RECORD[k]["sql"][:300]} for k, r in lewat.items()}},
                  f, ensure_ascii=False, indent=1)
    return len(ok), lewat


_RE_TABEL_ANY = re.compile(r"(indihome_ordering_detail_\d+)")


def jalankan_paket_lokal(path_sql, path_export):
    """Simulasi Console Rajawali: jalankan SQL gabungan di SQLite, tulis export CSV (q;j)."""
    import csv
    sql = open(path_sql, encoding="utf-8").read().replace("%%", "%")
    rows = _con.execute(sql).fetchall()
    with open(path_export, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["q", "j"])
        w.writerows(rows)
    return len(rows)


def _baca_export(path_export, path_manifest):
    man = json.load(open(path_manifest, encoding="utf-8"))
    with open(path_export, encoding="utf-8-sig") as f:
        baris1 = f.readline()
    skip = 1 if baris1.lower().startswith("sep=") else 0
    with open(path_export, encoding="utf-8-sig") as f:
        for _ in range(skip):
            f.readline()
        kepala = f.readline()
    sep = ";" if kepala.count(";") >= kepala.count(",") else ","
    df = pd.read_csv(path_export, sep=sep, skiprows=skip, dtype=str, keep_default_na=False,
                     encoding="utf-8-sig")
    df.columns = [c.strip().lower() for c in df.columns]
    hasil = {k: {"cols": v["cols"], "rows": [], "seen": False} for k, v in man["queries"].items()}
    for q, j in zip(df["q"], df["j"]):
        if q not in hasil:
            continue
        hasil[q]["seen"] = True
        if j.strip() and j.strip().lower() != "null":
            hasil[q]["rows"].append(json.loads(j))
    return hasil, man


def pasang_extra(path_export, path_manifest):
    """Mode hibrid: raw Jateng dari SQLite (install), query di manifest dijawab dari export agregat.
    path_export boleh list (beberapa run). Hanya query yang SUDAH dijalankan (ada penanda) yang dipakai."""
    global EXTRA
    EXTRA = {}
    for pth in ([path_export] if isinstance(path_export, str) else path_export):
        h, _ = _baca_export(pth, path_manifest)
        for k, v in h.items():
            if v["seen"]:
                EXTRA[k] = v if k not in EXTRA else {**EXTRA[k], "rows": EXTRA[k]["rows"] + v["rows"]}
    return len(EXTRA)


def install_replay(path_export, path_manifest):
    """Pasang DB 'tanpa tabel': semua query dijawab dari export agregat."""
    global REPLAY
    REPLAY, man = _baca_export(path_export, path_manifest)
    tgl = man["meta"].get("tanggal")

    import db
    import calculator_daily
    db.get_connection = get_connection
    db.port_terbuka = lambda *a, **k: True
    db.test_connection = lambda *a, **k: True
    calculator_daily.get_connection = get_connection
    db.query_tanggal_tersedia = lambda *a, **k: [datetime.strptime(tgl, "%d-%m-%Y").date()] if tgl else []
    return len(REPLAY)


# ── Tabel lain (mis. churn_dd_YYYYMM) dari ZIP/CSV export Rajawali ────────────
def install_kosong():
    """SQLite kosong + UDF + patch koneksi bot (untuk laporan yang tidak memakai ordering_detail)."""
    global _con
    _con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, fn, n in [("DATE", _udf_date, 1), ("HOUR", _udf_hour, 1), ("CONCAT", _udf_concat, -1),
                        ("LPAD", _udf_lpad, 3), ("YEAR", _udf_year, 1), ("MONTH", _udf_month, 1),
                        ("DAY", _udf_day, 1), ("DATEDIFF", _udf_datediff, 2)]:
        _con.create_function(name, n, fn)
    import db
    import calculator_daily
    db.get_connection = get_connection
    db.port_terbuka = lambda *a, **k: True
    db.test_connection = lambda *a, **k: True
    calculator_daily.get_connection = get_connection


def muat_tabel(path, tabel, tambah=None):
    """Muat 1 ZIP/CSV (format `sep=;` Rajawali) sebagai tabel SQLite `tabel`. Return jumlah baris."""
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df = df.replace({"": None})
    for c in df.columns:
        s = df[c]
        if s.dropna().str.match(r"^0000-00-00").any():
            df[c] = s.where(~s.fillna("").str.startswith("0000-00-00"), None)
    for k, v in (tambah or {}).items():      # kolom konstan utk export yang sudah difilter; tabel penuh dibiarkan
        if k not in df.columns:
            df[k] = v
    cols = ", ".join(f'"{c}" TEXT COLLATE NOCASE' for c in df.columns)
    _con.execute(f'CREATE TABLE "{tabel}" ({cols})')
    _con.executemany(f'INSERT INTO "{tabel}" VALUES ({",".join("?" * len(df.columns))})',
                     [tuple(None if pd.isna(v) else v for v in r) for r in df.itertuples(index=False, name=None)])
    _con.commit()
    _tables[tabel] = len(df)
    return len(df)


def muat_hourly(path, awalan="dashboard_hourly_sales_"):
    """Muat export dashboard_hourly_sales (boleh berisi >1 bulan) -> tabel per bulan activity_date."""
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df = df.replace({"": None})
    angka = {"activity_hour", "io_trx", "re_trx", "ps_trx", "ps_rev"} & set(df.columns)
    for c in angka:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    hasil = {}
    for bln, part in df.groupby(df["activity_date"].str[:7].str.replace("-", "", regex=False)):
        tabel = f"{awalan}{bln}"
        cols = ", ".join(f'"{c}" REAL' if c in angka else f'"{c}" TEXT COLLATE NOCASE' for c in part.columns)
        _con.execute(f'DROP TABLE IF EXISTS "{tabel}"')     # file bulan yang sama dimuat lagi = yang terbaru menggantikan
        _con.execute(f'CREATE TABLE "{tabel}" ({cols})')
        _con.executemany(f'INSERT INTO "{tabel}" VALUES ({",".join("?" * len(part.columns))})',
                         [tuple(None if pd.isna(v) else v for v in r) for r in part.itertuples(index=False, name=None)])
        hasil[tabel] = len(part)
        _tables[tabel] = len(part)
    _con.commit()
    return hasil


def muat_export_caps(path, tgl):
    """Export satu-query caps_sql.py (kolom q;j) -> 6 tabel SQLite bernama sama dgn tabel asli.
    Return {tabel: jumlah_baris}."""
    from dateutil.relativedelta import relativedelta
    ini = tgl.replace(day=1)
    lalu = ini - relativedelta(months=1)
    f = lambda d: d.strftime("%Y%m")
    churn_k = ["bb_id", "kabupaten", "region", "los_category", "deactivation_date"]
    seg_k = ["bb_id", "customer_segment"]
    ret_k = ["bb_id", "kabupaten", "region_sales", "unit_type", "reason", "deactivation_date", "retention_category"]
    skema = {
        "churn_ini": (f"churn_dd_{f(ini)}", churn_k), "churn_lalu": (f"churn_dd_{f(lalu)}", churn_k),
        "seg_ini": (f"ih_cb_cvm_prfl_mm_{f(ini - relativedelta(months=1))}", seg_k),
        "seg_lalu": (f"ih_cb_cvm_prfl_mm_{f(lalu - relativedelta(months=1))}", seg_k),
        "ret_ini": (f"retensi_dd_{f(ini)}", ret_k), "ret_lalu": (f"retensi_dd_{f(lalu)}", ret_k),
    }
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    hasil = {}
    for tag, (tabel, kolom) in skema.items():
        rows = [json.loads(j) for j in df.loc[df["q"] == tag, "j"]]
        _con.execute(f'CREATE TABLE "{tabel}" ({", ".join(chr(34) + c + chr(34) + " TEXT COLLATE NOCASE" for c in kolom)})')
        _con.executemany(f'INSERT INTO "{tabel}" VALUES ({",".join("?" * len(kolom))})', rows)
        hasil[tabel] = len(rows)
        _tables[tabel] = len(rows)
    _con.commit()
    return hasil


def muat_export_ms(path, tgl=None):
    """Export ms_sql.py (kolom q;j) -> tabel SQLite fixed_ms_city, fixed_ms_branch, fixed_ms_region.
    Return {tabel: jumlah_baris}."""
    kolom_pemain = [
        "indihome", "tsel_orbit", "cbn_network", "icon_pln", "xl_home",
        "first_media", "indosat", "myrepublic", "mnc_play", "biznet", "others",
    ]
    kolom_base = kolom_pemain + ["status", "closest_competitor"]
    skema = {
        "city": ("fixed_ms_city", ["event_date", "city"] + kolom_base, {"region": "JATENG-DIY"}),
        "branch": ("fixed_ms_branch", ["event_date", "branch"] + kolom_base, {"region": "JATENG-DIY"}),
        "region": ("fixed_ms_region", ["event_date", "region"] + kolom_base, {}),
    }
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    hasil = {}
    for tag, (tabel, kolom, tambah) in skema.items():
        sub = df.loc[df["q"] == tag, "j"]
        rows = [json.loads(j) for j in sub]
        cols_all = kolom + list(tambah.keys())
        for r in rows:
            for v in tambah.values():
                r.append(v)
        _con.execute(f'DROP TABLE IF EXISTS "{tabel}"')
        cols_def = ", ".join(f'"{c}" TEXT COLLATE NOCASE' for c in cols_all)
        _con.execute(f'CREATE TABLE "{tabel}" ({cols_def})')
        _con.executemany(f'INSERT INTO "{tabel}" VALUES ({",".join("?" * len(cols_all))})', rows)
        hasil[tabel] = len(rows)
        _tables[tabel] = len(rows)
    _con.commit()
    return hasil


def muat_export_c3mr(path, tgl):
    """Export c3mr_sql.py (q;j) -> ganti db.query_c3mr / query_c3mr_segment / query_c3mrnew supaya kalkulator ASLI
    (c3mr, c3mrsvp, c3mr10s, c3mrnew, c3mrnewch) memakainya tanpa MySQL. Label yang dikenali:
      A_ini/A_lalu [city, los, segment, subs, bill, paid_subs, clearing, unpaid]  -> c3mr, c3mrsvp, c3mr10s
      C_ini/C_lalu [city, los, subs, bill, paid_subs, clearing, unpaid]           -> c3mr, c3mrsvp saja (--bagian C)
      N_ini/N_lalu [city, bill_n, channel_group, subs, bill, clearing, unpaid]    -> c3mrnew, c3mrnewch
    Tiap kelompok diekspansi jadi `subs` baris dgn jumlah subs/bill/paid_subs/clearing/unpaid sama persis (diuji
    identik dgn data mentah). Dict dipakai ulang (referensi) agar hemat memori. Return ringkasan label."""
    import db
    import wilayah
    from dateutil.relativedelta import relativedelta
    bp_ini = (tgl - relativedelta(months=1)).replace(day=1) if tgl.day <= 5 else tgl.replace(day=1)
    cut = {"ini": tgl, "lalu": tgl - relativedelta(months=1)}
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    data = {}
    for q, j in zip(df["q"], df["j"]):
        data.setdefault(q, []).append(json.loads(j))
    ada = lambda k: bool(data.get(k))
    punya_a = ada("A_ini") and ada("A_lalu")
    punya_c = ada("C_ini") and ada("C_lalu")
    punya_n = ada("N_ini") and ada("N_lalu")
    if not (punya_a or punya_c or punya_n):
        raise ValueError("Export tidak berisi label A_*, C_* maupun N_* (jalankan c3mr_sql.py).")

    def periode(bp):
        return "ini" if (bp.year, bp.month) == (bp_ini.year, bp_ini.month) else "lalu"

    def kelompok(rows_q, tag_cut, with_city, flag_seg):
        """rows_q: baris (city, los, [segment], subs, bill, paid_subs, clearing, unpaid) -> (list baris, {gid: segment})."""
        out, seg_map = [], {}
        for gi, r in enumerate(rows_q):
            if flag_seg:
                city, los, seg, subs, bill, paid_subs, clr, unpaid = r
            else:
                city, los, subs, bill, paid_subs, clr, unpaid = r
                seg = None
            h = wilayah.petakan_kab(city)
            if h is None or not subs:
                continue
            gid = f"G{tag_cut}{gi}"
            if flag_seg:
                seg_map[gid] = seg
            base = {"wok": h[0], "branch": h[1], "account_num": None, "bb_id": gid, "los_category": los,
                    "bill_amount": (bill or 0) / subs}
            if with_city:
                base["city"] = wilayah.nama_kab(city)

            def mk(flag, bayar, clearing=0.0):
                d = dict(base)
                d.update(clearing_amount=clearing, paid_flag=flag, payment_date=cut[tag_cut] if bayar else None)
                return d
            out.append(mk(0 if unpaid > 0 else 1, paid_subs > 0, clr or 0))      # baris 0 membawa seluruh clearing
            n = subs - 1
            a_, b_ = max(unpaid - 1, 0), max(paid_subs - 1, 0)       # sisa unpaid / sisa paid utk baris 1..n
            lo, hi = min(a_, b_), max(a_, b_)
            if lo > 0:
                out += [mk(0, True)] * lo
            if hi - lo > 0:
                out += [mk(1, True) if a_ < b_ else mk(0, False)] * (hi - lo)
            if n - hi > 0:
                out += [mk(1, False)] * (n - hi)
        return out, seg_map

    cache = {}

    def bwmp(tag_cut, with_city):
        k = (tag_cut, with_city)
        if k not in cache:
            if punya_a:
                cache[k] = kelompok(data[f"A_{tag_cut}"], tag_cut, with_city, True)
            else:
                cache[k] = kelompok(data[f"C_{tag_cut}"], tag_cut, with_city, False)
        return cache[k]

    def query_c3mr(bill_period_date, with_city: bool = False):
        return list(bwmp(periode(bill_period_date), with_city)[0])

    def query_c3mr_segment(bill_period_date):
        if not punya_a:
            return {}
        return dict(bwmp(periode(bill_period_date), False)[1])

    def query_c3mrnew(bp_date, channel_group=None):
        tag = periode(bp_date)
        out = []
        for city, bill_n, ch, subs, bill, clr, unpaid in data.get(f"N_{tag}", []):
            h = wilayah.petakan_kab(city)
            if h is None or not subs:
                continue
            if channel_group and (ch or "").rstrip().upper() != channel_group.rstrip().upper():   # semantik "=" MySQL: spasi belakang diabaikan
                continue
            base = {"bb_id": None, "ps_ts": None, "channel_group": ch, "sf_code": None, "sf_company_name": None,
                    "product_commercial_name": None, "wok": h[0], "branch": h[1], "los_category": None,
                    "bill_n": bill_n, "bill_amount": (bill or 0) / subs}

            def mk(flag, clearing=0.0, tgl_bayar=None):
                d = dict(base)
                d.update(clearing_amount=clearing, paid_flag=flag, payment_date=tgl_bayar)
                return d
            out.append(mk(0 if unpaid > 0 else 1, clr or 0, cut[tag] if clr else None))
            if subs - 1 > 0:
                u = max(unpaid - 1, 0)
                out += [mk(0)] * u + [mk(1)] * (subs - 1 - u)
        return out

    if punya_a or punya_c:
        db.query_c3mr = query_c3mr
        db.query_c3mr_segment = query_c3mr_segment
    if punya_n:
        db.query_c3mrnew = query_c3mrnew
    return {k: (len(v), sum((x[2] if k.startswith("C") else x[3]) for x in v)) for k, v in data.items()}


def df_unpaid_c3mrnew(path):
    """Export c3mr_sql.py --bagian U (label U_ini) -> DataFrame lampiran CSV unpaid /c3mrnew dengan kolom & isi
    seperti calculator_c3mrnew (CSV_COLS; wok/branch dari city, bill_n = BILL-N). Baris city tak terpetakan dibuang
    (sama seperti bot yang membuang baris tanpa WOK)."""
    import wilayah
    kolom = ["bb_id", "ps_ts", "channel_group", "sf_code", "sf_company_name", "product_commercial_name", "city",
             "los_category", "bill_n", "bill_amount", "clearing_amount", "paid_flag", "payment_date"]
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    rows = [json.loads(j) for q, j in zip(df["q"], df["j"]) if q == "U_ini"]
    u = pd.DataFrame(rows, columns=kolom)
    peta = u["city"].map(lambda c: wilayah.petakan_kab(c))
    u = u[peta.notna()].copy()
    peta = peta[peta.notna()]
    u["wok"] = [h[0] for h in peta]
    u["branch"] = [h[1] for h in peta]
    for c in ("bill_amount", "clearing_amount"):
        u[c] = pd.to_numeric(u[c], errors="coerce").fillna(0)
    u["paid_flag"] = pd.to_numeric(u["paid_flag"], errors="coerce").fillna(0).astype(int)
    u["bill_n"] = pd.to_numeric(u["bill_n"], errors="coerce").fillna(0).astype(int).map(lambda n: f"BILL-{n}")
    u["ps_ts"] = u["ps_ts"].where(~u["ps_ts"].fillna("").str.startswith("0000-00-00"), None)
    return u[["bb_id", "ps_ts", "channel_group", "sf_code", "sf_company_name", "product_commercial_name", "wok",
              "branch", "los_category", "bill_n", "bill_amount", "clearing_amount", "paid_flag", "payment_date"]
             ].reset_index(drop=True)


def muat_export_homepass(path, tgl):
    """Export homepass_sql.py (kolom bln + kolom homepass_sales) -> tabel homepass_sales_YYYYMM (satu per bln).
    Ordering dimuat lebih dulu dari CSV iod_*; bulan ordering yang tidak diexport (2 bulan lalu, dipakai
    query_homepass utk bulan lalu) dibuat KOSONG berskema sama. Return {tabel: jumlah_baris}."""
    from dateutil.relativedelta import relativedelta
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df = df.replace({"": None})
    hasil = {}
    for bln, part in df.groupby("bln"):
        tabel = f"homepass_sales_{bln}"
        part = part.drop(columns="bln")
        _con.execute(f'CREATE TABLE "{tabel}" ({", ".join(chr(34) + c + chr(34) + " TEXT COLLATE NOCASE" for c in part.columns)})')
        _con.executemany(f'INSERT INTO "{tabel}" VALUES ({",".join("?" * len(part.columns))})',
                         [tuple(None if pd.isna(v) else v for v in r) for r in part.itertuples(index=False, name=None)])
        hasil[tabel] = len(part)
        _tables[tabel] = len(part)
    for i in range(3):                      # bulan homepass_sales yang tidak ada di export -> tabel kosong
        t = f"homepass_sales_{(tgl.replace(day=1) - relativedelta(months=i)):%Y%m}"
        if t not in _tables:
            _con.execute(f'CREATE TABLE "{t}" ({", ".join(chr(34) + c + chr(34) + " TEXT" for c in df.columns if c != "bln")})')
            _tables[t] = 0
    ord_ada = sorted(t for t in _tables if t.startswith("indihome_ordering_detail_"))
    if ord_ada:
        awal = tgl.replace(day=1)
        for i in range(3):
            t = f"indihome_ordering_detail_{(awal - relativedelta(months=i)):%Y%m}"
            if t not in _tables:
                _con.execute(f'CREATE TABLE "{t}" AS SELECT * FROM "{ord_ada[0]}" WHERE 0')
                _tables[t] = 0
    _con.commit()
    return hasil


def muat_export_sfo(path, tgl, lewati=()):
    """Export satu-query sfo_sql.py (kolom q;j) -> 6 tabel SQLite bernama sama dgn tabel asli
    (database_sf_*, indihome_ordering_detail_*, djp_daily_user_detailed_*). lewati = tag yang tidak dimuat
    (mis. {'djp_ini'} bila DJP bulan ini dipasok dari file lain). Return {tabel: jumlah_baris}."""
    from dateutil.relativedelta import relativedelta
    ini = tgl.replace(day=1)
    lalu = ini - relativedelta(months=1)
    f = lambda d: d.strftime("%Y%m")
    sf_k = ["kode", "nama", "wok", "region", "status", "event_date"]
    ord_k = ["order_id", "sf_code", "sf_name", "kabupaten", "event_date", "region", "order_type",
             "channel_group", "product_commercial_name", "ps_ts", "re_ts"]
    djp_k = ["user_code", "wok", "odp_name", "tugas_date", "regional"]
    skema = {}
    for tag, bln in (("ini", ini), ("lalu", lalu)):
        skema[f"sf_{tag}"] = (f"database_sf_{f(bln)}", sf_k)
        skema[f"ord_{tag}"] = (f"indihome_ordering_detail_{f(bln)}", ord_k)
        skema[f"djp_{tag}"] = (f"djp_daily_user_detailed_{f(bln)}", djp_k)
    df = pd.read_csv(path, sep=";", skiprows=1, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    ada = set(df["q"].unique())
    opsional = {"ord_ini", "ord_lalu", "djp_ini"}        # tidak wajib ada di export (lihat sfo_sql.py)
    hilang = [t for t in skema if t not in ada and t not in lewati and t not in opsional]
    if hilang:
        raise ValueError("Export tidak lengkap, label hilang: " + ", ".join(hilang))
    hasil = {}
    for tag, (tabel, kolom) in skema.items():
        if tag in lewati or (tag in opsional and tag not in ada):
            continue
        if tabel in _tables:                                # mis. ordering sudah dimuat dari CSV iod_*
            continue
        rows = []
        for j in df.loc[(df["q"] == tag) & (df["j"] != ""), "j"]:
            r = json.loads(j)
            rows.append([None if (isinstance(v, str) and v.startswith("0000-00-00")) else v for v in r])
        _con.execute(f'CREATE TABLE "{tabel}" ({", ".join(chr(34) + c + chr(34) + " TEXT COLLATE NOCASE" for c in kolom)})')
        _con.executemany(f'INSERT INTO "{tabel}" VALUES ({",".join("?" * len(kolom))})', rows)
        hasil[tabel] = len(rows)
        _tables[tabel] = len(rows)
    _con.commit()
    return hasil
