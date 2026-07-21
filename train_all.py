"""
train_all.py
============
Wrapper de treino multi-cidade.

Itera sobre cidades, treina cada uma usando run_training() do train.py,
e mostra resumo final comparativo.

Uso:
    python train_all.py                                 # todas as cidades
    python train_all.py --cities munich,dallas          # subset
    python train_all.py --no-wf                         # rápido (sem walk-forward)
    python train_all.py --skip-existing                 # pula cidades já treinadas

Saída:
    - cities/{city}/{city}_peak_model/lgbm_peak.pkl
    - cities/{city}/{city}_peak_model/peak_model_config.json
    - Tabela comparativa final (AUC walk-forward por cidade)
"""

import argparse
import os

from rich.console import Console
from rich.table import Table
from rich import box as rich_box

from cities.config import CITIES
from train import run_training


_console = Console()


def print_summary_table(rows: list[dict]) -> None:
    """Tabela comparativa final."""
    table = Table(box=rich_box.ROUNDED, border_style="cyan",
                  title="TRAIN ALL — Resumo", title_style="bold cyan")
    table.add_column("Cidade",      justify="left",  style="bold")
    table.add_column("Status",      justify="center")
    table.add_column("AUC WF",      justify="right")
    table.add_column("AUC In-Smp",  justify="right")
    table.add_column("Gap",         justify="right")
    table.add_column("N Rows",      justify="right")
    table.add_column("Model Dir",   justify="left", style="dim")

    for row in rows:
        if row.get("skipped"):
            table.add_row(row["city"], "[yellow]↷ SKIP[/yellow]", "—", "—", "—", "—",
                          "[dim]modelo já existe[/dim]")
            continue

        if row.get("error"):
            table.add_row(row["city"], "[red]ERROR[/red]", "—", "—", "—", "—",
                          f"[red]{row['error'][:30]}[/red]")
            continue

        result = row["result"]
        auc_wf = result.get("mean_auc_wf")
        auc_is = result.get("in_sample_auc")

        if auc_wf is None:
            auc_wf_str = "[dim]—[/dim]"
            gap_str = "[dim]—[/dim]"
        else:
            # Verde se >= 0.95, amarelo 0.90-0.95, vermelho < 0.90
            if auc_wf >= 0.95:
                colour = "green"
            elif auc_wf >= 0.90:
                colour = "yellow"
            else:
                colour = "red"
            auc_wf_str = f"[{colour}]{auc_wf:.4f}[/{colour}]"
            gap = (auc_is or 0) - auc_wf
            # Gap > 0.05 sugere overfit
            gap_colour = "yellow" if gap > 0.05 else "dim"
            gap_str = f"[{gap_colour}]{gap:+.3f}[/{gap_colour}]"

        auc_is_str = f"{auc_is:.4f}" if auc_is is not None else "—"

        table.add_row(
            row["city"],
            "[green]✓[/green]",
            auc_wf_str,
            auc_is_str,
            gap_str,
            f"{result.get('n_rows', 0):,}",
            result.get("model_dir", "—"),
        )

    _console.print(table)


def _model_exists(city_name: str) -> bool:
    """Verifica se o modelo já existe para a cidade."""
    model_path = f"cities/{city_name}/{city_name}_peak_model/lgbm_peak.pkl"
    return os.path.exists(model_path)


def main():
    parser = argparse.ArgumentParser(description="Treino multi-cidade")
    parser.add_argument("--cities", type=str, default=None,
                        help="Cidades separadas por vírgula. Default: todas em CITIES.")
    parser.add_argument("--no-wf", action="store_true",
                        help="Pula walk-forward (mais rápido, AUC menos honesto)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Pula cidades que já possuem modelo salvo")
    args = parser.parse_args()

    # Cidades alvo
    if args.cities:
        if args.cities.lower() == "all":
            city_names = [cfg.name for cfg in CITIES.values() if cfg.market_unit == "celsius"]
        else:
            city_names = [c.strip().lower() for c in args.cities.split(",")]
            for cn in city_names:
                if cn not in CITIES:
                    _console.print(f"[red]Erro: cidade desconhecida '{cn}'. "
                                   f"Disponíveis: {list(CITIES.keys())}[/red]")
                    return
    else:
        city_names = list(CITIES.keys())

    # Banner
    _console.print()
    _console.print("=" * 70, style="cyan")
    _console.print(f" [bold cyan]TRAIN ALL[/bold cyan] — multi-cidade", justify="center")
    _console.print("=" * 70, style="cyan")
    _console.print(f"  Cidades:    {', '.join(city_names)}")
    _console.print(f"  No-WF:      {args.no_wf}")
    _console.print(f"  Skip-Ex:    {args.skip_existing}")
    _console.print()

    # Treinar cada cidade
    rows = []
    for i, city_name in enumerate(city_names, 1):
        _console.print(f"\n[bold cyan][{i}/{len(city_names)}] Training {city_name}...[/bold cyan]")

        if args.skip_existing and _model_exists(city_name):
            _console.print(f"  [yellow]↷[/yellow] {city_name}: modelo já existe, pulando.")
            rows.append({"city": city_name, "skipped": True})
            continue

        try:
            result = run_training(city_name, no_wf=args.no_wf, quiet=False)
        except Exception as e:
            _console.print(f"  [red]Failed: {e}[/red]")
            rows.append({"city": city_name, "error": str(e)})
            continue

        if result is None:
            rows.append({"city": city_name, "error": "no result"})
            continue

        rows.append({
            "city":   city_name,
            "result": result,
        })

        auc_wf = result.get("mean_auc_wf")
        auc_str = f"{auc_wf:.4f}" if auc_wf is not None else "—"
        _console.print(f"  [green]✓[/green] {city_name}: AUC WF = {auc_str}, "
                       f"rows = {result.get('n_rows', 0):,}, "
                       f"saved to {result.get('model_dir', '?')}")

    # Resumo final
    _console.print()
    _console.print("=" * 70, style="cyan")
    _console.print(" [bold cyan]Resumo final[/bold cyan]", justify="center")
    _console.print("=" * 70, style="cyan")

    print_summary_table(rows)

    n_ok = sum(1 for r in rows if not r.get("error") and not r.get("skipped"))
    n_err = sum(1 for r in rows if r.get("error"))
    n_skip = sum(1 for r in rows if r.get("skipped"))
    _console.print(f"\n  Trained: [bold]{n_ok}[/bold]   Skipped: {n_skip}   Failed: {n_err}\n")


if __name__ == "__main__":
    main()
