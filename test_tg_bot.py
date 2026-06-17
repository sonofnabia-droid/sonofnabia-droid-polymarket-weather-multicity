#!/usr/bin/env python3
"""
Test script for Enhanced Telegram Bot
"""

import time
from pathlib import Path
import json
from datetime import datetime

# Importar o bot simplificado
try:
    from simplified_tg_bot import SimplifiedTGBot
    BOT_AVAILABLE = True
except ImportError:
    BOT_AVAILABLE = False
    print("Bot não disponível")

def test_dashboard():
    """Testar o dashboard do bot"""
    print("🤖 Testando Enhanced Telegram Bot\n")
    
    if not BOT_AVAILABLE:
        print("❌ Bot não disponível")
        return False
    
    # Iniciar bot
    bot = SimplifiedTGBot()
    
    # Testar carregamento de dados
    print("📊 Testando carregamento de dados...")
    snapshot_data = bot._load_snapshot_data()
    
    if snapshot_data:
        print("✅ Dados carregados com sucesso")
        print(f"   Modo: {snapshot_data.get('trading_mode', 'N/A')}")
        print(f"   Total trades: {snapshot_data.get('session', {}).get('total_trades', 0)}")
        print(f"   Total cidades: {len(snapshot_data.get('cities', []))}")
    else:
        print("❌ Falha ao carregar dados")
        return False
    
    # Testar geração de mensagem
    print("\n📝 Testando geração de mensagem...")
    message = bot._generate_dashboard_message(snapshot_data)
    
    if message:
        print("✅ Mensagem gerada com sucesso")
        print(f"   Tamanho: {len(message)} caracteres")
    else:
        print("❌ Falha ao gerar mensagem")
        return False
    
    # Testar envio (simulado)
    print("\n📤 Testando envio de mensagem...")
    success = bot.send("Mensagem de teste")
    
    if success:
        print("✅ Mensagem enviada com sucesso")
    else:
        print("❌ Falha ao enviar mensagem")
        return False
    
    return True

def test_probability_bar():
    """Testar a função de barra de probabilidade"""
    print("\n🎲 Testando barra de probabilidade...")
    
    bot = SimplifiedTGBot()
    
    test_values = [0.0, 0.01, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0]
    
    for value in test_values:
        bar = bot._probability_bar(value)
        print(f"   {value:.2f} -> {bar}")
    
    return True

def test_city_analysis():
    """Testar análise de cidades"""
    print("\n🌍 Testando análise de cidades...")
    
    bot = SimplifiedTGBot()
    snapshot_data = bot._load_snapshot_data()
    
    if not snapshot_data:
        print("❌ Dados não disponíveis")
        return False
    
    cities = snapshot_data.get("cities", [])
    
    if not cities:
        print("❌ Nenhuma cidade encontrada")
        return False
    
    # Ordenar por temperatura máxima
    sorted_by_temp = sorted(cities, key=lambda x: x.get("running_max", 0), reverse=True)
    print("\n🌡️ Cidades por temperatura máxima:")
    for city in sorted_by_temp[:5]:
        print(f"   {city['name'].title()}: {city['running_max']:.1f}°C")
    
    # Ordenar por probabilidade
    sorted_by_prob = sorted(cities, key=lambda x: x.get("p_ensemble", 0), reverse=True)
    print("\n🧒 Cidades por probabilidade de pico:")
    for city in sorted_by_prob[:5]:
        prob = city['p_ensemble'] * 100
        print(f"   {city['name'].title()}: {prob:.1f}%")
    
    return True

if __name__ == "__main__":
    print("🧪 Enhanced Telegram Bot Test Suite\n")
    
    # Executar testes
    tests = [
        ("Dashboard", test_dashboard),
        ("Probability Bar", test_probability_bar),
        ("City Analysis", test_city_analysis)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"🧪 Testando: {test_name}")
        print('='*50)
        
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                print(f"✅ {test_name}: PASS")
            else:
                print(f"❌ {test_name}: FAIL")
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            results.append((test_name, False))
    
    # Resumo
    print(f"\n{'='*50}")
    print("📊 TEST SUMMARY")
    print('='*50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {test_name}: {status}")
    
    print(f"\n📈 Resultado: {passed}/{total} testes passados")
    
    if passed == total:
        print("🎉 Todos os testes passaram!")
    else:
        print("⚠️  Alguns testes falharam")
    
    print(f"\n{'='*50}")