"""
reports/market_share/state.py — Catatan event_date terakhir yang sudah dikirim otomatis.

Dipakai job harian jam 10:00 (commands/market_share.py) supaya report hanya terkirim
SEKALI per update tabel: kirim kalau MAX(event_date) tabel > event_date yang tercatat.
File: reports/market_share/last_sent.json
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_DIR = Path(__file__).resolve().parents[2] / "storage" / "state"
_STATE_DIR.mkdir(parents=True, exist_ok=True)
_FILE = _STATE_DIR / "market_share_last_sent.json"


def baca_event_date_terkirim() -> date | None:
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        return date.fromisoformat(raw["event_date"])
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"[ms] last_sent.json tidak terbaca ({e}) — dianggap belum pernah kirim")
        return None


def simpan_event_date_terkirim(event_date: date) -> None:
    _FILE.write_text(
        json.dumps({"event_date": event_date.isoformat(),
                    "sent_at": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
