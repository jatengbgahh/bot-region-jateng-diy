"""
calculator_pranpc.py — /pranpcall: Recovery Rate (SSL) PraNPC All WO per WOK.

Rumus (mengikuti sheet "Report PraNPC" workbook Tracking PraNPC):
  WO MtD      = jumlah SSL base periode berjalan
  WO M-1      = jumlah SSL base periode bulan lalu
  Paid MtD    = SSL dengan status OCS != 'U' pada tanggal cut-off
  Paid M-1    = idem, base bulan lalu, pada tanggal yang sama bulan lalu
  MoM Paid    = Paid MtD / Paid M-1 - 1
  RR MtD      = Paid MtD / WO MtD
  MoM RR      = RR MtD - (Paid M-1 / WO M-1)               (selisih poin)
  Target RR   = target per Branch (pranpc_ref.TARGET_RR)
  Target Paid = Target RR x WO MtD
  Paid Gap    = Target Paid - Paid MtD
  Ach RR      = RR MtD / Target RR
"""

from collections import defaultdict
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import pranpc_data
import pranpc_ref
from config import REGION_NAME


class PranpcDataError(Exception):
    pass


def _periode(tgl: date) -> str:
    return tgl.strftime("%Y%m")


def resolve_tanggal(tgl_minta: date | None) -> tuple[date, str]:
    """
    Tentukan tanggal cut-off yang benar-benar ada datanya.
    Return (tgl, cur_periode). Tanpa argumen -> event_date terakhir bulan berjalan.
    """
    cur = pranpc_data.periode_berjalan()
    if tgl_minta is None:
        tgl = pranpc_data.tanggal_status_terakhir(cur, cur)
    else:
        tgl = pranpc_data.tanggal_status_terakhir(_periode(tgl_minta), cur, maks=tgl_minta)
    if tgl is None:
        raise PranpcDataError(
            f"Data status OCS PraNPC untuk "
            f"{tgl_minta.strftime('%d-%m-%Y') if tgl_minta else 'bulan berjalan'} belum tersedia."
        )
    if isinstance(tgl, datetime):
        tgl = tgl.date()
    return tgl, cur


def _agg(base: list[dict], status: dict) -> dict:
    """{wok: {'wo': n, 'paid': n, 'branch_votes': {branch: n}}}"""
    out = defaultdict(lambda: {"wo": 0, "paid": 0, "branch_votes": defaultdict(int)})
    for r in base:
        w = r["wok_svp"] or "(UNMAPPED)"
        a = out[w]
        a["wo"] += 1
        a["paid"] += pranpc_data.is_paid(status.get(str(r["snd"])))
        a["branch_votes"][r["branch"]] += 1
    return out


def _metrics(wo, paid, wo1, paid1, tgt_rr, tgt_paid=None):
    rr  = paid / wo if wo else None
    rr1 = paid1 / wo1 if wo1 else None
    if tgt_paid is None and tgt_rr is not None:
        tgt_paid = tgt_rr * wo
    return {
        "wo_m1"   : wo1,
        "wo"      : wo,
        "paid"    : paid,
        "paid_m1" : paid1,
        "mom_paid": (paid / paid1 - 1) * 100 if paid1 else None,
        "tgt_paid": tgt_paid,
        "gap"     : (tgt_paid - paid) if tgt_paid is not None else None,
        "tgt_rr"  : tgt_rr * 100 if tgt_rr is not None else None,
        "rr"      : rr * 100 if rr is not None else None,
        "ach"     : rr / tgt_rr * 100 if (rr is not None and tgt_rr) else None,
        "mom_rr"  : (rr - rr1) * 100 if (rr is not None and rr1 is not None) else None,
    }


