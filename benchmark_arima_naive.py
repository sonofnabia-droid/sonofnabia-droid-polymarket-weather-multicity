#!/usr/bin/env python3
"""
Benchmark simples para previsão de temperatura máxima diária e P/L simulado.

Modelos:
  - naive (y_t = y_{t-1})
  - seasonal_naive (y_t = y_{t-7})
  - arima (ordem configurável; requer statsmodels)

Exemplo:
  python benchmark_arima_naive.py --city miami --test-days 365 --bet-size 100
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.arima.model import ARIMA  # type: ignore
    HAS_STATSMODELS = True
except Exception:
    HAS_STATSMODELS = False


@dataclass
class EvalRow:
    model: str
    n: int
    mae: float
    rmse: float
    hit_exact_pct: float
    hit_pm1_pct: float
    winnings: float
    losses: float
    net_pl: float


def load_daily_max(city: str) -> pd.Series:
    path = Path("historic") / f"{city}.csv"
    if not path.exists():
        raise FileNotFoundError(f"CSV não encontrado: {path}")

    df = pd.read_csv(path)
    if "date" not in df.columns or "temp_c" not in df.columns:
        raise ValueError(f"{path} sem colunas esperadas: date,temp_c")

    # Formato atual: dd/mm/yyyy.
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df["temp_c"] = pd.to_numeric(df["temp_c"], errors="coerce")
    df = df.dropna(subset=["date", "temp_c"])

    daily_max = df.groupby("date", as_index=True)["temp_c"].max().sort_index()
    daily_max = daily_max[~daily_max.index.duplicated(keep="last")]
    return daily_max.astype(float)


def predict_naive(train: pd.Series) -> float:
    return float(train.iloc[-1])


def predict_seasonal_naive(train: pd.Series, season: int = 7) -> float:
    if len(train) >= season:
        return float(train.iloc[-season])
    return float(train.iloc[-1])


def predict_arima(train: pd.Series, order: tuple[int, int, int]) -> float:
    model = ARIMA(train.values, order=order)
    fit = model.fit()
    pred = fit.forecast(steps=1)
    return float(pred[0])


def simulated_trade_pl(
    y_true: float,
    y_pred: float,
    train_history: pd.Series,
    bet_size: float,
    min_price: float = 0.02,
    max_price: float = 0.95,
) -> float:
    """
    Simula uma compra de YES no bracket de temperatura arredondada ao inteiro.
    Preço sintético = probabilidade empírica histórica desse inteiro no train.
    """
    pred_bin = int(round(y_pred))
    true_bin = int(round(y_true))

    hist_bins = train_history.round().astype(int)
    p_emp = float((hist_bins == pred_bin).mean()) if len(hist_bins) else 0.1
    ask = float(np.clip(p_emp, min_price, max_price))

    shares = bet_size / ask
    payoff = shares if pred_bin == true_bin else 0.0
    pnl = payoff - bet_size
    return float(pnl)


def run_walk_forward(
    series: pd.Series,
    model_name: str,
    pred_fn: Callable[[pd.Series], float],
    test_days: int,
    min_train_days: int,
    bet_size: float,
) -> EvalRow:
    if len(series) < min_train_days + test_days + 1:
        raise ValueError(
            f"Série curta ({len(series)} dias). Precisa >= {min_train_days + test_days + 1}."
        )

    start = len(series) - test_days
    y_true, y_pred, pnl_list = [], [], []

    for i in range(start, len(series)):
        train = series.iloc[:i]
        true_val = float(series.iloc[i])
        pred_val = float(pred_fn(train))

        y_true.append(true_val)
        y_pred.append(pred_val)
        pnl_list.append(simulated_trade_pl(true_val, pred_val, train, bet_size=bet_size))

    yt = np.array(y_true)
    yp = np.array(y_pred)
    pnl = np.array(pnl_list)

    mae = float(np.mean(np.abs(yt - yp)))
    rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))
    hit_exact = float(np.mean(np.round(yt) == np.round(yp)) * 100.0)
    hit_pm1 = float(np.mean(np.abs(np.round(yt) - np.round(yp)) <= 1.0) * 100.0)

    winnings = float(pnl[pnl > 0].sum()) if np.any(pnl > 0) else 0.0
    losses = float(-pnl[pnl < 0].sum()) if np.any(pnl < 0) else 0.0
    net = float(pnl.sum())

    return EvalRow(
        model=model_name,
        n=len(yt),
        mae=mae,
        rmse=rmse,
        hit_exact_pct=hit_exact,
        hit_pm1_pct=hit_pm1,
        winnings=winnings,
        losses=losses,
        net_pl=net,
    )


def print_table(rows: list[EvalRow]) -> None:
    print(
        f"{'Model':16} {'N':>5} {'MAE':>7} {'RMSE':>7} "
        f"{'HitExact%':>10} {'Hit±1%':>8} {'Winnings':>11} {'Losses':>10} {'NetP/L':>10}"
    )
    print("-" * 96)
    for r in rows:
        print(
            f"{r.model:16} {r.n:5d} {r.mae:7.3f} {r.rmse:7.3f} "
            f"{r.hit_exact_pct:10.2f} {r.hit_pm1_pct:8.2f} "
            f"{r.winnings:11.2f} {r.losses:10.2f} {r.net_pl:10.2f}"
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark Naive/ARIMA para temperatura diária.")
    p.add_argument("--city", required=True, help="Cidade (nome do CSV em historic/<city>.csv)")
    p.add_argument("--test-days", type=int, default=365, help="Dias no bloco de teste walk-forward")
    p.add_argument("--min-train-days", type=int, default=730, help="Dias mínimos de treino inicial")
    p.add_argument("--bet-size", type=float, default=100.0, help="Stake por trade no P/L simulado")
    p.add_argument("--arima-order", type=str, default="2,1,2", help="Ordem ARIMA p,d,q")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    series = load_daily_max(args.city)

    p, d, q = [int(x.strip()) for x in args.arima_order.split(",")]
    order = (p, d, q)

    rows: list[EvalRow] = []
    rows.append(
        run_walk_forward(
            series, "Naive", predict_naive,
            test_days=args.test_days,
            min_train_days=args.min_train_days,
            bet_size=args.bet_size,
        )
    )
    rows.append(
        run_walk_forward(
            series, "SeasonalNaive(7)",
            lambda tr: predict_seasonal_naive(tr, 7),
            test_days=args.test_days,
            min_train_days=args.min_train_days,
            bet_size=args.bet_size,
        )
    )

    if HAS_STATSMODELS:
        rows.append(
            run_walk_forward(
                series, f"ARIMA{order}",
                lambda tr: predict_arima(tr, order=order),
                test_days=args.test_days,
                min_train_days=args.min_train_days,
                bet_size=args.bet_size,
            )
        )
    else:
        print("Aviso: statsmodels não instalado; ARIMA omitido.")

    rows = sorted(rows, key=lambda r: r.net_pl, reverse=True)
    print(f"\nCity: {args.city} | Daily points: {len(series)} | Test days: {args.test_days}\n")
    print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
