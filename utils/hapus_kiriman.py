"""
hapus_kiriman.py — hapus pesan yang tercatat oleh utils/csv_report_runner.py --kirim.

  python utils/hapus_kiriman.py storage/sql_packets/terkirim_20261021_084000.json          # tampilkan saja
  python utils/hapus_kiriman.py storage/sql_packets/terkirim_20261021_084000.json --ya     # benar-benar hapus
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telegram import Bot
from config import TOKEN

path = sys.argv[1]
data = json.load(open(path))
pesan = data["pesan"]
print(f"{len(pesan)} pesan (laporan {data['tanggal_laporan']}):", [m["message_id"] for m in pesan])
if "--ya" not in sys.argv:
    sys.exit("Dry-run. Tambahkan --ya untuk menghapus.")


async def main():
    async with Bot(TOKEN) as b:
        for m in pesan:
            try:
                await b.delete_message(chat_id=m["chat_id"], message_id=m["message_id"])
                print("dihapus", m["message_id"])
            except Exception as e:
                print("gagal", m["message_id"], e)

asyncio.run(main())
