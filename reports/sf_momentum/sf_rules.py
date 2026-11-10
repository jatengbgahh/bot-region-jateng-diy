"""
reports/sf_momentum/sf_rules.py — Shared business rules for the SF master data used by
/5so, /7so, the "5SO 7SO per SF + RAW" Excel and /clockin_sf_all.

1. DUMMY_SF_CODES
   SF codes that exist in database_sf but are test / dummy accounts (agency "PT. COMPANY TEST",
   "Super User", ...). They must never be counted as real Sales Force, so they are removed from
   every SF snapshot, ordering row and DJP row before any metric is computed.

2. SF_SNAPSHOT_SOURCE_MONTH (SF Registered snapshot override)
   database_sf_YYYYMM is filled per event_date (one snapshot per day). For November 2026 the
   table database_sf_202611 was NOT refreshed by the data owner: it is a plain copy of
   database_sf_202610 with the event_date shifted to November. Because the 5SO/7SO snapshot is
   taken "on the report date" (MAX(event_date) <= report date), an MTD report for 7 Nov returned
   the data of 7 Oct, i.e. the same value as M1, and SF Registered MoM was always 0.00%.
   The correct source for November is therefore the LAST snapshot of October (end of period),
   because the real SF list has not changed since then.
   Mapping: report month -> month of the database_sf table whose last snapshot is used.
   Remove the entry once database_sf_202611 is refreshed with real November data.

3. Team Leader mapping (resources/team_leader/*.xlsx)
   Latest SF -> Team Leader mapping supplied by the region (file "update team leader sales
   force.xlsx", sheet target_upload_<month>). The newest .xlsx in that folder is used, so a
   future update only needs a new file dropped into the folder (no code change).
"""
from __future__ import annotations

import glob
import logging
import os
from datetime import date, datetime
from functools import lru_cache

logger = logging.getLogger(__name__)

# Dummy / test SF accounts — excluded from 5SO, 7SO (scorecard, SF Belum RE, per SF + RAW Excel)
# and Clock-In SF All Category. Keep the codes UPPERCASE.
DUMMY_SF_CODES = frozenset({
    "PUR6966596",   # "purs"        - PT. COMPANY TEST
    "YUS7289802",   # "Yuswita"     - PT. COMPANY TEST
    "SUP5316382",   # "Super User"  - test account
})

# Report month (YYYYMM) -> month (YYYYMM) of the database_sf table to read instead.
# The LAST snapshot (MAX(event_date)) of the source table is used as "SF Registered MTD".
# See the module docstring (point 2) for the reason.
SF_SNAPSHOT_SOURCE_MONTH = {
    "202611": "202610",   # Nov 2026: database_sf_202611 is a copy of Oct -> use end-of-Oct snapshot
}

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def is_dummy(kode) -> bool:
    """True if the SF code is a dummy / test account (case and whitespace insensitive)."""
    return str(kode or "").strip().upper() in DUMMY_SF_CODES


def drop_dummy(df, col: str):
    """Return df without rows whose `col` is a dummy SF code (no-op for an empty frame)."""
    if df is None or df.empty or col not in df.columns:
        return df
    mask = df[col].fillna("").astype(str).str.strip().str.upper().isin(DUMMY_SF_CODES)
    return df[~mask].copy() if mask.any() else df


def sf_source_month(ym: str) -> str:
    """YYYYMM of the database_sf table that holds the SF Registered snapshot for report month ym."""
    return SF_SNAPSHOT_SOURCE_MONTH.get(ym, ym)


def sf_override_note(ym: str) -> str | None:
    """Short note (Indonesian, shown in captions/footers) when report month ym uses an override."""
    src = SF_SNAPSHOT_SOURCE_MONTH.get(ym)
    if not src:
        return None
    b_rep, b_src = int(ym[4:6]), int(src[4:6])
    # no underscore in this text: it is used inside Telegram Markdown captions
    return (f"SF Registered {_BULAN[b_rep - 1]} = snapshot akhir {_BULAN[b_src - 1]} "
            f"(data SF {_BULAN[b_rep - 1]} belum update)")


# ── Team Leader mapping ──────────────────────────────────────────────────────
TL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "resources", "team_leader")
_MON_EN = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _tl_code(v) -> str:
    """Excel turns codes like 'MAR3452' into a date (3452-03-01); rebuild the original text."""
    if isinstance(v, (datetime, date)):
        return f"{_MON_EN[v.month - 1]}{v.year}"
    return str(v or "").strip()


def tl_file() -> str | None:
    """Newest .xlsx in resources/team_leader (None if the folder is empty)."""
    files = [f for f in glob.glob(os.path.join(TL_DIR, "*.xlsx")) if not os.path.basename(f).startswith("~$")]
    return max(files, key=os.path.getmtime) if files else None


@lru_cache(maxsize=4)
def _load_tl(path: str, mtime: float) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        hdr = [str(c or "").strip().lower() for c in next(rows)]

        def col(*names):
            for n in names:
                if n in hdr:
                    return hdr.index(n)
            return None

        i_sf, i_tlc, i_tln = col("sf_code", "kode sf", "id sf"), col("tl_code"), col("tl_name", "team leader")
        i_ag, i_br, i_wok = col("agency"), col("branch"), col("wok")
        if i_sf is None or i_tln is None:
            raise ValueError(f"Kolom sf_code / tl_name tidak ada di {os.path.basename(path)}")
        out = {}
        for r in rows:
            kode = str(r[i_sf] or "").strip().upper() if len(r) > i_sf else ""
            if not kode:
                continue
            g = lambda i: (r[i] if i is not None and i < len(r) else None)
            out[kode] = {
                "tl_code": _tl_code(g(i_tlc)),
                "tl_name": str(g(i_tln) or "").strip(),
                "agency": str(g(i_ag) or "").strip(),
                "branch": str(g(i_br) or "").strip(),
                "wok": str(g(i_wok) or "").strip(),
            }
        return out
    finally:
        wb.close()


def load_tl_map() -> dict:
    """{SF CODE: {tl_code, tl_name, agency, branch, wok}} from the newest mapping file ({} if none)."""
    p = tl_file()
    if not p:
        logger.warning("Mapping Team Leader tidak ditemukan di %s", TL_DIR)
        return {}
    try:
        return _load_tl(p, os.path.getmtime(p))
    except Exception as e:                      # mapping is informative only: never break a report
        logger.warning("Gagal membaca mapping Team Leader %s: %s", p, e)
        return {}
