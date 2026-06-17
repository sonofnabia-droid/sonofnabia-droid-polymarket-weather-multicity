#!/usr/bin/env python3
"""
Análise dos logs do bot para entender a discrepância de P&L
"""

import json
from pathlib import Path
from datetime import datetime, date
import sys

def analyze_daily_stats():
    """Analisar os arquivos de estatísticas diárias"""
    LOG_DIR = Path("live_bot_logs")
    
    print("=== ANÁLISE DE LOGS ===\n")
    
    # 1. Verificar arquivos de estatísticas diárias
    print("1. Arquivos de estatísticas diárias:")
    stats_files = list(LOG_DIR.glob("*_2026-06-*.json"))
    stats_files = [f for f in stats_files if not f.name.startswith("bets_") and not f.name.startswith("orders_")]
    
    for f in sorted(stats_files):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                city_name = f.stem.replace("_2026-06-12", "").replace("_2026-06-11", "")
                daily_pnl = data.get("daily_pnl", 0.0)
                print(f"   {city_name}: ${daily_pnl:.2f}")
        except Exception as e:
            print(f"   {f.name}: ERRO - {e}")
    
    print()
    
    # 2. Verificar trade ledger
    print("2. Trade Ledger (últimas entradas):")
    trade_ledger = LOG_DIR / "trade_ledger.jsonl"
    
    if trade_ledger.exists():
        with open(trade_ledger, 'r') as f:
            lines = f.readlines()
            
        # Últimas 10 entradas
        recent_lines = lines[-10:] if len(lines) > 10 else lines
        
        for line in recent_lines:
            try:
                entry = json.loads(line.strip())
                if entry.get("event_type") in ["BET_OPEN", "BET_CLOSE"]:
                    print(f"   {entry.get('ts', 'N/A')} - {entry.get('event_type')} - {entry.get('city', 'N/A')} - ${entry.get('size_usdc', 0):.2f}")
            except Exception as e:
                print(f"   ERRO ao parsear: {e}")
    
    print()
    
    # 3. Verificar snapshot atual
    print("3. Snapshot atual:")
    snapshot = LOG_DIR / "live_snapshot.json"
    
    if snapshot.exists():
        with open(snapshot, 'r') as f:
            data = json.load(f)
            
        session_stats = data.get("session", {})
        summary = data.get("summary", {})
        
        print(f"   Modo: {data.get('trading_mode', 'N/A')}")
        print(f"   Total trades: {session_stats.get('total_trades', 0)}")
        print(f"   Total P&L: ${session_stats.get('total_pnl', 0):.2f}")
        print(f"   P&L diário: ${summary.get('daily_pnl', 0):.2f}")
        print(f"   Trades diários: {summary.get('daily_trades', 0)}")
        
        # Verificar cidades individuais
        cities = data.get("cities", [])
        print(f"\n   P&L por cidade:")
        for city in cities:
            name = city.get("name", "N/A")
            pnl = city.get("daily_pnl", 0.0)
            print(f"   {name}: ${pnl:.2f}")
    
    print()
    
    # 4. Verificar arquivos de apostas
    print("4. Arquivos de apostas:")
    bet_files = list(LOG_DIR.glob("bets_*_2026-06-*.json"))
    
    for f in sorted(bet_files):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                if isinstance(data, list) and data:
                    city_name = f.stem.replace("bets_", "").replace("_2026-06-12", "").replace("_2026-06-11", "")
                    print(f"   {city_name}: {len(data)} apostas")
                    for bet in data[-3:]:  # Últimas 3 apostas
                        print(f"     - {bet.get('time', 'N/A')} - ${bet.get('size_usdc', 0):.2f} - {bet.get('bracket', 'N/A')}")
                else:
                    city_name = f.stem.replace("bets_", "").replace("_2026-06-12", "").replace("_2026-06-11", "")
                    print(f"   {city_name}: 0 apostas")
        except Exception as e:
            print(f"   {f.name}: ERRO - {e}")

def analyze_telegram_reports():
    """Analisar os relatórios do Telegram"""
    print("\n=== ANÁLISE DE RELATÓRIOS DO TELEGRAM ===\n")
    
    # Verificar se há logs do Telegram
    LOG_DIR = Path("live_bot_logs")
    
    # Verificar positions
    positions_files = [
        LOG_DIR / "paper_positions.json",
        LOG_DIR / "real_positions.json"
    ]
    
    for f in positions_files:
        if f.exists():
            with open(f, 'r') as file:
                data = json.load(file)
                print(f"{f.name}: {len(data)} posições")
                for pos in data:
                    print(f"   - {pos.get('city', 'N/A')}: ${pos.get('size_usdc', 0):.2f}")

if __name__ == "__main__":
    analyze_daily_stats()
    analyze_telegram_reports()
    
    print("\n=== CONCLUSÕES ===")
    print("1. O P&L total de $13.95 parece vir de cálculos acumulados ou backfills")
    print("2. As cidades individuais mostram $0.00, indicando que não houve trades recentes")
    print("3. A única aposta mencionada pode ser de um backfill ou teste anterior")
    print("4. O bot pode estar em modo paper sem trades reais")