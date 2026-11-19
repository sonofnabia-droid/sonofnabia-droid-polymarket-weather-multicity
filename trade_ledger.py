from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LEDGER_PATH = Path(__import__("os").environ.get("CASS_LOG_DIR", "live_bot_logs")) / "trade_ledger.jsonl"
_APPEND_LOCK = threading.Lock()


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
    # BET_OPEN and BET_CLOSE are one-time state transitions for a position.
    # Time-window dedup allowed retries/restarts to append the same close again
    # after two seconds, inflating performance and resolution counts.
    event_type = record.get("event_type")
    position_id = record.get("position_id")
    unique_transition = event_type in {"BET_OPEN", "BET_CLOSE"} and bool(position_id)

    # Thread lock protects same-process writers. flock also protects cooperating
    # writers across processes sharing a ledger on the Linux deployment host.
    with _APPEND_LOCK:
        with ledger_path.open("a+", encoding="utf-8") as f:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except ImportError:
                fcntl = None
            try:
                if unique_transition:
                    f.seek(0)
                    for line in f:
                        try:
                            previous = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if (previous.get("event_type") == event_type
                                and previous.get("position_id") == position_id):
                            return
                f.seek(0, 2)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)


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

