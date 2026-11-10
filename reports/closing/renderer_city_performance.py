"""
renderer_city_performance.py — Render tabel Daily Performance level City
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import date
from dateutil.relativedelta import relativedelta
from config import REGION_NAME

C_BG          = "#FFFFFF"
C_HEADER_IO   = "#1B3A6B"
C_HEADER_RE   = "#8B2500"
C_HEADER_PS   = "#1E6B31"
C_HEADER_IORE = "#4A235A"
C_HEADER_REPS = "#784212"
C_HEADER_REV  = "#1A5276"
C_HEADER_SUB  = "#2C3E50"
C_REGION_BG   = "#2C3E50"
C_CITY_ODD    = "#FFFFFF"
C_CITY_EVEN   = "#F4F6F7"
C_SEP         = "#BDC3C7"
C_WHITE       = "#FFFFFF"
C_DARK        = "#1A1A1A"
C_MID         = "#2C3E50"
C_POS         = "#1E8449"
C_NEG         = "#C0392B"
ACH_GREEN     = 100.0
ACH_YELLOW    = 67.0

def _fmt(v, dec=0, pct=False):
    if v is None: return "-"
    if pct:
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.{dec}f}%"
    if isinstance(v, float): return f"{v:,.{dec}f}"
    return f"{int(v):,}"

def _ach_color(p):
    if p is None: return C_NEG
    if p >= ACH_GREEN: return C_POS
    if p >= ACH_YELLOW: return "#F39C12"
    return C_NEG

def render_city_performance(data: dict, cutoff: str = None) -> BytesIO:
    tgl_closing = data["tgl_closing"]
    hari_mtd    = data["hari_mtd"]
    total_hari  = data["total_hari"]
    region      = data["region"]
    cities      = data["cities"]

    bl = (tgl_closing - relativedelta(months=1)).strftime("%b").upper()
    bi = tgl_closing.strftime("%b").upper()

    all_rows = []
    for city in cities:
        all_rows.append({"_type":"city",**city})
    all_rows.append({"_type":"region",**region})

    CW = {
        "branch": 2.15, "wok": 4.75, "city": 3.85,   # wok 4.75: "DAERAH ISTIMEWA YOGYAKARTA"
        "num": 1.11, "mom": 1.37, "drr": 1.18, "ach": 1.18,
        "conv": 1.33, "dev": 1.37,
        "rev": 0.96, "arpu": 1.27, "momr": 1.21,
    }
    COLS = (
        [("branch",CW["branch"]),("wok",CW["wok"]),("city",CW["city"])] +
        [("io_tgt",CW["num"]),("io_m1",CW["num"]),("io_today",CW["num"]),
         ("io_mtd",CW["num"]),("io_mom",CW["mom"]),("io_drr",CW["drr"]),("io_ach",CW["ach"])] +
        [("re_tgt",CW["num"]),("re_m1",CW["num"]),("re_today",CW["num"]),
         ("re_mtd",CW["num"]),("re_mom",CW["mom"]),("re_drr",CW["drr"]),("re_ach",CW["ach"])] +
        [("ps_tgt",CW["num"]),("ps_m1",CW["num"]),("ps_today",CW["num"]),
         ("ps_mtd",CW["num"]),("ps_mom",CW["mom"]),("ps_drr",CW["drr"]),("ps_ach",CW["ach"])] +
        [("iore_m1",CW["conv"]),("iore_mtd",CW["conv"]),("iore_dev",CW["dev"])] +
        [("reps_m1",CW["conv"]),("reps_mtd",CW["conv"]),("reps_dev",CW["dev"])] +
        [("rev_m1",CW["rev"]),("arpu_m1",CW["arpu"]),
         ("rev_mtd",CW["rev"]),("arpu_mtd",CW["arpu"]),
         ("mom_rev",CW["momr"]),("mom_arpu",CW["momr"])]
    )
    col_widths = [c[1] for c in COLS]
    total_w    = sum(col_widths)

    FS_CITY   = 16.0
    FS_REGION = 16.0
    FS_HEAD1  = 14.0
    FS_HEAD2  = 12.0
    FS_TITLE  = 15.0

    ROW_H   = 0.52
    HEAD_H1 = 0.38
    HEAD_H2 = 0.32
    TITLE_H = 0.60
    MARGIN  = 0.25
    PAD     = 0.20

    fig_w = total_w + MARGIN*2
    fig_h = TITLE_H + HEAD_H1 + HEAD_H2 + len(all_rows)*ROW_H + PAD*2

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, fig_w); ax.set_ylim(0, fig_h)
    ax.axis("off"); fig.patch.set_facecolor(C_BG)

    xs = [MARGIN]
    for w in col_widths[:-1]:
        xs.append(xs[-1]+w)
    def cx(i): return xs[i]+col_widths[i]/2

    ax.text(MARGIN, fig_h-0.15,
            "Performance MtD Sales IndiHome JATENG-DIY by City",
            ha="left", va="top", fontsize=FS_TITLE+2, fontweight="bold", color=C_MID)
    subtitle = f"Update {tgl_closing.strftime('%d-%m-%Y')}"
    ax.text(MARGIN, fig_h-0.42, subtitle,
            ha="left", va="top", fontsize=FS_TITLE, color="#7F8C8D")

    def hcell(x, y, w, h, text, bg, fg=C_WHITE, fs=16):
        ax.add_patch(plt.Rectangle((x,y), w, h, color=bg, zorder=2))
        ax.text(x+w/2, y+h/2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold", color=fg, zorder=3)

    y_h1 = fig_h - TITLE_H - HEAD_H1
    y_h2 = y_h1 - HEAD_H2

    w_terr = CW["branch"]+CW["wok"]+CW["city"]
    hcell(xs[0], y_h2, w_terr, HEAD_H1+HEAD_H2, "TERRITORY", C_HEADER_SUB, fs=FS_HEAD1)

    groups = [
        (3, 10, "INPUT ORDER (EXCL HWA)", C_HEADER_IO),
        (10,17, "RE (EXCL HWA)",           C_HEADER_RE),
        (17,24, "PS (EXCL HWA)",           C_HEADER_PS),
        (24,27, "IO to RE",                C_HEADER_IORE),
        (27,30, "RE to PS",                C_HEADER_REPS),
        (30,36, "Revenue New Sales",       C_HEADER_REV),
    ]
    for (cs,ce,lbl,color) in groups:
        w = sum(col_widths[cs:ce])
        hcell(xs[cs], y_h1, w, HEAD_H1, lbl, color, fs=FS_HEAD1)

    sub_io   = [f"TGT\n{bi}",f"MTD\n{bl}","TODAY",f"MTD\n{bi}","MoM","DRR","ACH(%)"]
    sub_conv = ["MTD-1","MTD","DEV"]
    sub_rev  = [f"Rev\nM-1",f"Arpu\nM-1","Rev M","Arpu M","MoM\nRev","MoM\nArpu"]
    colors_h2 = [C_HEADER_IO]*7+[C_HEADER_RE]*7+[C_HEADER_PS]*7+\
                [C_HEADER_IORE]*3+[C_HEADER_REPS]*3+[C_HEADER_REV]*6
    sub_labels = sub_io*3 + sub_conv*2 + sub_rev
    for i,(lbl,col) in enumerate(zip(sub_labels,colors_h2)):
        ci = i+3
        hcell(xs[ci], y_h2, col_widths[ci], HEAD_H2, lbl, col, fs=FS_HEAD2)

    ax.add_patch(plt.Rectangle((xs[0],y_h2), total_w, HEAD_H1+HEAD_H2,
                               fill=False, edgecolor=C_SEP, linewidth=0.5, zorder=4))

    cur_y = y_h2
    city_i = 0

    for row in all_rows:
        rtype = row["_type"]
        cur_y -= ROW_H

        if rtype == "region":
            bg, fg, fs, bold = C_REGION_BG, C_WHITE, FS_REGION, True
        else:
            bg = C_CITY_ODD if city_i%2==0 else C_CITY_EVEN
            fg, fs, bold = C_DARK, FS_CITY, False
            city_i += 1

        ax.add_patch(plt.Rectangle((xs[0],cur_y), total_w, ROW_H, color=bg, zorder=1))
        mid_y = cur_y + ROW_H/2

        def txt(ci, text, color=None, ha="center"):
            t = str(text) if text is not None else "-"
            cw = col_widths[ci]
            fitted = fs
            while fitted > 5.5:
                if len(t)*0.07*fitted/10 <= cw-0.10: break
                fitted -= 0.5
            ax.text(cx(ci), mid_y, t, ha=ha, va="center",
                    fontsize=fitted, fontweight="bold" if bold else "normal",
                    color=color or fg, zorder=3, clip_on=True)

        def fit_label(xi, text, max_w):
            fitted = fs
            while fitted > 5.5:
                if len(text)*0.07*fitted/10 <= max_w-0.15: break
                fitted -= 0.5
            ax.text(xi, mid_y, text, ha="left", va="center",
                    fontsize=fitted, fontweight="bold",
                    color=fg, zorder=3, clip_on=True)

        def num_cell(ci,v): txt(ci,_fmt(v))
        def pct_cell(ci,v,drr=False):
            if v is None: txt(ci,"-"); return
            if drr: txt(ci,f"{v:.1f}%",color=fg)
            else: txt(ci,_fmt(v,dec=1,pct=True),
                      color=fg if rtype=="region" else (C_POS if v>=0 else C_NEG))
        def ach_cell(ci,v):
            if v is None: txt(ci,"-"); return
            if rtype=="region":
                txt(ci,f"{v:.1f}%")
                return
            color=_ach_color(v)
            pad=0.04
            ax.add_patch(plt.Rectangle((xs[ci]+pad,cur_y+pad),
                col_widths[ci]-pad*2,ROW_H-pad*2,color=color+"33",zorder=2))
            ax.text(cx(ci),mid_y,f"{v:.1f}%",ha="center",va="center",
                    fontsize=fs,fontweight="bold",color=color,zorder=3)
        def dev_cell(ci,v):
            if v is None: txt(ci,"-"); return
            txt(ci,f"{'+'if v>0 else''}{v:.1f}%",
                color=fg if rtype=="region" else (C_POS if v>=0 else C_NEG))
        def conv_cell(ci,v): txt(ci,"-"if v is None else f"{v:.2f}%")
        def rev_cell(ci,v):  txt(ci,"-"if v is None else f"{v/1_000_000:.1f}")
        def arpu_cell(ci,v): txt(ci,"-"if v is None else f"{round(v):,}")

        br   = row.get("branch","") if rtype=="city" else REGION_NAME
        wok  = row.get("wok","")    if rtype=="city" else ""
        city = row.get("name","")   if rtype=="city" else REGION_NAME
        fit_label(xs[0]+0.10, br,   CW["branch"])
        fit_label(xs[1]+0.10, wok,  CW["wok"])
        fit_label(xs[2]+0.10, city, CW["city"])

        num_cell(3,row.get("io_tgt")); num_cell(4,row.get("io_mtd_lalu"))
        num_cell(5,row.get("io_today")); num_cell(6,row.get("io_mtd"))
        pct_cell(7,row.get("io_mom")); pct_cell(8,row.get("io_drr"),drr=True)
        ach_cell(9,row.get("io_ach"))

        num_cell(10,row.get("re_tgt")); num_cell(11,row.get("re_mtd_lalu"))
        num_cell(12,row.get("re_today")); num_cell(13,row.get("re_mtd"))
        pct_cell(14,row.get("re_mom")); pct_cell(15,row.get("re_drr"),drr=True)
        ach_cell(16,row.get("re_ach"))

        num_cell(17,row.get("ps_tgt")); num_cell(18,row.get("ps_mtd_lalu"))
        num_cell(19,row.get("ps_today")); num_cell(20,row.get("ps_mtd"))
        pct_cell(21,row.get("ps_mom")); pct_cell(22,row.get("ps_drr"),drr=True)
        ach_cell(23,row.get("ps_ach"))

        conv_cell(24,row.get("io_re_lalu")); conv_cell(25,row.get("io_re_mtd"))
        dev_cell(26,row.get("io_re_dev"))
        conv_cell(27,row.get("re_ps_lalu")); conv_cell(28,row.get("re_ps_mtd"))
        dev_cell(29,row.get("re_ps_dev"))

        rev_cell(30,row.get("rev_mom")); arpu_cell(31,row.get("arpu_mom"))
        rev_cell(32,row.get("rev_mtd")); arpu_cell(33,row.get("arpu_mtd"))
        pct_cell(34,row.get("mom_rev")); pct_cell(35,row.get("mom_arpu"))

        lw = 0.8 if rtype=="region" else 0.3
        ax.plot([xs[0],xs[0]+total_w],[cur_y,cur_y],color=C_SEP,linewidth=lw,zorder=5)

    for x in xs:
        ax.plot([x,x],[cur_y,y_h2],color=C_SEP,linewidth=0.3,zorder=5)
    ax.plot([xs[-1]+col_widths[-1]]*2,[cur_y,y_h2],color=C_SEP,linewidth=0.3,zorder=5)

    for gx in [xs[3],xs[10],xs[17],xs[24],xs[27],xs[30],xs[-1]+col_widths[-1]]:
        ax.plot([gx,gx],[cur_y,y_h1],color=C_MID,linewidth=0.8,zorder=6)

    ax.add_patch(plt.Rectangle((xs[0],cur_y), total_w, y_h2-cur_y+HEAD_H1+HEAD_H2,
                               fill=False, edgecolor="#7F8C8D", linewidth=1.0, zorder=7))
    footer = "Excl HWA  |  Revenue = price_package order PS  |  Sumber: Rajawali indihome_ordering_detail"
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0], cur_y-0.08, footer,
            fontsize=6.5, color="#95A5A6", va="top", style="italic")

    plt.tight_layout(pad=0.1)
    buf = BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(300, int(8500 / (fig_w + fig_h)))
    plt.savefig(buf, format="png", dpi=_dpi, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    buf.seek(0)
    return buf
