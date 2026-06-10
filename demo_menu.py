#!/usr/bin/env python3
"""
Demonstração do menu interativo do Telegram Bot
=============================================
Este script demonstra como o menu interativo funciona.
"""

from tg import TG

def demo_menu():
    """Demonstra o menu interativo do Telegram Bot."""
    
    print("🤖 Demonstração do Menu Interativo do Telegram Bot")
    print("=" * 60)
    
    # Criar instância do TG
    tg = TG()
    
    if not tg.enabled:
        print("❌ Para usar o menu, configure as variáveis de ambiente:")
        print("   export TELEGRAM_TOKEN=seu_token_aqui")
        print("   export TELEGRAM_CHAT_ID=seu_chat_id_aqui")
        return
    
    print("\n📱 Comandos disponíveis:")
    print("  /menu     - Mostra o menu interativo com botões")
    print("  /resumo   - Resumo do dia: PnL, trades, win rate")
    print("  /posicoes - Posições abertas atuais")
    print("  /ultimas  - Últimas 5 vitórias")
    print("  /status   - Status do bot em todas as cidades")
    
    print("\n🎯 Como funciona:")
    print("1. Envie /menu no Telegram para ver o menu")
    print("2. Clique nos botões para ver detalhes")
    print("3. As informações são atualizadas em tempo real")
    print("4. O bot fica ativo enquanto o live_bot.py estiver rodando")
    
    print("\n📊 Exemplos de mensagens:")
    
    # Exemplo de resumo
    print("\n📈 Resumo do dia:")
    summary = tg._generate_daily_summary()
    print(summary)
    
    # Exemplo de posições
    print("\n📂 Posições abertas:")
    positions = tg._get_open_positions()
    print(positions)
    
    # Exemplo de vitórias
    print("\n🏆 Vitórias recentes:")
    wins = tg._get_recent_wins()
    print(wins)
    
    print("\n✅ Demonstração concluída!")

if __name__ == "__main__":
    demo_menu()