"""program_tracking.py — Ekstraksi PDF "Program Tracking" (GTM) jadi gambar
per halaman program, dikelompokkan otomatis berdasarkan nama program, lengkap
caption (nama program, tanggal cutoff, link monitoring) hasil parsing teks PDF.

Dipakai oleh bot.py saat user upload PDF dengan nama file mengandung
"program tracking" (lihat _is_program_tracking_upload di bot.py).

CATATAN keterbatasan (bukan 100% andal):
- Halaman "divider"/cover dideteksi lewat jumlah kata (heuristik, bukan
  hardcode nomor halaman) supaya tetap jalan walau jumlah halaman berubah
  bulan depan.
- Nama program dipakai sbg kunci pengelompokan halaman berurutan (mis. RACY
  4 halaman, TOP GUN SF+GRAPARI) — diambil dari potongan judul SEBELUM tanda
  pisah pertama ("–" atau " - ").
- Tanggal ("cutoff data ..."/"Posisi ...") & link ("Link <Label> : ...")
  diekstrak berbasis POSISI kata (bukan regex teks linear), karena PDF ini
  kadang merender keduanya terpotong 2-3 baris di kolom sempit "Key Visual"
  (pernah terjadi di W2 Agustus 2026: link GADIS MERDEKA & tanggalnya sendiri,
  link Red Priority, link HIT 360) — lihat _extract_links / _extract_cutoff_date.
  Kalau tetap tidak ketemu, caption dikasih tanda peringatan (bukan ditebak)
  — lihat build_caption().
- Satu halaman bisa punya >1 link (mis. TMW: Monitoring + Reimbursement +
  Evidence Event). _extract_links() mengambil SEMUANYA; baris lanjutan (wrap)
  dibatasi sampai sebelum baris "Link ..." berikutnya biar url tidak menyerempet
  label link setelahnya. Link digabung & dedup per grup di build_send_plan().
"""

import re
from io import BytesIO

import fitz  # PyMuPDF
import pdfplumber

MIN_WORDS_CONTENT_PAGE = 50  # halaman divider/cover selalu jauh di bawah ini
RENDER_ZOOM = 2.5  # ~180 dpi, cukup buat dibaca ulang di HP

_DATE_RE = re.compile(r"([0-3]?\d\s+\w+(?:\s+\d{4})?)")
_URL_RE  = re.compile(r"https?://\S+", re.IGNORECASE)


def _norm_url(u: str) -> str:
    """Kunci dedup: buang skema + trailing slash, lowercase — biar
    'tinyurl.com/X' dan 'https://tinyurl.com/X' dianggap link yang sama."""
    return re.sub(r"^https?://", "", u.strip(), flags=re.IGNORECASE).rstrip("/").lower()


def _dedup_links(pairs):
    """Buang link duplikat (berdasarkan _norm_url), urutan dipertahankan.
    Kalau url yang sama muncul dgn & tanpa 'https://', yang pakai skema menang."""
    order: list[str] = []
    best: dict[str, tuple[str, str]] = {}
    for lbl, url in pairs:
        if not url:
            continue
        k = _norm_url(url)
        if k not in best:
            best[k] = (lbl, url)
            order.append(k)
        else:
            _, cur = best[k]
            if not cur.lower().startswith(("http://", "https://")) and \
               url.lower().startswith(("http://", "https://")):
                best[k] = (lbl, url)
    return [best[k] for k in order]


def _program_key(title_line: str) -> str:
    """Nama program (kunci grouping + display) = potongan sebelum tanda pisah
    pertama, mis. "TOP GUN – Tsel ONE ... - SF" -> "TOP GUN"."""
    t = title_line.strip().replace("—", "–")
    for sep in (" – ", " - "):
        if sep in t:
            return t.split(sep, 1)[0].strip()
    return t


