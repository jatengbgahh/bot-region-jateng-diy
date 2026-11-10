"""
performance_browser.py — Jalankan Septian/SF_Performance_Report_22.html ASLI
lewat headless Chromium (Playwright), bukan reimplementasi ulang di Python.

KENAPA (ganti dari calculator_performance.py/renderer_performance.py):
  Reimplementasi matplotlib (renderer_performance.py) butuh disinkron ULANG
  MANUAL tiap kali HTML berubah (kolom baru/rumus beda/layout beda) — dan tetap
  rawan meleset detail visual (padding, spacing, warna persis) walau angkanya
  benar. Modul ini sebaliknya: BENERAN menjalankan HTML/JS aslinya di browser
  (upload file lewat file input, klik "Generate Report", screenshot elemen
  section-nya langsung via Playwright, panggil buildCaptionCombinedTelegram()
  JS langsung buat SATU caption gabungan report utama+SAPA — lihat komentar
  panjang di run_performance_report) — jadi hasilnya SELALU identik pixel-perfect
  dengan yang dilihat user kalau generate manual di browser, dan kalau HTML-nya
  diupdate (lihat bot.py: _handle_performance_html_upload, overwrite
  Septian/*.html), otomatis ikut kepakai TANPA perlu re-port apa pun di sini.

ARSITEKTUR: Playwright element screenshot (`locator.screenshot()`) dipakai
LANGSUNG, BUKAN lewat tombol "Download Image" HTML aslinya (yang pakai
html2canvas) — screenshot browser native lebih presisi (html2canvas kadang
punya bug render font/gradient) dan tidak perlu intercept file download blob.

Render TETAP async (Playwright async API) dan TIDAK bentrok dengan invariant
"render matplotlib harus sinkron" di modul lain (concurrency-model-bot-re-jateng)
— itu invariant KHUSUS matplotlib punya state global (pyplot), Playwright/
Chromium tidak punya masalah yang sama (tiap browser/page instance terisolasi).
"""
import os
import tempfile

from playwright.async_api import async_playwright

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HTML_PATH = os.path.join(_ROOT_DIR, "resources", "performance", "SF_Performance_Report_22.html")

MAIN_SECTIONS = [
    ("section-insight", "SF_Ringkasan_Eksekutif"),
    # WOW/MoM dipindah user ke tab1 per revisi HTML 2026-08-12 (dulu tab
    # terpisah "Growth Check") — render otomatis bareng section-insight/mb/djp/
    # result/churn di SATU compute yang sama (html:5058-5059 versi v26), TIDAK
    # perlu switchTab atau generate terpisah. Dibungkus try/catch SENDIRI2 di
    # HTML-nya (html:5043-5056) jadi TEORINYA bisa saja tidak ada di DOM kalau
    # computeWowReport() gagal — _screenshot_section_optional menangani ini
    # (skip diam2, bukan raise) supaya 1 section gagal tidak menggagalkan semua.
    ("section-wow", "SF_All_Parameter_WOW"),
    ("section-mom-all", "SF_All_Parameter_MoM"),
    ("section-mb", "SF_Performance_Process_MorningBriefing"),
    ("section-djp", "SF_Performance_Process_DJP"),
    ("section-result", "SF_Performance_Result"),
    ("section-churn", "SF_Tidak_Lanjut_MB_DJP_ActivePS"),
]
# Section 5-6 (Daily Monitoring) — beda TAB (tab2, html:289-297) dari 5 section
# di atas (semua tab1) — sudah otomatis ter-render ke #reportRootTab2 begitu
# "Generate Report" diklik (html:4869-4870, SATU compute yang sama dgn
# section 0-4, bukan generate terpisah), cuma tab-nya perlu diaktifkan dulu
# (switchTab) sebelum discreenshot krn tab non-aktif = display:none.
DAILY_SECTIONS = [
    ("section-daily-mb", "SF_Daily_Monitoring_MB"),
    ("section-daily-djp", "SF_Daily_Monitoring_DJP"),
]
SAPA_SECTION = ("section-sapa", "SF_Report_SAPA")
_OPTIONAL_MAIN_SECTIONS = {"section-wow", "section-mom-all"}

