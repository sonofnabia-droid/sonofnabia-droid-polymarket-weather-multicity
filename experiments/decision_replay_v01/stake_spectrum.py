#!/usr/bin/env python3
"""Exploratory price-band stake simulation from existing Cassiopeia tick logs.

READ ONLY: reads JSONL ticks, active config and winner cache; writes only this
experiment's CSV/Markdown outputs. Simulated book walking is not a fill record.
"""
from __future__ import annotations

import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TICKS = ROOT / "live_bot_logs" / "ticks"
START, END = date(2026, 11, 10), date(2026, 11, 16)
FEE_RATE_WEATHER_TAKER = 0.05
BANDS = [(0.35, 0.50, 1.0, "35–<50¢"), (0.50, 0.60, 2.0, "50–<60¢"),
         (0.60, 0.75, 3.0, "60–<75¢"), (0.75, 0.90 + 1e-9, 4.0, "75–90¢")]


def city_slug(city: str, day: date) -> str:
    month = day.strftime("%B").lower()
    return f"highest-temperature-in-{city.replace('_', '-')}-on-{month}-{day.day}-{day.year}"


def temp_key(label: str | None) -> float | None:
    if not label:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", label)
    return float(m.group()) if m else None


def find_band(price: float):
    for lo, hi, stake, label in BANDS:
        if lo <= price < hi:
            return lo, hi, stake, label
    return None


def reason_p(action: dict) -> float | None:
    m = re.search(r"p_rebound=([0-9.]+)", str(action.get("reason", "")))
    return float(m.group(1)) if m else None


def market_target_is_clob(row: dict) -> bool:
    target = row.get("target_bracket") or {}
    return any(x.get("label") == target.get("label") and x.get("src") == "clob"
               for x in row.get("market_full") or [])


def simulate_book(asks: list, budget: float, price_cap: float, won: bool) -> dict:
    left, cost, shares, fee = budget, 0.0, 0.0, 0.0
    fills = []
    for level in asks:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price, available = float(level[0]), float(level[1])
        if price > price_cap + 1e-9 or price <= 0 or available <= 0 or left <= 1e-10:
            continue
        qty = min(available, left / price)
        notional = qty * price
        if qty <= 0:
            continue
        shares += qty
        cost += notional
        fee += qty * FEE_RATE_WEATHER_TAKER * price * (1 - price)
        left -= notional
        fills.append((price, qty))
    payout = shares if won else 0.0
    gross = payout - cost
    return {"budget": budget, "spent": cost, "unspent": max(0.0, left),
            "shares": shares, "fee": fee, "gross_pnl": gross,
            "taker_net_pnl": gross - fee, "fill_ratio": cost / budget if budget else 0,
            "vwap": cost / shares if shares else None, "levels_used": len(fills)}


def event_stats(rows: list[dict], pnl_field: str, invest_field: str) -> dict:
    if not rows:
        return {}
    pnls = [r[pnl_field] for r in rows]
    invested = sum(r[invest_field] for r in rows)
    spent_total = sum(r["spent"] for r in rows)
    wins = sum(r["won"] for r in rows)
    pos = sum(x for x in pnls if x > 1e-12)
    neg = -sum(x for x in pnls if x < -1e-12)
    day_pnl = defaultdict(float)
    day_invest = defaultdict(float)
    city_pnl = defaultdict(float)
    for r in rows:
        day_pnl[r["date"]] += r[pnl_field]
        day_invest[r["date"]] += r[invest_field]
        city_pnl[r["city"]] += r[pnl_field]
    days = sorted(day_pnl)
    daily_returns = [day_pnl[d] / day_invest[d] for d in days if day_invest[d] > 0]
    mean_r = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    sd = math.sqrt(sum((x - mean_r) ** 2 for x in daily_returns) / (len(daily_returns) - 1)) if len(daily_returns) > 1 else 0.0
    downside = math.sqrt(sum(min(0.0, x) ** 2 for x in daily_returns) / len(daily_returns)) if daily_returns else 0.0
    sharpe = mean_r / sd * math.sqrt(252) if sd > 0 else None
    sortino = mean_r / downside * math.sqrt(252) if downside > 0 else None
    equity, peak, maxdd = 100.0, 100.0, 0.0
    for d in days:
        equity += day_pnl[d]
        peak = max(peak, equity)
        maxdd = max(maxdd, peak - equity)
    return {"n": len(rows), "cities": len(set(r["city"] for r in rows)), "days": len(days),
            "wins": wins, "hit_pct": 100 * wins / len(rows),
            "trade_profit_pct": 100 * sum(x > 1e-12 for x in pnls) / len(rows),
            "total_staked": invested, "total_spent": spent_total,
            "pnl": sum(pnls), "roi_spent_pct": 100 * sum(pnls) / max(1e-12, spent_total),
            "profit_factor": pos / neg if neg > 0 else None, "maxdd_dollars_100": maxdd,
            "maxdd_pct_100": 100 * maxdd / 100.0, "sharpe_ann": sharpe, "sortino_ann": sortino,
            "positive_days_pct": 100 * sum(v > 1e-12 for v in day_pnl.values()) / len(day_pnl),
            "day_pnl": dict(day_pnl), "city_pnl": dict(city_pnl)}