def _extract_links(page) -> list[tuple[str, str]]:
    """Semua baris "Link <Label> : <url>" di halaman (Monitoring, Reimbursement,
    Evidence Event, dll), berbasis POSISI kata — bukan regex atas teks linear —
    karena beberapa halaman PDF ini merender link terpotong 2-3 baris di kolom
    sempit ("Key Visual"); pdfplumber.extract_text() menyisipkan baris tabel
    lain di antara potongan link itu.

    Return: list of (label, url), mis. [("Link Monitoring", "https://..."),
    ("Link Reimbursement", "https://..."), ("Link Evidence Event", "https://...")].

    Baris lanjutan (wrap) align ke x0 kata "Link" itu sendiri, DAN dibatasi
    sampai sebelum baris "Link ..." berikutnya supaya url tidak ikut menyerempet
    label link setelahnya (bug lama: url jadi "...2026LinkLink")."""
    words = page.extract_words()

    # anchor = kata "Link" yang diikuti kata berhuruf (awal label), bukan url
    anchors = [
        i for i, w in enumerate(words)
        if w["text"] == "Link"
        and i + 1 < len(words)
        and words[i + 1]["text"][:1].isalpha()
    ]
    if not anchors:
        return []

    anchor_tops = sorted(words[i]["top"] for i in anchors)

    results: list[tuple[str, str]] = []
    for i in anchors:
        lw = words[i]

        line = sorted(
            (w for w in words
             if abs(w["top"] - lw["top"]) < 3 and w["x0"] >= lw["x0"] - 1),
            key=lambda w: w["x0"],
        )
        label_parts: list[str] = []
        url_parts: list[str] = []
        seen_colon = False
        prev_x1 = None
        for w in line:
            t = w["text"]
            if not seen_colon:
                if t == ":":
                    seen_colon = True
                    prev_x1 = w["x1"]
                    continue
                if ":" in t:
                    before, after = t.split(":", 1)
                    if before:
                        label_parts.append(before)
                    seen_colon = True
                    if after:
                        url_parts.append(after)
                    prev_x1 = w["x1"]
                    continue
                label_parts.append(t)
                prev_x1 = w["x1"]
            else:
                if t == "Link":            # label berikutnya di baris sama
                    break
                if prev_x1 is not None and w["x0"] - prev_x1 > 25:
                    break
                url_parts.append(t)
                prev_x1 = w["x1"]

        if not seen_colon:
            continue

        # batas atas baris lanjutan: sebelum anchor "Link" berikutnya
        next_top = next((tp for tp in anchor_tops if tp > lw["top"] + 3), None)
        top_hi = lw["top"] + 60
        if next_top is not None:
            top_hi = min(top_hi, next_top - 3)

        cont = sorted(
            (w for w in words
             if w["text"] != "Link"
             and abs(w["x0"] - lw["x0"]) < 5
             and lw["top"] + 3 <= w["top"] <= top_hi),
            key=lambda w: w["top"],
        )
        url_parts.extend(w["text"] for w in cont)

        label = " ".join(label_parts).strip().rstrip(":").strip()
        url = "".join(url_parts).strip().lstrip(":").strip()
        m = _URL_RE.search(url)
        if m:
            url = m.group(0)
        while url.endswith("Link"):        # sisa serpihan label yang nyasar
            url = url[:-4]
        url = url.rstrip(".,;)")
        if not url:
            continue
        if label and not label.lower().startswith("link"):
            label = f"Link {label}"
        results.append((label or "Link", url))

    return _dedup_links(results)


def _extract_link(page) -> str | None:
    """Kompat lama: url "Link Monitoring" saja (yang pertama kalau ada)."""
    links = _extract_links(page)
    mon = next((u for lbl, u in links if "monitoring" in lbl.lower()), None)
    return mon or (links[0][1] if links else None)


def _extract_cutoff_date(page) -> str | None:
    """Cari "cutoff data <tanggal>" (fallback "Posisi ... <tanggal>") berbasis
    POSISI kata, sama alasannya dengan _extract_link: tanggal bisa kepencar
    2 baris di kolom sempit (mis. "cutoff data" / "14 Agustus" / "2026" di 3
    baris terpisah pada halaman GADIS MERDEKA W2 Agustus 2026) sehingga regex
    atas teks linear gagal menyambungnya."""
    words = page.extract_words()
    label = None
    for i, w in enumerate(words):
        if w["text"].lower().startswith("cutoff") and i + 1 < len(words) \
                and words[i + 1]["text"].lower().startswith("data"):
            label = w
            break
    if not label:
        for w in words:
            if w["text"].lower().startswith("posisi"):
                label = w
                break
    if not label:
        return None

    box = [w for w in words
           if label["x0"] - 15 <= w["x0"] <= label["x0"] + 220
           and label["top"] <= w["top"] <= label["top"] + 40
           and w["text"].lower() not in ("cutoff", "data", "posisi", "per")]
    box.sort(key=lambda w: (round(w["top"] / 3), w["x0"]))
    joined = " ".join(w["text"] for w in box)
    m = _DATE_RE.search(joined)
    if m:
        return m.group(1).strip()
    return joined.strip() or None


