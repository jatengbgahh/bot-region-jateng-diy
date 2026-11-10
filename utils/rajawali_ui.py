"""
rajawali_ui.py — modul inti otomasi Prisma Browser + Rajawali berbasis "melihat layar".

Prisma tidak membuka elemen UI-nya ke Windows UI Automation (pohon elemen kosong), jadi semua
pencarian tombol/teks memakai OCR bawaan Windows (Windows.Media.Ocr) pada tangkapan layar JENDELA
Prisma. Posisi dihitung relatif terhadap jendela -> tidak tergantung resolusi / ukuran layar / DPI.

Fungsi utama:
  pastikan_prisma()          -> buka Prisma bila tertutup, kembalikan handle jendela utamanya
  layar(hwnd)                -> (PIL.Image, rect) tangkapan layar jendela
  ocr(img)                   -> list Kata(teks, x, y, w, h) koordinat dalam gambar
  cari(hwnd, pola, ...)      -> Kata pertama yang cocok (regex, tak peka huruf besar)
  klik(hwnd, kata | (fx,fy)) -> klik tengah kata, atau titik relatif jendela (0..1)
  ketik / tekan / tempel     -> keyboard ke jendela aktif
"""
import asyncio
import ctypes
import ctypes.wintypes as W
import os
import re
import subprocess
import time
from dataclasses import dataclass

import psutil
from PIL import Image, ImageGrab

PRISMA_EXE = r"C:\Program Files\Palo Alto Networks\PrismaAccessBrowser\Application\PrismaAccessBrowser.exe"
PRISMA_PROSES = "prismaaccessbrowser.exe"

u32 = ctypes.windll.user32
try:                                   # koordinat fisik piksel (aman untuk layar ber-skala DPI 125%/150%)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        u32.SetProcessDPIAware()
    except Exception:
        pass


@dataclass
class Kata:
    teks: str
    x: int
    y: int
    w: int
    h: int

    @property
    def tengah(self):
        return self.x + self.w // 2, self.y + self.h // 2


# ── jendela ──────────────────────────────────────────────────────────────────
def pastikan_desktop_default():
    """Pastikan thread terhubung ke desktop 'default' (layar interaktif Windows)
    supaya EnumWindows bisa mendeteksi jendela Prisma."""
    try:
        h_desk = u32.OpenDesktopW("default", 0, False, 0x01FF)
        if h_desk:
            u32.SetThreadDesktop(h_desk)
    except Exception:
        pass


def _pid_prisma():
    return {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == PRISMA_PROSES}


def jendela_prisma():
    """Semua jendela Prisma yang terlihat: list (hwnd, judul, (l,t,r,b)), terbesar dulu."""
    pastikan_desktop_default()
    pids = _pid_prisma()
    hasil = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)
    def cb(h, _):
        pid = W.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u32.IsWindowVisible(h):
            c = ctypes.create_unicode_buffer(128)
            u32.GetClassNameW(h, c, 128)
            if c.value == "Chrome_WidgetWin_1":
                t = ctypes.create_unicode_buffer(512)
                u32.GetWindowTextW(h, t, 512)
                r = W.RECT()
                u32.GetWindowRect(h, ctypes.byref(r))
                if r.right - r.left > 300 and r.bottom - r.top > 200:
                    hasil.append((h, t.value, (r.left, r.top, r.right, r.bottom)))
        return True

    u32.EnumWindows(cb, 0)
    hasil.sort(key=lambda x: (x[2][2] - x[2][0]) * (x[2][3] - x[2][1]), reverse=True)
    return hasil


def _pulihkan_minimize():
    """Jendela Prisma yang di-minimize (ukurannya ~160x28 di -32000, jadi tak lolos jendela_prisma) -> restore.
    Return jumlah jendela yang dipulihkan."""
    pastikan_desktop_default()
    pids, hs = _pid_prisma(), []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, W.HWND, W.LPARAM)
    def cb(h, _):
        pid = W.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value in pids and u32.IsWindowVisible(h) and u32.IsIconic(h):
            c = ctypes.create_unicode_buffer(128)
            u32.GetClassNameW(h, c, 128)
            if c.value == "Chrome_WidgetWin_1":
                hs.append(h)
        return True

    if pids:
        u32.EnumWindows(cb, 0)
    for h in hs:
        u32.ShowWindow(h, 9)             # SW_RESTORE
    if hs:
        time.sleep(1.5)
    return len(hs)


