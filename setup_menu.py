#!/usr/bin/env python3
"""
Script de configuração final do menu interativo
==============================================
Este script garante que tudo está configurado corretamente para usar o menu.
"""

import os
import sys
from pathlib import Path

def final_setup():
    """Configuração final."""
    
    print("🔧 Configuração Final do Menu Interativo")
    print("=" * 50)
    
    # Verificar se estamos no diretório correto
    if not Path("tg.py").exists():
        print("❌ Execute este script no diretório do projeto")
        return False
    
    # Verificar variáveis de ambiente
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    
    if not token or not chat_id:
        print("❌ Configure as variáveis de ambiente:")
        print("   export TELEGRAM_TOKEN=seu_token_aqui")
        print("   export TELEGRAM_CHAT_ID=seu_chat_id_aqui")
        return False
    
    # Criar arquivo .env se não existir
    env_file = Path(".env")
    if not env_file.exists():
        with open(env_file, "w") as f:
            f.write(f"TELEGRAM_TOKEN={token}\n")
            f.write(f"TELEGRAM_CHAT_ID={chat_id}\n")
        print("✅ Arquivo .env criado")
    
    # Verificar se os arquivos necessários existem
    required_files = [
        "tg.py",
        "live_bot.py",
        "trade_ledger.py",
        "cities/config.py"
    ]
    
    for file_name in required_files:
        if Path(file_name).exists():
            print(f"✅ {file_name} existe")
        else:
            print(f"❌ {file_name} não encontrado")
            return False
    
    # Testar import
    try:
        from tg import TG
        tg = TG()
        print("✅ TG importado com sucesso")
    except Exception as e:
        print(f"❌ Erro ao importar TG: {e}")
        return False
    
    print("\n🎉 Tudo configurado!")
    print("\n📱 Para usar o menu:")
    print("1. Inicie o bot: python live_bot.py --cities munich --mode single --run paper")
    print("2. Envie /menu no seu Telegram")
    print("3. Clique nos botões para ver detalhes")
    
    return True

if __name__ == "__main__":
    success = final_setup()
    sys.exit(0 if success else 1)