def hitung_pranpc_all(tgl_minta: date | None = None) -> dict:
    tgl, cur = resolve_tanggal(tgl_minta)
    per   = _periode(tgl)
    per1  = _periode(tgl - relativedelta(months=1))

    tgl1 = pranpc_data.tanggal_status_terakhir(per1, cur, maks=tgl - relativedelta(months=1))
    if isinstance(tgl1, datetime):
        tgl1 = tgl1.date()

    base   = pranpc_data.load_base(per, cur)
    status = pranpc_data.load_status(per, cur, tgl)
    if not base:
        raise PranpcDataError(f"Base WO PraNPC periode {per} kosong.")
    m = _agg(base, status)

    if tgl1:
        base1   = pranpc_data.load_base(per1, cur)
        status1 = pranpc_data.load_status(per1, cur, tgl1)
        m1 = _agg(base1, status1)
    else:
        m1 = {}

    targets, per_target = pranpc_ref.target_rr(per)

    woks = []
    for w, a in m.items():
        branch = max(a["branch_votes"].items(), key=lambda kv: kv[1])[0]
        b1 = m1.get(w, {"wo": 0, "paid": 0})
        woks.append({"name": w, "branch": branch,
                     **_metrics(a["wo"], a["paid"], b1["wo"], b1["paid"], targets.get(branch))})

    def _bkey(b):
        return (pranpc_ref.BRANCH_ORDER.index(b) if b in pranpc_ref.BRANCH_ORDER else 99, b)
    woks.sort(key=lambda r: (_bkey(r["branch"]), r["name"]))

    def _sum(rows, k):
        vals = [r[k] for r in rows if r[k] is not None]
        return sum(vals) if vals else None

    branches = []
    for b in sorted({w["branch"] for w in woks}, key=_bkey):
        rows = [w for w in woks if w["branch"] == b]
        branches.append({"name": b, **_metrics(
            _sum(rows, "wo"), _sum(rows, "paid"), _sum(rows, "wo_m1") or 0,
            _sum(rows, "paid_m1") or 0, targets.get(b), _sum(rows, "tgt_paid"))})

    region = {"name": REGION_NAME, **_metrics(
        _sum(woks, "wo"), _sum(woks, "paid"), _sum(woks, "wo_m1") or 0,
        _sum(woks, "paid_m1") or 0, targets.get("_REGION"), _sum(woks, "tgt_paid"))}

    return {
        "tgl"          : tgl,
        "tgl_m1"       : tgl1,
        "tgl_minta"    : tgl_minta,
        "periode"      : per,
        "periode_target": per_target,
        "woks"         : woks,
        "branches"     : branches,
        "region"       : region,
    }


def bottom_woks(result: dict, n: int = 5) -> list[dict]:
    rows = [w for w in result["woks"] if w["rr"] is not None]
    return sorted(rows, key=lambda w: w["rr"])[:n]


def top_woks(result: dict, n: int = 5) -> list[dict]:
    rows = [w for w in result["woks"] if w["rr"] is not None]
    return sorted(rows, key=lambda w: w["rr"], reverse=True)[:n]


# ── /pranpcagent: Report PraNPC per Channel Agent ────────────────────────────
# Mengikuti sheet "per channel" workbook Tracking PraNPC:
#   Agency/Super Partner = mitra AGENCY + Super Partner
#   CTB = CTB, Freelance = FREELANCE, OBC TRANSKOM = OBC
#   Cont. (%) = WO channel / WO All;  %RR SSL = Paid channel / WO channel
#   Unpaid (SSL) = status OCS 'U';     Unpaid Rate = Unpaid / WO All
# Catatan: kolom mitra di tabel = alokasi TERKINI (ikut berubah tiap update
# tabel), jadi re-run tanggal lampau tetap memakai alokasi channel terbaru.
CHANNELS = [
    ("agency",    "Agency/Super Partner"),
    ("ctb",       "CTB"),
    ("freelance", "Freelance"),
    ("obc",       "OBC TRANSKOM"),
]
_MITRA_TO_CH = {"AGENCY": "agency", "SUPER PARTNER": "agency", "CTB": "ctb",
                "FREELANCE": "freelance", "OBC": "obc"}


def channel_of(mitra: str | None) -> str:
    return _MITRA_TO_CH.get((mitra or "").strip().upper(), "other")


def _agent_metrics(cnt: dict) -> dict:
    wo = cnt["all"][0]; paid = cnt["all"][1]
    out = {"wo": wo, "paid": paid, "rr": paid / wo * 100 if wo else None,
           "unpaid": wo - paid, "unpaid_rate": (wo - paid) / wo * 100 if wo else None}
    for k, _ in CHANNELS:
        cwo, cpaid = cnt[k]
        out[k] = {"wo": cwo, "paid": cpaid,
                  "cont": cwo / wo * 100 if wo else None,
                  "rr": cpaid / cwo * 100 if cwo else None}
    return out


