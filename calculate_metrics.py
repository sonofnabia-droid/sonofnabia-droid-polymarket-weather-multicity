#!/usr/bin/env python3
import os
import json
from pathlib import Path
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box as rich_box

def main():
    console = Console()
    backtest_dir = Path("backtest_results")
    
    # 1. Encontrar todos os ficheiros de backtest mais recentes para o período 2010-01-01
    # Vamos agrupar por cidade e pegar o que tem a data de fim mais recente.
    files = list(backtest_dir.glob("*_backtest_single_2010-01-01_*.json"))
    if not files:
        console.print("[red]Nenhum ficheiro de backtest JSON encontrado em 'backtest_results'![/red]")
        return
        
    by_city = {}
    for f in files:
        # Exemplo: munich_backtest_single_2010-01-01_2026-06-19.json
        parts = f.name.replace(".json", "").split("_")
        if len(parts) >= 5:
            city = parts[0]
            end_date = parts[-1]
            if city not in by_city or end_date > by_city[city]["end_date"]:
                by_city[city] = {
                    "file": f,
                    "end_date": end_date
                }
                
    results = []
    for city, info in sorted(by_city.items()):
        try:
            with open(info["file"], 'r') as f:
                data = json.load(f)
                results.append(data)
        except Exception as e:
            console.print(f"[red]Erro ao ler {info['file']}: {e}[/red]")
            
    if not results:
        console.print("[red]Não foi possível carregar nenhum resultado.[/red]")
        return
        
    # 2. Processar métricas por cidade
    rows = []
    total_trades_all = 0
    total_wins_all = 0
    total_pnl_all = 0
    max_days = 0
    sum_sharpe = 0
    sum_sortino = 0
    valid_sharpe_count = 0
    valid_sortino_count = 0
    
    seasonal_totals = {
        "winter": {"n_days": 0, "n_trades": 0, "n_correct": 0, "pnl": 0.0},
        "spring": {"n_days": 0, "n_trades": 0, "n_correct": 0, "pnl": 0.0},
        "summer": {"n_days": 0, "n_trades": 0, "n_correct": 0, "pnl": 0.0},
        "autumn": {"n_days": 0, "n_trades": 0, "n_correct": 0, "pnl": 0.0},
    }
    
    for r in results:
        city = r["city"]
        single = r["single"]
        total_days = single["total_days"]
        if total_days > max_days:
            max_days = total_days
            
        # Calcular total de trades exato somando o das estações
        s_stats = single["seasonal_stats"]
        n_trades = sum(s_stats[s]["n_trades"] for s in s_stats)
        n_correct = sum(round(s_stats[s]["n_trades"] * s_stats[s]["win_pct"] / 100) for s in s_stats)
        
        win_rate = (n_correct / n_trades * 100) if n_trades > 0 else 0.0
        bets_per_day = n_trades / total_days if total_days > 0 else 0.0
        bets_per_week = bets_per_day * 7
        
        pnl = single["total_pnl"]
        sharpe = single.get("sharpe")
        sortino = single.get("sortino")
        
        total_trades_all += n_trades
        total_wins_all += n_correct
        total_pnl_all += pnl
        
        if sharpe is not None and not pd.isna(sharpe):
            sum_sharpe += sharpe
            valid_sharpe_count += 1
        if sortino is not None and not pd.isna(sortino):
            sum_sortino += sortino
            valid_sortino_count += 1
            
        for s in seasonal_totals:
            if s in s_stats:
                seasonal_totals[s]["n_days"] += s_stats[s].get("n_days", 0)
                seasonal_totals[s]["n_trades"] += s_stats[s].get("n_trades", 0)
                seasonal_totals[s]["n_correct"] += round(s_stats[s]["n_trades"] * s_stats[s]["win_pct"] / 100)
                seasonal_totals[s]["pnl"] += s_stats[s].get("pnl", 0.0)
                
        rows.append({
            "city": city.upper(),
            "days": total_days,
            "trades": n_trades,
            "wins": n_correct,
            "win_rate": win_rate,
            "bets_day": bets_per_day,
            "bets_week": bets_per_week,
            "pnl": pnl,
            "sharpe": sharpe,
            "sortino": sortino
        })
        
    # 3. Mostrar tabela detalhada por cidade
    table = Table(title="Métricas de Backtest por Cidade (Desde 2010)", box=rich_box.ROUNDED)
    table.add_column("Cidade", justify="left", style="cyan bold")
    table.add_column("Dias", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Vitórias", justify="right")
    table.add_column("Win %", justify="right", style="green")
    table.add_column("Bets/Dia", justify="right", style="magenta")
    table.add_column("Bets/Semana", justify="right")
    table.add_column("PnL $", justify="right", style="blue")
    table.add_column("Sharpe", justify="right")
    table.add_column("Sortino", justify="right")
    
    for row in rows:
        sharpe_str = f"{row['sharpe']:.2f}" if row['sharpe'] is not None else "N/A"
        sortino_str = f"{row['sortino']:.2f}" if row['sortino'] is not None else "N/A"
        table.add_row(
            row["city"],
            f"{row['days']:,}",
            f"{row['trades']:,}",
            f"{row['wins']:,}",
            f"{row['win_rate']:.1f}%",
            f"{row['bets_day']:.3f}",
            f"{row['bets_week']:.2f}",
            f"${row['pnl']:+,.2f}",
            sharpe_str,
            sortino_str
        )
        
    console.print(table)
    
    # 4. Mostrar métricas agregadas (portfolio-level)
    avg_sharpe = sum_sharpe / valid_sharpe_count if valid_sharpe_count > 0 else 0.0
    avg_sortino = sum_sortino / valid_sortino_count if valid_sortino_count > 0 else 0.0
    portfolio_win_rate = (total_wins_all / total_trades_all * 100) if total_trades_all > 0 else 0.0
    
    # O total_days do portfolio é o máximo de dias de qualquer cidade, já que correm em paralelo.
    portfolio_bets_day = total_trades_all / max_days if max_days > 0 else 0.0
    portfolio_bets_week = portfolio_bets_day * 7
    
    console.print("\n" + "="*80)
    console.print("[bold yellow]MÉTRICAS AGREGADAS (PORTFÓLIO GLOBAL)[/bold yellow]")
    console.print("="*80)
    console.print(f"  • Cidades Celsius Analisadas: {len(results)}")
    console.print(f"  • Janela do Portfólio (Max Dias): {max_days:,} dias (~{max_days/365:.1f} anos)")
    console.print(f"  • Total de Apostas (Trades): {total_trades_all:,}")
    console.print(f"  • Total de Vitórias: {total_wins_all:,}")
    console.print(f"  • [bold green]Win Rate Global: {portfolio_win_rate:.2f}%[/bold green]")
    console.print(f"  • [bold magenta]Média de Bets/Dia (Portfólio): {portfolio_bets_day:.3f} bets/dia[/bold magenta] (agregado das {len(results)} cidades)")
    console.print(f"  • [bold]Média de Bets/Semana (Portfólio): {portfolio_bets_week:.2f} bets/semana[/bold]")
    console.print(f"  • [bold blue]PnL Acumulado Total: ${total_pnl_all:+,.2f}[/bold blue] (assumindo $5 fixo por aposta)")
    console.print(f"  • Sharpe Médio: {avg_sharpe:.2f}")
    console.print(f"  • Sortino Médio: {avg_sortino:.2f}")
    
    # 5. Mostrar breakdown sazonal
    table_season = Table(title="\nDistribuição e Performance Sazonal (Agregado)", box=rich_box.SIMPLE)
    table_season.add_column("Estação", justify="left", style="cyan")
    table_season.add_column("Dias", justify="right")
    table_season.add_column("Trades", justify="right")
    table_season.add_column("Win %", justify="right", style="green")
    table_season.add_column("Bets/Dia", justify="right", style="magenta")
    table_season.add_column("PnL Sazonal $", justify="right", style="blue")
    
    for s, s_data in seasonal_totals.items():
        s_win_pct = (s_data["n_correct"] / s_data["n_trades"] * 100) if s_data["n_trades"] > 0 else 0.0
        s_bets_day = s_data["n_trades"] / s_data["n_days"] if s_data["n_days"] > 0 else 0.0
        table_season.add_row(
            s.capitalize(),
            f"{s_data['n_days']:,}",
            f"{s_data['n_trades']:,}",
            f"{s_win_pct:.1f}%",
            f"{s_bets_day:.3f}",
            f"${s_data['pnl']:+,.2f}"
        )
    console.print(table_season)

if __name__ == "__main__":
    main()
