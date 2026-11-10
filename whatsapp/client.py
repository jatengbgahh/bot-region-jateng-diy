"""
whatsapp/client.py — HTTP Client untuk WAHA (WhatsApp HTTP API).
Satu-satunya file yang tahu mesin pengirim WA (WAHA). Kalau mesinnya diganti,
cukup ganti file ini (+ get_waha_client di bawah) tanpa menyentuh file lain.
Menghubungkan bot dengan server WAHA yang berjalan di http://localhost:3000.
"""

import base64
import logging
from typing import Optional, Union
import requests

logger = logging.getLogger(__name__)


class WahaClient:
    """Client untuk berinteraksi dengan API WAHA (localhost:3000)."""

    def __init__(
        self,
        base_url: str = "http://localhost:3000",
        session: str = "default",
        api_key: Optional[str] = None,
        timeout: int = 60,
    ):
        raw_url = (base_url or "http://localhost:3000").rstrip("/")
        # Pastikan menggunakan http:// untuk localhost karena server WAHA lokal default-nya plain HTTP
        if raw_url.startswith("https://localhost") or raw_url.startswith("https://127.0.0.1"):
            raw_url = "http://" + raw_url.split("://", 1)[1]
        self.base_url = raw_url
        self.session = session or "default"
        self.api_key = api_key
        self.timeout = timeout

        # Gunakan session khusus dengan trust_env=False dan proxies=None.
        # Ini WAJIB agar request ke localhost tidak dicegat oleh proxy VPN (GlobalProtect/system proxy)
        # yang menyebabkan error: [SSL: WRONG_VERSION_NUMBER] wrong version number.
        self._http = requests.Session()
        self._http.trust_env = False
        self._http.proxies = {"http": None, "https": None}

    def _get_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    @staticmethod
    def format_chat_id(chat_id: str) -> str:
        """
        Format input nomor telepon atau grup ID menjadi format yang valid untuk WAHA:
        - Jika sudah ada '@' (cth: 628xxx@c.us atau xxx@g.us), gunakan langsung.
        - Jika nomor lokal (08xxx), ubah 0 di depan jadi 62 (628xxx@c.us).
        - Jika nomor internasional (+62xxx), hapus tanda +.
        - Jika hanya angka, tambahkan suffix '@c.us'.
        """
        if not chat_id:
            return ""
        cid = str(chat_id).strip()
        if "@" in cid:
            return cid

        cid = cid.replace(" ", "").replace("-", "").replace("+", "")
        if cid.startswith("0"):
            cid = "62" + cid[1:]

        # Jika ID grup lama menggunakan format "xxxx-xxxx"
        if "-" in cid:
            return f"{cid}@g.us"

        return f"{cid}@c.us"

    def send_text(self, chat_id: str, text: str, session: Optional[str] = None) -> dict:
        """
        Kirim pesan teks via WAHA (POST /api/sendText).
        """
        sess = session or self.session
        url = f"{self.base_url}/api/sendText"
        formatted_id = self.format_chat_id(chat_id)

        payload = {
            "session": sess,
            "chatId": formatted_id,
            "text": text,
        }

        logger.info(f"[WAHA] Mengirim teks ke {formatted_id} (session: {sess})")
        resp = self._http.post(url, json=payload, headers=self._get_headers(), timeout=self.timeout)
        if resp.status_code >= 400:
            err_msg = resp.text
            logger.error(f"[WAHA] Gagal kirim teks: {resp.status_code} - {err_msg}")
            raise RuntimeError(f"WAHA Error ({resp.status_code}): {err_msg}")

        return resp.json() if resp.content else {}

    def send_file(
        self,
        chat_id: str,
        file_data: Union[bytes, bytearray],
        filename: str = "file.png",
        caption: str = "",
        mimetype: str = "image/png",
        session: Optional[str] = None,
        as_document: bool = True,
    ) -> dict:
        """
        Kirim file via WAHA (POST /api/sendFile).
        WAHA menerima raw base64 string di dalam field 'file.data'.
        """
        sess = session or self.session
        url = f"{self.base_url}/api/sendFile"
        formatted_id = self.format_chat_id(chat_id)
        b64_data = base64.b64encode(file_data).decode("utf-8")

        payload = {
            "session": sess,
            "chatId": formatted_id,
            "file": {
                "mimetype": mimetype,
                "filename": filename,
                "data": b64_data,
            },
            "caption": caption or "",
            "asDocument": as_document,
        }

        logger.info(f"[WAHA] Mengirim file {filename} ke {formatted_id} (session: {sess})")
        resp = self._http.post(url, json=payload, headers=self._get_headers(), timeout=self.timeout)
        if resp.status_code >= 400:
            err_msg = resp.text
            logger.error(f"[WAHA] Gagal kirim file {filename}: {resp.status_code} - {err_msg}")
            raise RuntimeError(f"WAHA Error ({resp.status_code}): {err_msg}")

        return resp.json() if resp.content else {}

    def send_image(
        self,
        chat_id: str,
        image_bytes: Union[bytes, bytearray],
        filename: str = "laporan.png",
        caption: str = "",
        session: Optional[str] = None,
    ) -> dict:
        """
        Kirim gambar via endpoint khusus WAHA (POST /api/sendImage).
        WAHA memproses gambar lebih cepat & stabil di endpoint ini dengan raw base64 di file.data.
        """
        sess = session or self.session
        url = f"{self.base_url}/api/sendImage"
        formatted_id = self.format_chat_id(chat_id)
        mimetype = "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"
        b64_data = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "session": sess,
            "chatId": formatted_id,
            "file": {
                "mimetype": mimetype,
                "filename": filename,
                "data": b64_data,
            },
            "caption": caption or "",
        }

        logger.info(f"[WAHA] Mengirim gambar {filename} ke {formatted_id} (session: {sess})")
        resp = self._http.post(url, json=payload, headers=self._get_headers(), timeout=self.timeout)
        if resp.status_code >= 400:
            err_msg = resp.text
            logger.error(f"[WAHA] Gagal kirim gambar {filename}: {resp.status_code} - {err_msg}")
            raise RuntimeError(f"WAHA Error ({resp.status_code}): {err_msg}")

        return resp.json() if resp.content else {}

    def check_status(self, session: Optional[str] = None) -> dict:
        """Mengecek status session WAHA saat ini."""
        sess = session or self.session
        url = f"{self.base_url}/api/sessions/{sess}"
        resp = self._http.get(url, headers=self._get_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else {}


def get_waha_client() -> WahaClient:
    """Inisialisasi WahaClient menggunakan konfigurasi WAHA_* dari config.py."""
    try:
        from config import WAHA_BASE_URL, WAHA_SESSION, WAHA_API_KEY
    except ImportError:
        WAHA_BASE_URL = "http://localhost:3000"
        WAHA_SESSION  = "default"
        WAHA_API_KEY  = None

    return WahaClient(
        base_url=WAHA_BASE_URL,
        session=WAHA_SESSION,
        api_key=WAHA_API_KEY,
    )
