"""
leads_browser.py — /leads: login ke jatenggayeng.id (Playwright headless), buka
menu Caring Order, download PNG "Summary Keseluruhan per WOK - Agency" (tombol
asli #btnPivotPng -> downloadPivotPng(), html2canvas, filename
Caring_Pivot_YYYYMMDD.png — lihat komentar di run_leads_report) DAN ambil angka
Total Potensi Order belum caring + 3 WOK dgn kolom "Progress Caring" (tabel
pivot yang sama) TERENDAH langsung dari DOM tabel yang sama (bukan
reimplementasi/hitung ulang di Python) supaya selalu sinkron sama tampilan
dashboard aslinya.
"""
import os

from playwright.async_api import async_playwright

from config import JATENGGAYENG_BASE_URL, JATENGGAYENG_USER, JATENGGAYENG_PASS

CARING_ORDER_URL = JATENGGAYENG_BASE_URL.rstrip("/") + "/pages/caring_order/index"

_BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]

# Ambil kolom "Data Belum Caring" (Lead IO Agency/Digital/Data Q3/Data Blue
# Device) DAN kolom "Progress Caring" per WOK (pvt-prog, kolom PALING KANAN
# tabel pivot #pivotBody — BUKAN kolom "% Progress" di tabel "Summary per
# WOK — Leads IO Agency" di bawahnya, itu tabel/metrik BEDA) — semua dari
# baris yg sama (#pivotBody), SATU evaluate biar konsisten dgn PNG yg
# discreenshot dari tabel ini juga.
_EXTRACT_JS = """
() => {
  const allRows = [...document.querySelectorAll('#pivotBody tr')];
  const totalRow = allRows.find(tr => tr.classList.contains('pvt-total'));
  const totalTds = [...totalRow.querySelectorAll('td')];
  // totalTds[0] = sel "JATENG DIY" (colspan 3); Sudah Caring = [1..4];
  // Belum Caring = [5..8] (Lead IO Agency/Digital/Data Q3/Data Blue Device).
  const belum = {
    agency: totalTds[5].textContent.trim(),
    digital: totalTds[6].textContent.trim(),
    q3: totalTds[7].textContent.trim(),
    blue: totalTds[8].textContent.trim(),
  };
  const rows = allRows.filter(tr => !tr.classList.contains('pvt-total')).map(tr => {
    const tds = [...tr.querySelectorAll('td')];
    return { wok: tds[1].textContent.trim(), pct: parseFloat(tds[tds.length - 1].textContent) };
  });
  return { belum, rows };
}
"""


class LeadsReportError(RuntimeError):
    pass


def _fmt_ribuan(s: str) -> str:
    """Angka dari dashboard sudah pakai titik ribuan (format id-ID) — pass-through
    langsung, cuma tambahkan separator kalau suatu saat berubah jadi angka polos
    tanpa titik (mis. dashboard update, angka < 1000 tanpa pemisah)."""
    s = s.strip()
    if s.isdigit():
        return f"{int(s):,}".replace(",", ".")
    return s


async def run_leads_report(cutoff_date) -> dict:
    """cutoff_date: date — dipakai buat judul caption ("Progress Caring Leads IO
    <tanggal>"), BUKAN filter data (dashboard live, selalu tampilkan data
    terkini saat login, tidak ada parameter tanggal di menu Caring Order).

    Return: {"png": bytes, "png_filename": str, "caption": str}
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 1000},
                                            ignore_https_errors=True, accept_downloads=True)
            page.set_default_timeout(60_000)

            # ── Login ────────────────────────────────────────────────────
            # Dulu: goto(wait_until="networkidle") lalu langsung page.fill().
            # jatenggayeng.id kadang me-reload sendiri 1-2x sesaat setelah load
            # pertama (first visit / set cookie). page.fill() auto-wait lalu
            # ke-cancel terus krn "navigation in progress" -> Timeout 60s di
            # locator input username (persis error yg dilaporkan 07-Sep-2026).
            # Sekarang: domcontentloaded (bukan networkidle), tunggu field
            # muncul & terlihat secara eksplisit, beri jeda settle, dan ulang
            # seluruh rangkaian login sampai 3x kalau masih meleset.
            USER_SEL = 'input[placeholder="Masukkan username"]'
            login_err = None
            for attempt in range(3):
                try:
                    await page.goto(JATENGGAYENG_BASE_URL, wait_until="domcontentloaded")
                    await page.wait_for_selector(USER_SEL, state="visible", timeout=45_000)
                    await page.wait_for_timeout(800)   # biar reload susulan (kalau ada) kelar dulu
                    await page.fill(USER_SEL, JATENGGAYENG_USER)
                    await page.fill('input[placeholder="Masukkan password"]', JATENGGAYENG_PASS)
                    await page.click('button[type="submit"]')
                    try:
                        await page.wait_for_load_state("networkidle", timeout=30_000)
                    except Exception:
                        pass
                    # form login masih nongol = kredensial salah / login ditolak
                    if await page.locator(USER_SEL).count() > 0:
                        raise LeadsReportError(
                            "Login jatenggayeng.id gagal — cek username/password di config.py."
                        )
                    login_err = None
                    break
                except LeadsReportError:
                    raise
                except Exception as e:
                    login_err = e
                    await page.wait_for_timeout(2_000)
            if login_err is not None:
                raise LeadsReportError(f"Gagal membuka/mengisi form login (3x percobaan): {login_err}")

            await page.goto(CARING_ORDER_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("#pivotBody tr.pvt-total", timeout=45_000)

            data = await page.evaluate(_EXTRACT_JS)

            # html2canvas kadang lambat/keselip di headless (pernah timeout 90s x2
            # pas testing, terutama kalau ada beberapa instance headless jalan
            # bareng) — retry sampai 3x sebelum benar2 gagal, daripada /leads
            # gagal total krn hiccup sesaat.
            png_bytes = png_filename = None
            last_err = None
            for attempt in range(3):
                try:
                    async with page.expect_download(timeout=90_000) as dl_info:
                        await page.click("#btnPivotPng")
                    download = await dl_info.value
                    png_filename = download.suggested_filename
                    tmp_path = await download.path()
                    with open(tmp_path, "rb") as f:
                        png_bytes = f.read()
                    break
                except Exception as e:
                    last_err = e
            if png_bytes is None:
                raise LeadsReportError(f"Download PNG gagal (3x percobaan): {last_err}")
        finally:
            await browser.close()

    belum = data["belum"]
    rows = sorted(data["rows"], key=lambda r: r["pct"])
    bottom3 = rows[:3]

    tgl_str = f"{cutoff_date.day} {_BULAN_ID[cutoff_date.month]} {cutoff_date.year}"
    bottom_lines = "\n".join(f"- {r['wok']}" for r in bottom3)

    caption = (
        f"Progress Caring Leads IO\n"
        f"{tgl_str}\n"
        f"     \n"
        f"Total Potensi Order belum caring sebagai berikut :\n\n"
        f". Total Lead IO Agency : {_fmt_ribuan(belum['agency'])}\n"
        f". Total Lead IO Digital : {_fmt_ribuan(belum['digital'])}\n"
        f". Total Data Q3 : {_fmt_ribuan(belum['q3'])}\n"
        f". Total Data Blue Device : {_fmt_ribuan(belum['blue'])}\n\n"
        f"Bottom Progress Caring Leads IO ⚠️\n"
        f"{bottom_lines}\n\n"
        f"Source : {JATENGGAYENG_BASE_URL} menu caring order\n\n"
        f"Terimakasih"
    )

    return {"png": png_bytes, "png_filename": png_filename, "caption": caption}
