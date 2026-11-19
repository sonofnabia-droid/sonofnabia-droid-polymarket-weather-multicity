"""
cassiopeia_strategy.py v2
=========================
Wrapper fino sobre o cassiopeia_backtester v3.

CORREÇÃO FUNDAMENTAL: este ficheiro tinha placeholders divergentes do backtester
(spread calculado diferente, prev7 errado, predict_rebound_prob = random.random()).
Parâmetros calibrados no backtester eram inválidos aqui. Agora delega 100%
ao backtester v3 → paridade total calibração ↔ estratégia.

Este módulo NÃO faz trading real — é simulação/preview com a mesma semântica
do backtest. Trading real usa CassiopeiaEntry (cassiopeia_entry.py).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import argparse

try:
    from cassiopeia_params import resolve_params
except ImportError:
    resolve_params = None

from cassiopeia_backtester import run_backtest


def run_strategy(city: str, csv_path: str | None = None,
                 verbose: bool = False, use_ml: bool = True, **params) -> dict:
    """Corre a estratégia Cassiopeia com exatamente a mesma lógica do backtester."""
    results = run_backtest(city, csv_path=csv_path, verbose=verbose,
                           use_ml=use_ml, **params)
    print(f"\n📊 Cassiopeia — {city.upper()}")
    print(f"   entradas={results['entries']}  hit={results['hit_rate']:.2%}")
    print(f"   breakeven={results['breakeven_hit_rate']:.3f}  "
          f"edge={results['edge_vs_price']:+.2%}")
    print(f"   pnl={results['pnl']:+.3f}  roi={results['roi']:+.2%}  "
          f"max_dd={results['max_drawdown']:+.3f}")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Cassiopeia Strategy (wrapper sobre backtester v3)")
    parser.add_argument("--city", required=True)
    parser.add_argument("--csv")
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--spread", type=float, dest="min_spread")
    parser.add_argument("--bracket-half", type=float)
    parser.add_argument("--start-hour", type=int)
    parser.add_argument("--end-hour", type=int)
    parser.add_argument("--outlier-cap", type=float)
    parser.add_argument("--entry-price", type=float)
    parser.add_argument("--fee-rate", type=float)
    parser.add_argument("--auto-params", action="store_true",
                        help="Usa parâmetros do cassiopeia_active_config.json")
    parser.add_argument("--no-ml", action="store_true")
    parser.add_argument("--verbose", action="store_true",
                        help="Logs detalhados por slot")
    args = parser.parse_args()

    city = args.city.lower().strip()

    cli_overrides = {
        k: v for k, v in {
            "threshold": args.threshold, "min_spread": args.min_spread,
            "bracket_half": args.bracket_half, "start_hour": args.start_hour,
            "end_hour": args.end_hour, "outlier_cap": args.outlier_cap,
            "entry_price": args.entry_price, "fee_rate": args.fee_rate,
        }.items() if v is not None
    }

    if args.auto_params and resolve_params is not None:
        params = resolve_params(city, **cli_overrides)
        print("📡 Parâmetros carregados do active config.")
    else:
        params = cli_overrides
        print("⚙️  Parâmetros manuais / defaults.")

    run_strategy(city, csv_path=args.csv, verbose=args.verbose,
                 use_ml=not args.no_ml, **params)


if __name__ == "__main__":
    main()