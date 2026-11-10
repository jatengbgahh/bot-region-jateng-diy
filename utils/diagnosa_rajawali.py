"""
diagnosa_rajawali.py — cek apakah PC/server ini siap untuk otomasi Rajawali (OCR + jendela Prisma).
TIDAK mengklik atau mengetik apa pun; hanya membaca layar.

Pakai: buka Prisma, buka halaman Rajawali (login atau dashboard), lalu jalankan
    python utils/diagnosa_rajawali.py
Hasil: diagnosa_rajawali_<waktu>.png + .txt di folder ini (kirim dua file itu untuk dicek).
"""
import ctypes
import os
import platform
import sys
from datetime import datetime

import rajawali_ui as R

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # root proyek


def main():
    baris = []

    def tulis(t=""):
        print(t)
        baris.append(t)

    tulis(f"Python {sys.version.split()[0]} {platform.architecture()[0]} | Windows {platform.version()}")
    u32 = ctypes.windll.user32
    tulis(f"Layar utama: {u32.GetSystemMetrics(0)}x{u32.GetSystemMetrics(1)} | "
          f"semua monitor: {u32.GetSystemMetrics(78)}x{u32.GetSystemMetrics(79)}")
    sesi = os.environ.get("SESSIONNAME", "?")
    tulis(f"Sesi Windows: {sesi}" + ("  (RDP: jangan di-minimize/disconnect saat otomasi jalan)"
                                    if sesi.upper().startswith("RDP") else ""))

    from winrt.windows.media.ocr import OcrEngine
    bahasa = [l.language_tag for l in OcrEngine.available_recognizer_languages]
    tulis(f"Bahasa OCR terpasang: {bahasa or 'TIDAK ADA'}")
    eng = R._engine()
    if eng is None:
        tulis("!! OCR tidak bisa dibuat dari bahasa profil user. Pasang bahasa English (United States) "
              "di Settings > Time & language > Language, lalu login ulang.")
        return _simpan(baris, None)
    tulis(f"OCR memakai bahasa: {eng.recognizer_language.language_tag}")

    ws = R.jendela_prisma()
    tulis(f"Jendela Prisma: {[(w[1], w[2]) for w in ws] or 'TIDAK ADA (buka Prisma dulu)'}")
    if not ws:
        return _simpan(baris, None)
    h = next((w[0] for w in ws if w[1].strip()), ws[0][0])
    img, (l, t, r, b) = R.layar(h)
    tulis(f"Jendela dipakai: {R.judul(h)!r} ukuran {r - l}x{b - t} skala DPI {R.skala_dpi(h):.2f}")
    if img.convert("L").getextrema()[1] < 20:
        tulis("!! Tangkapan layar hitam: layar terkunci / sesi RDP di-minimize atau disconnect.")
    ks = [k for k in R.ocr(img, 1.5)]
    tulis(f"Teks terbaca OCR: {len(ks)} potong")
    tulis("--- hasil OCR (x,y,w,h  teks) ---")
    for k in ks:
        tulis(f"{k.x},{k.y},{k.w},{k.h}\t{k.teks}")
    _simpan(baris, img)


def _simpan(baris, img):
    dasar = os.path.join(BASE, f"diagnosa_rajawali_{datetime.now():%Y%m%d_%H%M%S}")
    with open(dasar + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(baris) + "\n")
    if img is not None:
        img.save(dasar + ".png")
    print(f"\nTersimpan: {dasar}.txt" + (f" dan {dasar}.png" if img is not None else ""))


if __name__ == "__main__":
    main()
