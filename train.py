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
from predictor import set_city, build_features, set_seasonal_prior, compute_prev7
from weather import ceil_slot

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
    with open(csv_path, "r", encoding="utf-8") as f:
        first = f.readline()
    sep = "\t" if "\t" in first else ","

    df = pd.read_csv(csv_path, sep=sep, low_memory=False)

    if "date" in df.columns and len(df) > 0 and isinstance(df["date"].iloc[0], str):
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

        city_tz = ZoneInfo(city.timezone)

        def normalize_ceiling(ts):
            dt = pd.to_datetime(ts)
            if dt.tz is None:
                dt = dt.tz_localize("UTC")
            dt_local = dt.astimezone(city_tz)
            h, m = dt_local.hour, dt_local.minute
            h2, s2 = ceil_slot(h, m)
            if h2 == 24:
                # Manter no mesmo dia como slot 23:30 (último slot do dia)
                h2 = 23
                s2 = 30
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
        df["date"] = [dt.date() for dt in dt_locals]  # Mantém como date objects

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

        # Skip dias sem dados de temperatura válidos
        valid_temps = day_df["temp_c"].dropna()
        if len(valid_temps) == 0:
            continue

        peak_temp = valid_temps.max()
        peak_matches = day_df[day_df["temp_c"] == peak_temp]
        if len(peak_matches) == 0:
            continue
        peak_idx = peak_matches.index[-1]

        slots_so_far: list[dict] = []

        for row in day_df.itertuples(index=True):
            i = row.Index
            h = int(row.hour)
            if h < city.day_start or h > city.day_end:
                continue
            slot30 = int(getattr(row, "slot30", 0))
            temp = float(row.temp_c)
            label = 1 if (i == peak_idx) else 0

            prev7 = compute_prev7(history_max, d, city.name)

            slot_entry = {
                "hour": h, "slot30": slot30, "temp_c": temp,
                "humidity": float(row.humidity),
                "cloud_cover": float(row.cloud_cover),
                "dewpoint_c": float(row.dewpoint_c),
                "pressure_hpa": float(row.pressure_hpa),
                "wind_dir_deg": float(row.wind_dir_deg),
                "wind_speed_kmh": float(row.wind_speed_kmh),
                "wind_gust_kmh": float(row.wind_gust_kmh),
                "uv_index": float(row.uv_index),
            }
            slots_so_far.append(slot_entry)

            current_extra = {
                **slot_entry,
                "prev_7d_avg_max": prev7,
            }

            feat_row = build_features(
                slots_so_far=slots_so_far,
                current=current_extra,
                month=int(getattr(row, "month", getattr(d, "month", 6))),
                doy=int(getattr(row, "doy", 180)),
            )

            feat_row["date"] = d
            feat_row["hour"] = h
            feat_row["slot30"] = slot30
            feat_row["label"] = label
            feat_row["month"] = int(getattr(row, "month", getattr(d, "month", 6)))
            feat_row["doy"] = int(getattr(row, "doy", 180))

            rows.append(feat_row)

        history_max[d] = peak_temp

    dataset = pd.DataFrame(rows)

    # Prior sazonal: cada linha usa apenas anos anteriores; o mapa final usa
    # todo o histórico e é guardado para inferência live.
    prior_values, prior_map = _compute_expanding_prior(dataset)
    set_seasonal_prior(prior_map)
    dataset["seasonal_peak_prior"] = prior_values
    return dataset, prior_map