def hitung_pranpc_agent(tgl_minta: date | None = None) -> dict:
    tgl, cur = resolve_tanggal(tgl_minta)
    per = _periode(tgl)
    base   = pranpc_data.load_base(per, cur)
    status = pranpc_data.load_status(per, cur, tgl)
    if not base:
        raise PranpcDataError(f"Base WO PraNPC periode {per} kosong.")

    def _new():
        return defaultdict(lambda: [0, 0])
    per_wok = defaultdict(_new)
    votes   = defaultdict(lambda: defaultdict(int))
    for r in base:
        w = r["wok_svp"] or "(UNMAPPED)"
        p = pranpc_data.is_paid(status.get(str(r["snd"])))
        for k in ("all", channel_of(r["mitra"])):
            per_wok[w][k][0] += 1
            per_wok[w][k][1] += p
        votes[w][r["branch"]] += 1

    def _bkey(b):
        return (pranpc_ref.BRANCH_ORDER.index(b) if b in pranpc_ref.BRANCH_ORDER else 99, b)

    woks = []
    for w, cnt in per_wok.items():
        branch = max(votes[w].items(), key=lambda kv: kv[1])[0]
        woks.append({"name": w, "branch": branch, "_cnt": cnt, **_agent_metrics(cnt)})
    woks.sort(key=lambda r: (_bkey(r["branch"]), r["name"]))

    def _gabung(rows):
        tot = _new()
        for r in rows:
            for k, (a, b) in r["_cnt"].items():
                tot[k][0] += a; tot[k][1] += b
        return tot

    branches = [{"name": b, **_agent_metrics(_gabung([w for w in woks if w["branch"] == b]))}
                for b in sorted({w["branch"] for w in woks}, key=_bkey)]
    region = {"name": REGION_NAME, **_agent_metrics(_gabung(woks))}
    for w in woks:
        w.pop("_cnt")

    return {"tgl": tgl, "tgl_minta": tgl_minta, "periode": per,
            "woks": woks, "branches": branches, "region": region}


# ── /moretensi: Retensi PraNPC All LoS ──────────────────────────────────────
# Mengikuti tabel "Retensi PraNPC All LoS" sheet Report PraNPC (semua basis Paid):
#   Target Retensi  = ROUND(10% x WO)
#   Paket Eksisting = Paid tanpa order (s/d cut off)
#   MO Retensi CTB / Non CTB = Paid, flag_order_created "MO CTB"/"MO non CTB",
#                     produk != "IndiHome Prepaid Retensi"
#   MO Prepaid      = Paid, produk "IndiHome Prepaid Retensi"
#   %MO Retensi     = (CTB + Non CTB) / Paid
#   Ach to Target   = (CTB + Non CTB) / Target
#   Gap to Target   = Target - MO Retensi CTB      (sesuai Excel: hanya CTB)
#   MoM MO Retensi  = (CTB + Non CTB) MtD / (CTB + Non CTB) M-1 s/d tgl sama - 1
#   DO              = Paid dengan do_order_id;  %DO = DO / Paid
#   New CT0 (Unpaid)= Unpaid - DO                  (sesuai Excel)
# Tabel hanya menyimpan kondisi TERKINI, jadi order/DO dihitung s/d akhir hari
# cut off (order_ts / do_order_ts) supaya tanggal lampau tetap benar.
PREPAID_RETENSI = "indihome prepaid retensi"
TARGET_RETENSI_PCT = 0.10


def _sd(ts, batas: datetime) -> bool:
    return ts is not None and ts <= batas


def _retensi_cnt(base, status, tgl) -> dict:
    batas = datetime(tgl.year, tgl.month, tgl.day, 23, 59, 59)
    out = defaultdict(lambda: defaultdict(int))
    for r in base:
        w = r["wok_svp"] or "(UNMAPPED)"
        a = out[w]
        a["wo"] += 1
        a["_br:" + str(r["branch"])] += 1
        if not pranpc_data.is_paid(status.get(str(r["snd"]))):
            a["unpaid"] += 1
            continue
        a["paid"] += 1
        punya_order = bool(r["order_id"]) and _sd(r["order_ts"], batas)
        pre = (r["product_commercial_name"] or "").strip().lower() == PREPAID_RETENSI
        if not punya_order:
            a["eks"] += 1
        elif pre:
            a["pre"] += 1
        elif r["flag_order_created"] == "MO CTB":
            a["ctb"] += 1
        elif r["flag_order_created"] == "MO non CTB":
            a["nonctb"] += 1
        if r["do_order_id"] and _sd(r["do_order_ts"], batas):
            a["do"] += 1
    return out


