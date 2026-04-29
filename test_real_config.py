"""
test_real_config.py
===================
Script de validação da configuração REAL do Polymarket CLOB.

Testa:
  1. Inicialização do ClobClient com as credenciais
  2. Saldo USDC disponível
  3. Acesso ao order book público
  4. Geração e assinatura de ordem (dry-run)
  5. Verificação de parâmetros de environment

Uso:
    python test_real_config.py

Variáveis de ambiente necessárias:
    POLY_PRIVATE_KEY=0x...
    POLY_FUNDER=0x...          (opcional)
    POLY_SIGNATURE_TYPE=0/1/2 (opcional, default=0 se sem funder)
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Importar do módulo principal
from polymarket_clob import ClobClient, TradingMode, GAMMA_API


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def print_success(msg: str):
    print(f"  ✅ {msg}")


def print_error(msg: str):
    print(f"  ❌ {msg}")


def print_warning(msg: str):
    print(f"  ⚠️  {msg}")


def print_info(msg: str):
    print(f"  ℹ️  {msg}")


def check_env_vars() -> bool:
    """Verifica se as variáveis de ambiente necessárias estão definidas."""
    print_header("1. Verificação de Variáveis de Ambiente")

    required = ["POLY_PRIVATE_KEY"]
    optional = ["POLY_FUNDER", "POLY_SIGNATURE_TYPE"]

    all_ok = True

    for var in required:
        value = os.environ.get(var)
        if value:
            # Mostrar apenas os primeiros/últimos caracteres da private key
            if var == "POLY_PRIVATE_KEY":
                masked = f"{value[:6]}...{value[-4:]}"
                print_success(f"{var} = {masked}")
            else:
                print_success(f"{var} = {value}")
        else:
            print_error(f"{var} não definida!")
            all_ok = False

    for var in optional:
        value = os.environ.get(var)
        if value:
            print_info(f"{var} = {value}")
        else:
            print_info(f"{var} (opcional) não definida")

    return all_ok


def test_clob_initialization() -> ClobClient | None:
    """Testa a inicialização do ClobClient."""
    print_header("2. Inicialização do ClobClient")

    private_key = os.environ.get("POLY_PRIVATE_KEY")
    if not private_key:
        print_error("POLY_PRIVATE_KEY não definida, impossível continuar.")
        return None

    try:
        clob = ClobClient(
            private_key=private_key,
            mode=TradingMode.REAL,
            max_daily_loss=50.0,
            log_dir=Path("test_logs"),
        )
        print_success("ClobClient inicializado com sucesso")
        print_info(f"   Mode: {clob.mode.value}")
        print_info(f"   Signature type: {getattr(clob, '_signature_type', 'unknown')}")
        print_info(f"   Funder: {getattr(clob, '_funder', 'none') or 'none'}")
        return clob

    except Exception as e:
        print_error(f"Falha ao inicializar ClobClient: {e}")
        return None


def test_usdc_balance(clob: ClobClient) -> bool:
    """Testa a verificação do saldo USDC."""
    print_header("3. Verificação de Saldo USDC")

    try:
        balance = clob.get_usdc_balance()
        if balance is not None:
            print_success(f"Saldo USDC: ${balance:.2f}")
            if balance < 5.0:
                print_warning("   Saldo abaixo de $5 (mínimo para ordens)")
            return True
        else:
            print_error("Não foi possível obter o saldo")
            return False

    except Exception as e:
        print_error(f"Falha ao obter saldo: {e}")
        return False


def test_market_fetch(clob: ClobClient) -> dict | None:
    """Testa a obtenção de um mercado de teste."""
    print_header("4. Obtenção de Mercado (Teste)")

    import requests
    from datetime import datetime, timedelta

    # Tentar primeiro obter um mercado ativo de qualquer categoria
    try:
        # Buscar eventos ativos com volume
        now = datetime.now()

        # Tentar obter mercados de amanhã de Munique para garantir que ainda não expiraram
        from munich_config import MONTH_NAMES
        tomorrow = now.date() + timedelta(days=1)
        slug = f"highest-temperature-in-munich-on-{MONTH_NAMES[tomorrow.month]}-{tomorrow.day}-{tomorrow.year}"

        r = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=15)
        if r.status_code == 200:
            events = r.json()
            if isinstance(events, list) and events:
                event = events[0]
                print_success(f"Mercado encontrado: {event.get('title', 'Unknown')}")
                print_info(f"   Slug: {slug}")
                print_info(f"   Volume: ${event.get('volume', 0):.2f}")
                print_info(f"   End date: {event.get('endDate', 'unknown')}")

                # Procurar por um bracket com token_id ativo no CLOB
                markets = event.get("markets", [])
                print_info(f"   Número de mercados: {len(markets)}")

                for mi, m in enumerate(markets):
                    outcomes = m.get("outcomes", [])
                    token_ids_raw = m.get("clobTokenIds", "[]")

                    if isinstance(token_ids_raw, str):
                        try:
                            token_ids = json.loads(token_ids_raw)
                            if len(token_ids) >= 2 and len(outcomes) >= 2:
                                # O primeiro token é sempre YES, segundo é NO
                                token_id = token_ids[0]
                                bracket = m.get('groupItemTitle') or m.get('question', 'unknown')
                                print_success(f"   ✅ Token YES obtido: {token_id[:20]}...")
                                print_info(f"      Bracket: {bracket}")
                                print_info(f"      Question: {m.get('question', 'unknown')}")
                                return {"slug": slug, "token_id": token_id, "market": event}
                        except Exception as e:
                            print_warning(f"      Erro ao parse token_ids: {e}")

        # Se falhar, tentar qualquer mercado ativo
        print_info("\n   Tentando mercado alternativo...")
        r = requests.get(f"{GAMMA_API}/events", params={"limit": 20}, timeout=15)
        if r.status_code == 200:
            events = r.json()
            if isinstance(events, list) and events:
                # Filtrar eventos que ainda não expiraram
                active_events = []
                for e in events:
                    try:
                        end_str = e.get("endDate", "")
                        if end_str:
                            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                            if end_date > now:
                                active_events.append(e)
                    except:
                        continue

                if active_events:
                    # Escolher mercado com maior volume
                    event = max(active_events, key=lambda e: float(e.get("volume", 0) or 0))
                    print_success(f"Mercado alternativo encontrado: {event.get('title', 'Unknown')}")
                    print_info(f"   Slug: {event.get('slug', 'unknown')}")
                    print_info(f"   Volume: ${event.get('volume', 0):.2f}")
                    print_info(f"   End date: {event.get('endDate', 'unknown')}")

                    markets = event.get("markets", [])
                    for mi, m in enumerate(markets):
                        token_ids_raw = m.get("clobTokenIds", "[]")
                        if isinstance(token_ids_raw, str):
                            try:
                                token_ids = json.loads(token_ids_raw)
                                if len(token_ids) >= 2:
                                    token_id = token_ids[0]  # YES é sempre o primeiro
                                    bracket = m.get('groupItemTitle') or m.get('question', 'unknown')
                                    print_success(f"   ✅ Token YES obtido: {token_id[:20]}...")
                                    print_info(f"      Bracket: {bracket}")
                                    return {"slug": event.get("slug", ""), "token_id": token_id, "market": event}
                            except:
                                continue

    except Exception as e:
        print_error(f"Falha ao obter mercado: {e}")
        import traceback
        traceback.print_exc()

    # Mercado dummy para fallback (apenas para testar assinatura)
    print_warning("Usando mercado dummy para testes de assinatura")
    print_warning("   (não corresponde a um mercado real, apenas valida a assinatura)")
    return {
        "slug": "dummy-test",
        "token_id": "0x0000000000000000000000000000000000000000000000000000000000000000",
        "market": None,
    }


def test_orderbook(clob: ClobClient, token_id: str) -> bool:
    """Testa o acesso ao order book."""
    print_header("5. Acesso ao Order Book")

    try:
        book = clob.get_orderbook(token_id)
        if book:
            print_success("Order book obtido com sucesso")
            print_info(f"   Best bid: {book.best_bid}")
            print_info(f"   Best ask: {book.best_ask}")
            print_info(f"   Mid price: {book.mid}")
            print_info(f"   Spread: {book.spread}")
            print_info(f"   Bid depth (top 5): ${book.bid_depth_usdc:.2f}")
            print_info(f"   Ask depth (top 5): ${book.ask_depth_usdc:.2f}")
            return True
        else:
            print_warning("Order book vazio ou inacessível (mercado fechado?)")
            return False

    except Exception as e:
        print_error(f"Falha ao obter order book: {e}")
        return False


def test_dry_run_order(clob: ClobClient, token_id: str) -> bool:
    """Testa a geração e assinatura de ordem (dry-run)."""
    print_header("6. Dry-Run de Ordem (Assinatura Apenas)")

    try:
        print_info("   A criar ordem FOK (market buy) de $5.00...")
        print_info("   dry_run=True: vai assinar mas NÃO submeter ao Polymarket\n")

        result = clob.buy_yes(
            token_id=token_id,
            price=0.50,  # dummy price
            size_usdc=5.0,
            bracket_label="TEST: 25°C or higher",
            market_slug="test-dry-run",
            order_type="FOK",
            dry_run=True,  # <-- CRÍTICO: não submete!
        )

        if result.success:
            print_success("Ordem assinada com sucesso (dry-run)")
            print_info(f"   Order ID: {result.order_id}")
            print_info(f"   Status: {result.status}")
            print_info(f"   Price: ${result.price:.4f}")
            print_info(f"   Size: ${result.size_usdc:.2f}")
            print_info(f"   Shares: {result.shares}")
            print_info("\n   🟡 Nenhum dinheiro foi gasto!")
            return True
        else:
            print_error(f"Falha na assinatura: {result.error}")
            return False

    except Exception as e:
        print_error(f"Erro no dry-run: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_positions_manager(clob: ClobClient) -> bool:
    """Testa o gerenciador de posições."""
    print_header("7. Gerenciador de Posições")

    try:
        opens = clob.positions.open_positions()
        print_success(f"PositionManager funcionando")
        print_info(f"   Posições abertas: {len(opens)}")

        summary = clob.positions.pnl_summary()
        print_info(f"   Total investido: ${summary['total_invested']:.2f}")
        print_info(f"   Total P&L: ${summary['total_pnl_usd']:+.2f} ({summary['total_pnl_pct']:+.1f}%)")
        print_info(f"   {summary['n_won']} ganhas | {summary['n_lost']} perdidas | {summary['n_open']} abertas")

        return True

    except Exception as e:
        print_error(f"Falha ao acessar posições: {e}")
        return False


def run_all_tests():
    """Executa todos os testes."""
    print("\n" + "="*60)
    print("  TESTE DE CONFIGURAÇÃO REAL - POLYMARKET CLOB")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60)

    # 1. Verificar env vars
    if not check_env_vars():
        print("\n" + "="*60)
        print("  ⚠️  Falha crítica: variáveis de ambiente em falta")
        print("  Define as variáveis necessárias antes de continuar:")
        print('     export POLY_PRIVATE_KEY="0x..."')
        print("="*60 + "\n")
        return False

    # 2. Inicializar ClobClient
    clob = test_clob_initialization()
    if not clob:
        print("\n❌ Falha na inicialização do ClobClient. Abortando.\n")
        return False

    # 3. Verificar saldo
    if not test_usdc_balance(clob):
        print("\n⚠️  Não foi possível verificar o saldo. Continuando...\n")

    # 4. Obter mercado de teste
    market_data = test_market_fetch(clob)
    if not market_data:
        print("\n❌ Não foi possível obter um mercado de teste. Abortando.\n")
        return False

    token_id = market_data["token_id"]

    # 5. Testar order book
    test_orderbook(clob, token_id)

    # 6. Dry-run de ordem (CRÍTICO)
    dry_run_ok = test_dry_run_order(clob, token_id)

    # 7. Testar positions manager
    test_positions_manager(clob)

    # Resumo final
    print_header("RESUMO FINAL")

    if dry_run_ok:
        print_success("✅ Todos os testes críticos passaram!")
        print("\n  A configuração REAL está pronta para uso.")
        print("\n  Próximos passos:")
        print("    1. Revê os resultados acima")
        print("    2. Verifica que o saldo é suficiente")
        print("    3. Executa o bot em modo PAPER primeiro:")
        print('       python munich_live_bot.py --run paper')
        print("    4. Quando pronto, muda para REAL:")
        print('       python munich_live_bot.py --run real')
        print("\n  Lembrete: em modo REAL, as ordens gastam dinheiro REAL!")
    else:
        print_error("❌ O dry-run falhou.")
        print("\n  Possíveis causas:")
        print("    - POLY_PRIVATE_KEY inválida")
        print("    - Conta não verificada no Polymarket")
        print("    - POLY_SIGNATURE_TYPE incorreto")
        print("    - POLY_FUNDER incorreto ou em falta")
        print("\n  Verifica a configuração e tenta novamente.")

    print("\n" + "="*60 + "\n")

    return dry_run_ok


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
