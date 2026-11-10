"""
whatsapp/errors.py — Perapi pesan error command "_wa" untuk ditampilkan di Telegram.
"""

import re

# Base64 (data gambar/file) yang ikut ke-echo di pesan error server WA bisa
# berupa satu token ribuan karakter — cocokkan runtutan panjang karakter base64
# (huruf/angka/+/=) dan potong supaya pesan error di Telegram tetap enak dibaca.
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")


def clean_wa_error(e: Exception, limit: int = 500) -> str:
    """
    Ringkas exception dari command "_wa" supaya aman & enak dibaca di Telegram:
    - Blob base64 panjang (payload gambar/file yang ke-echo balik) diganti placeholder.
    - Pesan akhir dipotong ke `limit` karakter.
    Traceback lengkap tetap ada di bot_re_jateng.log lewat logger.exception(...).
    """
    text = str(e)

    def _omit(m: "re.Match") -> str:
        return f"<data {len(m.group(0))} char dihilangkan>"

    text = _BASE64_BLOB_RE.sub(_omit, text)
    if len(text) > limit:
        text = text[:limit] + f"... (dipotong, {len(str(e))} char total — cek bot_re_jateng.log untuk detail lengkap)"
    return text
