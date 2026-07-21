#!/usr/bin/env python3
"""
test_v3_historical.py
=====================
Script para testar o endpoint V3 historical hourly com ICAO.

Uso:
    python test_v3_historical.py OPKC
    python test_v3_historical.py EDDM
    python test_v3_historical.py VILK
"""

import sys
import requests
from datetime import datetime

WU_API_KEY = "e1f10a1e78da46f5b10a1e78da96f525"
V3_BASE = "https://api.weather.com/v3"


def test_historical_hourly(icao):
    """Testa o endpoint V3 historical hourly."""
    url = f"{V3_BASE}/wx/conditions/historical/hourly/1day"
    params = {
        "icaoCode": icao,
        "units": "e",
        "language": "en-US",
        "format": "json",
        "apiKey": WU_API_KEY,
    }

    print(f"\n{'='*60}")
    print(f"TESTE: {icao}")
    print(f"{'='*60}")

    try:
        resp = requests.get(url, params=params, timeout=15)
        print(f"Status: HTTP {resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()

            # Extrair temperaturas directamente
            temps = data.get("temperature", [])
            if temps:
                print(f"\n✅ Temperaturas: {len(temps)} valores")
                print(f"   Fahrenheit: {temps[:5]}... (primeiros 5)")
                temps_c = [round((t - 32) * 5 / 9, 1) for t in temps if t is not None]
                print(f"   Celsius: {temps_c[:5]}... (primeiros 5)")
                print(f"   Min: {min(temps_c)}°C | Max: {max(temps_c)}°C")
            else:
                print(f"\n⚠️ Sem temperaturas")

            # Mostrar outras chaves
            print(f"\nChaves disponíveis: {list(data.keys())}")

        else:
            print(f"\n❌ Erro: HTTP {resp.status_code}")
            print(f"   Body: {resp.text[:200]}")

    except Exception as e:
        print(f"\n❌ Excepção: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python test_v3_historical.py <ICAO>")
        print("Exemplo: python test_v3_historical.py OPKC")
        sys.exit(1)

    icao = sys.argv[1].upper()
    test_historical_hourly(icao)
