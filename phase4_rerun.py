#!/usr/bin/env python3
"""
phase4_rerun.py — re-corre backtest + calibração com geometria half-up corrigida.

Fase 4 do plano de remediação. Como as labels de treino do LGBM são eventos
de temperatura (não de bracket), os modelos NÃO precisam re-treino. Basta
re-correr o backtester (que já usa round_half_up desde a Fase 1) e a
calibração (que usa o backtester) para obter thresholds corretos.

Uso:
    # Todas as cidades:
    python phase4_rerun.py --cities all

    # Cidades específicas:
    python phase4_rerun.py --cities munich,paris,london

    # Só backtest (sem calibração — mais rápido):
    python phase4_rerun.py --cities munich --skip-calibration

    # Calibração com grid detailed + walk-forward 25%:
    python phase4_rerun.py --cities munich --level detailed --holdout-frac 0.25

Output:
    phase4_results/
    ├── backtest_{city}.json      — resultado do backtest por cidade
    ├── calibration_{city}.json   — nova calibração por cidade
    └── summary.json              — resumo de todas as cidades
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _find_project_root() -> Path | None:
    """Encontra o project root procurando cassiopeia_backtester.py.
    Procura em: dir do script → pai do script → cwd → subir a partir de cwd."""
    candidates = []
    # 1. Dir do script
    candidates.append(Path(__file__).resolve().parent)
    # 2. Pai do script (caso esteja numa subpasta)
    candidates.append(Path(__file__).resolve().parent.parent)
    # 3. cwd
    candidates.append(Path.cwd().resolve())
    # 4. Subir a partir de cwd
    c = Path.cwd().resolve()
    while c != c.parent:
        candidates.append(c)
        c = c.parent

    for d in candidates:
        if (d / "cassiopeia_backtester.py").exists():
            return d
    return None


# Auto-detecção do project root para sys.path
_project_root = _find_project_root()
if _project_root:
    sys.path.insert(0, str(_project_root))
    # Mudar para o project root para que os caminhos relativos (historic/, etc.) funcionem
    import os
    os.chdir(_project_root)

RESULTS_DIR = Path("phase4_results")


def _get_cities(names: str) -> list[str]:
    """Resolve 'all' para a lista completa, ou split por vírgula."""
    if names.lower().strip() == "all":
        try:
            from cities.config import get_all_cities
            all_cfgs = get_all_cities()
            # Só cidades Celsius (Fahrenheit têm geometria diferente)
            return [c.name for c in all_cfgs if c.market_unit == "celsius"]
        except Exception as e:
            print(f"[ERRO] Não foi possível obter lista de cidades: {e}")
            sys.exit(1)
    return [c.strip() for c in names.split(",") if c.strip()]


def _run_backtest(city: str, assume_tz: str = "utc") -> dict:
    """Corre o backtester para uma cidade e retorna resultados."""
    from cassiopeia_backtester import run_backtest

    # Tentar usar auto-params (thresholds da config ativa)
    try:
        from cassiopeia_params import resolve_params
        params = resolve_params(city)
        print(f"  [{city}] auto-params: {params}")
    except Exception:
        params = {}
        print(f"  [{city}] sem auto-params — a usar defaults do backtester")

    results = run_backtest(
        city=city,
        use_ml=True,
        assume_tz=assume_tz,
        **params,
    )
    return results


def _run_calibration(
    city: str,
    csv_path: Path,
    level: str = "standard",
    metric: str = "hit_rate",
    holdout_frac: float = 0.25,
    entry_price: float | None = None,
    fee_rate: float | None = None,
    workers: int | None = None,
) -> dict | None:
    """Corre a calibração para uma cidade. Retorna o best_cfg.

    metric: 'hit_rate' (default — maximiza %acerto do bracket)
            'pnl_per_trade', 'edge_vs_price', 'sharpe', 'roi', 'max_drawdown'
    """
    from cassiopeia_calibrate import grid_search

    if workers is None:
        import os
        workers = max(1, (os.cpu_count() or 2) - 1)

    results = grid_search(
        csv_path=csv_path,
        city=city,
        metric=metric,
        level=level,
        workers=workers,
        top_n=10,
        min_entries=30,
        entry_price=entry_price,
        fee_rate=fee_rate,
        holdout_frac=holdout_frac,
        use_ml=True,
    )

    if not results:
        return None

    # O grid_search já guarda o JSON em cassiopeia_calibration_{city}.json
    # mas queremos uma cópia na pasta phase4_results
    best = results[0]
    return {
        "city": city,
        "level": level,
        "best_params": {
            "threshold": best["threshold"],
            "min_spread": best["spread"],
            "bracket_half": best["bracket"],
            "start_hour": best["min_hour"],
            "end_hour": best["max_hour"],
            "outlier_cap": best["outlier"],
        },
        "metrics": {
            "entries": best["entries"],
            "hit_rate": best["hit_rate"],
            "pnl_per_trade": best["pnl_per_trade"],
            "sharpe": best["sharpe"],
            "edge_vs_price": best.get("edge_vs_price", 0.0),
            "max_drawdown": best.get("max_drawdown", 0.0),
        },
        "n_valid_results": len(results),
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--cities", default="all",
                   help="Lista de cidades separada por vírgula, ou 'all'")
    p.add_argument("--skip-calibration", action="store_true",
                   help="Só corre backtest (pula calibração — muito mais rápido)")
    p.add_argument("--skip-backtest", action="store_true",
                   help="Só corre calibração (pula backtest)")
    p.add_argument("--level", default="standard",
                   choices=["fast", "standard", "detailed", "full"],
                   help="Nível do grid de calibração (default: standard)")
    p.add_argument("--metric", default="hit_rate",
                   choices=["hit_rate", "pnl_per_trade", "edge_vs_price",
                            "sharpe", "roi", "pnl", "max_drawdown"],
                   help="Métrica a otimizar (default: hit_rate — maximiza %%acerto do bracket)")
    p.add_argument("--holdout-frac", type=float, default=0.25,
                   help="Fração de dias para validação OOS walk-forward (default: 0.25)")
    p.add_argument("--entry-price", type=float, default=None,
                   help="Preço YES assumido (default: 0.60 do backtester)")
    p.add_argument("--fee-rate", type=float, default=None,
                   help="Fee rate linear legado (default: weather real 0.05·p·(1-p))")
    p.add_argument("--assume-tz", default="utc", choices=["utc", "local"],
                   help="Interpretação dos timestamps do CSV (default: utc)")
    p.add_argument("--workers", type=int, default=None,
                   help="Workers paralelos para calibração (default: cpu_count-1)")
    p.add_argument("--output-dir", default=str(RESULTS_DIR),
                   help=f"Diretório de output (default: {RESULTS_DIR})")
    args = p.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cities = _get_cities(args.cities)
    print(f"\n{'='*60}")
    print(f" FASE 4 — Re-run backtest + calibração (geometria half-up)")
    print(f"{'='*60}")
    print(f"  Cidades:       {len(cities)} — {', '.join(cities[:5])}"
          f"{'...' if len(cities) > 5 else ''}")
    print(f"  Backtest:      {'sim' if not args.skip_backtest else 'skip'}")
    print(f"  Calibração:    {'sim' if not args.skip_calibration else 'skip'}"
          f" (level={args.level}, metric={args.metric}, holdout={args.holdout_frac:.0%})")
    print(f"  Output:        {output_dir}")
    print()

    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "level": args.level,
        "holdout_frac": args.holdout_frac,
        "cities": {},
    }

    for i, city in enumerate(cities, 1):
        print(f"\n[{i}/{len(cities)}] {'='*50}")
        print(f"  Cidade: {city}")
        print(f"  {'='*50}")

        city_result = {"city": city}

        # ── Backtest ──
        if not args.skip_backtest:
            try:
                print(f"  A correr backtest...")
                bt = _run_backtest(city, assume_tz=args.assume_tz)
                bt_path = output_dir / f"backtest_{city}.json"
                bt_path.write_text(json.dumps(bt, indent=2, default=str))
                city_result["backtest"] = {
                    "entries": bt["entries"],
                    "hits": bt["hits"],
                    "hit_rate": round(bt["hit_rate"], 4),
                    "pnl": round(bt["pnl"], 2),
                    "pnl_per_trade": round(bt["pnl_per_trade"], 4),
                    "edge_vs_price": round(bt.get("edge_vs_price", 0), 4),
                    "breakeven_hit_rate": round(bt.get("breakeven_hit_rate", 0), 4),
                    "days_tested": bt["days_tested"],
                    "days_entered": bt["days_entered"],
                    "roi": round(bt.get("roi", 0), 4),
                    "max_drawdown": round(bt.get("max_drawdown", 0), 2),
                }
                print(f"  ✓ Backtest: {bt['entries']} trades, "
                      f"hit={bt['hit_rate']:.2%}, "
                      f"edge={bt.get('edge_vs_price', 0):+.2%}, "
                      f"P&L={bt['pnl']:+.2f}")
            except Exception as e:
                city_result["backtest_error"] = str(e)
                print(f"  [ERRO] backtest: {e}")
                traceback.print_exc()

        # ── Calibração ──
        if not args.skip_calibration:
            try:
                from cassiopeia_backtester import _find_csv
                csv_path = _find_csv(city)
                if not csv_path.exists():
                    raise FileNotFoundError(f"CSV não encontrado para {city}")

                print(f"  A correr calibração (level={args.level}, metric={args.metric})...")
                cal = _run_calibration(
                    city=city,
                    csv_path=csv_path,
                    level=args.level,
                    metric=args.metric,
                    holdout_frac=args.holdout_frac,
                    entry_price=args.entry_price,
                    fee_rate=args.fee_rate,
                    workers=args.workers,
                )
                if cal:
                    cal_path = output_dir / f"calibration_{city}.json"
                    cal_path.write_text(json.dumps(cal, indent=2, default=str))
                    city_result["calibration"] = cal
                    bp = cal["best_params"]
                    mt = cal["metrics"]
                    print(f"  ✓ Calibração: threshold={bp['threshold']}, "
                          f"hours={bp['start_hour']}-{bp['end_hour']}, "
                          f"hit={mt['hit_rate']:.2%}, "
                          f"edge={mt['edge_vs_price']:+.2%}")
                else:
                    city_result["calibration_error"] = "sem resultados válidos (min_entries?"
                    print(f"  [WARN] calibração sem resultados válidos")
            except Exception as e:
                city_result["calibration_error"] = str(e)
                print(f"  [ERRO] calibração: {e}")
                traceback.print_exc()

        summary["cities"][city] = city_result

    # ── Summary ──
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    # ── Relatório final ──
    print(f"\n{'='*60}")
    print(f" FASE 4 — RESUMO")
    print(f"{'='*60}")
    print(f"{'Cidade':<12} {'Entries':>8} {'Hit%':>7} {'Edge%':>7} "
          f"{'P&L':>8} {'Threshold':>10}")
    print("-" * 60)

    n_ok = 0
    n_err = 0
    for city, res in summary["cities"].items():
        bt = res.get("backtest", {})
        cal = res.get("calibration", {})
        if bt or cal:
            entries = bt.get("entries", "-")
            hit = bt.get("hit_rate", 0)
            edge = bt.get("edge_vs_price", 0)
            pnl = bt.get("pnl", 0)
            thr = cal.get("best_params", {}).get("threshold", "-")
            print(f"{city:<12} {entries:>8} {hit*100:>6.1f}% {edge*100:>+6.1f}% "
                  f"{pnl:>+8.2f} {thr:>10}")
            n_ok += 1
        else:
            err = res.get("backtest_error") or res.get("calibration_error")
            print(f"{city:<12} [ERRO: {err[:40] if err else 'desconhecido'}]")
            n_err += 1

    print("-" * 60)
    print(f"  OK: {n_ok} cidades  |  Erros: {n_err}")
    print(f"  Resultados em: {output_dir}")
    print(f"  Summary: {summary_path}")
    print()

    if n_err > 0:
        print("  Para ver erros detalhados:")
        print(f"    cat {output_dir}/summary.json | python -m json.tool")
    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