def pastikan_prisma(tunggu=60, log=print):
    """Buka Prisma bila belum jalan. Return hwnd jendela terbesar."""
    pastikan_desktop_default()
    if not jendela_prisma() and _pulihkan_minimize():
        log("Jendela Prisma ter-minimize -> dipulihkan (tidak membuka Prisma baru)")
    if not jendela_prisma():
        log("Prisma tertutup -> membuka...")
        # lepas dari proses runner supaya Prisma tidak ikut tertutup saat runner berhenti/dihentikan
        f = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        si = subprocess.STARTUPINFO()
        si.lpDesktop = r"WinSta0\default"
        try:
            subprocess.Popen([PRISMA_EXE], startupinfo=si, close_fds=True, creationflags=f | subprocess.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            subprocess.Popen([PRISMA_EXE], startupinfo=si, close_fds=True, creationflags=f)
    t0 = time.time()
    while time.time() - t0 < tunggu:
        ws = jendela_prisma()
        if ws:
            tidur(2)
            return jendela_prisma()[0][0]
        tidur(1.5)
    raise RuntimeError("Jendela Prisma tidak muncul.")


def depan(hwnd, maksimal=True):
    """Bawa jendela ke depan (dan maksimalkan supaya tata letak konsisten di layar mana pun)."""
    if maksimal:
        u32.ShowWindow(hwnd, 3)          # SW_MAXIMIZE
    else:
        u32.ShowWindow(hwnd, 9)          # SW_RESTORE
    # trik Alt agar SetForegroundWindow diizinkan Windows
    u32.keybd_event(0x12, 0, 0, 0)
    u32.SetForegroundWindow(hwnd)
    u32.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.6)


def rect(hwnd):
    r = W.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def skala_dpi(hwnd):
    """Faktor skala tampilan jendela (1.0 = 100%, 1.25 = 125%, ...)."""
    try:
        return u32.GetDpiForWindow(hwnd) / 96
    except Exception:
        return 1.0


def judul(hwnd):
    t = ctypes.create_unicode_buffer(512)
    u32.GetWindowTextW(hwnd, t, 512)
    return t.value


def _pastikan_depan(hwnd):
    """Tangkapan layar = isi LAYAR, jadi Prisma harus paling depan (jendela lain di atasnya = OCR salah baca)."""
    if u32.GetForegroundWindow() != hwnd:
        u32.keybd_event(0x12, 0, 0, 0)
        u32.SetForegroundWindow(hwnd)
        u32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.4)


def layar(hwnd):
    if hwnd:
        _pastikan_depan(hwnd)
    l, t, r, b = rect(hwnd)
    return ImageGrab.grab(bbox=(l, t, r, b), all_screens=True), (l, t, r, b)


# ── OCR (Windows.Media.Ocr) ──────────────────────────────────────────────────
_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from winrt.windows.media.ocr import OcrEngine
        _ENGINE = OcrEngine.try_create_from_user_profile_languages()
    return _ENGINE


async def _ocr_async(img):
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.storage.streams import DataWriter
    im = img.convert("RGBA")
    w, h = im.size
    dw = DataWriter()
    dw.write_bytes(bytearray(im.tobytes("raw", "BGRA")))
    sb = SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h,
                                               BitmapAlphaMode.PREMULTIPLIED)
    return await _engine().recognize_async(sb)


def ocr(img, skala=1.0):
    """Return list Kata per BARIS (teks baris + kotak gabungan) dan per KATA. Koordinat dlm gambar asli.
    skala>1 memperbesar gambar dulu (teks kecil di layar resolusi rendah lebih terbaca)."""
    src = img if skala == 1 else img.resize((int(img.width * skala), int(img.height * skala)), Image.LANCZOS)
    r = asyncio.run(_ocr_async(src))
    out = []
    for ln in r.lines:
        ws = list(ln.words)
        if not ws:
            continue
        xs = [(wd.bounding_rect.x, wd.bounding_rect.y, wd.bounding_rect.width, wd.bounding_rect.height) for wd in ws]
        x0, y0 = min(a for a, _, _, _ in xs), min(b for _, b, _, _ in xs)
        x1, y1 = max(a + c for a, _, c, _ in xs), max(b + d for _, b, _, d in xs)
        out.append(Kata(ln.text, int(x0 / skala), int(y0 / skala), int((x1 - x0) / skala), int((y1 - y0) / skala)))
        for wd, (a, b, c, d) in zip(ws, xs):
            out.append(Kata(wd.text, int(a / skala), int(b / skala), int(c / skala), int(d / skala)))
    return out


