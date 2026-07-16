"""
discover_pws_stations.py
========================
Descobre PWS stations do WU para todas as cidades configuradas.

Usa o endpoint /v3/location/near que o próprio site wunderground.com usa
(com a mesma API key free). Para cada cidade, encontra as 3 PWS stations
mais próximas e testa qual delas tem dados históricos disponíveis.

Uso:
    python discover_pws_stations.py
    python discover_pws_stations.py --cities munich,madrid
    python discover_pws_stations.py --apply  # actualiza cities/config.py automaticamente
"""

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Adicionar cwd ao path para importar cities.config
sys.path.insert(0, str(Path(__file__).parent))
from cities.config import CITIES, CityConfig

API_KEY = os.environ.get("WU_API_KEY", "")
WU_NEAR_URL = "https://api.weather.com/v3/location/near"
WU_HISTORY_URL = "https://api.weather.com/v2/pws/history/all"
WU_CURRENT_URL = "https://api.weather.com/v2/pws/observations/current"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.wunderground.com/",
        "Origin":          "https://www.wunderground.com",
    })
    return s


def find_pws_near(session: requests.Session, lat: float, lon: float, n: int = 5) -> list[dict]:
    """Encontra as N PWS stations mais próximas de (lat, lon)."""
    try:
        r = session.get(WU_NEAR_URL, params={
            "apiKey":   API_KEY,
            "geocode":  f"{lat},{lon}",
            "product":  "pws",
            "format":   "json",
        }, timeout=15)
    except Exception as e:
        print(f"    ERRO de rede: {e}")
        return []

    if r.status_code != 200:
        print(f"    HTTP {r.status_code}: {r.text[:200]}")
        return []

    try:
        data = r.json()
    except Exception:
        return []

    # Formato: {"location": {"stationName": [...], "distance": [...], ...}}
    loc = data.get("location", {}) if isinstance(data, dict) else {}
    stations = []
    names = loc.get("stationName", []) or []
    ids = loc.get("pwsId", []) or loc.get("stationId", []) or []
    distances = loc.get("distanceKm", []) or []
    lats = loc.get("latitude", []) or []
    lons = loc.get("longitude", []) or []

    for i in range(min(n, len(names))):
        stations.append({
            "station_id":   ids[i] if i < len(ids) else None,
            "station_name": names[i] if i < len(names) else None,
            "distance_km":  distances[i] if i < len(distances) else None,
            "latitude":     lats[i] if i < len(lats) else None,
            "longitude":    lons[i] if i < len(lons) else None,
        })
    return stations


def test_station_has_data(session: requests.Session, station_id: str) -> dict:
    """Testa se uma PWS station tem dados históricos para ontem."""
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        r = session.get(WU_HISTORY_URL, params={
            "apiKey":    API_KEY,
            "stationId": station_id,
            "format":    "json",
            "units":     "m",
            "date":      yesterday,
        }, timeout=15)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}

    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": "JSON invalido"}

    obs = data.get("observations", []) if isinstance(data, dict) else []
    if not obs:
        return {"ok": False, "error": "sem observations", "n_obs": 0}

    # Validar que tem pelo menos algumas observations com temp
    temps = []
    for o in obs:
        m = o.get("metric", {}) or {}
        t = m.get("tempAvg")
        if t is not None:
            try:
                temps.append(float(t))
            except Exception:
                pass

    if not temps:
        return {"ok": False, "error": "sem tempAvg nas observations", "n_obs": len(obs)}

    return {
        "ok": True,
        "n_obs": len(obs),
        "temp_min": min(temps),
        "temp_max": max(temps),
    }