# Port sebagian captureSectionCanvas() (html:2215-2255) — TANPA bagian
# html2canvas-nya (diganti Playwright locator.screenshot() native, lebih
# presisi). Yang tetap perlu direplikasi:
#   - class "capturing" -> .export-btns disembunyikan (html:86 CSS), biar
#     tombol "Capture Image/Download PDF/Download Excel" tidak ikut kefoto.
#   - .table-scroll dilebarkan penuh (bukan overflow-x:auto) supaya tabel
#     lebar (mis. section Daily Monitoring 31 kolom tanggal) tidak kepotong.
# YANG BEDA dari versi asli: <header> (position:sticky) di-hide PERMANEN
# sekali di awal (lihat run_performance_report) — html2canvas tidak kena
# masalah ini (dia "melukis ulang" DOM secara virtual, bukan screenshot
# viewport asli), tapi Playwright locator.screenshot() men-scroll elemen ke
# viewport dulu (browser sungguhan) sehingga header sticky ikut ke-composite
# menimpa bagian atas section — makanya WAJIB disembunyikan, bukan cuma utk
# section ini tapi utk SEMUA screenshot di sesi ini.
_PREP_CAPTURE_JS = """
(sectionId) => {
  const el = document.getElementById(sectionId);
  if (!el) return;
  el.classList.add('capturing');
  const scrollers = [...el.querySelectorAll('.table-scroll')];
  scrollers.forEach(s => { s.style.overflow = 'visible'; s.style.width = s.scrollWidth + 'px'; });
  const maxContentWidth = Math.ceil(Math.max(el.scrollWidth, ...scrollers.map(s => s.scrollWidth), 0));
  el.style.width = maxContentWidth + 'px';
  el.style.maxWidth = 'none';
  const wrapEl = el.closest('.wrap');
  if (wrapEl) wrapEl.style.maxWidth = 'none';
}
"""


async def _screenshot_section(page, sec_id: str) -> bytes:
    await page.evaluate(_PREP_CAPTURE_JS, sec_id)
    return await page.locator(f"#{sec_id}").screenshot()


async def _screenshot_section_optional(page, sec_id: str) -> bytes | None:
    """Sama seperti _screenshot_section, tapi return None (bukan raise) kalau
    elemennya tidak ada di DOM — dipakai utk section-wow/section-mom-all yang
    punya try/catch sendiri di HTML (bisa gagal generate independen dari
    report utama, html:5043-5056)."""
    exists = await page.evaluate(f"!!document.getElementById('{sec_id}')")
    if not exists:
        return None
    return await _screenshot_section(page, sec_id)


def _html_file_url() -> str:
    path = HTML_PATH.replace(os.sep, "/")
    return f"file:///{path}" if not path.startswith("/") else f"file://{path}"