def cari(hwnd, pola, area=None, skala=1.5, img=None):
    """Kata/baris pertama yang cocok regex `pola`. area=(fx0,fy0,fx1,fy1) membatasi ke bagian jendela (0..1).
    Return Kata dgn koordinat RELATIF JENDELA, atau None."""
    if img is None:
        img, _ = layar(hwnd)
    ox = oy = 0
    if area:
        W_, H_ = img.size
        ox, oy = int(area[0] * W_), int(area[1] * H_)
        img = img.crop((ox, oy, int(area[2] * W_), int(area[3] * H_)))
    rx = re.compile(pola, re.I)
    for k in ocr(img, skala):
        if rx.search(k.teks):
            return Kata(k.teks, k.x + ox, k.y + oy, k.w, k.h)
    return None


def tunggu_teks(hwnd, pola, batas=60, jeda=2, area=None, log=None):
    t0 = time.time()
    while time.time() - t0 < batas:
        k = cari(hwnd, pola, area=area)
        if k:
            return k
        tidur(jeda)
    if log:
        log(f"  (tidak muncul dalam {batas}s: {pola})")
    return None


# ── mouse & keyboard ─────────────────────────────────────────────────────────
def klik(hwnd, target, ganda=False):
    """target = Kata (koordinat relatif jendela) atau (fx, fy) pecahan 0..1 dari ukuran jendela."""
    l, t, r, b = rect(hwnd)
    if isinstance(target, Kata):
        x, y = target.tengah
        x, y = l + x, t + y
    else:
        x, y = l + int(target[0] * (r - l)), t + int(target[1] * (b - t))
    u32.SetCursorPos(x, y)
    time.sleep(0.15)
    for _ in range(2 if ganda else 1):
        u32.mouse_event(2, 0, 0, 0, 0)
        u32.mouse_event(4, 0, 0, 0, 0)
        time.sleep(0.08)
    time.sleep(0.4)


def tekan(keys):
    """Tombol pywinauto: '^a' Ctrl+A, '^v' paste, '{ENTER}', '{F5}', '^l', '^{ENTER}'."""
    from pywinauto.keyboard import send_keys
    send_keys(keys, pause=0.03)
    time.sleep(0.3)


def ketik(teks, jeda=0.0):
    """Ketik teks apa adanya (karakter khusus send_keys + ^ % ~ ( ) { } [ ] di-escape, aman untuk password).
    jeda>0 = ketik per karakter dgn jeda (kolom password Rajawali menjatuhkan karakter bila diketik cepat)."""
    from pywinauto.keyboard import send_keys
    esc = lambda c: "{%s}" % c if c in "+^%~(){}[]" else c
    if jeda > 0:
        for c in teks:
            send_keys(esc(c), with_spaces=True, with_tabs=True, pause=0)
            time.sleep(jeda)
    else:
        send_keys("".join(esc(c) for c in teks), with_spaces=True, with_tabs=True, pause=0.01)


def tempel(teks):
    """Isi clipboard lalu Ctrl+V (untuk SQL panjang, jauh lebih cepat & aman dari mengetik)."""
    import pyperclip
    pyperclip.copy(teks)
    time.sleep(0.2)
    tekan("^v")


# ── UI Automation (pohon aksesibilitas Chromium) ─────────────────────────────
# Prisma membuang --remote-debugging-port (diuji 28-10), tapi isi halaman tetap terbaca lewat UIA, lengkap dengan
# id elemen HTML Rajawali (username, password, v3WhatsNew, sqlcText, sqlcRun, ...). Id itu tidak terpengaruh
# watermark/resolusi/zoom seperti OCR. Pencarian HARUS per id (FindFirst): menelusuri seluruh pohon SQL Console
# (~19 ribu elemen karena daftar tabel) butuh 45 detik.
_UIA_AID, _UIA_NAMA, _UIA_NILAI = 30011, 30005, 10002     # AutomationIdProperty, NameProperty, ValuePattern


def _uia():
    from pywinauto.uia_defines import IUIA
    return IUIA()


def uia_cari(hwnd=None, aid=None, nama=None, akar=None, batas=0.0):
    """Elemen pertama ber-automation id `aid` (atau bernama persis `nama`) di bawah jendela hwnd / elemen `akar`.
    batas>0 = coba ulang sampai sekian detik (Chromium baru mengisi pohon halaman setelah ada yang meminta).
    Return elemen IUIAutomationElement atau None; galat UIA apa pun dianggap tidak ketemu (caller pakai OCR)."""
    t0 = time.time()
    while True:
        try:
            u = _uia()
            akar_ = akar or u.iuia.ElementFromHandle(hwnd)
            kond = u.iuia.CreatePropertyCondition(_UIA_AID if aid else _UIA_NAMA, aid or nama)
            e = akar_.FindFirst(4, kond)                  # 4 = TreeScope_Descendants
            if e:
                return e
        except Exception:
            pass
        if time.time() - t0 >= batas:
            return None
        time.sleep(1)


