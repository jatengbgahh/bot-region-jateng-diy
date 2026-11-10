"""
renderer_pranpc.py — Render tabel report PraNPC:
  /pranpcall (render_pranpc_all), /pranpcagent (render_pranpc_agent),
  /moretensi (render_pranpc_retensi), /pranpcsp (render_pranpc_sp),
  /pranpcprio (render_pranpc_prio) — 3 terakhir lewat _render_tabel generik.
Tone warna mengikuti renderer_daily_performance.py (Sales MtD by WOK):
  - Header grup navy / merah tua / hijau tua, territory abu gelap
  - Region = navy (sama dgn header BRANCH/WOK), Branch = grey, WOK = zebra
  - MoM: naik = hijau, turun = merah; %RR & Ach = color scale ala Excel (merah-putih-hijau)
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from config import REGION_NAME

C_HEADER_WO="#1B3A6B"; C_HEADER_PAID="#8B2500"; C_HEADER_RR="#1E6B31"
C_HEADER_SUB="#2C3E50"; C_REGION_BG="#2C3E50"; C_BRANCH_BG="#D5D8DC"
C_WOK_ODD="white"; C_WOK_EVEN="#F4F6F7"; C_SEP="#BDC3C7"
C_DARK="#1A1A1A"; C_MID="#2C3E50"; C_POS="#1E8449"; C_NEG="#C0392B"
C_BAND_ALT="#EAF2F8"   # pita selang-seling per branch (/pranpcprio)

BULAN = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


BULAN_PANJANG = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
                 "Agustus", "September", "Oktober", "November", "Desember"]


# Color scale 3 warna ala Excel (default "Green - White - Red"):
# min = merah, median (persentil 50) = putih, max = hijau.
C_SCALE_MIN = (0xF8, 0x69, 0x6B); C_SCALE_MID = (0xFF, 0xFF, 0xFF); C_SCALE_MAX = (0x63, 0xBE, 0x7B)


def _skala(values) -> tuple | None:
    """(min, median, max) dari daftar nilai (None diabaikan)."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    n = len(v)
    med = v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2
    return v[0], med, v[-1]


def _warna_skala(v, sk) -> str | None:
    if v is None or sk is None:
        return None
    lo, mid, hi = sk
    if hi == lo:
        return None
    if v <= mid:
        t = 0.0 if mid == lo else (v - lo) / (mid - lo); a, b = C_SCALE_MIN, C_SCALE_MID
    else:
        t = 1.0 if hi == mid else (v - mid) / (hi - mid); a, b = C_SCALE_MID, C_SCALE_MAX
    t = max(0.0, min(1.0, t))
    return "#%02X%02X%02X" % tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _tgl_id(d, panjang: bool = False) -> str:
    return f"{d.day} {(BULAN_PANJANG if panjang else BULAN)[d.month]} {d.year}"