def _write_temp(name: str, data: bytes) -> str:
    """Playwright set_input_files() menolak buffer in-memory > 50MB (approve-tugas
    real bisa 70MB+) — tulis ke file temp & pass path-nya, bukan buffer langsung."""
    suffix = os.path.splitext(name or "")[1] or ".tmp"
    fd, path = tempfile.mkstemp(prefix="performance_upload_", suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


async def _set_file(page, selector: str, name: str, data: bytes) -> str:
    """Return path temp file — SENGAJA belum dihapus di sini (baru dihapus
    caller SETELAH dz.ready dikonfirmasi, supaya tidak menghapus file yang
    mungkin belum selesai dibaca Chromium — lihat _run_main/_run_sapa)."""
    path = _write_temp(name, data)
    await page.set_input_files(selector, path)
    return path


def _cleanup(paths: list):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


class PerformanceReportError(RuntimeError):
    pass


async def run_performance_report(files: dict, cutoff_override: str | None = None,
                                   focus_region: str = "JATENG-DIY") -> dict:
    """files: dict kind -> (filename, bytes) — kind salah satu dari
    ps/tugas/sf_master/sapa_assign/sapa_survey/sapa_prospect (subset boleh,
    minimal ps+tugas ATAU sapa_assign+sapa_survey+sapa_prospect harus ada).
    cutoff_override: 'YYYY-MM-DD' atau None (pakai default HTML: tanggal
    terakhir yang ada di file — TIDAK perlu dihitung ulang di Python).

    Return: {"main": {...} | None, "sapa": {...} | None, "caption": str | None}
      main:  {"sections": [(base_name, png_bytes), ...], "cutoff_date": str,
              "sf_reg_source": "master"|"estimasi"}
      sapa:  {"sections": [(base_name, png_bytes)]}
      caption: SATU caption gabungan (revisi HTML 2026-08-12: buildCaptionCombinedTelegram
        mengganti buildCaption/buildCaptionSapa terpisah — otomatis include bagian SAPA
        kalau sapa_ready juga, otomatis skip kalau tidak) — None kalau generate gagal total.
        Fallback ke buildCaptionSapa() sendirian kalau CUMA sapa_ready (tanpa main_ready,
        combined caption butuh lastReport yg tidak ada dlm kasus itu).
    """
    main_ready = "ps" in files and "tugas" in files
    sapa_ready = all(k in files for k in ("sapa_assign", "sapa_survey", "sapa_prospect"))
    if not main_ready and not sapa_ready:
        raise PerformanceReportError("Tidak ada file lengkap (butuh ps+tugas, dan/atau 3 file SAPA).")

    result = {"main": None, "sapa": None, "caption": None}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1500, "height": 1100})
            page.set_default_timeout(120_000)
            await page.goto(_html_file_url())
            # header{position:sticky} bikin bar merah judul app ikut ke-composite
            # menimpa bagian atas tiap section screenshot (lihat _PREP_CAPTURE_JS
            # komentar) — disembunyikan permanen sekali di awal sesi, bukan cuma
            # cosmetic di halaman aslinya (yang memang selalu ada saat dipakai
            # manual), krn di sini TIDAK ada manusia yang scroll page secara wajar.
            await page.add_style_tag(content="header{display:none !important;}")

            if main_ready:
                result["main"] = await _run_main(page, files, cutoff_override, focus_region)
            if sapa_ready:
                result["sapa"] = await _run_sapa(page, files)

            # Caption GABUNGAN — dibangun SETELAH main & sapa selesai (butuh
            # lastReport DAN/ATAU lastSapaReport sudah keisi), lihat komentar
            # buildCaptionCombinedTelegram di HTML (html:4479-4481, revisi
            # 2026-08-12): parameter sapaReport boleh null, bagian SAPA di
            # caption otomatis hilang kalau begitu.
            if main_ready:
                result["caption"] = await page.evaluate(
                    "buildCaptionCombinedTelegram(lastReport, lastSapaReport)")
            elif sapa_ready:
                result["caption"] = await page.evaluate("buildCaptionSapa(lastSapaReport)")
        finally:
            await browser.close()

    return result


