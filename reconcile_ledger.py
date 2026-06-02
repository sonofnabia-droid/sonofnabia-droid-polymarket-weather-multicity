#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from trade_ledger import read_events


def day_of(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).date().isoformat()
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconciliar PnL e trades a partir do trade_ledger.jsonl")
    parser.add_argument("--from", dest="date_from", default=None, help="Data inicial YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", default=None, help="Data final YYYY-MM-DD")
    parser.add_argument("--write", action="store_true", help="Escrever resumo reconciliado em live_bot_logs/reconciled_summary.json")
    args = parser.parse_args()

    ev = read_events()
    if args.date_from or args.date_to:
        filtered = []
        for e in ev:
            d = day_of(e.get("ts") or e.get("opened_at") or e.get("closed_at"))
            if not d:
                continue
            if args.date_from and d < args.date_from:
                continue
            if args.date_to and d > args.date_to:
                continue
            filtered.append(e)
        ev = filtered

    opens = {}
    closes = {}
    daily = defaultdict(lambda: {"trades": 0, "realized_pnl": 0.0})

    for e in ev:
        et = e.get("event_type")
        pid = e.get("position_id")
        if et == "BET_OPEN" and pid:
            opens[pid] = e
            d = day_of(e.get("opened_at") or e.get("ts"))
            if d:
                daily[d]["trades"] += 1
        elif et == "BET_CLOSE" and pid:
            closes[pid] = e
            d = day_of(e.get("closed_at") or e.get("ts"))
            pnl = float(e.get("realized_pnl_usd") or 0.0)
            if d:
                daily[d]["realized_pnl"] += pnl

    total_realized = round(sum(float(v["realized_pnl"]) for v in daily.values()), 4)
    out = {
        "events": len(ev),
        "opens": len(opens),
        "closes": len(closes),
        "open_positions": max(0, len(opens) - len(closes)),
        "total_realized_pnl": total_realized,
        "daily": {k: {"trades": v["trades"], "realized_pnl": round(v["realized_pnl"], 4)} for k, v in sorted(daily.items())},
    }

    print(json.dumps(out, indent=2))

    if args.write:
        p = Path("live_bot_logs") / "reconciled_summary.json"
        p.write_text(json.dumps(out, indent=2))
        print(f"\nwritten: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

