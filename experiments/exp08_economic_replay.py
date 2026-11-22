
#!/usr/bin/env python3
"""EXP08: replay económico histórico B/C, sem alterar os modelos."""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from cities.config import get_city
from cassiopeia_backtester import resolve_params, round_half_up
from cassiopeia_train_metar_exp03 import BASE_FEATURES, build_time_features
from experiments.exp04_c180_noprior import train as c
from experiments.exp05.compare_hit_exp07 import (
    load_models,
    prepare_data,
    probability,
)

WINNERS = Path("live_bot_logs/market_winners.json")
QUOTES = Path("ask_collector_data.csv")
OUTPUT = Path("experiments/exp08_results")


def calibrated_probability(name, models, values):
    model, features = models[name]
    p = probability(model, features, values)

    if name == "B" and models["platt"] is not None:
        from scipy.special import expit, logit
        params = models["platt"]
        p = float(expit(
            float(params["a"]) *
            logit(np.clip(p, 1e-12, 1 - 1e-12)) +
            float(params["b"])
        ))

    if name == "B" and models["isotonic"] is not None:
        p = float(np.asarray(
            models["isotonic"].predict([p])
        ).ravel()[0])

    return p


def make_slot(row, ceil_slot):
    h, m = ceil_slot(int(row["_hour"]), int(row["_minute"]))
    temp = float(row["temp_c"])

    return {
        "hour": h,
        "slot30": m,
        "temp_c": temp,
        "cloud_cover": c.number(
            row, "cloud_cover", c.number(row, "sky_cover", 50)
        ),
        "humidity": c.number(
            row, "humidity", c.number(row, "humidity_pct", 70)
        ),
        "dewpoint_c": c.number(
            row, "dewpoint_c", c.number(row, "dewpt_c", temp - 10)
        ),
        "pressure_hpa": c.number(row, "pressure_hpa", 1013),
        "wind_dir_deg": c.number(row, "wind_dir_deg", 0),
        "wind_speed_kmh": c.number(row, "wind_speed_kmh", 5),
        "wind_gust_kmh": c.number(row, "wind_gust_kmh", 8),
        "uv_index": c.number(row, "uv_index", 3),
    }


def market_date_from_slug(slug):
    # Ex.: highest-temperature-in-munich-on-august-31-2026
    try:
        tail = slug.rsplit("-on-", 1)[1]
        return datetime.strptime(tail, "%B-%d-%Y").date()
    except (IndexError, ValueError):
        return None



def bracket_for_target(target, labels):
    """Resolve uma temperatura inteira para a bracket do mercado."""
    target = int(target)
    labels = set(labels)

    exact = f"{target}°C"
    if exact in labels:
        return exact

    matches = []

    for label in labels:
        m = re.fullmatch(
            r"(-?\\d+)°C or (below|higher)",
            str(label).strip(),
            flags=re.IGNORECASE,
        )
        if not m:
            continue

        boundary = int(m.group(1))
        direction = m.group(2).lower()

        if direction == "below" and target <= boundary:
            matches.append(label)
        elif direction == "higher" and target >= boundary:
            matches.append(label)

    return matches[0] if len(matches) == 1 else None