def _retensi_metrics(c: dict, mo_m1: int | None, target: int) -> dict:
    paid = c["paid"]; mo = c["ctb"] + c["nonctb"]
    return {
        "wo": c["wo"], "paid": paid, "target": target,
        "eks": c["eks"], "ctb": c["ctb"], "nonctb": c["nonctb"], "pre": c["pre"],
        "total": c["ctb"] + c["nonctb"] + c["pre"],
        "mo": mo, "mo_m1": mo_m1,
        "pct_eks": c["eks"] / paid * 100 if paid else None,
        "pct_mo": mo / paid * 100 if paid else None,
        "pct_pre": c["pre"] / paid * 100 if paid else None,
        "ach": mo / target * 100 if target else None,
        "mom": (mo / mo_m1 - 1) * 100 if mo_m1 else None,
        "gap": target - c["ctb"],
        "do": c["do"], "pct_do": c["do"] / paid * 100 if paid else None,
        "new_ct0": c["unpaid"] - c["do"],
    }


def hitung_pranpc_retensi(tgl_minta: date | None = None) -> dict:
    tgl, cur = resolve_tanggal(tgl_minta)
    per  = _periode(tgl)
    per1 = _periode(tgl - relativedelta(months=1))
    tgl1 = pranpc_data.tanggal_status_terakhir(per1, cur, maks=tgl - relativedelta(months=1))
    if isinstance(tgl1, datetime):
        tgl1 = tgl1.date()

    base = pranpc_data.load_base(per, cur)
    if not base:
        raise PranpcDataError(f"Base WO PraNPC periode {per} kosong.")
    m = _retensi_cnt(base, pranpc_data.load_status(per, cur, tgl), tgl)
    m1 = (_retensi_cnt(pranpc_data.load_base(per1, cur),
                       pranpc_data.load_status(per1, cur, tgl1), tgl1) if tgl1 else {})

    def _bkey(b):
        return (pranpc_ref.BRANCH_ORDER.index(b) if b in pranpc_ref.BRANCH_ORDER else 99, b)

    def _mo1(keys):
        if not m1:
            return None
        return sum(m1[k]["ctb"] + m1[k]["nonctb"] for k in keys if k in m1)

    woks = []
    for w, c in m.items():
        branch = max(((k[4:], v) for k, v in c.items() if k.startswith("_br:")), key=lambda kv: kv[1])[0]
        target = round(TARGET_RETENSI_PCT * c["wo"])
        woks.append({"name": w, "branch": branch, "_c": c,
                     **_retensi_metrics(c, _mo1([w]), target)})
    woks.sort(key=lambda r: (_bkey(r["branch"]), r["name"]))

    def _gabung(rows):
        tot = defaultdict(int)
        for r in rows:
            for k, v in r["_c"].items():
                if not k.startswith("_"):
                    tot[k] += v
        return tot

    branches = []
    for b in sorted({w["branch"] for w in woks}, key=_bkey):
        rows = [w for w in woks if w["branch"] == b]
        branches.append({"name": b, **_retensi_metrics(
            _gabung(rows), _mo1([w["name"] for w in rows]), sum(w["target"] for w in rows))})
    region = {"name": REGION_NAME, **_retensi_metrics(
        _gabung(woks), _mo1([w["name"] for w in woks]), sum(w["target"] for w in woks))}
    for w in woks:
        w.pop("_c")

    return {"tgl": tgl, "tgl_m1": tgl1, "tgl_minta": tgl_minta, "periode": per,
            "woks": woks, "branches": branches, "region": region}


def bottom_woks_retensi(result: dict, n: int = 5) -> list[dict]:
    rows = [w for w in result["woks"] if w["pct_mo"] is not None]
    return sorted(rows, key=lambda w: w["pct_mo"])[:n]


