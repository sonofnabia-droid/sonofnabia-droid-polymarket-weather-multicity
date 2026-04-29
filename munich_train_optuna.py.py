"""
munich_train_optuna.py — Otimização Optuna do modelo Munich Peak

Decisão 2026-04: LightGBM puro. Removido XGBoost e ensemble weights.
Esta versão otimiza apenas os **hiperparâmetros do LightGBM** usando
walk-forward AUC como critério (fora-da-amostra honesto).

Uso:
    python munich_train_optuna.py --n-trials 50
    python munich_train_optuna.py --n-trials 100
"""

import argparse
import json
from pathlib import Path
import warnings

import numpy as np
import optuna
import pandas as pd
import joblib
from rich.console import Console
from sklearn.metrics import roc_auc_score

from munich_config import FEATURE_COLS
from munich_train import load_csv, build_dataset

warnings.filterwarnings("ignore")
_console = Console()

MODEL_DIR = Path("munich_peak_model_optuna")
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════
# WALK-FORWARD AUC (LightGBM puro)
# ══════════════════════════════════════════════════════
def wf_lgbm_auc(
    dataset: pd.DataFrame,
    lgb_params: dict,
    min_train_years: int = 2,
) -> float:
    """
    Walk-forward por ano. Treina em [ano 1, ..., Y-1], testa em ano Y.
    Retorna AUC médio entre folds.
    """
    from lightgbm import LGBMClassifier

    if not pd.api.types.is_datetime64_any_dtype(dataset["date"]):
        dataset = dataset.copy()
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")

    years = sorted(dataset["date"].dt.year.unique())
    if len(years) < min_train_years + 1:
        return 0.5

    aucs = []
    for i in range(min_train_years, len(years)):
        train = dataset[dataset["date"].dt.year.isin(years[:i])]
        val = dataset[dataset["date"].dt.year == years[i]]
        if len(val) == 0 or val["label"].nunique() < 2:
            continue

        X_tr = train[FEATURE_COLS].fillna(0)
        y_tr = train["label"]
        X_val = val[FEATURE_COLS].fillna(0)
        y_val = val["label"]

        model = LGBMClassifier(**lgb_params, random_state=42, verbose=-1)
        model.fit(X_tr, y_tr)
        preds = model.predict_proba(X_val)[:, 1]
        aucs.append(roc_auc_score(y_val, preds))

    return float(np.mean(aucs)) if aucs else 0.5


# ══════════════════════════════════════════════════════
# OBJECTIVE — só hiperparâmetros LightGBM
# ══════════════════════════════════════════════════════
def make_objective(dataset: pd.DataFrame):
    def objective(trial: optuna.Trial) -> float:
        lgb_params = {
            "n_estimators": trial.suggest_int("n_estimators", 200, 900, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.08, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 9),
            "num_leaves": trial.suggest_int("num_leaves", 20, 90, step=2),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 60),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        }
        return wf_lgbm_auc(dataset, lgb_params, min_train_years=2)

    return objective


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-trials", type=int, default=50)
    args = parser.parse_args()

    _console.print("=" * 80)
    _console.print(f"  Munich Peak Model — Optuna ({args.n_trials} trials, LightGBM puro)")
    _console.print("=" * 80)

    _console.print("\n[1/4] Carregando dados...")
    df = load_csv()

    _console.print("\n[2/4] Construindo dataset (via build_features)...")
    result = build_dataset(df)
    dataset = result[0] if isinstance(result, tuple) else result

    _console.print(f"\n[3/4] Otimização Optuna ({args.n_trials} trials, walk-forward AUC)...")
    study = optuna.create_study(direction="maximize", study_name="munich_peak_lgbm")
    objective = make_objective(dataset)
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=True)

    best = study.best_trial
    _console.print(f"\n[bold green]Melhor AUC walk-forward: {best.value:.6f}[/bold green]")
    _console.print("[bold]Melhores hiperparâmetros LightGBM:[/bold]")
    for k, v in best.params.items():
        if isinstance(v, float):
            _console.print(f"  {k}: {v:.6f}")
        else:
            _console.print(f"  {k}: {v}")

    # ── Fit final ───────────────────────────────────
    _console.print("\n[4/4] Fit final no dataset completo...")

    from lightgbm import LGBMClassifier
    final_lgb = LGBMClassifier(**best.params, random_state=42, verbose=-1)
    X = dataset[FEATURE_COLS].fillna(0)
    y = dataset["label"]
    final_lgb.fit(X, y)
    joblib.dump(final_lgb, MODEL_DIR / "lgbm_peak.pkl")

    in_sample_auc = float(roc_auc_score(y, final_lgb.predict_proba(X)[:, 1]))
    _console.print(f"  AUC in-sample: {in_sample_auc:.4f}")
    _console.print(f"  Gap in-sample vs walk-forward: {in_sample_auc - best.value:.4f}")

    # Prior sazonal do próprio dataset
    prior_map = {}
    for (m, h, s), group in dataset.groupby(["month", "hour", "slot30"]):
        prior_map[(m, h, s)] = group["label"].mean()

    config = {
        "feature_cols": FEATURE_COLS,
        "lgb_params": best.params,
        "ensemble_weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
        "model_type": "lightgbm_pure_optuna",
        "global_auc": float(best.value),
        "mean_auc_wf": float(best.value),
        "in_sample_auc": in_sample_auc,
        "best_trial_number": best.number,
        "n_trials": args.n_trials,
        "seasonal_peak_prior": {f"{k[0]}_{k[1]}_{k[2]}": float(v) for k, v in prior_map.items()},
    }
    (MODEL_DIR / "peak_model_config.json").write_text(json.dumps(config, indent=2))

    _console.print(f"\n[green]Modelo Optuna guardado em: {MODEL_DIR}[/green]")
    _console.print(
        "Para usar como modelo principal: copia os ficheiros de "
        "munich_peak_model_optuna/ para munich_peak_model/, "
        "ou corre o backtester com --model optuna."
    )


if __name__ == "__main__":
    main()