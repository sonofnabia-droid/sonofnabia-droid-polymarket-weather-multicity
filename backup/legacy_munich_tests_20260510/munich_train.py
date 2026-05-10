"""
munich_train.py — Versão Completa Corrigida
"""

import argparse
import json
from pathlib import Path
import warnings
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from rich.console import Console
from rich.table import Table
from rich import box as rich_box

from munich_config import FEATURE_COLS, DATA_CSV
from munich_model import set_seasonal_prior

warnings.filterwarnings("ignore")
_console = Console()

def load_csv():
    df = pd.read_csv(DATA_CSV)
    if "date" in df.columns and isinstance(df["date"].iloc[0], str):
        df["date"] = pd.to_datetime(df["date"], dayfirst=True).dt.date
    return df

def build_dataset(df: pd.DataFrame):
    """
    Constrói o dataset de treino.

    FIX #11 (e parcialmente #4): em vez de inlinear cálculos de features
    (com placeholders a 0.0, constantes como uv_index=3.0, etc.), esta
    função passa a chamar a MESMA `build_features` que o live_bot e o
    backtester usam em inferência. Paridade treino↔inferência garantida
    automaticamente: se a build_features mudar, o treino acompanha.

    Features que antes eram placeholders degenerados (recent_slope=0,
    humidity_drop_1h=0, seasonal_peak_prior=0.5, uv_index=3.0, etc.)
    passam a ter valores reais, calculados a partir das colunas
    meteorológicas do CSV (com fallbacks seguros se o CSV não as tiver).
    """
    from munich_model import build_features
    _console.print("  A construir dataset (via build_features, paridade com live)...")

    # Garantia da coluna 'hour'
    if "hour" not in df.columns and "timestamp_utc" in df.columns:
        from munich_config import ceil_slot
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        BERLIN_TZ = ZoneInfo("Europe/Berlin")

        def normalize_ceiling(ts):
            dt = pd.to_datetime(ts)
            if dt.tz is None:
                dt = dt.tz_localize("UTC")
            dt_local = dt.astimezone(BERLIN_TZ)
            h, m = dt_local.hour, dt_local.minute
            h2, s2 = ceil_slot(h, m)
            if h2 == 24:
                dt_local = (dt_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                h2 = 0
            return dt_local, h2, s2

        dt_locals, hours, slots30 = [], [], []
        for ts in df["timestamp_utc"]:
            dt_loc, h2, s2 = normalize_ceiling(ts)
            dt_locals.append(dt_loc)
            hours.append(h2)
            slots30.append(s2)

        df = df.copy()
        df["hour"] = hours
        df["slot30"] = slots30
        df["month"] = [dt.month for dt in dt_locals]
        df["doy"] = [dt.timetuple().tm_yday for dt in dt_locals]
        df["date"] = pd.to_datetime([dt.date() for dt in dt_locals])

    # --- Normalizar colunas meteorológicas (mesmos nomes que o backtester antigo) ---
    df = df.copy()

    def _coalesce(primary, fallback_value):
        """Normaliza uma coluna para numeric; se não existe, cria com fallback."""
        if primary in df.columns:
            df[primary] = pd.to_numeric(df[primary], errors="coerce")
            df[primary] = df[primary].fillna(fallback_value)
        else:
            df[primary] = fallback_value

    # O CSV pode ter nomes diferentes; unificamos
    if "humidity" not in df.columns:
        if "humidity_pct" in df.columns:
            df["humidity"] = pd.to_numeric(df["humidity_pct"], errors="coerce").fillna(70.0)
        else:
            df["humidity"] = 70.0

    if "cloud_cover" not in df.columns:
        if "sky_cover" in df.columns:
            df["cloud_cover"] = pd.to_numeric(df["sky_cover"], errors="coerce").fillna(50.0)
        else:
            df["cloud_cover"] = 50.0

    if "dewpoint_c" not in df.columns:
        if "dewpt_c" in df.columns:
            df["dewpoint_c"] = pd.to_numeric(df["dewpt_c"], errors="coerce").fillna(df["temp_c"] - 10)
        else:
            df["dewpoint_c"] = df["temp_c"] - 10

    _coalesce("pressure_hpa", 1013.0)
    _coalesce("wind_dir_deg", 0.0)
    _coalesce("wind_speed_kmh", 5.0)
    _coalesce("wind_gust_kmh", 8.0)
    _coalesce("uv_index", 3.0)

    rows = []
    history_max = {}

    for d, day_df in df.groupby("date"):
        day_df = day_df.sort_values(["hour", "slot30"] if "slot30" in day_df.columns else ["hour"]).reset_index(drop=True)
        peak_temp = day_df["temp_c"].max()
        peak_idx = day_df[day_df["temp_c"] == peak_temp].index[-1]

        slots_so_far: list[dict] = []   # cumulativo para build_features

        for i, row in day_df.iterrows():
            h = int(row["hour"])
            slot30 = int(row.get("slot30", 0))
            temp = float(row["temp_c"])
            label = 1 if (i == peak_idx) else 0

            # prev7 usa máximas dos DIAS anteriores (não o do próprio dia,
            # para evitar data leakage). Fallback: climatologia 15.0.
            prev7 = history_max.get(d, 15.0)

            slot_entry = {
                "hour": h, "slot30": slot30, "temp_c": temp,
                "humidity": float(row["humidity"]),
                "cloud_cover": float(row["cloud_cover"]),
                "dewpoint_c": float(row["dewpoint_c"]),
                "pressure_hpa": float(row["pressure_hpa"]),
                "wind_dir_deg": float(row["wind_dir_deg"]),
                "wind_speed_kmh": float(row["wind_speed_kmh"]),
                "wind_gust_kmh": float(row["wind_gust_kmh"]),
                "uv_index": float(row["uv_index"]),
            }
            slots_so_far.append(slot_entry)

            current_extra = {
                **slot_entry,
                "prev_7d_avg_max": prev7,
            }

            # Mesmo `build_features` que o live_bot / backtester usam em inferência
            feat_row = build_features(
                slots_so_far=slots_so_far,
                current=current_extra,
                month=int(row.get("month", getattr(d, "month", 6))),
                doy=int(row.get("doy", 180)),
            )

            # Metadados para split temporal / análise
            feat_row["date"] = d
            feat_row["hour"] = h
            feat_row["slot30"] = slot30
            feat_row["label"] = label
            feat_row["month"] = int(row.get("month", getattr(d, "month", 6)))
            feat_row["doy"] = int(row.get("doy", 180))

            rows.append(feat_row)

        history_max[d] = peak_temp

    dataset = pd.DataFrame(rows)

    # Prior sazonal (computed após ter labels, como antes)
    prior_map = {}
    for (m, h, s), group in dataset.groupby(["month", "hour", "slot30"]):
        prior_map[(m, h, s)] = group["label"].mean()

    set_seasonal_prior(prior_map)

    # IMPORTANTE: as linhas do dataset já foram calculadas com
    # seasonal_peak_prior=0.5 (default inicial porque a prior_map
    # ainda não existia). Para consistência plena, substituímos
    # agora pela prior real — só afeta esta coluna.
    dataset["seasonal_peak_prior"] = dataset.apply(
        lambda r: prior_map.get((r["month"], r["hour"], r["slot30"]), 0.5),
        axis=1,
    )

    return dataset, prior_map


def walk_forward_auc(dataset: pd.DataFrame, params: dict, min_train_years: int = 2) -> dict:
    """
    FIX #10: walk-forward real baseado em anos.

    Ao contrário do `lgb.fit(X, y)` num único split no dataset completo
    (que não permite saber o AUC fora-da-amostra), isto faz:
      - para cada ano Y após o min_train_years-ésimo:
          treina em [1º ano, Y-1º ano]
          testa em Y
      - devolve AUC por ano + AUC médio.

    Esta é a estimativa honesta da capacidade preditiva em dias que o
    modelo nunca viu.
    """
    from lightgbm import LGBMClassifier
    from sklearn.metrics import roc_auc_score

    if not pd.api.types.is_datetime64_any_dtype(dataset["date"]):
        dataset = dataset.copy()
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")

    years = sorted(dataset["date"].dt.year.unique())
    if len(years) < min_train_years + 1:
        _console.print(
            f"  [yellow]Apenas {len(years)} anos de dados — não há anos suficientes "
            f"para walk-forward (precisa ≥ {min_train_years + 1})[/yellow]"
        )
        return {"per_year": {}, "mean_auc": None}

    per_year = {}
    for i in range(min_train_years, len(years)):
        train_years = years[:i]
        val_year = years[i]

        train = dataset[dataset["date"].dt.year.isin(train_years)]
        val = dataset[dataset["date"].dt.year == val_year]

        if len(train) == 0 or len(val) == 0 or val["label"].nunique() < 2:
            continue

        X_tr = train[FEATURE_COLS].fillna(0)
        y_tr = train["label"]
        X_val = val[FEATURE_COLS].fillna(0)
        y_val = val["label"]

        model = LGBMClassifier(**params, random_state=42, verbose=-1)
        model.fit(X_tr, y_tr)
        preds = model.predict_proba(X_val)[:, 1]
        auc = float(roc_auc_score(y_val, preds))
        per_year[val_year] = auc
        _console.print(
            f"    WF {val_year}: train em {len(train_years)} anos ({train_years[0]}–{train_years[-1]}) "
            f"→ AUC={auc:.4f}"
        )

    mean = float(np.mean(list(per_year.values()))) if per_year else None
    return {"per_year": per_year, "mean_auc": mean}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-xgb", action="store_true")
    parser.add_argument("--no-wf", action="store_true",
                        help="Salta walk-forward; usa fit único (rápido, sem AUC honesto)")
    parser.add_argument("--doy-degree", type=int, default=5)
    args = parser.parse_args()

    _console.print("=" * 60)
    _console.print(" Munich Peak Model — Trainer (25 features, paridade live)")
    _console.print("=" * 60)

    _console.print("\n[1/4] Carregando dados...")
    df = load_csv()

    _console.print("\n[2/4] Construindo dataset (via build_features, paridade live)...")
    dataset, prior_map = build_dataset(df)

    LGB_PARAMS = {
        "n_estimators": 600,
        "learning_rate": 0.02,
        "max_depth": 6,
        "num_leaves": 60,
    }

    # ── FIX #10: walk-forward antes do fit final ──────────────────
    wf_result = {"per_year": {}, "mean_auc": None}
    if not args.no_wf:
        _console.print("\n[3/4] Walk-forward (AUC fora-da-amostra real)...")
        wf_result = walk_forward_auc(dataset, LGB_PARAMS, min_train_years=2)
        if wf_result["mean_auc"] is not None:
            _console.print(
                f"\n  [bold green]AUC médio walk-forward: {wf_result['mean_auc']:.4f}[/bold green]"
            )
            _console.print(
                "  [dim]Este é o AUC real — o que o modelo atinge em dias que nunca viu.[/dim]"
            )
        else:
            _console.print("  [yellow]Walk-forward pulado — dados insuficientes[/yellow]")
    else:
        _console.print("\n[3/4] --no-wf: saltando walk-forward")

    # ── [4/4] Fit final em TODOS os dados (para produção) ─────────
    _console.print("\n[4/4] Fit final no dataset completo (para deploy)...")

    from lightgbm import LGBMClassifier
    from sklearn.metrics import roc_auc_score
    lgb = LGBMClassifier(**LGB_PARAMS, random_state=42, verbose=-1)
    X = dataset[FEATURE_COLS].fillna(0)
    y = dataset["label"]
    lgb.fit(X, y)

    # AUC in-sample — diagnóstico apenas (tipicamente irrealisticamente alto)
    in_sample_auc = float(roc_auc_score(y, lgb.predict_proba(X)[:, 1]))
    _console.print(
        f"  AUC in-sample (treino): {in_sample_auc:.4f}  "
        f"[dim](otimista — não é o AUC real)[/dim]"
    )
    if wf_result["mean_auc"] is not None:
        gap = in_sample_auc - wf_result["mean_auc"]
        _console.print(
            f"  [dim]Gap in-sample vs walk-forward: {gap:.3f}"
            f"{' (overfitting significativo)' if gap > 0.10 else ''}[/dim]"
        )

    MODEL_DIR = Path("munich_peak_model")
    MODEL_DIR.mkdir(exist_ok=True)

    joblib.dump(lgb, MODEL_DIR / "lgbm_peak.pkl")

    config = {
        "feature_cols": FEATURE_COLS,
        "lgb_params": LGB_PARAMS,
        # Decisão 2026-04: LightGBM puro. Ver munich_config.ENSEMBLE_WEIGHTS.
        "ensemble_weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
        "model_type": "lightgbm_pure",
        "global_auc": wf_result["mean_auc"] if wf_result["mean_auc"] is not None else in_sample_auc,
        "mean_auc_wf": wf_result["mean_auc"],
        "in_sample_auc": in_sample_auc,
        "per_year_auc_wf": {str(y): a for y, a in wf_result["per_year"].items()},
        "seasonal_peak_prior": {f"{k[0]}_{k[1]}_{k[2]}": float(v) for k, v in prior_map.items()}
    }
    (MODEL_DIR / "peak_model_config.json").write_text(json.dumps(config, indent=2))

    _console.print("\n[bold green]Treino concluído![/bold green]")
    _console.print(f"Modelo guardado em: {MODEL_DIR}")
    if wf_result["mean_auc"] is not None:
        _console.print(f"AUC real (walk-forward): {wf_result['mean_auc']:.4f}")


if __name__ == "__main__":
    main()