def uia_turunan(e):
    """Semua turunan elemen (untuk subpohon kecil, mis. menu profil). List pywinauto UIAElementInfo."""
    from pywinauto.uia_element_info import UIAElementInfo
    return UIAElementInfo(e).descendants()


def uia_anak(e):
    from pywinauto.uia_element_info import UIAElementInfo
    return UIAElementInfo(e).children()


def uia_induk(e):
    from pywinauto.uia_element_info import UIAElementInfo
    return UIAElementInfo(e).parent


def uia_nilai(e):
    """Isi kolom (ValuePattern), mis. teks kolom Username. None bila tidak bisa dibaca (kolom password)."""
    try:
        u = _uia()
        return e.GetCurrentPattern(_UIA_NILAI).QueryInterface(u.UIA_dll.IUIAutomationValuePattern).CurrentValue
    except Exception:
        return None


def uia_fokus(e, coba=5):
    """Pindahkan fokus keyboard ke elemen & PASTIKAN berhasil. Lebih aman dari klik: klik ke kolom Password bisa
    hanya menutup dropdown riwayat username sehingga password terketik di kolom Username (terjadi saat uji 28-10)."""
    for _ in range(coba):
        try:
            e.SetFocus()
            time.sleep(0.3)
            if e.CurrentHasKeyboardFocus:
                return True
        except Exception:
            time.sleep(0.3)
    return False


def _kembalikan_depan(sebelum, hwnd_prisma):
    """Chromium mengaktifkan jendelanya sendiri tiap aksi UIA; kembalikan jendela yang tadi dipakai user."""
    if not sebelum or sebelum == hwnd_prisma or not u32.IsWindow(sebelum):
        return
    for _ in range(15):                  # Chromium bisa mengaktifkan jendelanya agak terlambat -> ulang sebentar
        if u32.GetForegroundWindow() != sebelum:
            u32.keybd_event(0x12, 0, 0, 0)
            u32.SetForegroundWindow(sebelum)
            u32.keybd_event(0x12, 0, 2, 0)
        time.sleep(0.1)


def tampil_atas(hwnd, nyala):
    """Tampilkan jendela di atas semua jendela TANPA mengambil fokus keyboard (nyala=True), lalu turunkan lagi ke
    belakang (nyala=False). Chromium memperlambat halaman yang jendelanya tertutup penuh (hasil query baru tampil &
    unduhan baru jalan saat jendela terlihat lagi; opsi --disable-features=CalculateNativeWinOcclusion dibuang Prisma,
    diuji 28-10), jadi saat menunggu, Prisma 'diintip' sebentar dengan cara ini. Tidak ada efek bila Prisma memang
    jendela aktif."""
    if not hwnd:
        return
    f = 0x0001 | 0x0002 | 0x0010 | 0x0040                 # NOSIZE | NOMOVE | NOACTIVATE | SHOWWINDOW
    aktif = u32.GetForegroundWindow() == hwnd
    if nyala:
        if not aktif:
            u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, f)      # HWND_TOPMOST
    else:
        u32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, f)          # HWND_NOTOPMOST: selalu dilepas, jangan sampai tertinggal
        if not aktif:
            u32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, f)       # HWND_BOTTOM: kembali ke belakang jendela user


def intip(hwnd, detik=1.2):
    """Prisma terlihat sebentar (tanpa ambil fokus) supaya halaman sempat memproses & menggambar ulang."""
    if not hwnd or u32.GetForegroundWindow() == hwnd:
        return False
    tampil_atas(hwnd, True)
    time.sleep(detik)
    tampil_atas(hwnd, False)
    return True


def uia_invoke(e, hwnd_prisma=None):
    """'Klik' elemen tanpa mouse (InvokePattern, cadangan LegacyIAccessible.DoDefaultAction), lalu kembalikan jendela
    depan semula. Return True bila salah satu pola berhasil."""
    sebelum = u32.GetForegroundWindow()
    u = _uia()
    ok = False
    for pid, iface, aksi in ((10000, "IUIAutomationInvokePattern", "Invoke"),
                             (10018, "IUIAutomationLegacyIAccessiblePattern", "DoDefaultAction")):
        try:
            p = e.GetCurrentPattern(pid)
            if p:
                getattr(p.QueryInterface(getattr(u.UIA_dll, iface)), aksi)()
                ok = True
                break
        except Exception:
            continue
    time.sleep(0.3)
    _kembalikan_depan(sebelum, hwnd_prisma)
    return ok