def discover_for_city(session: requests.Session, city: CityConfig, max_test: int = 5) -> dict:
    """Descobre PWS stations para uma cidade."""
    print(f"\n{'='*70}")
    print(f"  {city.name.upper()} — lat={city.latitude}, lon={city.longitude}")
    print(f"  ICAO: {city.icao} | Timezone: {city.timezone}")
    print(f"{'='*70}")

    # Se já tem pws_station_id, testar primeiro
    existing = getattr(city, 'pws_station_id', None)
    if existing:
        print(f"  PWS já configurado: {existing}")
        result = test_station_has_data(session, existing)
        if result["ok"]:
            print(f"  ✓ {existing}: {result['n_obs']} obs, "
                  f"temp {result['temp_min']:.1f}–{result['temp_max']:.1f}°C")
            return {
                "city": city.name,
                "selected_station_id": existing,
                "tested": [({"station_id": existing, **result})],
            }
        else:
            print(f"  ✗ {existing} falhou: {result['error']}")

    # Procurar PWS near
    print(f"  Procurando PWS stations próximas...")
    stations = find_pws_near(session, city.latitude, city.longitude, n=max_test)
    if not stations:
        print(f"  ✗ Nenhuma PWS encontrada perto de ({city.latitude}, {city.longitude})")
        return {"city": city.name, "selected_station_id": None, "tested": []}

    print(f"  Encontradas {len(stations)} PWS stations. Testando cada uma...")

    tested = []
    selected = None
    for s in stations:
        sid = s.get("station_id")
        if not sid:
            continue
        dist = s.get("distance_km")
        dist_str = f"{dist:.1f}km" if dist is not None else "?"
        print(f"    Testando {sid} ({s.get('station_name', '?')[:30]}, {dist_str})...",
              end=" ", flush=True)
        result = test_station_has_data(session, sid)
        tested.append({**s, **result})
        if result["ok"]:
            print(f"✓ {result['n_obs']} obs, temp {result['temp_min']:.1f}–{result['temp_max']:.1f}°C")
            if selected is None:
                selected = sid
                print(f"    >>> SELECIONADA: {sid}")
        else:
            err = result.get("error", "?")
            n = result.get("n_obs", 0)
            print(f"✗ {err}" + (f" (n_obs={n})" if n else ""))
        time.sleep(0.5)  # rate limit friendly

    if selected is None:
        print(f"  ⚠ Nenhuma PWS funcionou para {city.name}")
    else:
        print(f"  ✓ Melhor PWS para {city.name}: {selected}")

    return {"city": city.name, "selected_station_id": selected, "tested": tested}


def update_config_py(results: dict) -> None:
    """Actualiza cities/config.py adicionando pws_station_id a cada cidade."""
    config_path = Path("cities/config.py")
    if not config_path.exists():
        print(f"  ✗ {config_path} não encontrado")
        return

    src = config_path.read_text()
    new_src = src

    for city_name, info in results.items():
        sid = info.get("selected_station_id")
        if not sid:
            continue
        # Verificar se city já tem pws_station_id definido
        import re
        # Procurar o bloco CityConfig da cidade
        # Padrão: "city_name": CityConfig(... name="city_name" ... wu_history_path="..." ...)
        pattern = rf'("{city_name}": CityConfig\(\s*name="{city_name}",.*?wu_history_path=(?:"[^"]*"|None),)'
        # Verificar se já tem pws_station_id nesse bloco
        m = re.search(pattern, new_src, re.DOTALL)
        if not m:
            print(f"  ! Não encontrei bloco de {city_name}")
            continue
        block = m.group(1)
        if "pws_station_id" in block:
            # Já tem — substituir
            new_block = re.sub(r'pws_station_id="[^"]*",', f'pws_station_id="{sid}",', block)
        else:
            # Adicionar após wu_history_path
            new_block = block + f'\n        pws_station_id="{sid}",'
        new_src = new_src.replace(block, new_block, 1)
        print(f"  ✓ {city_name}: pws_station_id=\"{sid}\"")

    if new_src != src:
        # Backup
        backup = config_path.with_suffix(".py.bak")
        backup.write_text(src)
        config_path.write_text(new_src)
        print(f"\n  Backup gravado em: {backup}")
        print(f"  {config_path} actualizado")
    else:
        print(f"\n  Sem alterações necessárias")