def _compute_expanding_prior(dataset: pd.DataFrame) -> tuple[pd.Series, dict]:
    """Computa prior por linha sem leakage e mapa final para live."""
    if "date" not in dataset.columns:
        # Fallback: sem datas, usar média por slot e aplicar ao próprio dataset.
        prior_map = {}
        for (m, h, s), group in dataset.groupby(["month", "hour", "slot30"]):
            prior_map[(int(m), int(h), int(s))] = float(group["label"].mean())
        prior_values = dataset.apply(
            lambda r: prior_map.get((int(r["month"]), int(r["hour"]), int(r["slot30"])), 0.5),
            axis=1,
        )
        return prior_values, prior_map

    if not pd.api.types.is_datetime64_any_dtype(dataset["date"]):
        dataset = dataset.copy()
        dataset["date"] = pd.to_datetime(dataset["date"], errors="coerce")

    sorted_dataset = dataset.sort_values("date")
    prior_values = pd.Series(0.5, index=dataset.index, dtype=float)

    # Para cada ano, calcular prior apenas com anos anteriores.
    years = sorted(sorted_dataset["date"].dropna().dt.year.unique())
    prior_accumulator = {}

    for year in years:
        year_data = sorted_dataset[sorted_dataset["date"].dt.year == year]

        for row in year_data.itertuples(index=True):
            idx = row.Index
            key = (int(row.month), int(row.hour), int(row.slot30))
            acc = prior_accumulator.get(key)
            if acc and acc["count"] > 0:
                prior_values.at[idx] = acc["sum"] / acc["count"]

        for (m, h, s), group in year_data.groupby(["month", "hour", "slot30"]):
            key = (int(m), int(h), int(s))
            if key not in prior_accumulator:
                prior_accumulator[key] = {"sum": 0.0, "count": 0}
            acc = prior_accumulator[key]
            acc["sum"] += group["label"].sum()
            acc["count"] += len(group)

    prior_map = {
        key: acc["sum"] / acc["count"]
        for key, acc in prior_accumulator.items()
        if acc["count"] > 0
    }

    return prior_values, prior_map

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


def run_training(city_name: str, no_wf: bool = False, quiet: bool = False) -> dict | None:
    """
    Treina modelo para 1 cidade. Função reutilizável para wrappers.

    Args:
        city_name: nome da cidade
        no_wf: se True, pula walk-forward
        quiet: se True, suprime alguns prints

    Returns:
        dict com:
            mean_auc_wf, in_sample_auc, n_features, n_rows, model_dir, ...
        ou None em caso de erro.
    """
    try:
        city = get_city(city_name)
        set_city(city_name)

        csv_path = Path(city.csv_path)
        if not csv_path.exists():
            if not quiet:
                _console.print(f"  [red][{city_name}] CSV não encontrado: {csv_path}[/red]")
            return None

        if not quiet:
            _console.print(f"  [{city_name}] Loading CSV: {csv_path}")
        df = load_csv(csv_path)

        if not quiet:
            _console.print(f"  [{city_name}] Building dataset ({len(df):,} raw rows)...")
        dataset, prior_map = build_dataset(df, city)

        LGB_PARAMS = {
            "n_estimators": 600,
            "learning_rate": 0.02,
            "max_depth": 6,
            "num_leaves": 60,
        }

        wf_result = {"per_year": {}, "mean_auc": None}
        if not no_wf:
            if not quiet:
                _console.print(f"  [{city_name}] Walk-forward...")
            wf_result = walk_forward_auc(dataset, LGB_PARAMS, min_train_years=2)

        # Fit final
        from lightgbm import LGBMClassifier
        lgb = LGBMClassifier(**LGB_PARAMS, random_state=42, verbose=-1)
        X = dataset[FEATURE_COLS].fillna(0)
        y = dataset["label"]
        lgb.fit(X, y)

        in_sample_auc = float(roc_auc_score(y, lgb.predict_proba(X)[:, 1]))

        # Save
        model_dir = Path(city.model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
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
            "seasonal_peak_prior": {f"{k[0]}_{k[1]}_{k[2]}": float(v) for k, v in prior_map.items()},
        }
        (model_dir / "peak_model_config.json").write_text(json.dumps(config, indent=2))

        return {
            "city":            city_name,
            "model_dir":       str(model_dir),
            "mean_auc_wf":     wf_result["mean_auc"],
            "in_sample_auc":   in_sample_auc,
            "per_year_auc_wf": wf_result["per_year"],
            "n_rows":          len(dataset),
            "n_features":      len(FEATURE_COLS),
        }

    except Exception as e:
        if not quiet:
            _console.print(f"  [red][{city_name}] Training failed: {e}[/red]")
        return None


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
    model_dir.mkdir(parents=True, exist_ok=True)

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