def render_pranpc_all(data, cutoff: str = None):
    tgl = data["tgl"]
    rows = ([{"_t": "wok", **w} for w in data["woks"]] +
            [{"_t": "br",  **b} for b in data["branches"]] +
            [{"_t": "reg", **data["region"]}])

    CW = dict(br=1.9, wok=4.6, num=1.15, pct=1.3)
    cw = [CW["br"], CW["wok"],
          CW["num"], CW["num"],                         # WO M-1, WO MtD
          CW["num"], CW["pct"], CW["num"], CW["num"],   # Paid MtD, MoM Paid, Target Paid, Gap
          CW["pct"], CW["pct"], CW["pct"], CW["pct"]]   # Target RR, RR MtD, Ach RR, MoM RR
    TW = sum(cw)

    RH = 0.52; HH1 = 0.54; HH2 = 0.50; TH = 0.75; MG = 0.25
    FH = TH + HH1 + HH2 + len(rows) * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [MG] + [0] * (len(cw) - 1)
    for i in range(1, len(cw)): xs[i] = xs[i - 1] + cw[i - 1]
    cx = lambda i: xs[i] + cw[i] / 2

    ax.text(MG, FH - 0.18, f"Recovery Rate (SSL) PraNPC All WO {REGION_NAME}",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    sub = f"Cut off {_tgl_id(tgl)}"
    if data.get("tgl_m1"):
        sub += f"  |  MoM vs {_tgl_id(data['tgl_m1'])}"
    ax.text(MG, FH - 0.50, sub, ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fg="white", fs=14):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3)

    yh1 = FH - TH - HH1; yh2 = yh1 - HH2
    hcell(xs[0], yh2, CW["br"], HH1 + HH2, "BRANCH", C_HEADER_SUB)
    hcell(xs[1], yh2, CW["wok"], HH1 + HH2, "WOK", C_HEADER_SUB)

    grps = [(2, 4, "WO (SSL)", C_HEADER_WO), (4, 8, "PAID (SSL)", C_HEADER_PAID),
            (8, 12, "RECOVERY RATE (SSL)", C_HEADER_RR)]
    for cs, ce, lb, col in grps:
        hcell(xs[cs], yh1, sum(cw[cs:ce]), HH1, lb, col)

    sub_lbl = ["WO M-1", "WO MtD",
               "Paid MtD", "MoM\nPaid", "Target\nPaid", "Paid\nGap",
               "Target\nRR", "RR MtD", "Ach RR", "MoM RR"]
    sub_col = [C_HEADER_WO] * 2 + [C_HEADER_PAID] * 4 + [C_HEADER_RR] * 4
    for i, (lb, col) in enumerate(zip(sub_lbl, sub_col)):
        hcell(xs[i + 2], yh2, cw[i + 2], HH2, lb, col, fs=12)

    # Color scale RR MtD & Ach RR — range terpisah untuk baris WOK dan baris Branch
    sk_rr = {"wok": _skala(r.get("rr") for r in rows if r["_t"] == "wok"),
             "br" : _skala(r.get("rr") for r in rows if r["_t"] == "br")}
    sk_ach = {"wok": _skala(r.get("ach") for r in rows if r["_t"] == "wok"),
              "br" : _skala(r.get("ach") for r in rows if r["_t"] == "br")}

    cy = yh2; wi = 0
    for row in rows:
        cy -= RH; t = row["_t"]
        if   t == "reg": bg, fg, bd = C_REGION_BG, "white", True
        elif t == "br":  bg, fg, bd = C_BRANCH_BG, C_DARK, True
        else:            bg, fg, bd = (C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN), C_DARK, False; wi += 1
        fs = 16.0
        ax.add_patch(plt.Rectangle((xs[0], cy), TW, RH, color=bg, zorder=1))
        my = cy + RH / 2

        def cell(ci, txt, color=None):
            t2 = str(txt) if txt is not None else "-"
            f2 = fs
            while f2 > 4.5 and len(t2) * 0.085 * f2 / 10 > cw[ci] - 0.12: f2 -= 0.3
            ax.text(cx(ci), my, t2, ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bd else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def lbl(xi, txt, maxw):
            f2 = fs
            while f2 > 4.5 and len(txt) * 0.085 * f2 / 10 > maxw - 0.20: f2 -= 0.3
            ax.text(xi, my, txt, ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        def num(ci, v):
            cell(ci, "-" if v is None else f"{int(round(v)):,}")

        def pct(ci, v):
            cell(ci, "-" if v is None else f"{v:.2f}%")

        def rr_cf(ci, v, sk):
            """Sel %RR dengan conditional formatting color scale ala Excel."""
            if v is None: cell(ci, "-"); return
            warna = _warna_skala(v, sk)
            if warna:
                ax.add_patch(plt.Rectangle((xs[ci], cy), cw[ci], RH, color=warna, zorder=2))
            cell(ci, f"{v:.2f}%", color=C_DARK if warna else None)

        def mom(ci, v):
            if v is None: cell(ci, "-"); return
            v = round(v, 2) + 0.0   # hindari tampilan "-0.00%"
            cell(ci, f"{'+' if v > 0 else ''}{v:.2f}%",
                 color=fg if t == "reg" else (C_POS if v >= 0 else C_NEG))

        def gap(ci, v):
            if v is None: cell(ci, "-"); return
            cell(ci, f"{int(round(v)):,}",
                 color=fg if t == "reg" else (C_NEG if v > 0 else C_POS))

        brl = (row["name"] if t == "br" else (REGION_NAME if t == "reg" else row.get("branch", "")))
        wkl = (row["name"] if t == "wok" else (REGION_NAME if t == "reg" else ""))
        lbl(xs[0] + 0.08, brl, CW["br"])
        lbl(xs[1] + 0.08, wkl, CW["wok"])

        num(2, row.get("wo_m1")); num(3, row.get("wo"))
        num(4, row.get("paid")); mom(5, row.get("mom_paid"))
        num(6, row.get("tgt_paid")); gap(7, row.get("gap"))
        pct(8, row.get("tgt_rr"))
        rr_cf(9, row.get("rr"), sk_rr.get(t))
        rr_cf(10, row.get("ach"), sk_ach.get(t)); mom(11, row.get("mom_rr"))

        ax.plot([xs[0], xs[0] + TW], [cy, cy], color=C_SEP,
                lw=0.8 if t in ("reg", "br") else 0.25, zorder=5)

    for x in xs: ax.plot([x, x], [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + cw[-1]] * 2, [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    for gx in [xs[2], xs[4], xs[8], xs[-1] + cw[-1]]:
        ax.plot([gx, gx], [cy, yh1], color=C_MID, lw=0.7, zorder=6)
    ax.add_patch(plt.Rectangle((xs[0], cy), TW, yh2 - cy + HH1 + HH2,
                               fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7))

    footer = ("Paid = status OCS != U pada tgl cut off  |  WOK = Cluster SVP (mapping kabupaten)"
              "  |  Sumber: Indiana indiana_tr_migrasi_pranpc + ocs_aging_migrasi_ih_pranpc_detail")
    if data.get("periode_target") and data["periode_target"] != data["periode"]:
        footer += f"  |  Target RR pakai periode {data['periode_target']}"
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cy - 0.06, footer, fontsize=6, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig); buf.seek(0)
    return buf


# ── /pranpcagent: Report PraNPC per Channel Agent ────────────────────────────
C_HEADER_CH = {"all": "#1B3A6B", "agency": "#8B2500", "ctb": "#1E6B31",
               "freelance": "#4A235A", "obc": "#784212", "unpaid": "#1A5276"}


def render_pranpc_agent(data, cutoff: str = None):
    from calculator_pranpc import CHANNELS
    tgl = data["tgl"]
    rows = ([{"_t": "wok", **w} for w in data["woks"]] +
            [{"_t": "br",  **b} for b in data["branches"]] +
            [{"_t": "reg", **data["region"]}])

    CW = dict(br=1.9, wok=4.6, num=1.1, pct=1.2)
    # (key, label, width, group)
    cols = [("wo", "WO MtD", CW["num"], "all"), ("paid", "Paid MtD", CW["num"], "all"),
            ("rr", "%RR SSL", CW["pct"], "all")]
    for k, _ in CHANNELS:
        cols += [(f"{k}.wo", "WO", CW["num"], k), (f"{k}.cont", "Cont.\n(%)", CW["pct"], k),
                 (f"{k}.paid", "Paid", CW["num"], k), (f"{k}.rr", "%RR SSL", CW["pct"], k)]
    cols += [("unpaid", "Unpaid\n(SSL)", CW["num"], "unpaid"),
             ("unpaid_rate", "Unpaid\nRate", CW["pct"], "unpaid")]
    cw = [CW["br"], CW["wok"]] + [c[2] for c in cols]
    TW = sum(cw)

    RH = 0.52; HH1 = 0.54; HH2 = 0.50; TH = 0.75; MG = 0.25
    FH = TH + HH1 + HH2 + len(rows) * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor("white")

    xs = [MG] + [0] * (len(cw) - 1)
    for i in range(1, len(cw)): xs[i] = xs[i - 1] + cw[i - 1]
    cx = lambda i: xs[i] + cw[i] / 2

    ax.text(MG, FH - 0.18, f"Report PraNPC per Channel Agent {REGION_NAME}",
            ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - 0.50, f"Cut off {_tgl_id(tgl)}", ha="left", va="top",
            fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fg="white", fs=14):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3)

    yh1 = FH - TH - HH1; yh2 = yh1 - HH2
    hcell(xs[0], yh2, CW["br"], HH1 + HH2, "BRANCH", C_HEADER_SUB)
    hcell(xs[1], yh2, CW["wok"], HH1 + HH2, "WOK", C_HEADER_SUB)

    grp_label = {"all": "ALL WO", **{k: lb.upper() for k, lb in CHANNELS}, "unpaid": "UNPAID"}
    grp_bounds = []
    i = 0
    while i < len(cols):
        g = cols[i][3]; j = i
        while j < len(cols) and cols[j][3] == g: j += 1
        grp_bounds.append((i + 2, j + 2, g)); i = j
    for cs, ce, g in grp_bounds:
        hcell(xs[cs], yh1, sum(cw[cs:ce]), HH1, grp_label[g], C_HEADER_CH[g])
    for ci, (_, lb, _, g) in enumerate(cols):
        hcell(xs[ci + 2], yh2, cw[ci + 2], HH2, lb, C_HEADER_CH[g], fs=12)

    def _get(row, key):
        if "." in key:
            a, b = key.split(".")
            return (row.get(a) or {}).get(b)
        return row.get(key)

    # Color scale tiap kolom %RR SSL — range terpisah per kolom dan per jenis
    # baris (WOK / Branch), seperti conditional formatting per range di Excel.
    rr_keys = [c[0] for c in cols if c[0].endswith("rr")]
    sk_rr = {(k, jt): _skala(_get(r, k) for r in rows if r["_t"] == jt)
             for k in rr_keys for jt in ("wok", "br")}

    cy = yh2; wi = 0
    for row in rows:
        cy -= RH; t = row["_t"]
        if   t == "reg": bg, fg, bd = C_REGION_BG, "white", True
        elif t == "br":  bg, fg, bd = C_BRANCH_BG, C_DARK, True
        else:            bg, fg, bd = (C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN), C_DARK, False; wi += 1
        fs = 16.0
        ax.add_patch(plt.Rectangle((xs[0], cy), TW, RH, color=bg, zorder=1))
        my = cy + RH / 2

        def cell(ci, txt, color=None):
            f2 = fs
            while f2 > 4.5 and len(txt) * 0.085 * f2 / 10 > cw[ci] - 0.12: f2 -= 0.3
            ax.text(cx(ci), my, txt, ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bd else "normal", color=color or fg, zorder=3, clip_on=True)

        def lbl(xi, txt, maxw):
            f2 = fs
            while f2 > 4.5 and len(txt) * 0.085 * f2 / 10 > maxw - 0.20: f2 -= 0.3
            ax.text(xi, my, txt, ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        brl = (row["name"] if t == "br" else (REGION_NAME if t == "reg" else row.get("branch", "")))
        wkl = (row["name"] if t == "wok" else (REGION_NAME if t == "reg" else ""))
        lbl(xs[0] + 0.08, brl, CW["br"])
        lbl(xs[1] + 0.08, wkl, CW["wok"])

        for ci, (key, _, _, _) in enumerate(cols):
            v = _get(row, key)
            if v is None:
                txt = "-"                      # channel tanpa WO -> %RR tidak berlaku
            elif key.endswith("rr"):
                warna = _warna_skala(v, sk_rr.get((key, t)))
                if warna:
                    ax.add_patch(plt.Rectangle((xs[ci + 2], cy), cw[ci + 2], RH, color=warna, zorder=2))
                cell(ci + 2, f"{v:.2f}%", color=C_DARK if warna else None); continue
            elif key.endswith("cont"):
                txt = f"{v:.1f}%"
            elif key == "unpaid_rate":
                txt = f"{v:.2f}%"
            else:
                txt = f"{int(v):,}"
            cell(ci + 2, txt)

        ax.plot([xs[0], xs[0] + TW], [cy, cy], color=C_SEP,
                lw=0.8 if t in ("reg", "br") else 0.25, zorder=5)

    for x in xs: ax.plot([x, x], [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + cw[-1]] * 2, [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    for cs, _, _ in grp_bounds:
        ax.plot([xs[cs], xs[cs]], [cy, yh1], color=C_MID, lw=0.7, zorder=6)
    ax.plot([xs[-1] + cw[-1]] * 2, [cy, yh1], color=C_MID, lw=0.7, zorder=6)
    ax.add_patch(plt.Rectangle((xs[0], cy), TW, yh2 - cy + HH1 + HH2,
                               fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7))

    footer = ("Paid = status OCS != U pada tgl cut off  |  Channel = kolom mitra (alokasi terkini): "
              "Agency/Super Partner = AGENCY + Super Partner, OBC TRANSKOM = OBC  |  "
              "Sumber: Indiana indiana_tr_migrasi_pranpc + ocs_aging_migrasi_ih_pranpc_detail")
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cy - 0.06, footer, fontsize=6, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig); buf.seek(0)
    return buf


# ── Renderer tabel generik PraNPC (dipakai /moretensi, dst.) ─────────────────
# cols: list of (key, label, width, group, kind)
#   kind: num | pct | mom | gap | cf (tinggi=hijau) | cf_rev (tinggi=merah)
def _render_tabel(data, title: str, subtitle: str, groups: dict, cols: list,
                  footer: str, cutoff: str = None, col2_label: str = "WOK",
                  w_col2: float = 4.6, zebra_per_branch: bool = False):
    rows = ([{"_t": "wok", **w} for w in data["woks"]] +
            [{"_t": "br",  **b} for b in data["branches"]] +
            [{"_t": "reg", **data["region"]}])
    W_BR, W_WOK = 1.9, w_col2
    cw = [W_BR, W_WOK] + [c[2] for c in cols]
    TW = sum(cw)
    RH = 0.52; HH1 = 0.54; HH2 = 0.62; TH = 0.75; MG = 0.25
    FH = TH + HH1 + HH2 + len(rows) * RH + MG * 2
    FW = TW + MG * 2

    fig, ax = plt.subplots(figsize=(FW, FH))
    ax.set_xlim(0, FW); ax.set_ylim(0, FH); ax.axis("off")
    fig.patch.set_facecolor("white")
    xs = [MG] + [0] * (len(cw) - 1)
    for i in range(1, len(cw)): xs[i] = xs[i - 1] + cw[i - 1]
    cx = lambda i: xs[i] + cw[i] / 2

    ax.text(MG, FH - 0.18, title, ha="left", va="top", fontsize=20, fontweight="bold", color=C_MID)
    ax.text(MG, FH - 0.50, subtitle, ha="left", va="top", fontsize=16, color="#7F8C8D")

    def hcell(x, y, w, h, txt, bg, fs=14):
        ax.add_patch(plt.Rectangle((x, y), w, h, color=bg, zorder=2))
        ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center",
                fontsize=fs, fontweight="bold", color="white", zorder=3)

    yh1 = FH - TH - HH1; yh2 = yh1 - HH2
    hcell(xs[0], yh2, W_BR, HH1 + HH2, "BRANCH", C_HEADER_SUB)
    hcell(xs[1], yh2, W_WOK, HH1 + HH2, col2_label, C_HEADER_SUB)
    bounds = []; i = 0
    while i < len(cols):
        g = cols[i][3]; j = i
        while j < len(cols) and cols[j][3] == g: j += 1
        bounds.append((i + 2, j + 2, g)); i = j
    for cs, ce, g in bounds:
        hcell(xs[cs], yh1, sum(cw[cs:ce]), HH1, groups[g][0], groups[g][1])
    for ci, (_, lb, _, g, _) in enumerate(cols):
        hcell(xs[ci + 2], yh2, cw[ci + 2], HH2, lb, groups[g][1], fs=12)

    skala = {(c[0], jt): _skala(r.get(c[0]) for r in rows if r["_t"] == jt)
             for c in cols if c[4] in ("cf", "cf_rev") for jt in ("wok", "br")}

    cy = yh2; wi = 0; prev_br = None; band = 0
    for row in rows:
        cy -= RH; t = row["_t"]
        if   t == "reg": bg, fg, bd = C_REGION_BG, "white", True
        elif t == "br":  bg, fg, bd = C_BRANCH_BG, C_DARK, True
        elif zebra_per_branch:
            # pita selang-seling per branch (semua prioritas 1 branch = 1 warna)
            if row.get("branch") != prev_br:
                band += 1; prev_br = row.get("branch")
            bg, fg, bd = (C_WOK_ODD if band % 2 else C_BAND_ALT), C_DARK, False
        else:            bg, fg, bd = (C_WOK_ODD if wi % 2 == 0 else C_WOK_EVEN), C_DARK, False; wi += 1
        fs = 16.0
        ax.add_patch(plt.Rectangle((xs[0], cy), TW, RH, color=bg, zorder=1))
        my = cy + RH / 2

        def cell(ci, txt, color=None):
            f2 = fs
            while f2 > 4.5 and len(txt) * 0.085 * f2 / 10 > cw[ci] - 0.12: f2 -= 0.3
            ax.text(cx(ci), my, txt, ha="center", va="center", fontsize=f2,
                    fontweight="bold" if bd else "normal", color=color or fg, zorder=3, clip_on=True)

        def lbl(xi, txt, maxw):
            f2 = fs
            while f2 > 4.5 and len(txt) * 0.085 * f2 / 10 > maxw - 0.20: f2 -= 0.3
            ax.text(xi, my, txt, ha="left", va="center", fontsize=f2,
                    fontweight="bold", color=fg, zorder=3, clip_on=True)

        brl = (row["name"] if t == "br" else (REGION_NAME if t == "reg" else row.get("branch", "")))
        wkl = (row["name"] if t == "wok" else (REGION_NAME if t == "reg" else ""))
        lbl(xs[0] + 0.08, brl, W_BR)
        lbl(xs[1] + 0.08, wkl, W_WOK)

        for k, (key, _, _, _, kind) in enumerate(cols):
            ci = k + 2; v = row.get(key)
            if v is None:
                cell(ci, "-"); continue
            if kind == "num":
                cell(ci, f"{int(round(v)):,}")
            elif kind == "pct":
                cell(ci, f"{v:.2f}%")
            elif kind == "mom":
                v = round(v, 2) + 0.0
                cell(ci, f"{'+' if v > 0 else ''}{v:.2f}%",
                     color=fg if t == "reg" else (C_POS if v >= 0 else C_NEG))
            elif kind == "gap":
                cell(ci, f"{int(round(v)):,}", color=fg if t == "reg" else (C_NEG if v > 0 else C_POS))
            elif kind in ("cf", "cf_rev"):
                sk = skala.get((key, t))
                if sk and kind == "cf_rev":
                    lo, mid, hi = sk
                    warna = _warna_skala(lo + hi - v, (lo, lo + hi - mid, hi))
                else:
                    warna = _warna_skala(v, sk)
                if warna:
                    ax.add_patch(plt.Rectangle((xs[ci], cy), cw[ci], RH, color=warna, zorder=2))
                cell(ci, f"{v:.2f}%", color=C_DARK if warna else None)

        ax.plot([xs[0], xs[0] + TW], [cy, cy], color=C_SEP,
                lw=0.8 if t in ("reg", "br") else 0.25, zorder=5)

    for x in xs: ax.plot([x, x], [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    ax.plot([xs[-1] + cw[-1]] * 2, [cy, yh2], color=C_SEP, lw=0.25, zorder=5)
    for cs, _, _ in bounds:
        ax.plot([xs[cs], xs[cs]], [cy, yh1], color=C_MID, lw=0.7, zorder=6)
    ax.plot([xs[-1] + cw[-1]] * 2, [cy, yh1], color=C_MID, lw=0.7, zorder=6)
    ax.add_patch(plt.Rectangle((xs[0], cy), TW, yh2 - cy + HH1 + HH2,
                               fill=False, edgecolor="#7F8C8D", lw=0.9, zorder=7))
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cy - 0.06, footer, fontsize=6, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    _dpi = min(300, int(8500 / (FW + FH)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig); buf.seek(0)
    return buf


def render_pranpc_retensi(data, cutoff: str = None):
    groups = {"base": ("BASE",                        "#1B3A6B"),
              "mo"  : ("JUMLAH MO",                   "#8B2500"),
              "ret" : ("RETENSI",                     "#1E6B31"),
              "churn": ("CHURN (DO & NEW CT0)", "#4A235A")}
    N, P = 1.1, 1.35
    cols = [("wo", "WO", N, "base", "num"), ("paid", "Paid", N, "base", "num"),
            ("target", "Target\nRetensi*", N, "base", "num"),
            ("ctb", "MO Retensi\n(CTB)", 1.3, "mo", "num"),
            ("nonctb", "MO Retensi\n(Non CTB)", 1.3, "mo", "num"),
            ("pre", "MO\nPrepaid", N, "mo", "num"), ("total", "TOTAL", N, "mo", "num"),
            ("pct_mo", "%MO Retensi\nto Total Paid", 1.6, "ret", "cf"),
            ("ach", "Ach to\nTarget", P, "ret", "cf"),
            ("mom", "MoM MO\nRetensi", P, "ret", "mom"),
            ("gap", "Gap to\nTarget", N, "ret", "gap"),
            ("do", "DO", N, "churn", "num"), ("pct_do", "%DO", P, "churn", "cf_rev"),
            ("new_ct0", "New CT0\n(Unpaid)", 1.2, "churn", "num")]
    sub = f"Cut off {_tgl_id(data['tgl'])}"
    if data.get("tgl_m1"):
        sub += f"  |  MoM vs {_tgl_id(data['tgl_m1'])}"
    footer = ("*Target Retensi = 10% x WO  |  MO Retensi = Non Prepaid (CTB + Non CTB), basis Paid  |  "
              "Gap = Target - MO Retensi CTB  |  New CT0 = Unpaid - DO  |  "
              "Order & DO dihitung s/d tgl cut off (sama dgn status bayar)  |  "
              "Sumber: Indiana indiana_tr_migrasi_pranpc + ocs_aging_migrasi_ih_pranpc_detail")
    return _render_tabel(data, f"Retensi PraNPC All LoS {REGION_NAME}", sub, groups, cols, footer, cutoff)


def render_pranpc_sp(data, cutoff: str = None, judul: str = "PraNPC by Agency & Super Partner"):
    groups = {"base" : ("BASE (SSL)",    "#1B3A6B"),
              "rr"   : ("RECOVERY RATE", "#1E6B31"),
              "care" : ("CARING",        "#784212"),
              "unpd" : ("UNPAID & MoM",  "#8B2500")}
    N, P = 1.15, 1.35
    cols = [("wo", "WO_SSL", N, "base", "num"), ("paid", "PAID_SSL", N, "base", "num"),
            ("rr", "%RR SSL", P, "rr", "cf"), ("rr_rp", "%RR Rp", P, "rr", "cf"),
            ("pct_caring", "%Caring", P, "care", "cf"), ("pct_visit", "%Visit", P, "care", "cf"),
            ("pct_contacted", "%Contacted", 1.45, "care", "cf"),
            ("unpaid", "Unpaid\n(SSL)", N, "unpd", "num"), ("mom_paid", "MoM Paid", P, "unpd", "mom")]
    sub = f"Cut off {_tgl_id(data['tgl'])}"
    if data.get("tgl_m1"):
        sub += f"  |  MoM vs {_tgl_id(data['tgl_m1'])}"
    footer = ("%RR Rp = (byr1+byr2-adjustment) / (bucket1+bucket2)  |  %Caring & %Visit = / WO, "
              "%Contacted = / Caring (data caring terakhir Transkom)  |  "
              "Sumber: Indiana indiana_tr_migrasi_pranpc + ocs_aging + indiana_tr_migrasi_pranpc_transkom")
    return _render_tabel(data, f"{judul} {REGION_NAME}", sub, groups, cols, footer, cutoff)


def render_pranpc_prio(data, cutoff: str = None):
    groups = {"base": ("BASE (SSL)",    "#1B3A6B"),
              "rr"  : ("RECOVERY RATE", "#1E6B31"),
              "care": ("CARING",        "#784212"),
              "unpd": ("UNPAID",        "#8B2500")}
    N, P = 1.15, 1.35
    cols = [("wo", "WO_SSL", N, "base", "num"), ("paid", "PAID_SSL", N, "base", "num"),
            ("rr", "%RR SSL", P, "rr", "cf"), ("rr_rp", "%RR Rp", P, "rr", "cf"),
            ("pct_caring_x", "%Caring", P, "care", "cf"), ("pct_visit_x", "%Visit", P, "care", "cf"),
            ("pct_contacted_x", "%Contacted", 1.45, "care", "cf"),
            ("unpaid", "Unpaid\n(SSL)", N, "unpd", "num")]
    footer = ("Prioritas = num_priority Transkom  |  %Caring & %Visit = / (WO - Paid Not Caring), "
              "%Contacted = / (Caring - Paid Not Caring)  |  data caring terakhir Transkom  |  "
              "Sumber: Indiana indiana_tr_migrasi_pranpc + ocs_aging + indiana_tr_migrasi_pranpc_transkom")
    return _render_tabel(data, f"PraNPC by Prioritas {REGION_NAME}", f"Cut off {_tgl_id(data['tgl'])}",
                         groups, cols, footer, cutoff, col2_label="PRIORITAS", w_col2=2.2,
                         zebra_per_branch=True)