# ── RR + Caring per WOK (dipakai /pranpcsp, bisa difilter channel) ──────────
# Mengikuti tabel "PraNPC by Agency & Super Partner" sheet Report PraNPC:
#   WO_RP     = bucket1 + bucket2
#   PAID_RP   = byr1 + byr2 - adjustment_crd - adjustment_dbt
#   %RR Rp    = PAID_RP / WO_RP
#   Caring    = SND ada di data caring Transkom (jenis terisi)
#   %Caring   = Caring / WO;  %Visit = Visit / WO;  %Contacted = Contacted / Caring
#   Unpaid    = WO - Paid;    MoM Paid = Paid / Paid M-1 (tgl sama) - 1
def _rrc_cnt(base, status, caring, filt, key=None):
    """key(r, caring_row) -> kunci grup; default WOK SVP."""
    out = defaultdict(lambda: defaultdict(float))
    for r in base:
        if filt and not filt(r):
            continue
        c = caring.get(str(r["snd"])) if caring is not None else None
        w = key(r, c) if key else (r["wok_svp"] or "(UNMAPPED)")
        a = out[w]
        a["wo"] += 1
        a["_br:" + str(r["branch"])] += 1
        paid = pranpc_data.is_paid(status.get(str(r["snd"])))
        a["paid"] += paid
        a["wo_rp"] += float(r["bucket1"] or 0) + float(r["bucket2"] or 0)
        a["paid_rp"] += (float(r["byr1"] or 0) + float(r["byr2"] or 0)
                         - float(r["adjustment_crd"] or 0) - float(r["adjustment_dbt"] or 0))
        if caring is not None:
            if paid and not (c and c["jenis"]):
                a["pnc"] += 1                      # Paid Not Caring
            if c and c["jenis"]:
                a["caring"] += 1
                a["visit"] += c["jenis"] == "Visit"
                a["digital"] += c["jenis"] == "Digital"
                a["contacted"] += c["status_voc"] == "Contacted"
    return out


def _rrc_metrics(c, paid_m1):
    wo, paid = int(c["wo"]), int(c["paid"])
    return {
        "wo": wo, "paid": paid, "unpaid": wo - paid, "paid_m1": paid_m1,
        "wo_rp": c["wo_rp"], "paid_rp": c["paid_rp"],
        "rr": paid / wo * 100 if wo else None,
        "rr_rp": c["paid_rp"] / c["wo_rp"] * 100 if c["wo_rp"] else None,
        "caring": int(c["caring"]), "visit": int(c["visit"]),
        "digital": int(c["digital"]), "contacted": int(c["contacted"]),
        "pct_caring": c["caring"] / wo * 100 if wo else None,
        "pct_visit": c["visit"] / wo * 100 if wo else None,
        "pct_contacted": c["contacted"] / c["caring"] * 100 if c["caring"] else None,
        "mom_paid": (paid / paid_m1 - 1) * 100 if paid_m1 else None,
        # Versi sheet "PraNPC by Prioritas": penyebut dikurangi Paid Not Caring
        "pnc": int(c["pnc"]),
        "pct_caring_x": c["caring"] / (wo - c["pnc"]) * 100 if wo - c["pnc"] else None,
        "pct_visit_x": c["visit"] / (wo - c["pnc"]) * 100 if wo - c["pnc"] else None,
        "pct_contacted_x": (c["contacted"] / (c["caring"] - c["pnc"]) * 100
                            if c["caring"] - c["pnc"] else None),
    }


_CARING_KEYS = ("caring", "visit", "digital", "contacted", "pnc", "pct_caring", "pct_visit",
                "pct_contacted", "pct_caring_x", "pct_visit_x", "pct_contacted_x")


