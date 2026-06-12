#!/usr/bin/env python3
"""
Análise completa dos backtests desde 2010
"""
import json
import os
from datetime import datetime
import pandas as pd

def load_backtest_results():
    """Carrega todos os resultados de backtest"""
    results = []
    backtest_dir = "backtest_results"
    
    for filename in os.listdir(backtest_dir):
        if filename.endswith("_backtest_single_") and filename.endswith(".json"):
            # Extrair cidade e datas do nome do arquivo
            parts = filename.replace(".json", "").split("_")
            if len(parts) >= 5:
                city = parts[0]
                start_date = parts[3]
                end_date = parts[4]
                
                try:
                    with open(os.path.join(backtest_dir, filename), 'r') as f:
                        data = json.load(f)
                        results.append({
                            'city': city,
                            'start_date': start_date,
                            'end_date': end_date,
                            **data['single']
                        })
                except Exception as e:
                    print(f"Erro ao carregar {filename}: {e}")
    
    return results

def calculate_daily_weekly_stats(results):
    """Calcula estatísticas diárias e semanais"""
    total_days = 0
    total_trades = 0
    total_pnl = 0
    
    for result in results:
        days = result['total_days']
        trades = result['total_days'] * result['correct_pct'] / 100  # Estimativa
        
        total_days += days
        total_trades += trades
        total_pnl += result['total_pnl']
    
    daily_trades = total_trades / total_days if total_days > 0 else 0
    weekly_trades = daily_trades * 7
    
    return {
        'total_days': total_days,
        'total_trades': total_trades,
        'total_pnl': total_pnl,
        'daily_trades': daily_trades,
        'weekly_trades': weekly_trades
    }

def generate_report():
    """Gera relatório completo"""
    print("=" * 60)
    print("ANÁLISE COMPLETA DE BACKTESTS DESDE 2010")
    print("=" * 60)
    
    # Carregar resultados
    results = load_backtest_results()
    
    if not results:
        print("Nenhum resultado de backtest encontrado!")
        return
    
    # Calcular estatísticas
    stats = calculate_daily_weekly_stats(results)
    
    print(f"\nPERÍODO ANALISADO:")
    print(f"  De: 2010-01-01 até: 2026-06-10")
    print(f"  Total de dias: {stats['total_days']:,}")
    print(f"  Total de trades: {stats['total_trades']:,.1f}")
    print(f"  Total PnL: ${stats['total_pnl']:,.2f}")
    
    print(f"\nFREQUÊNCIA DE TRADES:")
    print(f"  Média diária: {stats['daily_trades']:.2f} trades/dia")
    print(f"  Média semanal: {stats['weekly_trades']:.2f} trades/semana")
    
    print(f"\nDETALHES POR CIDADE E PERÍODO:")
    print("-" * 80)
    
    for result in results:
        print(f"\n{result['city'].upper()} ({result['start_date']} até {result['end_date']}):")
        print(f"  Trades: {result['total_days'] * result['correct_pct'] / 100:,.1f}")
        print(f"  PnL: ${result['total_pnl']:,.2f}")
        print(f"  Win Rate: {result['correct_pct']:.1f}%")
        print(f"  Sharpe: {result['sharpe']:.2f}")
        print(f"  Sortino: {result['sortino']:.2f}")
        
        # Estatísticas sazonais
        seasonal = result['seasonal_stats']
        print(f"  Trades por estação:")
        for season in ['winter', 'spring', 'summer', 'autumn']:
            season_data = seasonal[season]
            print(f"    {season}: {season_data['n_trades']} trades ({season_data['win_pct']:.1f}% win)")
    
    print(f"\nRESUMO GERAL:")
    print("-" * 40)
    avg_sharpe = sum(r['sharpe'] for r in results) / len(results)
    avg_sortino = sum(r['sortino'] for r in results) / len(results)
    avg_win_rate = sum(r['correct_pct'] for r in results) / len(results)
    
    print(f"  Sharpe médio: {avg_sharpe:.2f}")
    print(f"  Sortino médio: {avg_sortino:.2f}")
    print(f"  Win rate médio: {avg_win_rate:.1f}%")
    print(f"  Sharpe/Sortino ratio: {avg_sharpe/avg_sortino:.3f}")

if __name__ == "__main__":
    generate_report()