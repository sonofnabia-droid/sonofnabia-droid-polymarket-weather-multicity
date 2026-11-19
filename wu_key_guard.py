#!/usr/bin/env python3
"""wu_key_guard.py — verifica a saúde da key WU no arranque dos bots.
1. key do .env/shell responde? (200 = viva)
2. a public key do SITE (view-source) mudou? (se sim, a rotação vem aí)
Verde/vermelho no terminal + sai com exit code p/ scripts."""
import re, sys, requests

def get_site_key():
    try:
        r = requests.get("https://www.wunderground.com/history/daily/de/munich/EDDM",
                         timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                                              "Chrome/120.0 Safari/537.36"})
        m = re.search(r'"API_KEY":"([a-f0-9]{32})"', r.text)
        return m.group(1) if m else None
    except Exception:
        return None

def test_key(key, icao="EDDM"):
    r = requests.get("https://api.weather.com/v3/wx/conditions/historical/hourly/1day",
                     params={"icaoCode": icao, "units": "e", "language": "en-US",
                             "format": "json", "apiKey": key}, timeout=15)
    return r.status_code

def main():
    import os
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("WU_API_KEY", "")
    print("── WU KEY GUARD ──")
    if not key:
        print("🔴 FATAL: sem WU_API_KEY no .env/ambiente — bots correm cegos")
        sys.exit(2)

    st = test_key(key)
    print(f"{'🟢' if st == 200 else '🔴'} key em uso ({key[:8]}...): HTTP {st}")

    site = get_site_key()
    if site is None:
        print("🟡 site indisponível para comparação (verificar manualmente)")
    elif site == key:
        print(f"🟢 site key igual à em uso ({site[:8]}...)")
    else:
        print(f"🟡 ATENÇÃO: site tem key DIFERENTE ({site[:8]}...) — a nossa pode "
              f"rodar a qualquer momento; considera migrar para key legítima")

    if st != 200:
        print("🔴 AÇÃO: bots cegos — atualizar .env WU_API_KEY")
        sys.exit(1)
    print("── OK ──")

if __name__ == "__main__":
    main()
