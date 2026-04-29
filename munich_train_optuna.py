"""
munich_train_optuna.py — Otimização Optuna do modelo Munich Peak

FIX #9: o Optuna passa a realmente otimizar os weights do ensemble.
Antes sugeria w_lgbm/w_xgb/w_z mas nunca os usava no cálculo do score
— o AUC reportado era só do LightGBM puro. E no final tentava ler de
best.user_attrs.get(...) que nunca era escrito, devolvendo sempre o
default 0.50.

Este ficheiro substitui os dois anteriores (munich_train_optuna.py e
munich_train_optuna_py.py). Usa o novo build_dataset do munich_train.py
(Fix #11) que já normaliza internamente o CSV.

Uso:
    python munich_train_optuna.py --n-trials 50
    python munich_train_optuna.py --n-trials 100 --with-xgb
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
# Z-SCORE offline — replica o comportamento do StreamingPeakDetector
# (necessário para avaliar o ensemble em validação)
# ══════════════════════════════════════════════════════
def _zscore_series(temps: np.ndarray, lookback: int = 24, threshold_z: float = 1.5) -> np.ndarray:
    """
    Aplica o StreamingPeakDetector slot-a-slot a uma série de temperaturas.
    Devolve p_zscore para cada ponto (0.0 nos primeiros <8 pontos).
    """
    from munich_model import StreamingPeakDetector
    det = StreamingPeakDetector(lookback=lookback, threshold_z=threshold_z)
    return np.array([det.update(float(t)) for t in temps], dtype=np.float32)


# ══════════════════════════════════════════════════════
# WALK-FORWARD ENSEMBLE AUC
# ══════════════════════════════════════════════════════
def wf_ensemble_auc(
    dataset: pd.DataFrame,
    lgb_params: dict,
    xgb_params: dict | None,
    w_lgbm: float, w_xgb: float, w_z: float,
    min_train_years: int = 2,
) -> float:
    """
    FIX #9 + #10: walk-forward por ano, e o score é do ENSEMBLE
    (lgbm + xgb + zscore) com os weights sugeridos — não do LGBM puro.

    É isto que permite ao Optuna realmente otimizar os weights.
    """
    from lightgbm import LGBMClassifier

    if not pd.api.types.is_datetime64_any_dtype(dataset["date"]):
        dataset = dataset.copy()
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")

    years = sorted(dataset["date"].dt.year.unique())
    if len(years) < min_train_years + 1:
        return 0.5  # não há dados suficientes

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

        # 1) LGBM
        lgb = LGBMClassifier(**lgb_params, random_state=42, verbose=-1)
        lgb.fit(X_tr, y_tr)
        p_lgbm = lgb.predict_proba(X_val)[:, 1]

        # 2) XGB (opcional)
        p_xgb = None
        if xgb_params is not None:
            try:
                from xgboost import XGBClassifier
                xgb = XGBClassifier(**xgb_params, random_state=42, verbosity=0,
                                    use_label_encoder=False, eval_metric="logloss")
                xgb.fit(X_tr, y_tr)
                p_xgb = xgb.predict_proba(X_val)[:, 1]
            except Exception:
                p_xgb = None

        # 3) Z-score — aplicado POR DIA à temperatura do val
        p_z_vals = []
        for _, day_df in val.sort_values(["date", "hour", "slot30"]).groupby("date"):
            temps = day_df["temp_c"].to_numpy()
            p_z_vals.extend(_zscore_series(temps))
        p_zscore = np.array(p_z_vals, dtype=np.float32)

        # Alinhar tamanho (groupby pode reordenar; reconstituir índice)
        val_sorted = val.sort_values(["date", "hour", "slot30"]).reset_index()
        order_back = val_sorted["index"].to_numpy()
        p_zscore_aligned = np.empty_like(p_zscore)
        p_zscore_aligned[order_back - val.index.min()] = p_zscore

        # 4) Ensemble
        if p_xgb is not None:
            p_ens = w_lgbm * p_lgbm + w_xgb * p_xgb + w_z * p_zscore_aligned
        else:
            # Sem XGB: redistribui o peso dele proporcionalmente
            norm = w_lgbm + w_z
            if norm > 0:
                p_ens = (w_lgbm / norm) * p_lgbm + (w_z / norm) * p_zscore_aligned
            else:
                p_ens = p_lgbm

        p_ens = np.clip(p_ens, 0.0, 1.0)
        aucs.append(roc_auc_score(y_val, p_ens))

    return float(np.mean(aucs)) if aucs else 0.5


# ══════════════════════════════════════════════════════
# OBJECTIVE
# ══════════════════════════════════════════════════════
def make_objective(dataset: pd.DataFrame, with_xgb: bool):
    def objective(trial: optuna.Trial) -> float:
        # LGBM hyperparams
        lgb_params = {
            "n_estimators": trial.suggest_int("n_estimators", 200, 900, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.08, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 9),
            "num_leaves": trial.suggest_int("num_leaves", 20, 90, step=2),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 60),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        }

        # XGB (opcional)
        xgb_params = None
        if with_xgb:
            xgb_params = {
                "n_estimators": trial.suggest_int("xgb_n_estimators", 200, 700, step=50),
                "learning_rate": trial.suggest_float("xgb_learning_rate", 0.01, 0.1, log=True),
                "max_depth": trial.suggest_int("xgb_max_depth", 3, 8),
            }

        # Weights do ensemble — SUGERIDOS E USADOS
        w_lgbm = trial.suggest_float("w_lgbm", 0.35, 0.70)
        if with_xgb:
            w_xgb = trial.suggest_float("w_xgb", 0.15, 0.45)
        else:
            w_xgb = 0.0
        # w_z complementa. Se for negativo (weights somam >1), penalizamos
        # o trial em vez de rejeitar, para o Optuna aprender a região boa.
        w_z = 1.0 - w_lgbm - w_xgb
        if w_z < 0.05:
            # Não rejeitamos: forçamos bounds e deixamos que o AUC caia
            # se os weights não fazem sentido.
            w_z = 0.05
            # Re-normalizar
            tot = w_lgbm + w_xgb + w_z
            w_lgbm /= tot
            w_xgb /= tot
            w_z /= tot

        # Guardar os weights NORMALIZADOS como user_attr para diagnóstico
        trial.set_user_attr("w_lgbm_final", w_lgbm)
        trial.set_user_attr("w_xgb_final", w_xgb)
        trial.set_user_attr("w_z_final", w_z)

        # Walk-forward AUC do ENSEMBLE (Fix #9 principal)
        return wf_ensemble_auc(
            dataset, lgb_params, xgb_params,
            w_lgbm=w_lgbm, w_xgb=w_xgb, w_z=w_z,
            min_train_years=2,
        )

    return objective


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--with-xgb", action="store_true",
                        help="Inclui XGBoost no ensemble (requer xgboost instalado)")
    args = parser.parse_args()

    _console.print("=" * 80)
    _console.print(
        f"  Munich Peak Model — Optuna ({args.n_trials} trials, "
        f"{'com XGB' if args.with_xgb else 'sem XGB'})"
    )
    _console.print("=" * 80)

    _console.print("\n[1/4] Carregando dados...")
    df = load_csv()

    _console.print("\n[2/4] Construindo dataset (via build_features)...")
    result = build_dataset(df)
    dataset = result[0] if isinstance(result, tuple) else result

    _console.print(f"\n[3/4] Otimização Optuna ({args.n_trials} trials)...")
    study = optuna.create_study(direction="maximize", study_name="munich_peak_ensemble")
    objective = make_objective(dataset, with_xgb=args.with_xgb)
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=True)

    best = study.best_trial
    _console.print(f"\n[bold green]Melhor AUC walk-forward: {best.value:.6f}[/bold green]")
    _console.print("[bold]Melhores parâmetros:[/bold]")
    for k, v in best.params.items():
        _console.print(f"  {k}: {v}")

    # FIX #9: weights agora lidos de user_attrs (que JÁ são escritos)
    # ou, equivalentemente, recalculados a partir de best.params.
    w_lgbm_final = best.user_attrs.get("w_lgbm_final")
    w_xgb_final = best.user_attrs.get("w_xgb_final")
    w_z_final = best.user_attrs.get("w_z_final")
    _console.print(
        f"\n[bold]Weights ensemble escolhidos:[/bold] "
        f"LGBM={w_lgbm_final:.3f}  XGB={w_xgb_final:.3f}  Z={w_z_final:.3f}"
    )

    # ── Fit final nos dados completos com os melhores params ─────
    _console.print("\n[4/4] Fit final no dataset completo...")

    lgb_params_final = {
        k: best.params[k]
        for k in ["n_estimators", "learning_rate", "max_depth", "num_leaves",
                  "min_child_samples", "subsample", "colsample_bytree"]
    }

    from lightgbm import LGBMClassifier
    final_lgb = LGBMClassifier(**lgb_params_final, random_state=42, verbose=-1)
    X = dataset[FEATURE_COLS].fillna(0)
    y = dataset["label"]
    final_lgb.fit(X, y)
    joblib.dump(final_lgb, MODEL_DIR / "lgbm_peak.pkl")

    # XGB final (se aplicável)
    if args.with_xgb:
        try:
            from xgboost import XGBClassifier
            xgb_params_final = {
                "n_estimators": best.params["xgb_n_estimators"],
                "learning_rate": best.params["xgb_learning_rate"],
                "max_depth": best.params["xgb_max_depth"],
            }
            final_xgb = XGBClassifier(
                **xgb_params_final, random_state=42, verbosity=0,
                use_label_encoder=False, eval_metric="logloss",
            )
            final_xgb.fit(X, y)
            joblib.dump(final_xgb, MODEL_DIR / "xgb_peak.pkl")
            _console.print("  [green]✓[/green] XGB guardado")
        except Exception as e:
            _console.print(f"  [yellow]XGB falhou: {e}[/yellow]")

    config = {
        "feature_cols": FEATURE_COLS,
        "lgb_params": lgb_params_final,
        "ensemble_weights": {
            "lgbm": float(w_lgbm_final),
            "xgb": float(w_xgb_final),
            "zscore": float(w_z_final),
        },
        "global_auc": float(best.value),
        "mean_auc_wf": float(best.value),
        "best_trial_number": best.number,
        "n_trials": args.n_trials,
    }
    (MODEL_DIR / "peak_model_config.json").write_text(json.dumps(config, indent=2))

    _console.print(f"\n[green]Modelo Optuna guardado em: {MODEL_DIR}[/green]")
    _console.print(
        "Para usar: copia/move o conteúdo de munich_peak_model_optuna/ "
        "para munich_peak_model/ ou aponta o load_models para esta pasta."
    )


if __name__ == "__main__":
    main()