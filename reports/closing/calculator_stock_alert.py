"""
calculator_stock_alert.py — Ekstrak alert shortage stock ONT/STB/Orbit/Kartu
Perdana dari PDF "Stock ONT Report" (sumber: Stock Paradise), yang dikirim
manual ke topic Partnership (lihat bot.py: _tolak_chat_diblokir & handle_file).

PDF-nya BUKAN hasil scan — teks & tabelnya asli (dibuat dari HTML/print-to-PDF),
jadi diekstrak presisi lewat pdfplumber, tanpa OCR. Selalu 3 halaman:
  Section 1 — Ringkasan Regional & Branch   (dilewati, cuma rekap agregat)
  Section 2 — Rekap ONT per WH SO           (Single/Dual/Premium + status Dual & Premium)
  Section 3 — Rekap STB/Orbit/Kartu Perdana per WH SO

Dari Section 2 & 3 diambil SEMUA baris WH SO (baris "Main WH" otomatis
terlewat karena status-nya selalu "N/A") yang salah satu kolom Status-nya
"SHORTAGE" → 1 item alert per kategori (ONT Dual Band / ONT Premium / STB /
Orbit / Kartu Perdana), diurutkan dari stock days PALING KRITIS per kategori.
"""
import re
from io import BytesIO

import pdfplumber

KATEGORI_LABEL = {
    "ont_dual":    "ONT Dual Band",
    "ont_premium": "ONT Premium",
    "stb":         "STB",
    "orbit":       "Orbit",
    "kartu":       "Kartu Perdana",
}
KATEGORI_ORDER = ["ont_dual", "ont_premium", "stb", "orbit", "kartu"]


def _to_float(txt):
    """Format Indonesia ('14,9' / '1.076') -> float. 'N/A'/'-'/kosong -> None."""
    if txt is None:
        return None
    t = str(txt).strip()
    if not t or t.upper() in ("N/A", "-"):
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_stock_ont_report(pdf_bytes: bytes) -> dict:
    """Return {"tanggal": str, "items": [...]}.

    Tiap item: {"kategori", "branch", "wh_so", "days", "jumlah"} — "jumlah"
    = sisa stok unit real (bukan stock days) kategori tsb di WH SO itu.
    days/jumlah bisa None kalau kolomnya "N/A" di sumber, meski berstatus
    SHORTAGE.
    """
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if len(pdf.pages) < 3:
            raise ValueError(
                f"PDF cuma {len(pdf.pages)} halaman — format tidak dikenali "
                f"(Stock ONT Report harus 3 halaman: Section 1/2/3)"
            )
        header_text  = pdf.pages[0].extract_text() or ""
        page2_tables = pdf.pages[1].extract_tables()
        page3_tables = pdf.pages[2].extract_tables()

    if not page2_tables:
        raise ValueError("Tabel Section 2 (Rekap ONT per WH SO) tidak ditemukan di PDF")
    if not page3_tables:
        raise ValueError("Tabel Section 3 (Rekap STB/Orbit/Kartu Perdana) tidak ditemukan di PDF")

    tbl2 = page2_tables[0]
    tbl3 = page3_tables[0]

    m = re.search(r"Dibuat:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[^\n]*)", header_text)
    tanggal = m.group(1).strip() if m else "-"

    items = []

    # Section 2: Branch, WH SO, Single, Dual, Premium, Total,
    #            Days Dual, Days Premium, Status ONT Dual Band, Status Premium
    for row in tbl2[1:]:
        if not row or len(row) < 10:
            continue
        branch, wh_so = row[0], row[1]
        if not branch or not wh_so:
            continue
        jml_dual, jml_prem       = _to_float(row[3]), _to_float(row[4])
        days_dual, days_prem     = _to_float(row[6]), _to_float(row[7])
        status_dual, status_prem = (row[8] or "").strip().upper(), (row[9] or "").strip().upper()
        if status_dual == "SHORTAGE":
            items.append({"kategori": "ont_dual", "branch": branch, "wh_so": wh_so,
                          "days": days_dual, "jumlah": jml_dual})
        if status_prem == "SHORTAGE":
            items.append({"kategori": "ont_premium", "branch": branch, "wh_so": wh_so,
                          "days": days_prem, "jumlah": jml_prem})

    # Section 3: Branch, WH SO, STB New, STB Refurb, STB Total, Days STB, Status STB,
    #            Orbit Total, Days Orbit, Status Orbit, Kartu Perdana, Days Kartu, Status Kartu
    for row in tbl3[1:]:
        if not row or len(row) < 13:
            continue
        branch, wh_so = row[0], row[1]
        if not branch or not wh_so:
            continue
        jml_stb, days_stb, status_stb       = _to_float(row[4]),  _to_float(row[5]),  (row[6]  or "").strip().upper()
        jml_orbit, days_orbit, status_orbit = _to_float(row[7]),  _to_float(row[8]),  (row[9]  or "").strip().upper()
        jml_kartu, days_kartu, status_kartu = _to_float(row[10]), _to_float(row[11]), (row[12] or "").strip().upper()
        if status_stb == "SHORTAGE":
            items.append({"kategori": "stb", "branch": branch, "wh_so": wh_so,
                          "days": days_stb, "jumlah": jml_stb})
        if status_orbit == "SHORTAGE":
            items.append({"kategori": "orbit", "branch": branch, "wh_so": wh_so,
                          "days": days_orbit, "jumlah": jml_orbit})
        if status_kartu == "SHORTAGE":
            items.append({"kategori": "kartu", "branch": branch, "wh_so": wh_so,
                          "days": days_kartu, "jumlah": jml_kartu})

    # Urut per kategori (mengikuti KATEGORI_ORDER), lalu stock days paling
    # kritis (kosong/None dianggap paling akhir dalam kategorinya).
    urutan_kat = {k: i for i, k in enumerate(KATEGORI_ORDER)}
    items.sort(key=lambda it: (
        urutan_kat.get(it["kategori"], 99),
        it["days"] if it["days"] is not None else 9e9,
    ))

    return {"tanggal": tanggal, "items": items}


