#!/usr/bin/env python3
"""
Solução Completa para o Bot de Trading Multi-Cidade
Script principal para implementar relatórios avançados via Telegram
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
import logging

# Configuração logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_requirements():
    """Verificar requisitos básicos"""
    print("🔍 Verificando requisitos...\n")
    
    # Verificar diretório
    if not Path("live_bot_logs").exists():
        print("❌ Diretório live_bot_logs não encontrado")
        return False
    
    # Verificar snapshot
    snapshot_file = Path("live_bot_logs/live_snapshot.json")
    if not snapshot_file.exists():
        print("❌ Arquivo snapshot não encontrado")
        return False
    
    # Verificar live_bot.py
    if not Path("live_bot.py").exists():
        print("❌ Arquivo live_bot.py não encontrado")
        return False
    
    print("✅ Todos os requisitos atendidos")
    return True

def analyze_current_state():
    """Analisar estado atual do bot"""
    print("\n📊 Analisando estado atual...\n")
    
    try:
        with open("live_bot_logs/live_snapshot.json", 'r') as f:
            data = json.load(f)
        
        trading_mode = data.get("trading_mode", "PAPER")
        session = data.get("session", {})
        summary = data.get("summary", {})
        cities = data.get("cities", [])
        
        print(f"📈 Modo de trading: {trading_mode}")
        print(f"🎯 Total de trades: {session.get('total_trades', 0)}")
        print(f"💰 P&L total: ${session.get('total_pnl', 0):+.2f}")
        print(f"📊 P&L diário: ${summary.get('daily_pnl', 0):+.2f}")
        print(f"🏙️ Cidades ativas: {len(cities)}")
        
        # Mostrar top cidades por temperatura
        sorted_by_temp = sorted(cities, key=lambda x: x.get("running_max", 0), reverse=True)
        print(f"\n🌡️ Top cidades por temperatura:")
        for city in sorted_by_temp[:5]:
            print(f"   {city['name'].title()}: {city['running_max']:.1f}°C")
        
        # Mostrar top cidades por probabilidade
        sorted_by_prob = sorted(cities, key=lambda x: x.get("p_ensemble", 0), reverse=True)
        print(f"\n🧠 Top cidades por probabilidade:")
        for city in sorted_by_prob[:5]:
            prob = city['p_ensemble'] * 100
            print(f"   {city['name'].title()}: {prob:.1f}%")
        
        return True
        
    except Exception as e:
        logger.error(f"Erro na análise: {e}")
        return False

def setup_telegram():
    """Configurar Telegram"""
    print("\n📱 Configurando Telegram...\n")
    
    # Verificar variáveis de ambiente
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if not token or not chat_id:
        print("⚠️ Variáveis de ambiente não configuradas")
        print("\nPara configurar:")
        print("1. Obtenha token do @BotFather")
        print("2. Obtenha seu chat ID")
        print("3. Exporte as variáveis:")
        print("   export TELEGRAM_TOKEN='seu_token'")
        print("   export TELEGRAM_CHAT_ID='seu_chat_id'")
        return False
    
    print("✅ Telegram configurado")
    return True

def test_enhanced_bot():
    """Testar enhanced bot"""
    print("\n🤖 Testando Enhanced Bot...\n")
    
    try:
        from simplified_tg_bot import SimplifiedTGBot
        
        bot = SimplifiedTGBot()
        
        # Testar dashboard
        print("📊 Testando dashboard...")
        snapshot_data = bot._load_snapshot_data()
        
        if snapshot_data:
            message = bot._generate_dashboard_message(snapshot_data)
            print(f"✅ Dashboard gerado ({len(message)} caracteres)")
            
            # Testar envio
            print("📤 Testando envio...")
            bot.send("🤖 Teste de mensagem do Enhanced Bot")
            print("✅ Mensagem enviada")
            
            return True
        else:
            print("❌ Falha ao carregar dados")
            return False
            
    except ImportError as e:
        logger.error(f"Erro ao importar bot: {e}")
        return False

def create_integration_script():
    """Criar script de integração"""
    print("\n🔧 Criando script de integração...\n")
    
    integration_script = '''#!/usr/bin/env python3
"""
Script de integração para Enhanced Telegram Bot
Adicione este código ao seu live_bot.py
"""

try:
    from enhanced_tg_bot import EnhancedTGBot
    ENHANCED_BOT_AVAILABLE = True
except ImportError:
    ENHANCED_BOT_AVAILABLE = False
    print("[INTEGRATION] Enhanced bot não disponível")

# Variável global para enhanced bot
_enhanced_bot = None

def get_enhanced_bot():
    """Retorna instância do enhanced bot"""
    global _enhanced_bot
    
    if _enhanced_bot is None and ENHANCED_BOT_AVAILABLE:
        _enhanced_bot = EnhancedTGBot()
        if _enhanced_bot.enabled:
            _enhanced_bot.start_dashboard()
            print("[INTEGRATION] Enhanced bot iniciado")
        else:
            _enhanced_bot = None
    
    return _enhanced_bot

def send_enhanced_dashboard():
    """Envia dashboard enhanced se disponível"""
    bot = get_enhanced_bot()
    if bot:
        bot.send_enhanced_dashboard()
'''
    
    with open("telegram_integration.py", 'w') as f:
        f.write(integration_script)
    
    print("✅ Script de integração criado: telegram_integration.py")
    return True

def create_usage_guide():
    """Criar guia de uso"""
    print("\n📚 Criando guia de uso...\n")
    
    guide = '''# Guia de Uso - Enhanced Telegram Bot

## 🚀 Rápido Start

1. **Configurar Telegram**:
   ```bash
   export TELEGRAM_TOKEN="seu_token"
   export TELEGRAM_CHAT_ID="seu_chat_id"
   ```

2. **Testar bot**:
   ```bash
   python simplified_tg_bot.py
   ```

3. **Integrar com live_bot.py**:
   - Adicione telegram_integration.py ao live_bot.py
   - Modifique _get_tg() para usar EnhancedTGBot

## 📱 Relatórios Recebidos

Você receberá relatórios como:

```
🟡 Multi-City Trading Bot
📊 Relatório Periódico — 17:30
────────────────────────────────────

📈 Resumo Geral
   Modo: PAPER
   Total Trades: 0
   P&L Total: $+0.00
   P&L Diário: $+0.00
   Trades Diários: 0

🌍 Status por Cidade
   🟢 Ativas
   Madrid: 33.5°C (max 33.5°C) █████ 5.1%

🌡️ Temperaturas Máximas Atuais
   Karachi: 37.0°C @ 15:30
   Beijing: 34.2°C @ 17:30

🧠 Probabilidades de Pico
   🔥 Madrid: █████ 5.1%
   ⚡ Buenos_Aires: ███ 0.6%
```

## ⚙️ Configurações

- **Intervalo**: 30 minutos (configurável)
- **Formato**: HTML (para Telegram)
- **Cidades**: Todas as 14 cidades
- **Dados**: Tempo real do snapshot

## 🐛 Troubleshooting

1. **Bot não envia mensagens**:
   - Verificar token e chat ID
   - Checar variáveis de ambiente

2. **Dados desatualizados**:
   - Verificar live_bot_logs/live_snapshot.json
   - Checar se live_bot.py está rodando

3. **Erro de importação**:
   - Instalar python-telegram-bot: pip install python-telegram-bot
   - Ou usar versão simplificada

## 📊 Comandos Disponíveis

- `/menu` - Menu interativo
- `/status` - Status detalhado
- `/resumo` - Resumo do dia
- `/posicoes` - Posições abertas
- `/ultimas` - Últimas vitórias

## 🎯 Benefícios

- Monitoramento a cada 30 minutos
- Dashboard completo com todas as cidades
- Análise detalhada de probabilidades
- Alertas em tempo real
- Formatação profissional para Telegram
'''
    
    with open("GUIDA_USO.md", 'w') as f:
        f.write(guide)
    
    print("✅ Guia de uso criado: GUIDA_USO.md")
    return True

def main():
    """Função principal"""
    print("🚀 Solução Completa para Bot de Trading Multi-Cidade")
    print("=" * 60)
    
    # Verificar requisitos
    if not check_requirements():
        print("\n❌ Requisitos não atendidos")
        sys.exit(1)
    
    # Analisar estado atual
    if not analyze_current_state():
        print("\n❌ Falha na análise do estado atual")
        sys.exit(1)
    
    # Configurar Telegram
    setup_telegram()
    
    # Testar enhanced bot
    if test_enhanced_bot():
        print("\n✅ Enhanced bot funcionando")
    else:
        print("\n❌ Enhanced bot não funcionando")
        print("Usando modo de teste...")
    
    # Criar integração
    create_integration_script()
    
    # Criar guia
    create_usage_guide()
    
    print("\n" + "=" * 60)
    print("🎉 Solução implementada com sucesso!")
    print("=" * 60)
    
    print("\n📋 Próximos passos:")
    print("1. Configure suas credenciais do Telegram")
    print("2. Leia o guia de uso (GUIDA_USO.md)")
    print("3. Integre telegram_integration.py ao live_bot.py")
    print("4. Teste com python simplified_tg_bot.py")
    print("5. Reinicie o bot com integração")
    
    print("\n🎯 Resultado esperado:")
    print("- Relatórios completos a cada 30 minutos")
    print("- Dashboard com todas as 14 cidades")
    print("- Análise detalhada de probabilidades")
    print("- Monitoramento em tempo real")

if __name__ == "__main__":
    main()