"""
whatsapp/adapter.py — Adapter yang menyerupai objek bot Telegram, tapi mengirim ke WhatsApp.

_kirim_laporan_sql (bot.py) memanggil bot.send_photo / send_message / send_document.
Kalau `bot`-nya diganti WahaBotAdapter, panggilan yang sama diteruskan ke WhatsApp,
jadi format laporan WA otomatis sama dengan versi Telegram.
"""

import asyncio
import logging

from .client import WahaClient

logger = logging.getLogger(__name__)


def _extract_bytes_and_filename(file_obj, default_name: str = "file.png") -> tuple[bytes, str]:
    """Ekstrak bytes dan filename dari InputFile Telegram atau objek BytesIO/file."""
    filename = getattr(file_obj, "filename", default_name)
    raw = getattr(file_obj, "input_file_content", file_obj)

    if hasattr(raw, "seek"):
        try:
            raw.seek(0)
        except Exception:
            pass

    if hasattr(raw, "read"):
        content = raw.read()
    elif isinstance(raw, (bytes, bytearray)):
        content = bytes(raw)
    else:
        content = str(raw).encode("utf-8")

    return content, filename


class WahaBotAdapter:
    """
    Adapter tiruan bot Telegram untuk dialihkan ke WhatsApp.
    Menerima panggilan `send_photo`, `send_message`, dan `send_document` dari fungsi
    `_kirim_laporan_sql`, kemudian meneruskannya langsung ke WhatsApp via WAHA HTTP API.
    """

    def __init__(
        self,
        client: WahaClient,
        target_chat_id: str,
        send_images: bool = True,
    ):
        self.client = client
        self.target_chat_id = target_chat_id
        self.send_images = send_images
        self.sent_count = 0

    async def send_message(self, chat_id=None, text: str = "", **kwargs):
        """Kirim pesan teks biasa ke WhatsApp."""
        if not text:
            return None

        clean_text = text.replace("`", "")

        def _send():
            return self.client.send_text(self.target_chat_id, clean_text)

        result = await asyncio.to_thread(_send)
        self.sent_count += 1
        return result

    async def send_photo(self, chat_id=None, photo=None, caption: str = None, **kwargs):
        """Kirim gambar (atau caption-nya saja jika send_images=False)."""
        if self.send_images and photo:
            img_bytes, filename = _extract_bytes_and_filename(photo, "laporan.png")

            def _send_img():
                return self.client.send_image(
                    self.target_chat_id,
                    img_bytes,
                    filename=filename,
                    caption=caption or "",
                )

            try:
                result = await asyncio.to_thread(_send_img)
                self.sent_count += 1
                return result
            except Exception as e:
                logger.warning(f"[WAHA] Gagal kirim gambar {filename}, fallback kirim teks: {e}")
                if caption:
                    return await self.send_message(text=caption)
                raise
        else:
            if caption:
                return await self.send_message(text=caption)

        return None

    async def send_document(self, chat_id=None, document=None, caption: str = None, **kwargs):
        """Kirim dokumen (misal ZIP raw CSV) ke WhatsApp."""
        if self.send_images and document:
            doc_bytes, filename = _extract_bytes_and_filename(document, "dokumen.zip")
            mimetype = "application/zip" if filename.endswith(".zip") else "application/octet-stream"

            def _send_doc():
                return self.client.send_file(
                    self.target_chat_id,
                    doc_bytes,
                    filename=filename,
                    caption=caption or "",
                    mimetype=mimetype,
                )

            try:
                result = await asyncio.to_thread(_send_doc)
                self.sent_count += 1
                return result
            except Exception as e:
                logger.warning(f"[WAHA] Gagal kirim dokumen {filename}, fallback kirim teks: {e}")
                if caption:
                    return await self.send_message(text=caption)
                raise
        else:
            if caption:
                return await self.send_message(text=caption)

        return None