def _fmt_days(v):
    if v is None:
        return "N/A"
    if v == int(v):
        return f"{int(v)} hari"
    return f"{v:.1f} hari".replace(".", ",")


def _fmt_jumlah(v):
    if v is None:
        return "N/A"
    return f"{int(v):,}".replace(",", ".")


def _ikon_severity(v):
    """🔴 <3 hari (kritis) | 🟠 3-10 hari (waspada) | 🟡 >=10 hari / N-A (ringan)."""
    if v is None or v < 3:
        return "🔴"
    if v < 10:
        return "🟠"
    return "🟡"


def format_stock_alert_messages(data: dict, max_chars: int = 3500) -> list:
    """
    Susun alert jadi list pesan teks Telegram (plain, tanpa parse_mode — nama
    WH SO bisa mengandung karakter yang bentrok dengan Markdown). Dipecah per
    BATAS KATEGORI supaya tiap pesan tetap utuh 1 kategori (kalau 1 kategori
    sendiri sudah melebihi max_chars, baru dipecah per-baris di dalamnya).
    Selalu berada di bawah batas 4096 karakter Telegram per pesan.
    """
    items = data["items"]
    by_kat = {}
    for it in items:
        by_kat.setdefault(it["kategori"], []).append(it)

    header = (
        f"🚨 STOCK ALERT — ONT / STB / Orbit / Kartu Perdana\n"
        f"Sumber: Stock Paradise | Dibuat: {data['tanggal']}\n"
        f"Total: {len(items)} WH SO berstatus SHORTAGE"
    )

    if not items:
        return [header + "\n\n✅ Tidak ada WH SO berstatus SHORTAGE di laporan ini."]

    blocks = []   # 1 block teks per kategori (tanpa newline di awal/akhir)
    for kat in KATEGORI_ORDER:
        rows = by_kat.get(kat)
        if not rows:
            continue
        lines = [f"📦 {KATEGORI_LABEL[kat]} — {len(rows)} WH SO"]
        for it in rows:
            lines.append(
                f"{_ikon_severity(it['days'])} {it['branch']} – {it['wh_so']}: "
                f"{_fmt_days(it['days'])} – {_fmt_jumlah(it['jumlah'])} unit"
            )
        blocks.append("\n".join(lines))

    messages = []
    current = header
    for block in blocks:
        gabungan = current + "\n\n" + block
        if len(gabungan) <= max_chars:
            current = gabungan
            continue
        # Block sendiri tidak muat digabung ke pesan berjalan -> tutup pesan
        # berjalan, mulai pesan baru. Kalau block itu SENDIRI masih melebihi
        # max_chars (kategori sangat panjang), pecah lagi per-baris.
        messages.append(current)
        if len("(lanjutan)\n\n" + block) <= max_chars:
            current = "(lanjutan)\n\n" + block
        else:
            sub_lines = block.split("\n")
            current = "(lanjutan)\n\n" + sub_lines[0]
            for line in sub_lines[1:]:
                if len(current) + len(line) + 1 > max_chars:
                    messages.append(current)
                    current = "(lanjutan)\n\n" + line
                else:
                    current += "\n" + line
    messages.append(current)

    return messages