def hitung_rr_caring(tgl_minta: date | None = None, filt=None) -> dict:
    tgl, cur = resolve_tanggal(tgl_minta)
    per  = _periode(tgl)
    per1 = _periode(tgl - relativedelta(months=1))
    tgl1 = pranpc_data.tanggal_status_terakhir(per1, cur, maks=tgl - relativedelta(months=1))
    if isinstance(tgl1, datetime):
        tgl1 = tgl1.date()

    base = pranpc_data.load_base(per, cur)
    if not base:
        raise PranpcDataError(f"Base WO PraNPC periode {per} kosong.")
    caring = pranpc_data.load_caring(per) or None   # None = data caring periode ini tidak ada
    m = _rrc_cnt(base, pranpc_data.load_status(per, cur, tgl), caring, filt)
    m1 = (_rrc_cnt(pranpc_data.load_base(per1, cur), pranpc_data.load_status(per1, cur, tgl1),
                   None, filt) if tgl1 else {})

    def _bkey(b):
        return (pranpc_ref.BRANCH_ORDER.index(b) if b in pranpc_ref.BRANCH_ORDER else 99, b)

    def _p1(keys):
        return int(sum(m1[k]["paid"] for k in keys if k in m1)) if m1 else None

    woks = []
    for w, c in m.items():
        branch = max(((k[4:], v) for k, v in c.items() if k.startswith("_br:")), key=lambda kv: kv[1])[0]
        woks.append({"name": w, "branch": branch, "_c": c, **_rrc_metrics(c, _p1([w]))})
    woks.sort(key=lambda r: (_bkey(r["branch"]), r["name"]))

    def _gabung(rows):
        tot = defaultdict(float)
        for r in rows:
            for k, v in r["_c"].items():
                if not k.startswith("_"):
                    tot[k] += v
        return tot

    branches = []
    for b in sorted({w["branch"] for w in woks}, key=_bkey):
        rows = [w for w in woks if w["branch"] == b]
        branches.append({"name": b, **_rrc_metrics(_gabung(rows), _p1([w["name"] for w in rows]))})
    region = {"name": REGION_NAME, **_rrc_metrics(_gabung(woks), _p1([w["name"] for w in woks]))}
    for w in woks:
        w.pop("_c")
    if caring is None:
        # Tanpa data caring, kolom caring ditampilkan "-" (bukan 0% yang menyesatkan)
        for r in woks + branches + [region]:
            for k in _CARING_KEYS:
                r[k] = None
    return {"tgl": tgl, "tgl_m1": tgl1, "tgl_minta": tgl_minta, "periode": per,
            "caring_ada": caring is not None,
            "woks": woks, "branches": branches, "region": region}


def hitung_pranpc_sp(tgl_minta: date | None = None) -> dict:
    """/pranpcsp — channel Agency & Super Partner saja."""
    return hitung_rr_caring(tgl_minta, filt=lambda r: channel_of(r["mitra"]) == "agency")


def bottom_woks_rr(result: dict, n: int = 5) -> list[dict]:
    rows = [w for w in result["woks"] if w["rr"] is not None]
    return sorted(rows, key=lambda w: w["rr"])[:n]


# ── /pranpcprio: PraNPC by Prioritas (Branch x num_priority Transkom) ───────
PRIO_ORDER = ["P1", "P2", "P3", "TACTICAL"]


def hitung_pranpc_prio(tgl_minta: date | None = None) -> dict:
    """
    Mengikuti tabel "PraNPC by Prioritas" sheet Report PraNPC. Rumus sama dengan
    hitung_rr_caring, tapi %Caring/%Visit = / (WO - Paid Not Caring) dan
    %Contacted = Contacted / (Caring - Paid Not Caring) — sesuai Excel.
    """
    tgl, cur = resolve_tanggal(tgl_minta)
    per = _periode(tgl)
    base = pranpc_data.load_base(per, cur)
    if not base:
        raise PranpcDataError(f"Base WO PraNPC periode {per} kosong.")
    caring = pranpc_data.load_caring(per)
    if not caring:
        raise PranpcDataError(
            f"Data prioritas/caring Transkom periode {per} belum tersedia di DB "
            f"(tabel {pranpc_data.CARING_TABLE}).")
    kunci = lambda r, c: (r["branch"], (c or {}).get("num_priority") or "(N/A)")
    m = _rrc_cnt(base, pranpc_data.load_status(per, cur, tgl), caring, None, kunci)

    def _bkey(b):
        return pranpc_ref.BRANCH_ORDER.index(b) if b in pranpc_ref.BRANCH_ORDER else 99

    def _pkey(p):
        return PRIO_ORDER.index(p) if p in PRIO_ORDER else 99

    rows = []
    for (br, pr), c in sorted(m.items(), key=lambda kv: (_bkey(kv[0][0]), kv[0][0], _pkey(kv[0][1]))):
        rows.append({"branch": br, "name": pr, **_rrc_metrics(c, None)})
    tot = defaultdict(float)
    for c in m.values():
        for k, v in c.items():
            if not k.startswith("_"):
                tot[k] += v
    return {"tgl": tgl, "tgl_minta": tgl_minta, "periode": per,
            "woks": rows, "branches": [], "region": {"name": REGION_NAME, **_rrc_metrics(tot, None)}}