async def _run_main(page, files: dict, cutoff_override: str | None, focus_region: str) -> dict:
    ps_name, ps_bytes = files["ps"]
    tugas_name, tugas_bytes = files["tugas"]
    temp_paths = []

    try:
        temp_paths.append(await _set_file(page, "#file1", ps_name, ps_bytes))
        await page.wait_for_selector("#dz1.ready", timeout=30_000)

        # approve-tugas bisa besar (puluhan MB, ratusan ribu baris) — parsing
        # PapaParse (worker thread) butuh waktu lebih lama, timeout digenerouskan.
        temp_paths.append(await _set_file(page, "#file2", tugas_name, tugas_bytes))
        try:
            await page.wait_for_selector("#dz2.ready", timeout=300_000)
        except Exception:
            status = await page.evaluate("document.getElementById('status').textContent")
            fname2 = await page.evaluate("document.getElementById('fname2').textContent")
            raise PerformanceReportError(
                f"Parsing Sumber Data 2 (approve-tugas) gagal/timeout — status: {status!r}, fname2: {fname2!r}")

        if "sf_master" in files:
            sf_name, sf_bytes = files["sf_master"]
            temp_paths.append(await _set_file(page, "#file3", sf_name, sf_bytes))
            await page.wait_for_selector("#dz3.ready", timeout=30_000)
    finally:
        # File sudah dibaca penuh oleh Chromium begitu dz.ready (Papa.parse
        # complete callback sudah jalan) — aman dihapus sekarang.
        _cleanup(temp_paths)

    await page.wait_for_function("!document.getElementById('runBtn').disabled", timeout=30_000)

    # focusRegion/cutoffDate <select> baru ke-populate SETELAH file1+file2 sukses
    # (populateDateAndRegionOptions, dipanggil dari maybeEnableControls) — aman
    # diisi di sini karena runBtn baru enabled setelah itu juga.
    await page.select_option("#focusRegion", focus_region)
    if cutoff_override:
        await page.select_option("#cutoffDate", cutoff_override)

    await page.click("#runBtn")
    try:
        # PENTING: lastReport dideklarasi `let` di top-level script (html:936),
        # BUKAN `var` — jadi TIDAK jadi properti window.lastReport (beda dari
        # var yang otomatis nempel ke window). Cek identifier bare-nya langsung,
        # bukan window.lastReport (itu SELALU undefined, bikin wait_for_function
        # timeout terus walau report-nya sendiri sukses di-generate).
        await page.wait_for_function("typeof lastReport !== 'undefined' && lastReport !== null", timeout=90_000)
    except Exception as e:
        status = await page.evaluate("document.getElementById('status').textContent")
        raise PerformanceReportError(f"Generate Report gagal: {status or e}")

    cutoff_date = await page.evaluate("lastReport.cutoffDate")
    sf_reg_source = await page.evaluate("lastReport.sfRegSource")

    sections = []
    for sec_id, base_name in MAIN_SECTIONS:
        if sec_id in _OPTIONAL_MAIN_SECTIONS:
            png = await _screenshot_section_optional(page, sec_id)
            if png is None:
                continue
        else:
            png = await _screenshot_section(page, sec_id)
        sections.append((base_name, png))

    # Section 5-6 hidup di tab2 (display:none selagi tab1 aktif) — aktifkan
    # dulu sebelum screenshot, sama seperti exportSectionsImage() aslinya
    # (html:2335-2364) yang juga switchTab() dulu per section sebelum capture.
    await page.evaluate("switchTab('tab2')")
    for sec_id, base_name in DAILY_SECTIONS:
        png = await _screenshot_section(page, sec_id)
        sections.append((base_name, png))

    return {"sections": sections, "cutoff_date": cutoff_date, "sf_reg_source": sf_reg_source}


async def _run_sapa(page, files: dict) -> dict:
    assign_name, assign_bytes = files["sapa_assign"]
    survey_name, survey_bytes = files["sapa_survey"]
    prospect_name, prospect_bytes = files["sapa_prospect"]
    temp_paths = []

    try:
        temp_paths.append(await _set_file(page, "#fileSapa1", assign_name, assign_bytes))
        await page.wait_for_selector("#dzSapa1.ready", timeout=30_000)
        temp_paths.append(await _set_file(page, "#fileSapa2", survey_name, survey_bytes))
        await page.wait_for_selector("#dzSapa2.ready", timeout=30_000)
        temp_paths.append(await _set_file(page, "#fileSapa3", prospect_name, prospect_bytes))
        await page.wait_for_selector("#dzSapa3.ready", timeout=30_000)
    finally:
        _cleanup(temp_paths)

    await page.wait_for_function("!document.getElementById('runSapaBtn').disabled", timeout=30_000)
    await page.click("#runSapaBtn")
    try:
        await page.wait_for_function("typeof lastSapaReport !== 'undefined' && lastSapaReport !== null", timeout=60_000)
    except Exception as e:
        status = await page.evaluate("document.getElementById('statusSapa').textContent")
        raise PerformanceReportError(f"Generate Report SAPA gagal: {status or e}")

    sec_id, base_name = SAPA_SECTION
    png = await _screenshot_section(page, sec_id)

    return {"sections": [(base_name, png)]}
