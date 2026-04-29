"""
test_clob_dryrun.py
===================
Teste DRY-RUN Polymarket CLOB — Versão corrigida (26 Abril 2026)
"""

import os
import sys
import json
import requests
from datetime import date

# ========================= CONFIGURAÇÃO =========================
required = ["POLY_PRIVATE_KEY"]
recommended = ["POLY_FUNDER", "POLY_SIGNATURE_TYPE"]

missing = [v for v in required if not os.environ.get(v)]
if missing:
    print(f"❌ ERRO: Falta(m) variável(eis): {', '.join(missing)}")
    sys.exit(1)

print("=" * 70)
print("🟡 DRY-RUN TEST — Polymarket CLOB (versão corrigida)")
print("=" * 70)
print()

print("Configuração:")
for v in required + recommended:
    val = os.environ.get(v, "<não definido>")
    if v == "POLY_PRIVATE_KEY" and val != "<não definido>":
        val = val[:6] + "..." + val[-4:]
    print(f"  {v} = {val}")
print()

# Validar endereços
try:
    from eth_account import Account
    pk = os.environ["POLY_PRIVATE_KEY"]
    metamask_addr = Account.from_key(pk).address
    funder = os.environ.get("POLY_FUNDER", "")
    print(f"  MetaMask addr: {metamask_addr}")
    print(f"  Funder addr:   {funder or '<não definido>'}")
    if funder and metamask_addr.lower() == funder.lower():
        print("  ⚠️ Endereços iguais!")
    elif funder:
        print("  ✓ Browser wallet OK")
    print()
except ImportError:
    print("  (eth_account não instalado)")
    print()

# ─── 1. Buscar mercado Munich de HOJE ───
print("[1/4] A buscar mercado de temperatura em Munich...")

today = date.today()
month_str = today.strftime("%B").lower()
day = today.day
year = today.year

slug = f"highest-temperature-in-munich-on-{month_str}-{day}-{year}"
print(f"  Slug: {slug}")

api_url = "https://gamma-api.polymarket.com"
events = []

# Tentativa 1: Slug exato
try:
    r = requests.get(f"{api_url}/events", params={"slug": slug}, timeout=15)
    if r.ok:
        data = r.json()
        events = data if isinstance(data, list) else [data] if data else []
        print("  ✓ Encontrado via slug exato")
except Exception as e:
    print(f"  Slug falhou: {e}")

# Fallback: busca por texto
if not events:
    queries = [
        f"highest temperature Munich {month_str} {day} {year}",
        f"Munich temperature {month_str} {day}",
        "Munich temperature"
    ]
    for q in queries:
        try:
            r = requests.get(f"{api_url}/events", params={"q": q, "limit": 10}, timeout=15)
            if r.ok:
                data = r.json()
                events = data if isinstance(data, list) else [data] if data else []
                if events:
                    break
        except:
            pass

# Filtrar mercado válido
def is_valid_munich(e):
    if not isinstance(e, dict):
        return False
    title = str(e.get("title", "")).lower()
    return ("munich" in title and "temperature" in title and 
            not e.get("closed", True))

munich_events = [e for e in events if is_valid_munich(e)]

if not munich_events:
    print("  ❌ Mercado não encontrado via API.")
    print("     Usa este link direto:")
    print("     https://polymarket.com/event/highest-temperature-in-munich-on-april-26-2026")
    sys.exit(1)

event = max(munich_events, key=lambda e: float(e.get("volume", 0) or 0))
print(f"  ✓ Mercado: {event.get('title')}")
print(f"    Volume: ${float(event.get('volume', 0) or 0):,.0f}")
print()

# ─── 2. Brackets ───
print("[2/4] Brackets com preço válido:")

brackets = []
for m in event.get("markets", []):
    raw_label = m.get("groupItemTitle") or m.get("outcomeTitle") or m.get("title", "")

    def _jload(x):
        if isinstance(x, str):
            try: return json.loads(x)
            except: return []
        return x

    outcomes = _jload(m.get("outcomes", "[]"))
    prices = _jload(m.get("outcomePrices", "[]"))
    token_ids = _jload(m.get("clobTokenIds", "[]"))

    for i, out in enumerate(outcomes):
        if str(out).lower() in ("yes", "1", "true"):
            try:
                price = float(prices[i]) if i < len(prices) else 0
            except:
                continue
            token = token_ids[i] if i < len(token_ids) else None
            if token and 0.01 <= price <= 0.99:
                brackets.append({
                    "label": raw_label,
                    "price": price,
                    "token_id": token
                })
                short = token[:24] + "..." if len(token) > 24 else token
                print(f"  {raw_label:>25} → {price:>6.3f}  {short}")
            break

if not brackets:
    print("  ❌ Nenhum bracket com preço válido.")
    sys.exit(1)

# Escolher um barato
cheap = [b for b in brackets if 0.05 < b["price"] < 0.25]
chosen = cheap[0] if cheap else min(brackets, key=lambda b: b["price"])

print(f"\n[3/4] Escolhido: {chosen['label']} @ {chosen['price']:.3f}")

# ─── 4. Dry-run CLOB ───
print("\n[4/4] A conectar ao CLOB (dry-run)...")

try:
    from polymarket_clob import ClobClient, TradingMode
except ImportError:
    print("❌ polymarket_clob.py não encontrado!")
    sys.exit(1)

clob = ClobClient(
    private_key=os.environ["POLY_PRIVATE_KEY"],
    mode=TradingMode.REAL,
    max_daily_loss=50.0,
)

balance = clob.get_usdc_balance()
print(f"  Saldo USDC: ${balance if balance else 'N/A'}")

print("  A assinar ordem (NÃO vai submeter)...")
result = clob.buy_yes(
    token_id      = chosen["token_id"],
    price         = chosen["price"],
    size_usdc     = 5.0,
    bracket_label = chosen["label"],
    market_slug   = slug,
    order_type    = "FOK",
    dry_run       = True,
)

print("\n" + "="*70)
print("RESULTADO DO DRY-RUN")
print("="*70)
print(f"  Success: {result.success}")
print(f"  Error:   {result.error or 'Nenhum'}")

if result.success:
    print("\n✅ DRY-RUN PASSOU! Tudo OK.")
else:
    print("\n❌ Falhou. Ver erro acima.")