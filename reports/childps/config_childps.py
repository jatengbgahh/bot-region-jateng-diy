"""
config_childps.py — Konfigurasi sumber data report Child per PS Telkomsel One (/childps).
Seluruh nilai kini dibaca dari `.env` melalui `config.py`.
"""

from config import CHILDPS_KIRIM_KE_GRUP, CHILDPS_SQL

__all__ = ["CHILDPS_SQL", "CHILDPS_KIRIM_KE_GRUP"]
