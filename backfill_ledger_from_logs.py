#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trade_ledger import append_event, make_position_id, read_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill trade_ledger.jsonl a partir de logs antigos.")
    parser.add_argument("--logs-dir", default="live_bot_logs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logs = Path(args.logs_dir)
    existing = {e.get("position_id") for e in read_events() if e.get("position_id")}

    opens = []
    for f in sorted(logs.glob("bets_*_*.json")):
        try:
            arr = json.loads(f.read_text())
        except Exception:
            continue
        city = f.name.split("_")[1]
        for b in arr:
            opened_at = b.get("timestamp") or b.get("time")
            if not opened_at:
                continue
            date_opened = str(opened_at)[:10]
            pid = make_position_id(
                date_opened=date_opened,
                city=city,
                token_id=str(b.get("token_id") or ""),
                order_id=str(b.get("order_id") or ""),
                market_slug=str(b.get("market_slug") or ""),
            )
            if pid in existing:
                continue
            opens.append((pid, city, b, opened_at))
            existing.add(pid)

    closes = []
    pp = logs / "paper_positions.json"
    if pp.exists():
        try:
            arr = json.loads(pp.read_text())
        except Exception:
            arr = []
        for p in arr:
            if p.get("status") not in ("won", "lost"):
                continue
            city = ""
            slug = str(p.get("market_slug") or "")
            if "-in-" in slug and "-on-" in slug:
                city = slug.split("-on-")[0].split("-in-")[1]
            date_opened = str(p.get("date_opened") or "")[:10]
            pid = p.get("position_id") or make_position_id(
                date_opened=date_opened,
                city=city,
                token_id=str(p.get("token_id") or ""),
                order_id=str(p.get("order_id") or ""),
                market_slug=slug,
            )
            closes.append((pid, p))

    print(f"opens_to_backfill={len(opens)} closes_to_backfill={len(closes)}")
    if args.dry_run:
        return 0

    for pid, city, b, opened_at in opens:
        append_event({
            "event_type": "BET_OPEN",
            "position_id": pid,
            "city": city,
            "market_slug": b.get("market_slug"),
            "token_id": b.get("token_id"),
            "order_id": b.get("order_id"),
            "opened_at": opened_at,
            "entry_ask": b.get("ask"),
            "shares": b.get("shares"),
            "size_usdc": b.get("size_usdc") or b.get("bet_size"),
            "mode": "paper",
            "source": "backfill_bets",
            "ts": opened_at,
        })

    for pid, p in closes:
        append_event({
            "event_type": "BET_CLOSE",
            "position_id": pid,
            "market_slug": p.get("market_slug"),
            "token_id": p.get("token_id"),
            "closed_at": p.get("last_updated") or p.get("date_opened"),
            "exit_price": p.get("current_mid"),
            "realized_pnl_usd": p.get("pnl_usd"),
            "result": p.get("status"),
            "mode": p.get("mode", "paper"),
            "source": "backfill_positions",
            "ts": p.get("last_updated") or p.get("date_opened"),
        })

    print("backfill done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

