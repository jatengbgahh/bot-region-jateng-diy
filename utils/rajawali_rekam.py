"""
rajawali_rekam.py — rekam interaksi kamu di Prisma (klik + tombol khusus) untuk dijadikan langkah otomasi.

  python utils/rajawali_rekam.py          # mulai rekam; kerjakan langkahnya di Prisma; tekan F12 untuk berhenti

Tiap KLIK di jendela Prisma disimpan sebagai:
  - posisi relatif jendela (0..1)       -> tetap berlaku di resolusi/ukuran layar lain
  - teks OCR terdekat ("anchor")         -> dipakai lebih dulu saat replay (paling tahan perubahan tata letak)
  - potongan gambar sekitar klik         -> untuk dicek manusia
Keyboard: HANYA tombol khusus/kombinasi (Enter, Tab, F5, Ctrl+V, Ctrl+Enter, ...). Huruf/angka yang
diketik TIDAK disimpan (cuma dicatat "N karakter") supaya PIN/password tidak pernah masuk ke rekaman.

Hasil: rekaman/<waktu>/langkah.json + gambar per langkah.
"""
import json
import math
import os
import time
from datetime import datetime

from pynput import keyboard, mouse

import rajawali_ui as R

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # root proyek
OUT = os.path.join(BASE, "rekaman", datetime.now().strftime("%Y%m%d_%H%M%S"))
os.makedirs(OUT, exist_ok=True)

kejadian = []          # diproses (OCR) setelah selesai supaya rekaman tidak lambat
mod = set()
ketikan = {"n": 0}
selesai = {"ya": False}


def _fg():
    return R.u32.GetForegroundWindow()


def _prisma_hwnd(h):
    return any(h == w[0] for w in R.jendela_prisma())


def _flush_ketikan():
    if ketikan["n"]:
        kejadian.append({"jenis": "ketik", "karakter": ketikan["n"], "t": time.time()})
        ketikan["n"] = 0


def on_click(x, y, tombol, ditekan):
    if not ditekan or selesai["ya"]:
        return
    h = _fg()
    if not _prisma_hwnd(h):
        return
    _flush_ketikan()
    img, (l, t, r, b) = R.layar(h)
    kejadian.append({"jenis": "klik", "tombol": str(tombol).split(".")[-1], "x": x - l, "y": y - t,
                     "w": r - l, "h": b - t, "img": img, "t": time.time()})


NAMA_KHUSUS = {keyboard.Key.enter: "{ENTER}", keyboard.Key.tab: "{TAB}", keyboard.Key.esc: "{ESC}",
               keyboard.Key.f5: "{F5}", keyboard.Key.backspace: "{BACKSPACE}", keyboard.Key.delete: "{DELETE}",
               keyboard.Key.up: "{UP}", keyboard.Key.down: "{DOWN}", keyboard.Key.left: "{LEFT}",
               keyboard.Key.right: "{RIGHT}", keyboard.Key.page_down: "{PGDN}", keyboard.Key.page_up: "{PGUP}"}
MOD = {keyboard.Key.ctrl_l: "^", keyboard.Key.ctrl_r: "^", keyboard.Key.shift: "+", keyboard.Key.shift_r: "+",
       keyboard.Key.alt_l: "%", keyboard.Key.alt_r: "%"}


def on_press(k):
    if k == keyboard.Key.f12:
        selesai["ya"] = True
        return False
    if not _prisma_hwnd(_fg()):
        return
    if k in MOD:
        mod.add(MOD[k])
        return
    pre = "".join(sorted(mod))
    if k in NAMA_KHUSUS:
        _flush_ketikan()
        kejadian.append({"jenis": "tombol", "keys": pre + NAMA_KHUSUS[k], "t": time.time()})
    elif "^" in pre or "%" in pre:          # kombinasi Ctrl/Alt + huruf (mis. Ctrl+V, Ctrl+L)
        _flush_ketikan()
        ch = getattr(k, "char", None) or ""
        if ch and ord(ch) < 32:                       # Ctrl+huruf terbaca sbg karakter kontrol
            ch = chr(ord(ch) + 96)
        kejadian.append({"jenis": "tombol", "keys": pre + ch.lower(), "t": time.time()})
    else:
        ketikan["n"] += 1                             # isi ketikan TIDAK disimpan


def on_release(k):
    if k in MOD:
        mod.discard(MOD[k])


def anchor(img, x, y):
    """Teks OCR terdekat ke titik klik (baris/kata), jarak dlm piksel."""
    terbaik = None
    for kt in R.ocr(img, 1.5):
        cx, cy = kt.tengah
        di_dalam = kt.x <= x <= kt.x + kt.w and kt.y <= y <= kt.y + kt.h
        d = 0 if di_dalam else math.hypot(cx - x, cy - y)
        if len(kt.teks.strip()) >= 2 and (terbaik is None or d < terbaik[0]):
            terbaik = (d, kt)
    return terbaik


def main():
    print(f"MEREKAM -> {OUT}\nKerjakan langkahnya di Prisma. Tekan F12 untuk berhenti.\n"
          "(Huruf/angka yang kamu ketik tidak direkam, hanya jumlahnya.)")
    with mouse.Listener(on_click=on_click) as ml, keyboard.Listener(on_press=on_press, on_release=on_release) as kl:
        while not selesai["ya"]:
            time.sleep(0.2)
        ml.stop()
    _flush_ketikan()
    print(f"Berhenti. Memproses {len(kejadian)} kejadian (OCR)...")
    langkah = []
    t0 = kejadian[0]["t"] if kejadian else time.time()
    for i, e in enumerate(kejadian, 1):
        d = {"no": i, "jenis": e["jenis"], "detik": round(e["t"] - t0, 1)}
        if e["jenis"] == "klik":
            img = e.pop("img")
            img.save(os.path.join(OUT, f"{i:02d}_layar.png"))
            x, y = e["x"], e["y"]
            img.crop((max(0, x - 90), max(0, y - 30), x + 90, y + 30)).save(os.path.join(OUT, f"{i:02d}_sekitar.png"))
            a = anchor(img, x, y)
            d.update({"fx": round(x / e["w"], 4), "fy": round(y / e["h"], 4), "ukuran_jendela": [e["w"], e["h"]],
                      "tombol": e["tombol"],
                      "anchor": a[1].teks if a else None, "jarak_anchor": round(a[0]) if a else None,
                      "offset_anchor": [x - a[1].tengah[0], y - a[1].tengah[1]] if a else None})
        else:
            d.update({k: v for k, v in e.items() if k in ("keys", "karakter")})
        langkah.append(d)
        print(d)
    json.dump(langkah, open(os.path.join(OUT, "langkah.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nTersimpan: {os.path.join(OUT, 'langkah.json')}")


if __name__ == "__main__":
    main()
