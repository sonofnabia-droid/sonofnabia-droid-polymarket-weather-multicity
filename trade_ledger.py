from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LEDGER_PATH = Path("live_bot_logs") / "trade_ledger.jsonl"


def make_position_id(
    date_opened: str,
    city: str,
    token_id: str,
    order_id: str,
    market_slug: str,
) -> str:
    raw = f"{date_opened}|{city}|{token_id}|{order_id}|{market_slug}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def append_event(event: dict[str, Any], ledger_path: Path = LEDGER_PATH) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(event)
    record.setdefault("ts", datetime.now().isoformat())
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_events(ledger_path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


@dataclass
class PnLSummary:
    realized_pnl: float
    n_open: int
    n_closed: int

