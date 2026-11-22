#!/usr/bin/env python3
"""Build a static, read-only replay from existing Cassiopeia tick logs."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CASES = {
    "seoul": {"name": "Seoul", "timezone": "Asia/Seoul", "station": "RKSI", "settlement": "Routine METAR T remarks; whole °C rounding per archived market metadata."},
    "panama_city": {"name": "Panama City", "timezone": "America/Panama", "station": "MPMG", "settlement": "Routine METAR T remarks; whole °C rounding per archived market metadata."},
}


def p_rebound(row: dict) -> float | None:
    for action in row.get("actions") or []:
        reason = str(action.get("reason", ""))
        marker = "p_rebound="
        if marker in reason:
            try:
                return float(reason.split(marker, 1)[1].split()[0])
            except (ValueError, IndexError):
                pass
    return None


def load_city(city: str) -> list[dict]:
    path = ROOT / "live_bot_logs" / "ticks" / f"ticks_{city}_2026-11-16.jsonl"
    rows = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            raw = json.loads(line)
            target = raw.get("target_bracket") or {}
            book = raw.get("target_book") or {}
            actions = raw.get("actions") or []
            rows.append({
                "time": raw.get("city_local_hhmm"),
                "ts_utc": raw.get("ts"),
                "temp": raw.get("temp_now"),
                "rmax": raw.get("running_max"),
                "target": target.get("label"),
                "ask": target.get("ask"),
                "bid": target.get("bid"),
                "p_ensemble": raw.get("p_ensemble"),
                "p_rebound": p_rebound(raw),
                "threshold": raw.get("threshold"),
                "ask_depth_usdc": book.get("ask_depth_usdc"),
                "bid_depth_usdc": book.get("bid_depth_usdc"),
                "asks": book.get("asks") or [],
                "bids": book.get("bids") or [],
                "market_src": next((x.get("src") for x in raw.get("market_full", []) if x.get("label") == target.get("label")), None),
                "actions": [a.get("reason", "") for a in actions],
            })
    return rows


def main() -> None:
    payload = {city: {**meta, "rows": load_city(city)} for city, meta in CASES.items()}
    payload["notes"] = {
        "scope": "Existing bot tick logs only; no SQLite writes, downloads, or live-system access.",
        "p_rebound": "Only recoverable from action reason strings. Missing values are unknown, not zero. p_ensemble is a distinct display/model field.",
        "quote": "A logged top-of-book snapshot is not proof of a fill. Gamma-sourced prices are not CLOB asks. Depth is logged top-five aggregate when present.",
        "outcome": "Official Nov 16 winner was not present in the inspected winner cache at audit time. Dashboard RESOLVED label can be a price heuristic and is not proof of settlement.",
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    template = (OUT / "template.html").read_text(encoding="utf-8")
    (OUT / "index.html").write_text(template.replace("__DATA__", data), encoding="utf-8")
    print(f"Wrote {OUT / 'index.html'} from {sum(len(payload[c]['rows']) for c in CASES)} logged ticks.")


if __name__ == "__main__":
    main()