def extract_groups(pdf_bytes: bytes):
    """Baca PDF, buang halaman divider/cover, lalu kelompokkan halaman program
    berurutan yang punya nama program (kunci) sama.

    Return: list of {"name": str, "pages": [{"page_no", "date", "link", "links"}]}
    ("links" = list of (label, url); "link" = url monitoring saja, kompat lama)
    """
    groups = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if len(text.split()) < MIN_WORDS_CONTENT_PAGE:
                continue  # halaman cover/divider/thank-you

            title = text.split("\n")[0].strip()
            name = _program_key(title)

            date_val  = _extract_cutoff_date(page)
            links_val = _extract_links(page)
            link_mon  = next((u for lbl, u in links_val if "monitoring" in lbl.lower()), None)
            link_mon  = link_mon or (links_val[0][1] if links_val else None)

            entry = {"page_no": i + 1, "date": date_val,
                     "link": link_mon, "links": links_val}

            if groups and groups[-1]["name"].casefold() == name.casefold():
                groups[-1]["pages"].append(entry)
            else:
                groups.append({"name": name, "pages": [entry]})
    return groups


def render_pages(pdf_bytes: bytes, page_numbers):
    """Render halaman (1-indexed) jadi PNG. Return {page_no: png_bytes}."""
    result = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        mat = fitz.Matrix(RENDER_ZOOM, RENDER_ZOOM)
        for pno in page_numbers:
            pix = doc[pno - 1].get_pixmap(matrix=mat)
            result[pno] = pix.tobytes("png")
    finally:
        doc.close()
    return result


def clean_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def build_caption(name: str, date: str | None, links,
                   part: int | None = None, total: int | None = None) -> str:
    """Halaman pertama grup -> caption lengkap (nama, tanggal, SEMUA link).
    Halaman lanjutan (part > 1) -> caption ringkas "(part/total)" saja, tidak
    mengulang tanggal/link (grup dianggap satu sumber data yang sama).

    `links` menerima:
      - list of (label, url)  -> ditampilkan semua, satu baris per link
      - str atau None          -> kompat lama (dianggap 1 link Monitoring)
    """
    if part and part > 1:
        return f"Program Tracking - {name} ({part}/{total})"

    if isinstance(links, str) or links is None:
        links = [("Link Monitoring", links)] if links else []
    links = [(lbl or "Link", url) for lbl, url in links if url]

    title_line = f"Program Tracking - {name}"
    if total and total > 1:
        title_line += f" (1/{total})"
    lines = [title_line, date or "(tanggal tidak terdeteksi, cek manual)", ""]
    if links:
        for lbl, url in links:
            lines.append(f"\U0001F517 {lbl} : {url}")
    else:
        lines.append("⚠️ Link tidak terdeteksi, cek manual di PDF")
    return "\n".join(lines)


def build_send_plan(pdf_bytes: bytes):
    """Siapkan render + caption lengkap, siap dikirim.

    Return: list of dict {"name", "files": [(filename, png_bytes, caption), ...]}
    satu dict per program (grup), "files" berisi 1 halaman (single) atau lebih
    (album, sudah terurut sesuai halaman PDF).
    """
    groups = extract_groups(pdf_bytes)
    all_pages = [p["page_no"] for g in groups for p in g["pages"]]
    rendered = render_pages(pdf_bytes, all_pages)

    plan = []
    for g in groups:
        total = len(g["pages"])
        # tanggal grup: dari halaman pertama yang kedeteksi
        date_val = next((p["date"] for p in g["pages"] if p["date"]), None)
        # link grup: gabung SEMUA link dari semua halaman grup, dedup per url,
        # urutan dipertahankan (Monitoring biasanya duluan)
        links_val = _dedup_links(
            (lbl, url) for p in g["pages"] for lbl, url in p.get("links", [])
        )
        files = []
        for idx, p in enumerate(g["pages"], start=1):
            caption = build_caption(g["name"], date_val, links_val,
                                     part=idx if total > 1 else None, total=total)
            fname = f"{clean_filename(g['name'])}_p{p['page_no']}.png"
            files.append((fname, rendered[p["page_no"]], caption))
        plan.append({"name": g["name"], "files": files})
    return plan
