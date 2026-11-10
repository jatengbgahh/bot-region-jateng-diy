"""
tes_koneksi_indiana.py — Cek server bisa konek ke DB Indiana (report /pranpc*).
Jalankan dari folder bot:  python3 utils/tes_koneksi_indiana.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pranpc_data

try:
    per = pranpc_data.periode_berjalan()
    tgl = pranpc_data.tanggal_status_terakhir(per, per)
    n = pranpc_data._query(
        "SELECT COUNT(*) FROM indiana_tr_migrasi_pranpc WHERE regional = %s",
        (pranpc_data.DB2_REGIONAL,), label="tes")[0][0]
    print(f"OK  - periode berjalan {per}, status OCS terakhir {tgl}, WO {pranpc_data.DB2_REGIONAL}: {n:,}")
except Exception as e:
    print(f"GAGAL - {e}")
