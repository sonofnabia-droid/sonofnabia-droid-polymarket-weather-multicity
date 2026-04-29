"""
train.py
=========
Treinador multi-cidade genérico. Usa predictor.py e cities/config.py.

Uso:
    python train.py --city munich
    python train.py --city dallas --no-wf
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

from cities.config import CityConfig, get_city, CITIES
from predictor import set_city, build_features, set_seasonal_prior

warnings.filterwarnings("ignore")
_console = Console()

FEATURE_COLS = [
    "slot_frac", "doy_sin", "doy_cos",
    "temp_c", "running_max", "temp_vs_climatology",
    "delta_30m", "delta_1h", "accel", "recent_slope",
    "temp_lag_3", "roll3_std", "plateau_indicator",
    "morning_max", "radiation_proxy", "humidity_drop_1h",
    "prev_7d_avg_max", "seasonal_peak_prior",
    "dewpoint_c", "temp_to_dewpoint_gap", "pressure_trend_3h",
    "wind_south_proxy", "wind_speed_kmh", "uv_index", "foehn_indicator",
]


def load_csv(csv_path: Path):
    df = pd.read_csv(csv_path)
    if "date" in df.columns and isinstance(df["date"].iloc[0], str):
        # Auto-detect format: try dayfirst, if fails use default
        try:
            df["date"] = pd.to_datetime(df["date"], dayfirst=True).dt.date
        except ValueError:
            df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def build_dataset(df: pd.DataFrame, city: CityConfig):
    """Constrói dataset de treino com paridade com inferência (build_features)."""
    _console.print("  A construir dataset (via build_features, paridade com live)...")

    # Garantia da coluna 'hour'
    if "hour" not in df.columns and "timestamp_utc" in df.columns:
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        def ceil_slot(hour: int, minute: int) -> tuple[int, int]:
            if minute < 30:
                return (hour, 30)
            else:
                return (hour + 1, 0)

        city_tz = ZoneInfo(city.timezone)

        def normalize_ceiling(ts):
            dt = pd.to_datetime(ts)
            if dt.tz is None:
                dt = dt.tz_localize("UTC")
            dt_local = dt.astimezone(city_tz)
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

    # Normalizar colunas meteorológicas
    df = df.copy()

    def _coalesce(primary, fallback_value):
        if primary in df.columns:
            df[primary] = pd.to_numeric(df[primary], errors="coerce")
            df[primary] = df[primary].fillna(fallback_value)
        else:
            df[primary] = fallback_value

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

        slots_so_far: list[dict] = []

        for i, row in day_df.iterrows():
            h = int(row["hour"])
            slot30 = int(row.get("slot30", 0))
            temp = float(row["temp_c"])
            label = 1 if (i == peak_idx) else 0

            prev7 = history_max.get(d, city.climatology.get(d.month, 15.0) if city.climatology else 15.0)

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

            feat_row = build_features(
                slots_so_far=slots_so_far,
                current=current_extra,
                month=int(row.get("month", getattr(d, "month", 6))),
                doy=int(row.get("doy", 180)),
            )

            feat_row["date"] = d
            feat_row["hour"] = h
            feat_row["slot30"] = slot30
            feat_row["label"] = label
            feat_row["month"] = int(row.get("month", getattr(d, "month", 6)))
            feat_row["doy"] = int(row.get("doy", 180))

            rows.append(feat_row)

        history_max[d] = peak_temp

    dataset = pd.DataFrame(rows)

    # Prior sazonal
    prior_map = {}
    for (m, h, s), group in dataset.groupby(["month", "hour", "slot30"]):
        prior_map[(m, h, s)] = group["label"].mean()

    set_seasonal_prior(prior_map)

    dataset["seasonal_peak_prior"] = dataset.apply(
        lambda r: prior_map.get((r["month"], r["hour"], r["slot30"]), 0.5),
        axis=1,
    )

    return dataset, prior_map


def walk_forward_auc(dataset: pd.DataFrame, params: dict, min_train_years: int = 2) -> dict:
    """Walk-forward real baseado em anos."""
    from lightgbm import LGBMClassifier

    if not pd.api.types.is_datetime64_any_dtype(dataset["date"]):
        dataset = dataset.copy()
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")

    years = sorted(dataset["date"].dt.year.unique())
    if len(years) < min_train_years + 1:
        _console.print(
            f"  [yellow]Apenas {len(years)} anos de dados — walk-forward impossível[/yellow]"
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
    parser = argparse.ArgumentParser(description="Treinador multi-cidade")
    parser.add_argument("--city", type=str, default="munich", choices=list(CITIES.keys()),
                        help="Cidade para treinar")
    parser.add_argument("--no-wf", action="store_true",
                        help="Salta walk-forward; usa fit único (rápido, sem AUC honesto)")
    args = parser.parse_args()

    city = get_city(args.city)
    set_city(args.city)

    _console.print("=" * 60)
    _console.print(f" {city.name.title()} Peak Model — Trainer (25 features)")
    _console.print("=" * 60)

    csv_path = Path(city.csv_path)
    if not csv_path.exists():
        _console.print(f"[red]Erro: {csv_path} não encontrado[/red]")
        return

    _console.print(f"\n[1/4] Carregando dados: {csv_path}")
    df = load_csv(csv_path)

    _console.print("\n[2/4] Construindo dataset...")
    dataset, prior_map = build_dataset(df, city)

    LGB_PARAMS = {
        "n_estimators": 600,
        "learning_rate": 0.02,
        "max_depth": 6,
        "num_leaves": 60,
    }

    # Walk-forward antes do fit final
    wf_result = {"per_year": {}, "mean_auc": None}
    if not args.no_wf:
        _console.print("\n[3/4] Walk-forward (AUC fora-da-amostra real)...")
        wf_result = walk_forward_auc(dataset, LGB_PARAMS, min_train_years=2)
        if wf_result["mean_auc"] is not None:
            _console.print(
                f"\n  [bold green]AUC médio walk-forward: {wf_result['mean_auc']:.4f}[/bold green]"
            )
        else:
            _console.print("  [yellow]Walk-forward pulado — dados insuficientes[/yellow]")
    else:
        _console.print("\n[3/4] --no-wf: saltando walk-forward")

    # Fit final em TODOS os dados
    _console.print("\n[4/4] Fit final no dataset completo...")

    from lightgbm import LGBMClassifier
    lgb = LGBMClassifier(**LGB_PARAMS, random_state=42, verbose=-1)
    X = dataset[FEATURE_COLS].fillna(0)
    y = dataset["label"]
    lgb.fit(X, y)

    in_sample_auc = float(roc_auc_score(y, lgb.predict_proba(X)[:, 1]))
    _console.print(
        f"  AUC in-sample (treino): {in_sample_auc:.4f}  "
        f"[dim](otimista — não é o AUC real)[/dim]"
    )
    if wf_result["mean_auc"] is not None:
        gap = in_sample_auc - wf_result["mean_auc"]
        _console.print(
            f"  [dim]Gap in-sample vs walk-forward: {gap:.3f}[/dim]"
        )

    model_dir = Path(city.model_dir)
    model_dir.mkdir(exist_ok=True)

    joblib.dump(lgb, model_dir / "lgbm_peak.pkl")

    config = {
        "feature_cols": FEATURE_COLS,
        "lgb_params": LGB_PARAMS,
        "ensemble_weights": {"lgbm": 1.0, "xgb": 0.0, "zscore": 0.0},
        "model_type": "lightgbm_pure",
        "global_auc": wf_result["mean_auc"] if wf_result["mean_auc"] is not None else in_sample_auc,
        "mean_auc_wf": wf_result["mean_auc"],
        "in_sample_auc": in_sample_auc,
        "per_year_auc_wf": {str(y): a for y, a in wf_result["per_year"].items()},
        "seasonal_peak_prior": {f"{k[0]}_{k[1]}_{k[2]}": float(v) for k, v in prior_map.items()}
    }
    (model_dir / "peak_model_config.json").write_text(json.dumps(config, indent=2))

    _console.print("\n[bold green]Treino concluído![/bold green]")
    _console.print(f"Modelo guardado em: {model_dir}")
    if wf_result["mean_auc"] is not None:
        _console.print(f"AUC real (walk-forward): {wf_result['mean_auc']:.4f}")


if __name__ == "__main__":
    main()
