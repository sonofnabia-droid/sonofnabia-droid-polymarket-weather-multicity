#!/usr/bin/env python3
"""
Compara métricas calibradas entre cidades.

Uso:
    python compare_cities.py
    python compare_cities.py --sort win_pct
    python compare_cities.py --csv city_comparison.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


VALID_SORT_KEYS = (
    "outcome_score",
    "win_pct",
    "trades_per_year",
    "n_trades",
    "city",
    "calibrated_at",
)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:.{decimals}f}"


def load_rows(cities_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for city_dir in sorted(cities_root.iterdir()):
        if not city_dir.is_dir() or city_dir.name == "__pycache__":
            continue

        cfg_path = city_dir / f"strategy_config_{city_dir.name}.json"
        if not cfg_path.exists():
            continue

        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception:
            continue

        single = (cfg.get("strategies") or {}).get("single_entry") or {}
        meta = cfg.get("_meta") or {}

        rows.append(
            {
                "city": city_dir.name,
                "outcome_score": meta.get("outcome_score"),
                "win_pct": meta.get("win_pct"),
                "trades_per_year": meta.get("trades_per_year"),
                "n_trades": meta.get("n_trades"),
                "threshold": single.get("threshold"),
                "hour_min": single.get("hour_min"),
                "calibrated_at": meta.get("calibrated_at"),
            }
        )
    return rows


def sort_rows(rows: list[dict[str, Any]], sort_key: str, desc: bool) -> list[dict[str, Any]]:
    def key_fn(row: dict[str, Any]) -> Any:
        if sort_key == "city":
            return row.get("city") or ""
        if sort_key == "calibrated_at":
            return row.get("calibrated_at") or ""
        number = _to_float(row.get(sort_key))
        return float("-inf") if number is None else number

    return sorted(rows, key=key_fn, reverse=desc)


def print_table(rows: list[dict[str, Any]]) -> None:
    print(f"{'city':14} {'outcome':>8} {'win%':>7} {'tr/yr':>8} {'n':>5} {'thr':>6} {'hmin':>5}  calibrated_at")
    print("-" * 80)
    for row in rows:
        print(
            f"{(row.get('city') or '-')[:14]:14} "
            f"{_fmt_num(row.get('outcome_score'), 2):>8} "
            f"{_fmt_num(row.get('win_pct'), 1):>7} "
            f"{_fmt_num(row.get('trades_per_year'), 1):>8} "
            f"{str(row.get('n_trades') if row.get('n_trades') is not None else '-'):>5} "
            f"{_fmt_num(row.get('threshold'), 2):>6} "
            f"{str(row.get('hour_min') if row.get('hour_min') is not None else '-'):>5}  "
            f"{row.get('calibrated_at') or '-'}"
        )


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    fields = [
        "city",
        "outcome_score",
        "win_pct",
        "trades_per_year",
        "n_trades",
        "threshold",
        "hour_min",
        "calibrated_at",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compara métricas calibradas das cidades.")
    parser.add_argument(
        "--sort",
        default="outcome_score",
        choices=VALID_SORT_KEYS,
        help="Campo para ordenar (default: outcome_score).",
    )
    parser.add_argument(
        "--asc",
        action="store_true",
        help="Ordenar ascendente (default é descendente).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Caminho para exportar CSV (opcional).",
    )
    parser.add_argument(
        "--cities-root",
        type=Path,
        default=Path("cities"),
        help="Pasta raiz das cidades (default: cities).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = load_rows(args.cities_root)
    if not rows:
        print("Nenhuma cidade encontrada com strategy_config_<city>.json.")
        return 1

    rows = sort_rows(rows, sort_key=args.sort, desc=not args.asc)
    print_table(rows)

    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nCSV escrito em: {args.csv}")

    top = rows[0]
    print(
        "\nTOP city:",
        top.get("city"),
        "| outcome_score=",
        _fmt_num(top.get("outcome_score"), 2),
        "| win%=",
        _fmt_num(top.get("win_pct"), 1),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
