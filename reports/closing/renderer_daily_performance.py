"""
renderer_daily_performance.py — Render tabel Daily Performance level WOK
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from dateutil.relativedelta import relativedelta
from config import REGION_NAME
from renderer_caps_font import fit_fs

C_BG="white"; C_HEADER_IO="#1B3A6B"; C_HEADER_RE="#8B2500"; C_HEADER_PS="#1E6B31"
C_HEADER_IORE="#4A235A"; C_HEADER_REPS="#784212"; C_HEADER_REV="#1A5276"
C_HEADER_SUB="#2C3E50"; C_REGION_BG="#2C3E50"; C_BRANCH_BG="#D5D8DC"
C_WOK_ODD="white"; C_WOK_EVEN="#F4F6F7"; C_SEP="#BDC3C7"; C_WHITE="white"
C_DARK="#1A1A1A"; C_MID="#2C3E50"; C_POS="#1E8449"; C_NEG="#C0392B"

def _fmt(v, dec=0, pct=False):
    if v is None: return "-"
    if pct:
        return f"{'+'if v>0 else''}{v:.{dec}f}%"
    return f"{int(v):,}" if not isinstance(v,float) else f"{v:,.{dec}f}"

def _ach_color(p):
    if p is None: return C_NEG
    return C_POS if p>=100 else ("#F39C12" if p>=67 else C_NEG)

def render_daily_performance(data, cutoff: str = None):
    tgl = data["tgl_closing"]
    bl = (tgl - relativedelta(months=1)).strftime("%b").upper()
    bi = tgl.strftime("%b").upper()

    rows = ([{"_t":"wok",**w} for w in data["woks"]] +
            [{"_t":"br",**b}  for b in data["branches"]] +
            [{"_t":"reg",**data["region"]}])

    # Lebar kolom scale 1.6x — gambar lebih besar, font lebih jelas
    CW = dict(br=2.15, wok=4.75,
              num=1.11, mom=1.37, drr=1.18, ach=1.18,
              conv=1.33, dev=1.37,
              rev=0.96, arpu=1.27, momr=1.21)

    COLS = (
        [("br",CW["br"]),("wok",CW["wok"])] +
        [("",CW["num"])]*2 + [("",CW["num"])]*2 + [("",CW["mom"]),("",CW["drr"]),("",CW["ach"])]) + (
        [("",CW["num"])]*2 + [("",CW["num"])]*2 + [("",CW["mom"]),("",CW["drr"]),("",CW["ach"])]) + (
        [("",CW["num"])]*2 + [("",CW["num"])]*2 + [("",CW["mom"]),("",CW["drr"]),("",CW["ach"])]) + (
        [("",CW["conv"])]*2 + [("",CW["dev"])]) + (
        [("",CW["conv"])]*2 + [("",CW["dev"])]) + (
        [("",CW["rev"]),("",CW["arpu"]),("",CW["rev"]),("",CW["arpu"]),("",CW["momr"]),("",CW["momr"])])
    cw = [c[1] for c in COLS]; TW = sum(cw)

    # Tinggi baris proporsional dengan font 14pt
    RH=0.52; HH1=0.54; HH2=0.46; TH=0.75; MG=0.25
    FH = TH+HH1+HH2+len(rows)*RH+MG*2
    FW = TW+MG*2

    # Telegram menolak foto dengan rasio lebar:tinggi > 20:1 (error
    # "Photo_invalid_dimensions") — kalau baris dikit (mis. hasil FMC yang
    # gagal sebagian), FW (banyak kolom tetap) vs FH (dikit baris) bisa
    # melewati itu. Tambah margin bawah (blank space, tidak ganggu tabel,
    # karena semua elemen digambar relatif ke atas FH) supaya rasio aman.
    MAX_RATIO = 15.0
    if FH > 0 and FW / FH > MAX_RATIO:
        FH = FW / MAX_RATIO

    fig,ax=plt.subplots(figsize=(FW,FH))
    ax.set_xlim(0,FW); ax.set_ylim(0,FH); ax.axis("off")
    fig.patch.set_facecolor("white")

    xs=[MG]+[0]*(len(cw)-1)
    for i in range(1,len(cw)): xs[i]=xs[i-1]+cw[i-1]
    cx=lambda i: xs[i]+cw[i]/2

    # Judul
    ax.text(MG,FH-0.18,"Performance MtD Sales IndiHome JATENG-DIY by WOK",
            ha="left",va="top",fontsize=20,fontweight="bold",color=C_MID)
    subtitle = f"Update {tgl.strftime('%d-%m-%Y')}"
    ax.text(MG,FH-0.50,subtitle,
            ha="left",va="top",fontsize=16,color="#7F8C8D")

    def hcell(x,y,w,h,txt,bg,fg="white",fs=14):
        ax.add_patch(plt.Rectangle((x,y),w,h,color=bg,zorder=2))
        ax.text(x+w/2,y+h/2,txt,ha="center",va="center",
                fontsize=fs,fontweight="bold",color=fg,zorder=3)

    yh1=FH-TH-HH1; yh2=yh1-HH2
    hcell(xs[0],yh2,CW["br"]+CW["wok"],HH1+HH2,"TERRITORY",C_HEADER_SUB,fs=14)

    grps=[(2,9,"INPUT ORDER (EXCL HWA)",C_HEADER_IO),(9,16,"RE (EXCL HWA)",C_HEADER_RE),
          (16,23,"PS (EXCL HWA)",C_HEADER_PS),(23,26,"IO to RE",C_HEADER_IORE),
          (26,29,"RE to PS",C_HEADER_REPS),(29,35,"Revenue New Sales",C_HEADER_REV)]
    for cs,ce,lb,col in grps:
        hcell(xs[cs],yh1,sum(cw[cs:ce]),HH1,lb,col,fs=14)

    sio=[f"TGT\n{bi}",f"MTD\n{bl}","TODAY",f"MTD\n{bi}","MoM","DRR","ACH(%)"]
    scv=["MTD-1","MTD","DEV"]
    srv=[f"Rev\nM-1",f"Arpu\nM-1","Rev M","Arpu M","MoM\nRev","MoM\nArpu"]
    ch2=([C_HEADER_IO]*7+[C_HEADER_RE]*7+[C_HEADER_PS]*7+
         [C_HEADER_IORE]*3+[C_HEADER_REPS]*3+[C_HEADER_REV]*6)
    sl=sio*3+scv*2+srv
    for i,(lb,col) in enumerate(zip(sl,ch2)):
        hcell(xs[i+2],yh2,cw[i+2],HH2,lb,col,fs=12)

    ax.add_patch(plt.Rectangle((xs[0],yh2),TW,HH1+HH2,
                               fill=False,edgecolor=C_SEP,lw=0.5,zorder=4))

    cy=yh2; wi=0
    for row in rows:
        cy-=RH; t=row["_t"]
        if   t=="reg": bg,fg,fs,bd=C_REGION_BG,"white",16.0,True
        elif t=="br":  bg,fg,fs,bd=C_BRANCH_BG,C_DARK,16.0,True
        else:          bg,fg,fs,bd=(C_WOK_ODD if wi%2==0 else C_WOK_EVEN),C_DARK,16.0,False; wi+=1
        ax.add_patch(plt.Rectangle((xs[0],cy),TW,RH,color=bg,zorder=1))
        my=cy+RH/2

        def cell(ci,txt,color=None,ha="center"):
            t2=str(txt) if txt is not None else "-"
            # auto-shrink font jika terlalu lebar. Estimasi lebar karakter
            # 0.085*f2/10 inch (bukan 0.068) — dikalibrasi ke lebar rata-rata
            # glyph bold DejaVu Sans (~0.6em), 0.068 lama meremehkan lebar
            # asli sehingga angka panjang bisa nyenggol kolom sebelah.
            # Floor diturunkan ke 4.5 (dari 6.0) supaya SELALU bisa menyusut
            # sampai benar-benar muat — presisi angka lebih penting daripada
            # ukuran font minimum, dan tidak boleh ada digit yang dipotong.
            f2=fs
            while f2>4.5 and len(t2)*0.085*f2/10>cw[ci]-0.12: f2-=0.3
            ax.text(cx(ci),my,t2,ha=ha,va="center",fontsize=f2,
                    fontweight="bold" if bd else "normal",
                    color=color or fg,zorder=3,clip_on=True)

        def lbl(xi,txt,maxw):
            f2 = fit_fs(txt, fs, maxw, floor=4.5)
            ax.text(xi,my,txt,ha="left",va="center",fontsize=f2,
                    fontweight="bold",color=fg,zorder=3,clip_on=True)

        def num(ci,v): cell(ci,_fmt(v))
        def pct(ci,v,drr=False):
            if v is None: cell(ci,"-"); return
            cell(ci,f"{v:.1f}%" if drr else _fmt(v,1,True),
                 color=fg if (drr or t=="reg") else (C_POS if v>=0 else C_NEG))
        def ach(ci,v):
            if v is None: cell(ci,"-"); return
            if t=="reg":
                cell(ci,f"{v:.1f}%")
                return
            col=_ach_color(v); pad=0.03
            ax.add_patch(plt.Rectangle((xs[ci]+pad,cy+pad),cw[ci]-pad*2,RH-pad*2,
                                       color=col+"33",zorder=2))
            ax.text(cx(ci),my,f"{v:.1f}%",ha="center",va="center",
                    fontsize=fs,fontweight="bold",color=col,zorder=3)
        def dev(ci,v):
            if v is None: cell(ci,"-"); return
            cell(ci,f"{'+'if v>0 else''}{v:.1f}%",
                 color=fg if t=="reg" else (C_POS if v>=0 else C_NEG))
        def conv(ci,v): cell(ci,"-"if v is None else f"{v:.2f}%")
        def rev(ci,v):  cell(ci,"-"if v is None else f"{v/1e6:.1f}")
        def arpu(ci,v): cell(ci,"-"if v is None else f"{round(v):,}")

        brl=(row.get("name","") if t=="br" else
             (REGION_NAME if t=="reg" else row.get("branch","")))
        wkl=(row.get("name","") if t=="wok" else
             (REGION_NAME if t=="reg" else ""))
        lbl(xs[0]+0.08,brl,CW["br"])
        lbl(xs[1]+0.08,wkl,CW["wok"])

        num(2,row.get("io_tgt")); num(3,row.get("io_mtd_lalu"))
        num(4,row.get("io_today")); num(5,row.get("io_mtd"))
        pct(6,row.get("io_mom")); pct(7,row.get("io_drr"),True); ach(8,row.get("io_ach"))
        num(9,row.get("re_tgt")); num(10,row.get("re_mtd_lalu"))
        num(11,row.get("re_today")); num(12,row.get("re_mtd"))
        pct(13,row.get("re_mom")); pct(14,row.get("re_drr"),True); ach(15,row.get("re_ach"))
        num(16,row.get("ps_tgt")); num(17,row.get("ps_mtd_lalu"))
        num(18,row.get("ps_today")); num(19,row.get("ps_mtd"))
        pct(20,row.get("ps_mom")); pct(21,row.get("ps_drr"),True); ach(22,row.get("ps_ach"))
        conv(23,row.get("io_re_lalu")); conv(24,row.get("io_re_mtd")); dev(25,row.get("io_re_dev"))
        conv(26,row.get("re_ps_lalu")); conv(27,row.get("re_ps_mtd")); dev(28,row.get("re_ps_dev"))
        rev(29,row.get("rev_mom")); arpu(30,row.get("arpu_mom"))
        rev(31,row.get("rev_mtd")); arpu(32,row.get("arpu_mtd"))
        pct(33,row.get("mom_rev")); pct(34,row.get("mom_arpu"))

        ax.plot([xs[0],xs[0]+TW],[cy,cy],color=C_SEP,
                lw=0.8 if t in("reg","br") else 0.25,zorder=5)

    for x in xs: ax.plot([x,x],[cy,yh2],color=C_SEP,lw=0.25,zorder=5)
    ax.plot([xs[-1]+cw[-1]]*2,[cy,yh2],color=C_SEP,lw=0.25,zorder=5)
    for gx in [xs[2],xs[9],xs[16],xs[23],xs[26],xs[29],xs[-1]+cw[-1]]:
        ax.plot([gx,gx],[cy,yh1],color=C_MID,lw=0.7,zorder=6)
    ax.add_patch(plt.Rectangle((xs[0],cy),TW,yh2-cy+HH1+HH2,
                               fill=False,edgecolor="#7F8C8D",lw=0.9,zorder=7))
    footer = "Excl HWA  |  Revenue = price_package order PS  |  Sumber: Rajawali indihome_ordering_detail"
    if cutoff:
        footer += f"  |  Cutoff data: {cutoff}"
    ax.text(xs[0],cy-0.06,footer,
            fontsize=6,color="#95A5A6",va="top",style="italic")

    plt.tight_layout(pad=0.1)
    buf=BytesIO()
    # Cap dpi supaya lebar+tinggi foto tidak melewati batas Telegram (~10000px)
    _dpi = min(300, int(8500 / (FW + FH)))
    plt.savefig(buf,format="png",dpi=_dpi,bbox_inches="tight",facecolor="white")
    plt.close(fig); buf.seek(0)
    return buf