def run(city_name, delay, shares, fee_rate, slippage):
    city = get_city(city_name)
    params = resolve_params(city_name)
    models = load_models(city_name)
    weather = prepare_data(city_name, city)

    # O máximo final de cada dia só é usado para calcular o
    # prior de dias anteriores, nunca para decidir no dia atual.
    daily_max = weather.groupby("_day")["temp_c"].max().to_dict()

    winners = json.loads(WINNERS.read_text())

    quotes = pd.read_csv(
        QUOTES,
        usecols=[
            "ts", "city", "slug", "bracket",
            "best_ask", "ask_depth_usdc",
        ],
    )

    quotes = quotes[quotes["city"] == city_name].copy()
    quotes["quote_ts"] = pd.to_datetime(
        quotes["ts"], format="ISO8601",
        utc=True, errors="coerce",
    )
    quotes["best_ask"] = pd.to_numeric(
        quotes["best_ask"], errors="coerce"
    )
    quotes["ask_depth_usdc"] = pd.to_numeric(
        quotes["ask_depth_usdc"], errors="coerce"
    )

    quotes = quotes[
        quotes["quote_ts"].notna()
        & quotes["best_ask"].between(0.001, 0.999)
        & (quotes["ask_depth_usdc"] > 0)
    ].copy()

    quotes["local_day"] = (
        quotes["quote_ts"].dt.tz_convert(city.timezone).dt.date
    )
    quotes["market_day"] = quotes["slug"].map(market_date_from_slug)

    quotes = quotes[
        quotes["local_day"] == quotes["market_day"]
    ].sort_values("quote_ts")

    ceil_slot = c._get_ceil_slot()
    trades = []
    counters = defaultdict(int)

    for (day, slug), qday in quotes.groupby(
        ["local_day", "slug"], sort=True
    ):
        if day.year != 2026:
            continue

        record = winners.get(slug, {})
        labels = record.get("winners") or []

        if not (
            record.get("resolved") is True
            and len(labels) == 1
        ):
            counters["unconfirmed_market"] += 1
            continue

        winner = labels[0]
        available_brackets = set(qday["bracket"].dropna())

        if winner not in available_brackets:
            counters["winner_missing_from_market"] += 1
            continue

        previous = {
            d: maximum
            for d, maximum in daily_max.items()
            if d < day
        }
        prev7 = c.compute_prev7(previous, day, city.name)

        if prev7 is None or not np.isfinite(prev7):
            counters["missing_prev7"] += 1
            continue

        wday = weather[weather["_day"] == day]
        wday = wday.sort_values("_utc")

        if wday.empty:
            counters["missing_weather"] += 1
            continue

        observations = list(wday.iterrows())
        weather_index = 0
        slots_by_key = {}
        history = []
        entered = {"B": False, "C": False}

        # Uma decisão por timestamp de recolha, com todas
        # as brackets disponíveis nesse instante.
        for quote_ts, snapshot in qday.groupby(
            "quote_ts", sort=True
        ):
            if all(entered.values()):
                break

            cutoff = quote_ts - pd.Timedelta(minutes=delay)

            while weather_index < len(observations):
                _, row = observations[weather_index]

                if row["_utc"] > cutoff:
                    break

                weather_index += 1
                h, m = ceil_slot(
                    int(row["_hour"]), int(row["_minute"])
                )

                if not (city.day_start <= h <= city.day_end):
                    continue

                slot = make_slot(row, ceil_slot)
                slots_by_key[(h, m)] = slot

                history.append({
                    "timestamp_utc": row["_utc"],
                    "temp_c": float(row["temp_c"]),
                    "humidity": slot["humidity"],
                    "slot_hour": h,
                    "slot_minute": m,
                })

            local_ts = quote_ts.tz_convert(city.timezone)
            current_hour = local_ts.hour

            if not (
                int(params["start_hour"])
                <= current_hour
                <= int(params["end_hour"])
            ):
                continue

            if current_hour < 12 or len(slots_by_key) < 4:
                continue

            if not history:
                continue

            last_age = (
                quote_ts - history[-1]["timestamp_utc"]
            ).total_seconds() / 60

            if last_age > 120:
                counters["stale_weather"] += 1
                continue

            slots = [
                slots_by_key[key]
                for key in sorted(slots_by_key)
            ]

            rmax = max(s["temp_c"] for s in slots)
            rmin = min(s["temp_c"] for s in slots)

            if rmax - rmin < float(params["min_spread"]):
                continue

            if rmax > prev7 + float(params["outlier_cap"]):
                continue

            slot = slots_by_key[(history[-1]['slot_hour'], history[-1]['slot_minute'])]
            baseline = c.build_features(
                slots,
                {**slot, "prev_7d_avg_max": prev7},
                day.month,
                day.timetuple().tm_yday,
            )

            # Equivalência EXP07: features temporais avaliadas
            # no timestamp do último METAR disponível.
            # A elegibilidade respeita o atraso configurado.
            timed = build_time_features(history, history[-1]['timestamp_utc'])

            b_values = {
                **{
                    f: baseline.get(f, np.nan)
                    for f in BASE_FEATURES
                },
                **timed,
            }

            target = round_half_up(rmax)
            bracket = bracket_for_target(
                target, available_brackets
            )
            matching = (
                snapshot[snapshot["bracket"] == bracket]
                if bracket is not None
                else snapshot.iloc[0:0]
            )

            for name, values in [
                ("B", b_values),
                ("C", baseline),
            ]:
                if entered[name]:
                    continue

                p = calibrated_probability(name, models, values)

                if not np.isfinite(p):
                    counters["invalid_prediction"] += 1
                    continue

                if p >= float(params["threshold"]):
                    continue

                counters[f"{name}_signals"] += 1

                if bracket is None:
                    counters[f"{name}_bracket_not_in_market"] += 1
                    continue

                if matching.empty:
                    counters[f"{name}_no_ask_for_bracket"] += 1
                    continue

                quote = matching.sort_values(
                    ["best_ask", "ask_depth_usdc"],
                    ascending=[True, False],
                ).iloc[0]

                ask = float(quote["best_ask"])
                depth = float(quote["ask_depth_usdc"])

                # Slippage é um acréscimo absoluto ao preço
                # por share, não uma percentagem.
                execution_price = ask + slippage

                if not 0 < execution_price < 1:
                    counters[f"{name}_invalid_execution"] += 1
                    continue

                if depth < ask * shares:
                    counters[f"{name}_insufficient_depth"] += 1
                    continue

                payout = float(bracket == winner) * shares
                gross_cost = execution_price * shares

                # Fee hipotética proporcional ao notional.
                # Não representa a fórmula oficial de taxas.
                fee = gross_cost * fee_rate
                pnl = payout - gross_cost - fee

                trades.append({
                    "city": city_name,
                    "date": str(day),
                    "slug": slug,
                    "model": name,
                    "quote_ts": quote_ts.isoformat(),
                    "metar_ts": history[-1][
                        "timestamp_utc"
                    ].isoformat(),
                    "metar_age_min": round(last_age, 2),
                    "delay_min": delay,
                    "p_rebound": p,
                    "threshold": float(params["threshold"]),
                    "running_max": rmax,
                    "bracket": bracket,
                    "winner": winner,
                    "ask": ask,
                    "depth_usdc": depth,
                    "shares": shares,
                    "execution_price": execution_price,
                    "gross_cost": gross_cost,
                    "fee_assumed": fee,
                    "payout": payout,
                    "hit": int(bracket == winner),
                    "pnl": pnl,
                })

                entered[name] = True

    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / f"{city_name}_delay{delay}.csv"
    columns = [
        "city", "date", "slug", "model", "quote_ts",
        "metar_ts", "metar_age_min", "delay_min",
        "p_rebound", "threshold", "running_max",
        "bracket", "winner", "ask", "depth_usdc",
        "shares", "execution_price", "gross_cost",
        "fee_assumed", "payout", "hit", "pnl",
    ]
    result = pd.DataFrame(trades, columns=columns)
    result.to_csv(out, index=False)

    print(f"\n=== EXP08 — {city_name.upper()} ===")
    print(f"Atraso METAR: {delay} min")
    print(f"Shares por operação: {shares}")
    print(f"Fee hipotética: {fee_rate:.4%}")
    print(f"Slippage absoluto: {slippage:.4f}")
    print(f"Operações guardadas: {out}")

    for name in ("B", "C"):
        subset = result[result["model"] == name]
        n = len(subset)

        if not n:
            print(f"\n{name}: 0 operações")
            continue

        print(
            f"\n{name}: trades={n}, "
            f"hits={int(subset['hit'].sum())}, "
            f"hit_rate={subset['hit'].mean():.2%}, "
            f"capital_gasto={subset['gross_cost'].sum():.2f}, "
            f"pnl={subset['pnl'].sum():+.2f}, "
            f"roi={subset['pnl'].sum() / (subset['gross_cost'].sum() + subset['fee_assumed'].sum()):+.2%}"
        )

    print("\nCONTADORES:")
    for key, value in sorted(counters.items()):
        print(f"  {key}: {value}")

    print("\nReplay concluído.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="munich")
    parser.add_argument(
        "--delay", type=int, default=30,
        choices=[0, 15, 30, 60],
    )
    parser.add_argument("--shares", type=float, default=1.0)
    parser.add_argument("--fee-rate", type=float, default=0.0)
    parser.add_argument("--slippage", type=float, default=0.0)
    args = parser.parse_args()

    if args.shares <= 0:
        parser.error("--shares deve ser positivo")
    if args.fee_rate < 0 or args.slippage < 0:
        parser.error("Custos não podem ser negativos")

    run(
        args.city,
        args.delay,
        args.shares,
        args.fee_rate,
        args.slippage,
    )


if __name__ == "__main__":
    main()