def add_pws_field_to_dataclass():
    """Adiciona o campo pws_station_id ao CityConfig dataclass em config.py."""
    config_path = Path("cities/config.py")
    if not config_path.exists():
        return False
    src = config_path.read_text()
    if "pws_station_id" in src:
        return False  # já tem
    # Adicionar campo ao dataclass, após wu_history_path
    new_src = src.replace(
        'wu_history_path: Optional[str]       # Caminho WU (se aplicável)',
        'wu_history_path: Optional[str]       # Caminho WU (se aplicável)\n'
        '    pws_station_id: str = ""                # PWS station ID para histórico (WU v2)'
    )
    if new_src != src:
        backup = config_path.with_suffix(".py.bak")
        backup.write_text(src)
        config_path.write_text(new_src)
        print(f"  ✓ Adicionado campo pws_station_id ao CityConfig")
        print(f"  Backup gravado em: {backup}")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Descobre PWS stations para cidades.")
    parser.add_argument("--cities", type=str, default=None,
                        help="Cidades separadas por vírgula (default: todas)")
    parser.add_argument("--apply", action="store_true",
                        help="Actualiza cities/config.py com os stationIds descobertos")
    parser.add_argument("--max-test", type=int, default=5,
                        help="Máximo de stations a testar por cidade (default 5)")
    args = parser.parse_args()

    if not API_KEY:
        print("ERRO: WU_API_KEY não definida no .env ou ambiente")
        sys.exit(1)

    # Filtrar cidades
    if args.cities:
        if args.cities.lower() == "all":
            cities_to_test = list(CITIES.values())
        else:
            city_names = [c.strip().lower() for c in args.cities.split(",")]
            cities_to_test = [CITIES[n] for n in city_names if n in CITIES]
    else:
        cities_to_test = list(CITIES.values())

    # Só testar cidades com wu_history_path (as outras não vão usar WU)
    cities_with_wu = [c for c in cities_to_test if c.wu_history_path]
    cities_without_wu = [c for c in cities_to_test if not c.wu_history_path]

    if cities_without_wu:
        print(f"\nINFO: {len(cities_without_wu)} cidades sem wu_history_path (sem WU):")
        for c in cities_without_wu:
            print(f"  - {c.name}")
        print(f"\nVou tentar descobrir PWS para estas cidades também (precisas de")
        print(f"adicionar wu_history_path manualmente se quiseres usar WU).")
        # Na verdade, vamos testar todas

    print(f"\nVou descobrir PWS stations para {len(cities_to_test)} cidades...")
    session = make_session()

    all_results = {}
    for city in cities_to_test:
        result = discover_for_city(session, city, max_test=args.max_test)
        all_results[city.name] = result
        time.sleep(1)  # rate limit friendly entre cidades

    # Resumo final
    print(f"\n{'='*70}")
    print(f"  RESUMO FINAL")
    print(f"{'='*70}")
    n_ok = 0
    n_fail = 0
    for city_name, info in all_results.items():
        sid = info.get("selected_station_id")
        if sid:
            print(f"  ✓ {city_name:20s} → {sid}")
            n_ok += 1
        else:
            print(f"  ✗ {city_name:20s} → sem PWS funcional")
            n_fail += 1
    print(f"\n  Total: {n_ok} OK, {n_fail} falharam")

    # Gravar JSON para referência
    out_path = Path("pws_stations_discovered.json")
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n  Detalhes gravados em: {out_path}")

    # Aplicar a config.py se pedido
    if args.apply and n_ok > 0:
        print(f"\n{'='*70}")
        print(f"  A actualizar cities/config.py...")
        print(f"{'='*70}")
        # Primeiro garantir que o campo existe no dataclass
        add_pws_field_to_dataclass()
        update_config_py(all_results)
    elif n_ok > 0 and not args.apply:
        print(f"\n  Para aplicar as alterações a cities/config.py, corre:")
        print(f"    python discover_pws_stations.py --apply")


if __name__ == "__main__":
    main()
