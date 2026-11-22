#!/usr/bin/env python3
"""EXP03: isolated, causal native-METAR rebound experiment.

Preflight by default. --train creates a new experiment directory only.
Never modifies live bots, predictors, source CSVs, or existing models.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

from cities.config import get_city
from cassiopeia_train import load_csv, _train_lgbm, _get_ceil_slot
from cassiopeia_predictor import build_features, compute_prev7
from cassiopeia_metar_features_exp03 import build_time_features

NAME = 'cassiopeia_rebound_metar_exp03'
BASE_FEATURES = [
    'slot_frac', 'doy_sin', 'doy_cos', 'temp_c', 'running_max',
    'temp_vs_climatology', 'morning_max', 'radiation_proxy',
    'prev_7d_avg_max', 'dewpoint_c', 'temp_to_dewpoint_gap',
    'wind_south_proxy', 'wind_speed_kmh', 'foehn_indicator',
]
TIME_FEATURES = [
    'temp_delta_30m', 'temp_delta_60m', 'temp_delta_180m',
    'observation_age_minutes', 'observations_last_3h',
]
FEATURES = BASE_FEATURES + TIME_FEATURES


def score(y, p):
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-7, 1 - 1e-7)
    return dict(samples=len(y), positive_rate=float(y.mean()),
                auc=float(roc_auc_score(y, p)),
                brier=float(brier_score_loss(y, p)),
                log_loss=float(log_loss(y, p, labels=[0, 1])))


def number(row, key, default):
    val = row.get(key, np.nan)
    try:
        return float(val) if pd.notna(val) else float(default)
    except (TypeError, ValueError):
        return float(default)


def build(df, city):
    if 'timestamp_utc' not in df or 'temp_c' not in df:
        raise ValueError('Missing native METAR timestamp_utc or temp_c')
    df = df.copy()
    df['_utc'] = pd.to_datetime(df['timestamp_utc'], utc=True, errors='coerce')
    df['temp_c'] = pd.to_numeric(df['temp_c'], errors='coerce')
    df = df.dropna(subset=['_utc', 'temp_c']).sort_values('_utc')
    df = df.drop_duplicates('_utc', keep='last')
    local = df['_utc'].dt.tz_convert(city.timezone)
    df['_day'] = local.dt.date
    df['_hour'] = local.dt.hour
    df['_minute'] = local.dt.minute
    ceil_slot = _get_ceil_slot()
    rows = []
    history_max = {}
    discarded = dict(insufficient_history=0, missing_future=0,
                     no_3h_coverage=0, collisions=0, outside_window=0)
    min_hour = int(getattr(city, 'cassiopeia_min_hour_target', 12))
    for day, group in df.groupby('_day', sort=True):
        group = group.sort_values('_utc').reset_index(drop=True)
        ns = pd.DatetimeIndex(group['_utc']).as_unit('ns').asi8
        temps = group['temp_c'].to_numpy(dtype=float)
        prev7 = compute_prev7(history_max, day, city.name)
        slots_by_key = {}
        # History is observation-time causal, never populated from future rows.
        history = []
        for i, row in group.iterrows():
            h, m = ceil_slot(int(row['_hour']), int(row['_minute']))
            if not (city.day_start <= h <= city.day_end):
                discarded['outside_window'] += 1
                continue
            temp = float(row['temp_c'])
            slot = dict(hour=h, slot30=m, temp_c=temp,
                        cloud_cover=number(row, 'cloud_cover', number(row, 'sky_cover', 50)),
                        humidity=number(row, 'humidity', number(row, 'humidity_pct', 70)),
                        dewpoint_c=number(row, 'dewpoint_c', number(row, 'dewpt_c', temp - 10)),
                        pressure_hpa=number(row, 'pressure_hpa', 1013),
                        wind_dir_deg=number(row, 'wind_dir_deg', 0),
                        wind_speed_kmh=number(row, 'wind_speed_kmh', 5),
                        wind_gust_kmh=number(row, 'wind_gust_kmh', 8),
                        uv_index=number(row, 'uv_index', 3))
            key = (h, m)
            if key in slots_by_key:
                discarded['collisions'] += 1
            slots_by_key[key] = slot
            history.append(dict(timestamp_utc=row['_utc'], temp_c=temp,
                                humidity=slot['humidity']))
            slots = [slots_by_key[k] for k in sorted(slots_by_key)]
            if h < min_hour or len(slots) < 4:
                discarded['insufficient_history'] += 1
                continue
            dt = (ns[i + 1:] - ns[i]) / 60_000_000_000
            ix = np.where((dt > 0) & (dt <= 180))[0] + i + 1
            if len(ix) < 2:
                discarded['missing_future'] += 1
                continue
            if (ns[ix[-1]] - ns[i]) < 150 * 60_000_000_000:
                discarded['no_3h_coverage'] += 1
                continue
            running_max = max(s['temp_c'] for s in slots)
            label = int(float(np.max(temps[ix])) > running_max + 0.3)
            baseline = build_features(slots, {**slot, 'prev_7d_avg_max': prev7},
                                      day.month, day.timetuple().tm_yday)
            timed = build_time_features(history, row['_utc'])
            rows.append({**{f: baseline.get(f, np.nan) for f in BASE_FEATURES},
                         **timed, 'date': day, 'timestamp_utc': row['_utc'], 'label': label})
        # Full-day maximum is used only for the following days' prior.
        history_max[day] = float(np.max(temps))
    return pd.DataFrame(rows), discarded


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--city', default='munich')
    ap.add_argument('--train', action='store_true')
    args = ap.parse_args()
    city = get_city(args.city)
    source = Path('historic_metar') / f'{args.city}.csv'
    out = Path(city.model_dir).parent / NAME
    if not source.is_file():
        ap.error(f'Missing native METAR CSV: {source}')
    if out.exists():
        ap.error(f'REFUSING existing output directory: {out}')
    if not out.resolve().is_relative_to((Path.cwd() / 'cities').resolve()):
        ap.error('Output outside cities directory')
    print(f'City: {args.city}; source: {source}; output: {out}', flush=True)
    print('EXP03: local timezone, causal slots, native METAR, real-minute deltas', flush=True)
    print('Target: rebound >0.3C within 180min; coverage >=150min', flush=True)
    print('Splits: train <=2022; validation 2023-2024; test >=2025', flush=True)
    if not args.train:
        print('PREFLIGHT ONLY: no data loaded, no training, no writes.')
        return
    df = load_csv(source, city_name=args.city)
    dataset, discarded = build(df, city)
    if dataset.empty:
        ap.error('No eligible observations')
    dataset['date'] = pd.to_datetime(dataset['date'])
    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    # LightGBM supports NaNs; preserve missing temporal observations.
    dataset = dataset.dropna(subset=['label'])
    tr = dataset[dataset.date <= '2022-12-31']
    va = dataset[(dataset.date >= '2023-01-01') & (dataset.date <= '2024-12-31')]
    te = dataset[dataset.date >= '2025-01-01']
    for label, part in [('train', tr), ('validation', va), ('test', te)]:
        print(label, len(part), part.date.min(), part.date.max(),
              'positive_rate', part.label.mean(), flush=True)
        if len(part) < 200 or part.label.nunique() < 2:
            ap.error(f'{label}: insufficient samples or only one class')
    if not (tr.date.max() < va.date.min() < te.date.min()):
        ap.error('Overlapping chronological splits')
    xtr, xva, xte = (p[FEATURES].astype(np.float32).values for p in (tr, va, te))
    model = _train_lgbm(xtr, tr.label.astype(int).values,
                        xva, va.label.astype(int).values)
    pva = model.predict(xva, num_iteration=model.best_iteration)
    pte = model.predict(xte, num_iteration=model.best_iteration)
    report = dict(experiment=NAME, city=args.city,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  source_csv=str(source),
                  target='native_metar_observed_180min_delta_gt_0.3C',
                  target_coverage_min_minutes=150,
                  splits=dict(train_end='2022-12-31', validation='2023-2024',
                              test_start='2025-01-01'),
                  features=FEATURES, best_iteration=int(model.best_iteration),
                  discarded=discarded, validation=score(va.label, pva),
                  test=score(te.label, pte),
                  caveats=[
                      'Experimental only: no live inference adapter or deployment',
                      'Observation timestamps are not guaranteed availability times',
                      'No Polymarket settlement or trading PnL parity',
                      'Feature definitions and sample selection differ from EXP02',
                      'Time deltas require an exact older observation within 15min tolerance',
                      'Slot history sorted by local clock; DST fallback may reorder repeated hours',
                      'Cloud cover schema and live prev7 parity remain unverified',
                  ])
    out.mkdir(parents=True, exist_ok=False)
    import joblib
    joblib.dump(model, out / 'lgbm_rebound.pkl')
    (out / 'experiment_report.json').write_text(json.dumps(report, indent=2))
    (out / 'rebound_model_config.json').write_text(json.dumps(dict(
        feature_cols=FEATURES, best_model='lgbm',
        global_auc=report['test']['auc'], future_horizon_minutes=180,
        delta_threshold=0.3, seasonal_peak_prior={},
        experimental_only=True), indent=2))
    print(json.dumps(dict(output=str(out), validation=report['validation'],
                          test=report['test']), indent=2))


if __name__ == '__main__':
    main()