def uia_isi(e, teks, hwnd_prisma=None):
    """Isi kolom/editor tanpa keyboard (ValuePattern.SetValue). Editor SQL Rajawali menerima ini (diuji 28-10), tapi
    nilai yang dibaca balik baru benar setelah sesaat -> caller cek ulang dengan jeda."""
    sebelum = u32.GetForegroundWindow()
    try:
        e.GetCurrentPattern(_UIA_NILAI).QueryInterface(_uia().UIA_dll.IUIAutomationValuePattern).SetValue(teks)
        ok = True
    except Exception:
        ok = False
    time.sleep(0.3)
    _kembalikan_depan(sebelum, hwnd_prisma)
    return ok


def uia_klik(e):
    """Klik tengah kotak elemen (koordinat layar dari UIA). Return False bila elemen tak terlihat di layar."""
    try:
        r = e.CurrentBoundingRectangle
    except Exception:
        return False
    if r.right - r.left < 2 or r.bottom - r.top < 2:
        return False
    u32.SetCursorPos((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    time.sleep(0.15)
    u32.mouse_event(2, 0, 0, 0, 0)
    u32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.5)
    return True


# ── blok input fisik / remote selama otomasi ─────────────────────────────────
# Saat diblok, Ctrl+Alt+Del dari Chrome Remote Desktop ikut terblok, jadi pintu darurat dibuat di sini:
#   1. tidur(): selama menunggu (OCR/query/unduhan) blok dilepas sebentar-sebentar; di jendela itu
#      tombol Ctrl+Shift+Q (fisik atau CRD) menghentikan program -> blok lepas.
#   2. file STOP_OTOMASI di folder ini -> program berhenti (bisa dibuat dari PC lain lewat share folder).
#   3. blok tanpa jeda lebih dari maks_detik -> dianggap macet, program berhenti.
# Program berhenti = thread pemblok mati = Windows melepas blok (sama seperti Ctrl+Alt+Del fisik).
STOP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STOP_OTOMASI")
TOMBOL_STOP = "Ctrl+Shift+Q"
_BLOK = {"aktif": False, "sejak": 0.0}


def _tombol_stop():
    ks = u32.GetAsyncKeyState
    return bool(ks(0x11) & 0x8000 and ks(0x10) & 0x8000 and ks(0x51) & 0x8000)   # Ctrl + Shift + Q


def mulai_penjaga(maks_detik=120, log=print):
    """Thread penjaga pintu darurat (lihat atas). Aman dipanggil berkali-kali."""
    import threading
    if _BLOK.get("penjaga"):
        return
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)                 # sisa dari penghentian sebelumnya

    def jaga():
        while True:
            alasan = None
            if os.path.exists(STOP_FILE):
                alasan = "file STOP_OTOMASI ditemukan"
            elif _tombol_stop():
                alasan = f"tombol {TOMBOL_STOP} ditekan"
            elif _BLOK["aktif"] and time.time() - _BLOK["sejak"] > maks_detik:
                alasan = f"input terblok tanpa jeda > {maks_detik} detik (macet?)"
            if alasan:
                try:
                    log(f"DIHENTIKAN: {alasan} -> program keluar, blok input lepas")
                finally:
                    os._exit(3)
            time.sleep(0.05)

    threading.Thread(target=jaga, daemon=True, name="penjaga-blok").start()
    _BLOK["penjaga"] = True


def tidur(detik):
    """Pengganti time.sleep di loop menunggu: bila input sedang diblok dan jeda >= 1.5 detik, blok dilepas
    selama tidur (jendela untuk pintu darurat Ctrl+Shift+Q) lalu dipasang lagi."""
    lepas = _BLOK["aktif"] and detik >= 1.5
    if lepas:
        blok_input(False)
    try:
        time.sleep(detik)
    finally:
        if lepas:
            blok_input(True)


def admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def blok_input(nyala):
    """Blok (True) / lepas (False) SEMUA input mouse+keyboard dari luar program ini: fisik, Chrome Remote
    Desktop, dll. Klik/ketik dari program ini sendiri tetap jalan (Windows mengizinkan input dari thread
    yang memanggil BlockInput). Butuh hak Administrator. Pintu darurat: Ctrl+Alt+Del selalu melepas blok.
    Blok juga otomatis lepas bila program berhenti/crash. Return True bila berhasil."""
    if nyala and not admin():
        return False
    ok = bool(u32.BlockInput(bool(nyala)))
    if nyala and ok and not _BLOK["aktif"]:
        _BLOK["sejak"] = time.time()
    _BLOK["aktif"] = bool(nyala) and ok
    return ok


def blok_aktif():
    return _BLOK["aktif"]