def bootstrap_delta(fixed_rows, curve_rows, n=10000):
    a, b = defaultdict(float), defaultdict(float)
    for r in fixed_rows:
        a[r["date"]] += r["taker_net_pnl"]
    for r in curve_rows:
        b[r["date"]] += r["taker_net_pnl"]
    days = sorted(set(a) & set(b))
    diffs = [b[d] - a[d] for d in days]
    if len(diffs) < 2:
        return len(days), None, None
    rng = random.Random(20261116)
    draws = sorted(sum(rng.choice(diffs) for _ in diffs) for __ in range(n))
    return len(days), draws[int(.025 * n)], draws[int(.975 * n)]


def main():
    cfg = json.loads((ROOT / "cassiopeia_active_config.json").read_text())
    winners = json.loads((ROOT / "live_bot_logs" / "market_winners.json").read_text())
    counters = Counter()
    candidates = defaultdict(list)
    for path in sorted(TICKS.glob("ticks_*_2026-11-*.jsonl")):
        m = re.fullmatch(r"ticks_(.+)_(2026-11-\d\d)\.jsonl", path.name)
        if not m:
            continue
        city, day_s = m.groups()
        day = date.fromisoformat(day_s)
        if not START <= day <= END:
            continue
        counters["files"] += 1
        with path.open(encoding="utf-8") as f:
            for line in f:
                counters["raw_jsonl_lines"] += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    counters["malformed_or_incomplete_jsonl"] += 1
                    continue
                acts = [a for a in row.get("actions") or [] if a.get("strategy") == "cassiopeia" and reason_p(a) is not None]
                if not acts:
                    continue
                counters["action_ticks"] += 1
                target = row.get("target_bracket") or {}
                book = row.get("target_book") or {}
                if not market_target_is_clob(row):
                    counters["no_clob_target"] += 1
                    continue
                asks = book.get("asks") or []
                bids = book.get("bids") or []
                if not asks:
                    counters["no_ask_ladder"] += 1
                    continue
                best_ask = float(asks[0][0])
                best_bid = float(bids[0][0]) if bids else None
                band = find_band(best_ask)
                if not band:
                    counters["outside_spectrum"] += 1
                    continue
                # Require the book best ask to agree with the target quote closely.
                target_ask = target.get("ask")
                if target_ask is None or abs(float(target_ask) - best_ask) > 0.011:
                    counters["book_quote_mismatch"] += 1
                    continue
                # Contract outcome from local winner cache; market key and target bracket are not a verified official source.
                outcome = winners.get(city_slug(city, day), {})
                if not outcome.get("resolved") or len(outcome.get("winners") or []) != 1:
                    counters["no_unique_cached_outcome"] += 1
                    continue
                winner_temp = temp_key(outcome["winners"][0])
                target_temp = temp_key(target.get("label"))
                if winner_temp is None or target_temp is None:
                    counters["unparsed_label"] += 1
                    continue
                lo, hi, curve_stake, band_name = band
                active = cfg.get(city, {})
                min_ask = float(active.get("min_buy_ask", 0.60))
                max_ask = float(active.get("max_buy_ask", 0.85))
                record = {"city": city, "date": day_s, "time": row.get("city_local_hhmm"),
                          "ts": row.get("ts"), "target": target.get("label"),
                          "price": best_ask, "bid": best_bid, "spread": best_ask-best_bid if best_bid is not None else None,
                          "band": band_name, "curve_stake": curve_stake, "min_active": min_ask,
                          "max_active": max_ask, "current_eligible": min_ask <= best_ask <= max_ask,
                          "p_rebound": reason_p(acts[0]), "won": winner_temp == target_temp,
                          "winner_cache_label": outcome["winners"][0], "asks": asks,
                          "ask_depth_usdc": book.get("ask_depth_usdc"), "target_src": "clob"}
                candidates[(city, day_s)].append(record)
                counters["candidate_ticks_qualified"] += 1
    # One first entry candidate per city-day and per arm.
    all_rows, current_rows = [], []
    for key, rows in candidates.items():
        rows.sort(key=lambda r: (r["ts"] or "", r["time"] or ""))
        first = rows[0]
        all_rows.append(first)
        eligible = [r for r in rows if r["current_eligible"]]
        if eligible:
            current_rows.append(eligible[0])
    all_rows.sort(key=lambda r: (r["date"], r["ts"], r["city"]))
    current_rows.sort(key=lambda r: (r["date"], r["ts"], r["city"]))
    early_displaces = []
    current_by_key = {(r["city"], r["date"]): r for r in current_rows}
    first_by_key = {(r["city"], r["date"]): r for r in all_rows}
    for key, early in first_by_key.items():
        later = current_by_key.get(key)
        if later and (early["ts"] or "") < (later["ts"] or ""):
            early_displaces.append((early, later))
    early_loss_late_win = sum((not a["won"]) and b["won"] for a, b in early_displaces)
    early_win_late_loss = sum(a["won"] and (not b["won"]) for a, b in early_displaces)

    def scenario(rows, stake_mode):
        out = []
        for r in rows:
            stake = 1.0 if stake_mode == "flat1" else r["curve_stake"]
            _, hi, _, _ = next(b for b in BANDS if b[3] == r["band"])
            sim = simulate_book(r["asks"], stake, hi, r["won"])
            out.append({**{k: v for k, v in r.items() if k != "asks"},
                        "stake": stake, "spent": sim["spent"], "unspent": sim["unspent"],
                        "shares": sim["shares"], "vwap": sim["vwap"],
                        "fill_ratio": sim["fill_ratio"], "levels_used": sim["levels_used"],
                        "gross_pnl": sim["gross_pnl"], "fee_taker": sim["fee"],
                        "taker_net_pnl": sim["taker_net_pnl"],
                        "positive_gross": sim["gross_pnl"] > 1e-12,
                        "positive_net": sim["taker_net_pnl"] > 1e-12})
        return out

    all_flat, all_curve = scenario(all_rows, "flat1"), scenario(all_rows, "curve")
    current_flat, current_curve = scenario(current_rows, "flat1"), scenario(current_rows, "curve")
    out_csv = OUT / "stake_spectrum_events.csv"
    fields = ["arm", "city", "date", "time", "ts", "target", "winner_cache_label", "won", "price", "bid", "spread", "band", "min_active", "max_active", "current_eligible", "p_rebound", "stake", "spent", "unspent", "shares", "vwap", "ask_depth_usdc", "fill_ratio", "levels_used", "gross_pnl", "fee_taker", "taker_net_pnl", "positive_gross", "positive_net"]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for arm, rows in [("spectrum_flat1", all_flat), ("spectrum_curve", all_curve),
                          ("current_gate_flat1", current_flat), ("current_gate_curve", current_curve)]:
            for r in rows:
                w.writerow({k: r.get(k) for k in fields} | {"arm": arm})

    summaries = {
        "spectrum_flat1": (all_flat, "taker_net_pnl"),
        "spectrum_curve": (all_curve, "taker_net_pnl"),
        "current_gate_flat1": (current_flat, "taker_net_pnl"),
        "current_gate_curve": (current_curve, "taker_net_pnl"),
    }
    lines = ["# Stake spectrum diagnostic — price bands 35–90¢", "",
             "**READ-ONLY historical simulation.** Reads Cassiopeia tick JSONL, `cassiopeia_active_config.json` and `market_winners.json`; only this experiment directory is written. No orders, bots, services, SQLite or source data changed.", "",
             "## Pre-registered hypothetical schedule", "",
             "| Best ask CLOB | Stake per signal |", "|---:|---:|",
             "| 35–<50¢ | $1 |", "| 50–<60¢ | $2 |", "| 60–<75¢ | $3 |", "| 75–90¢ | $4 |", "",
             "## Dataset filters and execution caveat", "",
             f"Dates scanned: {START}–{END}. Parsed {counters['raw_jsonl_lines'] - counters['malformed_or_incomplete_jsonl']} of {counters['raw_jsonl_lines']} JSONL lines; {counters['malformed_or_incomplete_jsonl']} malformed/incomplete lines were skipped. Action ticks with a Cassiopeia `p_rebound` reason were filtered to target market source CLOB, non-empty target ask ladder, target quote/book best ask within 1.1¢, best ask in [35¢,90¢], and one unique resolved winner in the local cache. One earliest qualifying candidate per city-day. Qualified candidate ticks before dedup: {counters['candidate_ticks_qualified']}; unique city-days: {len(all_rows)}; cities: {len(set(r['city'] for r in all_rows))}; dates: {len(set(r['date'] for r in all_rows))}.",
             "The bot allows one entry per city/day. The `spectrum_*` arms enter once at the first Cassiopeia signal whose CLOB ask falls in [35¢,90¢]; the $1-flat and banded-stake arms use this exact same first entry. They never add a later purchase, so an early low-price entry can displace a later high-price confirmation. The `current_gate_*` arms instead select the first signal that passes the active per-city min/max. These are competing path policies, not positions that can all be held together.",
             "The order-book walk consumes displayed asks up to the band's upper boundary and stake budget. This is a snapshot-depth upper bound, not a fill; book age, queue, latency, cancellation, market impact, settlement-source correctness and outcome-cache provenance remain unverified. P&L shown after fee assumes taker fee 5% for Weather; actual maker/taker treatment may differ by execution. No-fee gross is also included in CSV.",
             "Labels come from local `market_winners.json`, not an independent audit of official settlement. Nov 16 is included only if the cache reports one resolved winner.", "",
             "## Entry timing and displaced later opportunities", "",
             f"Among {len(all_rows)} city-days with a qualifying 35–90¢ spectrum candidate, {sum(not r['current_eligible'] for r in all_rows)} first entries were below the current city min or otherwise outside the active band. In {len(early_displaces)} city-days a later candidate did pass the current gate; the current-gate arm takes that later signal, while the spectrum arm is already committed to its first entry. Outcomes in those paired paths: early loss/later win {early_loss_late_win}; early win/later loss {early_win_late_loss}. The event CSV has separate records for both paths.", "",
             "## Aggregate results", "",
             "All P&L metrics below use simulated top-five ask ladder VWAP and taker-fee scenario. Percent positive is per contract (net P&L > 0). Sharpe/Sortino annualize daily P&L divided by that day's deployed stake with √252; the short sample makes them unstable and non-predictive. Drawdown assumes $100 starting equity and additive, fixed stakes, no compounding.", "",
             "| Arm | n | cities | dates | wins | hit % | profitable contracts % | invested $ | net P&L $ | ROI on spent % | profit factor | positive days % | MaxDD $ (from $100) | Sharpe | Sortino |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, (rows, field) in summaries.items():
        s = event_stats(rows, field, "stake")
        def v(x, n=2): return "—" if x is None else f"{x:.{n}f}"
        lines.append(f"| {name} | {s.get('n',0)} | {s.get('cities',0)} | {s.get('days',0)} | {s.get('wins',0)} | {v(s.get('hit_pct'))} | {v(s.get('trade_profit_pct'))} | {v(s.get('total_staked'))} | {v(s.get('pnl'))} | {v(s.get('roi_spent_pct'))} | {v(s.get('profit_factor'))} | {v(s.get('positive_days_pct'))} | {v(s.get('maxdd_dollars_100'))} | {v(s.get('sharpe_ann'))} | {v(s.get('sortino_ann'))} |")
    n_days, ci_lo, ci_hi = bootstrap_delta(all_flat, all_curve)
    lines += ["", f"Paired day-cluster bootstrap (10,000 draws, seed 20261116) for curve minus flat-$1 taker-net P&L in the full 35–90¢ spectrum: {n_days} shared event dates; 95% percentile interval [{ci_lo:.2f}, {ci_hi:.2f}] USD." if ci_lo is not None else "Paired day bootstrap unavailable: fewer than two shared event dates.", "",
              "## Results by price band", "", "| Band | n | cities | wins | hit % | curve stake | gross P&L $ | taker fee $ | net P&L $ | profitable contracts % | median ask depth $ | full scheduled stake visible |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for _, _, stake, band_name in BANDS:
        rs = [r for r in all_curve if r["band"] == band_name]
        n = len(rs)
        depths = sorted(float(r["ask_depth_usdc"] or 0) for r in rs)
        med = depths[len(depths)//2] if depths else None
        s = event_stats(rs, "taker_net_pnl", "stake")
        full = sum(r["fill_ratio"] >= 0.999 for r in rs)
        med_text = f"{med:.2f}" if med is not None else "—"
        lines.append(f"| {band_name} | {n} | {s.get('cities',0)} | {s.get('wins',0)} | {s.get('hit_pct',0):.1f} | ${stake:.0f} | {sum(r['gross_pnl'] for r in rs):.2f} | {sum(r['fee_taker'] for r in rs):.3f} | {sum(r['taker_net_pnl'] for r in rs):.2f} | {s.get('trade_profit_pct',0):.1f} | {med_text} | {full}/{n} |")
    lines += ["", "## Per-city table", "", "O CSV contém cada cidade-dia e os quatro braços; não promover cidades por desempenho nesta amostra curta.", "", "| Cidade | candidatos 35–90¢ | wins | preço mediano | curva gross $ | curva fee-net $ | atuais elegíveis | current-gate curve net $ |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    cities = sorted(set(r['city'] for r in all_curve))
    for city in cities:
        rs = [r for r in all_curve if r['city'] == city]
        cr = [r for r in current_curve if r['city'] == city]
        prices = sorted(r['price'] for r in rs)
        medp = prices[len(prices)//2]
        lines.append(f"| {city} | {len(rs)} | {sum(r['won'] for r in rs)} | {medp*100:.1f}¢ | {sum(r['gross_pnl'] for r in rs):.2f} | {sum(r['taker_net_pnl'] for r in rs):.2f} | {len(cr)} | {sum(r['taker_net_pnl'] for r in cr):.2f} |")
    lines += ["", "## Interpretation limits", "", "- Este resultado testa uma regra hipotética de stake e, no braço amplo, também a inclusão contrafactual de sinais abaixo do mínimo atualmente ativo; não é validação prospectiva nem recomendação de alteração.",
              "- O `p_rebound` é guardado no motivo da ação, mas continua a prever rebound de temperatura, não probabilidade calibrada da bracket final. Esta experiência não usa `p_rebound` como `p_win`; apenas toma os sinais existentes como universo de candidatos.",
              "- Um snapshot com depth suficiente não garante execução, e a taxa de taker é cenário conservador de fee, não prova do tipo de execução do PAPER.",
              "- A amostra é pequena, multi-cidade e possivelmente dependente; os dias do holdout já foram vistos. Sharpe/Sortino não validam edge com poucos dias.",
              "- Próximo teste confirmatório: nova janela intocada e PAPER prospectivo, com labels oficiais auditados, bid/ask/depth frescos, fills, fees reais, capital total simultaneamente exposto e bootstrap agrupado por data.", ""]
    (OUT / "STAKE_SPECTRUM_DIAGNOSTIC.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_csv.name} ({len(all_rows)} spectrum and {len(current_rows)} current-gate city-days) and STAKE_SPECTRUM_DIAGNOSTIC.md")
    print("Excluded/action counters:", json.dumps(counters, sort_keys=True))


if __name__ == "__main__":
    main()
