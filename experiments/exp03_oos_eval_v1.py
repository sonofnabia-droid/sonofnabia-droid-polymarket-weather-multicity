#!/usr/bin/env python3
"""EXP03 OOS v1 — avaliação meteorológica isolada, sem trading."""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit, logit
from sklearn.metrics import (
    roc_auc_score,
    brier_score_loss,
    log_loss,
)

from cities.config import get_city
from cassiopeia_train import load_csv
from cassiopeia_train_metar_exp03 import build, FEATURES

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "experiments/exp03_calibration_full_20261113_v2"


def evaluate(city):
    folder = MODELS / city

    report = json.loads(
        (folder / "selection_report.json").read_text()
    )

    if not report.get("experimental_only"):
        raise RuntimeError("Modelo não identificado como experimental")

    if report.get("test_period_used") is not False:
        raise RuntimeError("O período de teste já foi utilizado")

    if report["features"] != FEATURES:
        raise RuntimeError("Features incompatíveis")

    model = joblib.load(folder / "experimental_lgbm.pkl")

    if model.feature_name() != FEATURES:
        raise RuntimeError("Features do modelo incompatíveis")

    df = load_csv(
        ROOT / "historic_metar" / f"{city}.csv",
        city_name=city,
    )

    # Preservar histórico anterior e incluir todo o ano local de 2025.
    # Excluir integralmente 2026 no calendário local da cidade.
    ts = pd.to_datetime(
        df["timestamp_utc"],
        utc=True,
        errors="coerce",
    )

    from zoneinfo import ZoneInfo

    local_ts = ts.dt.tz_convert(
        ZoneInfo(get_city(city).timezone)
    )

    df = df.loc[
        local_ts.dt.year <= 2025
    ].copy()

    data, discarded = build(df, get_city(city))

    dates = pd.to_datetime(data["date"])

    train = data.loc[
        dates < pd.Timestamp("2023-01-01")
    ]

    test = data.loc[
        (dates >= pd.Timestamp("2025-01-01"))
        & (dates < pd.Timestamp("2026-01-01"))
    ]

    if len(train) < 200 or len(test) < 200:
        raise RuntimeError("Amostras insuficientes")

    y = test["label"].astype(int).to_numpy()

    if len(np.unique(y)) < 2:
        raise RuntimeError("Teste sem ambas as classes")

    X = test[FEATURES].astype(np.float32).to_numpy()

    original = np.clip(
        model.predict(
            X,
            num_iteration=report["best_iteration"],
        ),
        1e-7,
        1 - 1e-7,
    )

    method = report["selected_method"]

    if method == "Original":
        selected = original

    elif method == "Platt":
        a = report["platt"]["a"]
        b = report["platt"]["b"]
        selected = expit(a * logit(original) + b)

    elif method == "Isotonic":
        calibrator = joblib.load(
            folder / "experimental_isotonic.pkl"
        )
        selected = calibrator.predict(original)

    else:
        raise RuntimeError(f"Método desconhecido: {method}")

    baseline_rate = float(train["label"].mean())

    def metrics(p):
        p = np.clip(np.asarray(p), 1e-7, 1 - 1e-7)
        return {
            "brier": float(brier_score_loss(y, p)),
            "logloss": float(log_loss(y, p, labels=[0, 1])),
            "auc": float(roc_auc_score(y, p)),
        }

    baseline = np.full(len(y), baseline_rate)

    return {
        "city": city,
        "period": "2025",
        "samples": len(y),
        "positive_rate": float(y.mean()),
        "train_baseline_rate": baseline_rate,
        "selected_method": method,
        "original": metrics(original),
        "selected": metrics(selected),
        "baseline": metrics(baseline),
        "discarded": discarded,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument(
        "--cities",
        nargs="+",
        default=["munich", "shenzhen", "sao_paulo"],
    )
    args = parser.parse_args()

    print("EXP03-OOS v1")
    print("Cidades:", ", ".join(args.cities))
    print("Período: 2025")
    print("Sem treino, trading ou alterações aos modelos")

    if not args.run:
        print("PREFLIGHT: acrescentar --run para avaliar")
        return

    results = []

    for city in args.cities:
        print(f"\n=== {city.upper()} ===", flush=True)
        result = evaluate(city)
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)

    print("\n=== RESUMO ===")
    for result in results:
        print(
            result["city"],
            "n=", result["samples"],
            "method=", result["selected_method"],
            "brier=", round(result["selected"]["brier"], 5),
            "baseline=", round(result["baseline"]["brier"], 5),
        )


if __name__ == "__main__":
    main()
