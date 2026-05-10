"""
calibrate_all.py
================
Wrapper de calibração multi-cidade.

Itera sobre cidades, calibra cada uma usando run_calibration() do calibrate.py,
compara com strategy_config_{city}.json existente, e só sobrescreve se a nova
calibração for melhor por uma margem mínima (default 5%).

Uso:
    python calibrate_all.py                           # todas as cidades
    python calibrate_all.py --cities munich,dallas    # subset
    python calibrate_all.py --mode full               # mode override
    python calibrate_all.py --years 3                 # menos anos
    python calibrate_all.py --dry-run                 # ver sem escrever
    python calibrate_all.py --force-write             # ignora margem (escreve sempre)
    python calibrate_all.py --margin 0.10             # margem 10% (default 5%)

Saída:
    - strategy_config_{city}.json: actualizado se calibração nova é melhor
    - backups/calibrate_all_{timestamp}/: backups dos JSON antigos
    - Tabela comparativa final no terminal
"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich import box as rich_box

from cities.config import CITIES
from calibrate import run_calibration


_console = Console()

DEFAULT_MIN_IMPROVEMENT = 0.05  # 5%


# ════════════════════════════════════════════════════════
#  JSON I/O
# ════════════════════════════════════════════════════════

def load_existing_config(city_name: str) -> dict | None:
    """Lê strategy_config_{city}.json se existir, senão None."""
    cfg_path = Path(__file__).parent / f"strategy_config_{city_name}.json"
    if not cfg_path.exists():
        return None
    try:
        return json.loads(cfg_path.read_text())
    except Exception as e:
        _console.print(f"  [yellow]Warning: failed to read {cfg_path}: {e}[/yellow]")
        return None


def get_existing_metric(cfg: dict | None, metric_name: str = "outcome_score") -> float | None:
    """Extrai outcome_score da config existente. None se não existe."""
    if not cfg:
        return None
    meta = cfg.get("_meta", {})
    return meta.get(metric_name)


def get_existing_thresholds(cfg: dict | None) -> tuple[float | None, int | None]:
    """Extrai (threshold, hour_min) da config existente."""
    if not cfg:
        return None, None
    single = cfg.get("single", {})
    return single.get("threshold"), single.get("hour_min")


def backup_config(city_name: str, backup_dir: Path) -> Path | None:
    """Faz backup do strategy_config_{city}.json se existir."""
    cfg_path = Path(__file__).parent / f"strategy_config_{city_name}.json"
    if not cfg_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / cfg_path.name
    shutil.copy2(cfg_path, target)
    return target


def write_config(city_name: str, calibration: dict, existing: dict | None) -> Path:
    """
    Escreve strategy_config_{city}.json com nova calibração.

    Preserva chaves não-single do existente (ex: dual config).
    Adiciona/actualiza _meta com info da calibração.
    """
    cfg_path = Path(__file__).parent / f"strategy_config_{city_name}.json"

    # Preservar config existente (especialmente dual)
    new_cfg = dict(existing) if existing else {}

    # Garantir bloco single
    single_block = new_cfg.get("single", {})
    single_block["threshold"] = calibration["threshold"]
    single_block["hour_min"] = calibration["hour_min"]
    # Manter stop_loss_delta existente, ou default 1.0
    if "stop_loss_delta" not in single_block:
        single_block["stop_loss_delta"] = 1.0
    new_cfg["single"] = single_block

    # Meta
    new_cfg["_meta"] = {
        "outcome_score":    calibration["outcome_score"],
        "win_pct":          calibration["win_pct"],
        "trades_per_year":  calibration["trades_per_year"],
        "n_trades":         calibration["n_trades"],
        "median_lag_h":     calibration.get("median_lag_h", 0),
        "data_period":      calibration["data_period"],
        "selection_period":  calibration.get("selection_period"),
        "validation_period": calibration.get("validation_period"),
        "validation_years":  calibration.get("validation_years", []),
        "selection":         calibration.get("selection"),
        "validation":        calibration.get("validation"),
        "n_days":           calibration["n_days"],
        "metric":           calibration["metric"],
        "mode":             calibration["mode"],
        "years":            calibration["years"],
        "calibrated_at":    datetime.now().isoformat(timespec="seconds"),
        "calibrated_with":  "calibrate_all.py",
    }

    cfg_path.write_text(json.dumps(new_cfg, indent=2, ensure_ascii=False))
    return cfg_path


# ════════════════════════════════════════════════════════
#  COMPARAÇÃO E DECISÃO
# ════════════════════════════════════════════════════════

def decide_action(new_cal: dict, old_cfg: dict | None,
                  margin: float, force: bool) -> tuple[str, str]:
    """
    Decide se actualiza, mantém ou cria.

    Returns: (action, reason)
        action ∈ {'CREATE', 'UPDATE', 'KEEP'}
    """
    if not old_cfg:
        return "CREATE", "no existing config"

    if force:
        return "UPDATE", "--force-write"

    old_score = get_existing_metric(old_cfg, "outcome_score")
    new_score = new_cal.get("outcome_score", 0)

    if old_score is None:
        return "UPDATE", "existing has no _meta.outcome_score"

    # Margem mínima
    threshold = old_score * (1 + margin)
    if new_score >= threshold:
        improvement_pct = (new_score - old_score) / old_score * 100 if old_score else 0
        return "UPDATE", f"+{improvement_pct:.1f}% (>= {margin*100:.0f}% threshold)"

    diff_pct = (new_score - old_score) / old_score * 100 if old_score else 0
    return "KEEP", f"{diff_pct:+.1f}% (below {margin*100:.0f}% threshold)"


# ════════════════════════════════════════════════════════
#  TABELA COMPARATIVA
# ════════════════════════════════════════════════════════

def print_summary_table(rows: list[dict], dry_run: bool = False) -> None:
    """Imprime tabela comparativa final."""
    table = Table(box=rich_box.ROUNDED, border_style="cyan",
                  title="CALIBRATE ALL — Comparativo", title_style="bold cyan")
    table.add_column("Cidade",     justify="left",  style="bold")
    table.add_column("Old thr",    justify="right")
    table.add_column("New thr",    justify="right")
    table.add_column("Old hmin",   justify="right")
    table.add_column("New hmin",   justify="right")
    table.add_column("Old score",  justify="right")
    table.add_column("New score",  justify="right")
    table.add_column("Δ",          justify="right")
    table.add_column("Win%",       justify="right")
    table.add_column("Val Win%",   justify="right")
    table.add_column("Trades/yr",  justify="right")
    table.add_column("Action",     justify="center")

    for row in rows:
        if row.get("error"):
            table.add_row(row["city"], "—", "—", "—", "—", "—", "—", "—", "—", "—", "—",
                          f"[red]ERROR[/red]")
            continue

        cal = row["calibration"]
        old_thr, old_hmin = row["old_threshold"], row["old_hour_min"]
        old_score = row.get("old_score")
        new_score = cal["outcome_score"]

        # Δ
        if old_score is not None and old_score > 0:
            delta_pct = (new_score - old_score) / old_score * 100
            delta_str = f"{delta_pct:+.1f}%"
            if delta_pct > 0:
                delta_str = f"[green]{delta_str}[/green]"
            elif delta_pct < 0:
                delta_str = f"[red]{delta_str}[/red]"
        else:
            delta_str = "[dim]—[/dim]"

        # Action style
        action = row["action"]
        if action == "UPDATE":
            action_str = "[green]✓ UPDATE[/green]" if not dry_run else "[yellow]→ would UPDATE[/yellow]"
        elif action == "CREATE":
            action_str = "[cyan]+ CREATE[/cyan]" if not dry_run else "[yellow]→ would CREATE[/yellow]"
        else:
            action_str = "[dim]⏸ KEEP[/dim]"

        table.add_row(
            row["city"],
            f"{old_thr:.3f}" if old_thr is not None else "—",
            f"{cal['threshold']:.3f}",
            str(old_hmin) if old_hmin is not None else "—",
            str(cal["hour_min"]),
            f"{old_score:.3f}" if old_score is not None else "[dim]—[/dim]",
            f"{new_score:.3f}",
            delta_str,
            f"{cal['win_pct']:.1f}%",
            f"{cal['validation']['win_pct']:.1f}%" if cal.get("validation") else "—",
            f"{cal['trades_per_year']:.0f}",
            action_str,
        )

    _console.print(table)


# ════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Calibração multi-cidade (single strategy).",
    )
    parser.add_argument("--cities", type=str, default=None,
                        help="Cidades separadas por vírgula. Default: todas em CITIES.")
    parser.add_argument("--years", type=int, default=5,
                        help="Anos de histórico (default 5)")
    parser.add_argument("--mode", choices=["fast", "standard", "detailed", "full"],
                        default="standard",
                        help="Densidade do grid (default: standard)")
    parser.add_argument("--metric", choices=["outcome", "roi"], default="outcome",
                        help="Métrica de optimização (default: outcome)")
    parser.add_argument("--margin", type=float, default=DEFAULT_MIN_IMPROVEMENT,
                        help=f"Margem mínima de melhoria para sobrescrever "
                             f"(default {DEFAULT_MIN_IMPROVEMENT*100:.0f}%%)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra resultados mas NÃO escreve nem faz backup")
    parser.add_argument("--force-write", action="store_true",
                        help="Sobrescreve mesmo se calibração nova é pior (cuidado)")
    parser.add_argument("--realistic", action="store_true",
                        help="Usa SimulatedMarket realista (preços com ruído)")
    args = parser.parse_args()

    # Cidades alvo
    if args.cities:
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
    _console.print(f" [bold cyan]CALIBRATE ALL[/bold cyan] — multi-cidade", justify="center")
    _console.print("=" * 70, style="cyan")
    _console.print(f"  Cidades:    {', '.join(city_names)}")
    _console.print(f"  Modo grid:  {args.mode}")
    _console.print(f"  Métrica:    {args.metric}")
    _console.print(f"  Anos:       {args.years}")
    _console.print(f"  Margin:     {args.margin*100:.0f}% (mínimo para sobrescrever)")
    if args.dry_run:
        _console.print("  [yellow]DRY-RUN: nenhum ficheiro será escrito[/yellow]")
    if args.force_write:
        _console.print("  [yellow]FORCE-WRITE: ignora margem[/yellow]")
    _console.print()

    # Backup dir (mesmo se não escrever, criar antes para consistência se vamos escrever)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path("backups") / f"calibrate_all_{timestamp}"

    # Calibrar cada cidade
    rows = []
    for i, city_name in enumerate(city_names, 1):
        _console.print(f"\n[bold cyan][{i}/{len(city_names)}] Calibrando {city_name}...[/bold cyan]")

        # Calibrar
        try:
            cal = run_calibration(
                city_name=city_name,
                years=args.years,
                mode=args.mode,
                metric=args.metric,
                realistic=args.realistic,
                quiet=False,
            )
        except Exception as e:
            _console.print(f"  [red]Failed: {e}[/red]")
            rows.append({"city": city_name, "error": str(e)})
            continue

        if cal is None:
            _console.print(f"  [red]Calibration returned no result[/red]")
            rows.append({"city": city_name, "error": "no result"})
            continue

        # Carregar config existente
        old_cfg = load_existing_config(city_name)
        old_thr, old_hmin = get_existing_thresholds(old_cfg)
        old_score = get_existing_metric(old_cfg, "outcome_score")

        # Decidir
        action, reason = decide_action(cal, old_cfg, args.margin, args.force_write)

        rows.append({
            "city":           city_name,
            "calibration":    cal,
            "old_threshold":  old_thr,
            "old_hour_min":   old_hmin,
            "old_score":      old_score,
            "action":         action,
            "reason":         reason,
        })

        val_win_str = (
            f"val_win={cal['validation']['win_pct']:.1f}%, "
            if cal.get("validation") else ""
        )
        _console.print(f"  Result: thr={cal['threshold']:.3f}, hmin={cal['hour_min']}, "
                       f"score={cal['outcome_score']:.3f}, "
                       f"win={cal['win_pct']:.1f}%, "
                       f"{val_win_str}"
                       f"trades/yr={cal['trades_per_year']:.0f}")
        _console.print(f"  Action: [bold]{action}[/bold] — {reason}")

    # Aplicar mudanças
    _console.print()
    _console.print("=" * 70, style="cyan")
    _console.print(" [bold cyan]Resumo final[/bold cyan]", justify="center")
    _console.print("=" * 70, style="cyan")

    print_summary_table(rows, dry_run=args.dry_run)

    if args.dry_run:
        _console.print("\n[yellow]DRY-RUN: nenhum ficheiro foi escrito. "
                       "Remove --dry-run para aplicar mudanças.[/yellow]\n")
        return

    # Escrever ficheiros
    written_count = 0
    backed_up = []
    for row in rows:
        if row.get("error"):
            continue
        if row["action"] not in ("UPDATE", "CREATE"):
            continue

        city_name = row["city"]
        cal = row["calibration"]
        old_cfg = load_existing_config(city_name)

        # Backup obrigatório (sempre antes de escrever)
        if old_cfg is not None:
            backup_path = backup_config(city_name, backup_dir)
            if backup_path:
                backed_up.append(backup_path)

        # Escrever
        try:
            written_path = write_config(city_name, cal, old_cfg)
            _console.print(f"  [green]✓[/green] {written_path.name} written")
            written_count += 1
        except Exception as e:
            _console.print(f"  [red]✗ {city_name}: write failed: {e}[/red]")

    _console.print()
    _console.print(f"  Files written/updated:  [bold]{written_count}[/bold]")
    _console.print(f"  Files unchanged:         {len(rows) - written_count - sum(1 for r in rows if r.get('error'))}")
    if backed_up:
        _console.print(f"  Backups in:              [dim]{backup_dir}/[/dim]")
    _console.print()


if __name__ == "__main__":
    main()
