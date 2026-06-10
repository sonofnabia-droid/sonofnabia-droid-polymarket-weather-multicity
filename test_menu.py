#!/usr/bin/env python3
"""
Teste do menu interativo do Telegram Bot
=======================================
Script de teste para verificar se o menu funciona corretamente.
"""

import json
from pathlib import Path
from tg import TG

def test_menu_functionality():
    """Testa a funcionalidade do menu sem enviar para o Telegram."""
    
    print("🧪 Testando funcionalidade do menu interativo...")
    
    # Criar instância do TG
    tg = TG()
    
    # Testar se o TG está habilitado
    if not tg.enabled:
        print("❌ TG não está habilitado - definir TELEGRAM_TOKEN e TELEGRAM_CHAT_ID")
        return False
    
    print("✅ TG está habilitado")
    
    # Testar geração de resumo
    print("\n📊 Testando geração de resumo...")
    try:
        summary = tg._generate_daily_summary()
        print("✅ Resumo gerado com sucesso")
        print(f"Resumo: {summary[:200]}...")
    except Exception as e:
        print(f"❌ Erro ao gerar resumo: {e}")
    
    # Testar obtenção de posições abertas
    print("\n📂 Testando obtenção de posições abertas...")
    try:
        positions = tg._get_open_positions()
        print("✅ Posições obtidas com sucesso")
        print(f"Posições: {positions[:200]}...")
    except Exception as e:
        print(f"❌ Erro ao obter posições: {e}")
    
    # Testar obtenção de vitórias recentes
    print("\n🏆 Testando obtenção de vitórias recentes...")
    try:
        wins = tg._get_recent_wins()
        print("✅ Vitórias obtidas com sucesso")
        print(f"Vitórias: {wins[:200]}...")
    except Exception as e:
        print(f"❌ Erro ao obter vitórias: {e}")
    
    # Testar obtenção de status do bot
    print("\n⚙️ Testando obtenção de status do bot...")
    try:
        status = tg._get_bot_status()
        print("✅ Status obtido com sucesso")
        print(f"Status: {status[:200]}...")
    except Exception as e:
        print(f"❌ Erro ao obter status: {e}")
    
    print("\n🎉 Todos os testes concluídos!")
    return True

def test_file_access():
    """Testa acesso aos arquivos necessários."""
    
    print("\n📁 Testando acesso aos arquivos...")
    
    # Testar acesso ao trade_ledger.jsonl
    ledger_path = Path("live_bot_logs") / "trade_ledger.jsonl"
    if ledger_path.exists():
        print("✅ trade_ledger.jsonl encontrado")
    else:
        print("⚠️ trade_ledger.jsonl não encontrado - será criado automaticamente")
    
    # Testar acesso ao paper_positions.json
    paper_path = Path("live_bot_logs") / "paper_positions.json"
    if paper_path.exists():
        print("✅ paper_positions.json encontrado")
    else:
        print("⚠️ paper_positions.json não encontrado - será criado automaticamente")
    
    # Testar acesso ao real_positions.json
    real_path = Path("live_bot_logs") / "real_positions.json"
    if real_path.exists():
        print("✅ real_positions.json encontrado")
    else:
        print("⚠️ real_positions.json não encontrado - será criado automaticamente")

if __name__ == "__main__":
    print("=" * 50)
    print(" Teste do Menu Interativo do Telegram Bot")
    print("=" * 50)
    
    # Testar acesso aos arquivos
    test_file_access()
    
    # Testar funcionalidade do menu
    test_menu_functionality()