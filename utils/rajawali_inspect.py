"""
rajawali_inspect.py — HANYA MEMBACA: cari jendela Prisma Browser dan daftar elemen penting di halaman
SQL Console Rajawali (editor SQL, tombol Run/Export, teks status). Tidak mengklik / mengetik apa pun.

  python utils/rajawali_inspect.py            # ringkas (elemen yang relevan)
  python utils/rajawali_inspect.py --semua    # dump pohon elemen lengkap ke rajawali_uia_dump.txt
"""
import sys

from pywinauto import Desktop

PROSES = "PrismaAccessBrowser.exe"
KATA = ("run", "export", "select", "sql", "console", "rows", "history", "error", "statement")


def jendela_prisma():
    import psutil  # bawaan pywinauto
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == PROSES.lower()}
    return [w for w in Desktop(backend="uia").windows() if w.process_id() in pids and w.window_text()]


def main():
    ws = jendela_prisma()
    if not ws:
        sys.exit("Prisma Browser tidak ditemukan. Buka Prisma, login, dan buka SQL Console Rajawali dulu.")
    for w in ws:
        print(f"JENDELA: {w.window_text()!r}")
    w = next((x for x in ws if "rajawali" in x.window_text().lower() or "performance" in x.window_text().lower()
              or "worklist" in x.window_text().lower()), ws[0])
    print(f"\nDipakai: {w.window_text()!r}\n")
    semua = "--semua" in sys.argv
    out = open("rajawali_uia_dump.txt", "w", encoding="utf-8") if semua else None
    n = 0
    for e in w.descendants():
        try:
            ct = e.element_info.control_type
            nm = (e.element_info.name or "").strip()
            aid = e.element_info.automation_id or ""
            cls = e.element_info.class_name or ""
        except Exception:
            continue
        baris = f"{ct:12} | name={nm[:90]!r} | id={aid[:40]!r} | class={cls[:30]!r}"
        if out:
            out.write(baris + "\n")
        relevan = ct in ("Edit", "Button", "Document") or any(k in nm.lower() for k in KATA)
        if relevan and (nm or ct == "Edit"):
            print(baris)
            n += 1
            if n > 250:
                print("... (dipotong)")
                break
    if out:
        out.close()
        print("\nPohon lengkap: rajawali_uia_dump.txt")


if __name__ == "__main__":
    main()
