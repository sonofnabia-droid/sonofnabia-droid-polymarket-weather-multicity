"""
discover_pws_from_wu_pages.py
=============================
Descobre qual a PWS station que wunderground.com/history/daily/{country}/{city}/{ICAO}
usa internamente para cada cidade — que é a mesma que o Polymarket usa para resolver.

Como funciona:
  1. Para cada cidade, vai buscar a página WU history do ICAO correspondente
  2. Extrai do HTML o endpoint /v2/pws/history com o stationId PWS real
  3. Testa essa station com /v2/pws/history/all para confirmar que tem dados

Output: pws_stations_official.json com o stationId correcto para cada cidade.

Uso:
    python discover_pws_from_wu_pages.py
    python discover_pws_from_wu_pages.py --cities munich,madrid
    python discover_pws_from_wu_pages.py --apply
"""

import argparse
import json
import os
import re
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

sys.path.insert(0, str(Path(__file__).parent))
from cities.config import CITIES, CityConfig

API_KEY = os.environ.get("WU_API_KEY", "")

# Mapa ICAO → (país, cidade) para construir URL WU history
# Baseado nas cidades existentes no config.py
ICAO_TO_WU_PATH = {
    "EDDM":          "de/munich/EDDM",            # Germany, Munich
    "WSSS":          "sg/singapore/WSSS",          # Singapore
    "RCSS":          "tw/taipei/RCSS",             # Taiwan, Taipei
    "KDFW":          "us/tx/dallas/KDFW",          # USA TX, Dallas
    "LTAC":          "tr/ankara/LTAC",             # Turkey, Ankara
    "WIII":          "id/jakarta/WIII",            # Indonesia, Jakarta
    "WMKK":          "my/kuala-lumpur/WMKK",       # Malaysia, Kuala Lumpur
    "DNMM":          "ng/lagos/DNMM",              # Nigeria, Lagos
    "OPKC":          "pk/karachi/OPKC",            # Pakistan, Karachi
    "UUEE":          "ru/moscow/UUEE",             # Russia, Moscow
    "EPWA":          "pl/warsaw/EPWA",             # Poland, Warsaw
    "ZBAA":          "cn/beijing/ZBAA",            # China, Beijing
    "LEMD":          "es/madrid/LEMD",             # Spain, Madrid
    "LLBG":          "il/tel-aviv/LLBG",           # Israel, Tel Aviv
    "KMIA":          "us/fl/miami/KMIA",           # USA FL, Miami
    "KORD":          "us/il/chicago/KORD",         # USA IL, Chicago
    "KPHX":          "us/az/phoenix/KPHX",         # USA AZ, Phoenix
    "KLAS":          "us/nv/las-vegas/KLAS",       # USA NV, Las Vegas
    "SAEZ":          "ar/buenos-aires/SAEZ",       # Argentina, Buenos Aires
}

WU_HISTORY_URL = "https://www.wunderground.com/history/daily/{path}"
WU_PWS_HISTORY_API = "https://api.weather.com/v2/pws/history/all"
WU_PWS_OBS_API = "https://api.weather.com/v2/pws/observations/current"
WU_NEAR_URL = "https://api.weather.com/v3/location/near"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.wunderground.com/",
        "Origin":          "https://www.wunderground.com",
    })
    return s


def fetch_wu_history_page(session: requests.Session, wu_path: str) -> str | None:
    """Vai buscar a página HTML do WU history para o path dado."""
    url = WU_HISTORY_URL.format(path=wu_path)
    try:
        r = session.get(url, timeout=20)
    except Exception as e:
        print(f"    ERRO: {e}")
        return None
    if r.status_code != 200:
        print(f"    HTTP {r.status_code}")
        return None
    return r.text


def extract_pws_station_id(html: str, expected_country: str = None) -> tuple[str | None, str | None]:
    """Extrai o PWS stationId do HTML da página WU history.

    Retorna (station_id, matched_country).

    Se expected_country for fornecido (ex: 'cn' para China), prioriza matches
    desse país. Isto evita que o regex pegue em links de "Popular Stations"
    da sidebar que são de outros países (ex: San Francisco numa página de Beijing).

    O HTML contém referências a endpoints como:
      /history/daily/de/oberding/IOBERD38/date/2026-6-18
    ou:
      https://api.weather.com/v2/pws/observations/current?...&stationId=IOBERD38&...
    """
    # Padrão 1: URL no path /history/daily/{country}/{location}/{stationId}/date/...
    # Capturar também o country para filtragem
    all_matches = re.findall(
        r'/history/daily/([a-z]{2})/[a-z\-]+/([A-Z][A-Z0-9]+)/date/',
        html,
        re.IGNORECASE,
    )

    if all_matches:
        # Se temos expected_country, filtrar por ele
        if expected_country:
            expected_lower = expected_country.lower()
            for country, station_id in all_matches:
                if country.lower() == expected_lower:
                    return station_id, country
            # Se nenhum match do país esperado, retornar o primeiro com warning
            first_country, first_station = all_matches[0]
            return first_station, first_country  # caller pode verificar
        else:
            # Sem expected_country, retornar o primeiro match
            return all_matches[0][1], all_matches[0][0]

    # Padrão 2: stationId= nos parâmetros de URL (API calls)
    m = re.search(r'stationId=([A-Z][A-Z0-9]+)', html)
    if m:
        return m.group(1), None

    # Padrão 3: API call com stationId em JSON
    m = re.search(r'"stationId":"([A-Z][A-Z0-9]+)"', html)
    if m:
        return m.group(1), None

    # Padrão 4: pwsId em JSON
    m = re.search(r'"pwsId":"([A-Z][A-Z0-9]+)"', html)
    if m:
        return m.group(1), None

    return None, None


def sanity_check_temp(city: CityConfig, temp_min: float, temp_max: float) -> tuple[bool, str]:
    """Verifica se as temperaturas da PWS fazem sentido vs climatologia.

    Retorna (ok, message).
    """
    if not city.climatology:
        return True, "sem climatologia para verificar"

    from datetime import date
    month = date.today().month
    clim_max = city.climatology.get(month)
    if clim_max is None:
        return True, f"sem climatologia para mês {month}"

    # Tolerância generosa: ±15°C do máximo climatológico
    # (para dias quentes/frios extremos)
    tolerance = 15.0
    expected_low = clim_max - tolerance
    expected_high = clim_max + tolerance

    if temp_max < expected_low:
        return False, (
            f"temp_max={temp_max:.1f}°C muito baixa vs climatologia mês {month}={clim_max}°C "
            f"(esperado >= {expected_low:.1f}°C) — PWS provavelmente errada"
        )
    if temp_max > expected_high:
        return False, (
            f"temp_max={temp_max:.1f}°C muito alta vs climatologia mês {month}={clim_max}°C "
            f"(esperado <= {expected_high:.1f}°C) — PWS provavelmente errada"
        )

    return True, f"OK (climatologia mês {month}={clim_max}°C, PWS max={temp_max:.1f}°C)"


def extract_pws_station_name(html: str) -> str | None:
    """Tenta extrair o nome da localidade da PWS."""
    m = re.search(r'/history/daily/[a-z]+/([a-z\-]+)/[A-Z][A-Z0-9]+/date/', html, re.IGNORECASE)
    if m:
        return m.group(1).replace('-', ' ').title()
    return None


def test_pws_station(session: requests.Session, station_id: str) -> dict:
    """Testa se a PWS station tem dados históricos para ontem."""
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        r = session.get(WU_PWS_HISTORY_API, params={
            "apiKey":    API_KEY,
            "stationId": station_id,
            "format":    "json",
            "units":     "m",
            "date":      yesterday,
        }, timeout=15)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}

    try:
        data = r.json()
    except Exception:
        return {"ok": False, "error": "JSON invalido"}

    obs = data.get("observations", []) if isinstance(data, dict) else []
    if not obs:
        return {"ok": False, "error": "sem observations", "n_obs": 0}

    temps = []
    for o in obs:
        m = o.get("metric", {}) or {}
        t = m.get("tempAvg")
        if t is not None:
            try:
                temps.append(float(t))
            except Exception:
                pass

    return {
        "ok":       len(temps) > 0,
        "n_obs":    len(obs),
        "temp_min": min(temps) if temps else None,
        "temp_max": max(temps) if temps else None,
        "error":    "sem tempAvg" if not temps else None,
    }


def find_pws_via_near(session: requests.Session, lat: float, lon: float,
                       max_test: int = 5) -> tuple[str | None, list[dict]]:
    """Fallback: usa /v3/location/near para encontrar PWS próximas.
    Retorna (best_station_id, all_tested).
    """
    try:
        r = session.get(WU_NEAR_URL, params={
            "apiKey":  API_KEY,
            "geocode": f"{lat},{lon}",
            "product": "pws",
            "format":  "json",
        }, timeout=15)
    except Exception:
        return None, []

    if r.status_code != 200:
        return None, []

    try:
        data = r.json()
    except Exception:
        return None, []

    loc = data.get("location", {}) if isinstance(data, dict) else {}
    names = loc.get("stationName", []) or []
    ids = loc.get("pwsId", []) or loc.get("stationId", []) or []
    distances = loc.get("distanceKm", []) or []

    tested = []
    for i in range(min(max_test, len(ids))):
        sid = ids[i] if i < len(ids) else None
        if not sid:
            continue
        dist = distances[i] if i < len(distances) else None
        name = names[i] if i < len(names) else None

        # Testar esta station
        test_result = test_pws_station(session, sid)
        tested.append({
            "station_id":   sid,
            "station_name": name,
            "distance_km":  dist,
            **test_result,
        })
        if test_result["ok"]:
            return sid, tested
        time.sleep(0.3)

    return None, tested


def discover_for_city(session: requests.Session, city: CityConfig) -> dict:
    """Descobre o PWS stationId para uma cidade a partir da página WU history."""
    print(f"\n{'='*70}")
    print(f"  {city.name.upper()} — ICAO: {city.icao}")
    print(f"{'='*70}")

    wu_path = ICAO_TO_WU_PATH.get(city.icao)
    if not wu_path:
        if city.wu_history_path:
            wu_path = city.wu_history_path
        else:
            print(f"  ✗ Sem mapeamento ICAO→path para {city.icao}")
            return {"city": city.name, "icao": city.icao, "pws_station_id": None,
                    "pws_location_name": None, "wu_url": None, "test": None,
                    "sanity_check": None, "country_match": None}

    # Extrair country code esperado do wu_path (ex: "cn/beijing/ZBAA" → "cn")
    expected_country = wu_path.split("/")[0] if "/" in wu_path else None

    wu_url = WU_HISTORY_URL.format(path=wu_path)
    print(f"  WU URL: {wu_url}")
    print(f"  País esperado: {expected_country}")

    # Buscar HTML
    html = fetch_wu_history_page(session, wu_path)
    if not html:
        return {"city": city.name, "icao": city.icao, "pws_station_id": None,
                "pws_location_name": None, "wu_url": wu_url, "test": None,
                "sanity_check": None, "country_match": None}

    print(f"  HTML recebido: {len(html)} bytes")

    # Extrair stationId com filtro de país
    station_id, matched_country = extract_pws_station_id(html, expected_country)

    # Verificar se o country do match corresponde ao esperado
    country_match = True
    use_fallback = False
    if station_id and matched_country and expected_country:
        if matched_country.lower() != expected_country.lower():
            country_match = False
            print(f"  ⚠ PWS stationId encontrado: {station_id}")
            print(f"  ⚠ Mas é do país '{matched_country}' (esperado '{expected_country}')!")
            print(f"  ⚠ Isto é provavelmente um link de 'Popular Stations' da sidebar.")
            print(f"  ⚠ Vou tentar fallback com /v3/location/near...")
            use_fallback = True
        else:
            print(f"  ✓ PWS stationId encontrado: {station_id} (país {matched_country} ✓)")
    elif station_id:
        print(f"  ✓ PWS stationId encontrado: {station_id} (país não determinado)")
    else:
        print(f"  ✗ Não consegui extrair PWS stationId do HTML")
        print(f"  ⚠ Vou tentar fallback com /v3/location/near...")
        use_fallback = True

    # FALLBACK: se HTML não deu PWS do país certo, usar /v3/location/near
    fallback_tested = []
    if use_fallback:
        print(f"  Procurando PWS próximas de ({city.latitude}, {city.longitude})...")
        station_id, fallback_tested = find_pws_via_near(
            session, city.latitude, city.longitude, max_test=5
        )
        if station_id:
            print(f"  ✓ Fallback encontrou: {station_id}")
            country_match = True  # fallback é sempre válido para o país
        else:
            print(f"  ✗ Fallback também não encontrou PWS com dados")
            return {
                "city": city.name, "icao": city.icao,
                "pws_station_id": None, "pws_location_name": None,
                "wu_url": wu_url, "test": None,
                "sanity_check": None, "country_match": False,
                "fallback_tested": fallback_tested,
            }

    location_name = extract_pws_station_name(html)

    # Testar station
    print(f"  Testando {station_id} com /v2/pws/history/all (ontem)...", end=" ", flush=True)
    test_result = test_pws_station(session, station_id)

    sanity_ok = None
    sanity_msg = ""
    if test_result["ok"]:
        print(f"✓ {test_result['n_obs']} obs, temp {test_result['temp_min']:.1f}–{test_result['temp_max']:.1f}°C")

        # Sanity check vs climatologia
        sanity_ok, sanity_msg = sanity_check_temp(city, test_result["temp_min"], test_result["temp_max"])
        if sanity_ok:
            print(f"  ✓ Sanity check: {sanity_msg}")
        else:
            print(f"  🚨 SANITY CHECK FALHOU: {sanity_msg}")
    else:
        print(f"✗ {test_result.get('error', '?')}")

    time.sleep(0.5)

    return {
        "city":               city.name,
        "icao":               city.icao,
        "pws_station_id":     station_id,
        "pws_location_name":  location_name,
        "wu_url":             wu_url,
        "test":               test_result,
        "sanity_check":       {"ok": sanity_ok, "msg": sanity_msg},
        "country_match":      country_match,
        "via_fallback":       use_fallback,
        "fallback_tested":    fallback_tested,
    }


def update_config_py(results: dict) -> None:
    """Actualiza cities/config.py com os pws_station_id descobertos."""
    config_path = Path("cities/config.py")
    if not config_path.exists():
        print(f"  ✗ {config_path} não encontrado")
        return

    src = config_path.read_text()
    new_src = src

    # 1. Adicionar campo pws_station_id ao dataclass (se não existir)
    # IMPORTANTE: tem de ser inserido DEPOIS de todos os campos sem default.
    # No config.py original, os campos sem default são: name, icao, timezone,
    # latitude, longitude, polymarket_slug_pfx, wu_history_path, csv_path,
    # model_dir, unit, temp_range, max_daily_loss, max_per_trade, extra_features,
    # threshold, hour_min.
    # Os campos COM default começam em market_unit.
    # Inserir pws_station_id logo ANTES de market_unit (campo com default).
    if "pws_station_id" not in new_src:
        # Tentar inserir antes de market_unit (campo com default)
        if '    market_unit: str = "celsius"' in new_src:
            new_src = new_src.replace(
                '    market_unit: str = "celsius"',
                '    pws_station_id: str = ""                # PWS station ID (WU v2) — mesma que Polymarket usa\n'
                '    market_unit: str = "celsius"'
            )
            print(f"  ✓ Adicionado campo pws_station_id ao CityConfig (antes de market_unit)")
        else:
            # Fallback: inserir antes de wu_history_path (mas vai falhar se houver campos sem default depois)
            # NÃO usar este caminho — preferir falhar com mensagem clara
            print(f"  ✗ Não encontrei o ponto de inserção (market_unit). Edita config.py manualmente.")
            print(f"    Adiciona este campo ao CityConfig (depois dos campos sem default):")
            print(f'        pws_station_id: str = ""')
            return

    # 2. Para cada cidade com stationId descoberto, adicionar pws_station_id
    #    SÓ aplicar se: country_match=True E sanity_check=True
    #    Também activa o wu_history_path (de None para "pws") para a cidade ser
    #    considerada pelo _bootstrap_state_today no live_bot.py
    for city_name, info in results.items():
        sid = info.get("pws_station_id")
        if not sid:
            continue
        if not info.get("test", {}).get("ok"):
            print(f"  ! {city_name}: station {sid} não passou no teste — skip")
            continue
        if not info.get("country_match", True):
            print(f"  ! {city_name}: station {sid} é de país errado — skip (country_match=False)")
            continue
        sanity = info.get("sanity_check", {})
        if not sanity.get("ok", False):
            print(f"  ! {city_name}: station {sid} falhou sanity check — skip ({sanity.get('msg', '')})")
            continue

        # Procurar o bloco CityConfig da cidade
        pattern = rf'("{city_name}": CityConfig\(\s*name="{city_name}",.*?wu_history_path=(?:"[^"]+"|None),)'
        m = re.search(pattern, new_src, re.DOTALL)
        if not m:
            print(f"  ! {city_name}: não encontrei bloco no config.py")
            continue
        block = m.group(1)

        # 2a. Activar wu_history_path se for None (mudar para "pws" simbólico)
        if 'wu_history_path=None' in block:
            block = block.replace('wu_history_path=None', 'wu_history_path="pws"')
            print(f"  ✓ {city_name}: wu_history_path activado (None → \"pws\")")

        # 2b. Adicionar ou actualizar pws_station_id
        if "pws_station_id" in block:
            # Já tem — substituir
            new_block = re.sub(r'pws_station_id="[^"]*",', f'pws_station_id="{sid}",', block)
        else:
            # Adicionar após wu_history_path
            new_block = block + f'\n        pws_station_id="{sid}",'
        new_src = new_src.replace(block, new_block, 1)
        print(f"  ✓ {city_name}: pws_station_id=\"{sid}\"")

    if new_src != src:
        backup = config_path.with_suffix(".py.bak")
        backup.write_text(src)
        config_path.write_text(new_src)
        print(f"\n  Backup: {backup}")
        print(f"  {config_path} actualizado")
    else:
        print(f"\n  Sem alterações necessárias")


def main():
    parser = argparse.ArgumentParser(
        description="Descobre PWS stationId oficial usado pelo WU/Polymarket para cada cidade."
    )
    parser.add_argument("--cities", type=str, default=None,
                        help="Cidades separadas por vírgula (default: todas)")
    parser.add_argument("--apply", action="store_true",
                        help="Actualiza cities/config.py com os stationIds descobertos")
    args = parser.parse_args()

    if not API_KEY:
        print("ERRO: WU_API_KEY não definida")
        sys.exit(1)

    if args.cities:
        if args.cities.lower() == "all":
            cities_to_test = list(CITIES.values())
        else:
            city_names = [c.strip().lower() for c in args.cities.split(",")]
            cities_to_test = [CITIES[n] for n in city_names if n in CITIES]
    else:
        cities_to_test = list(CITIES.values())

    print(f"\nVou descobrir PWS stations para {len(cities_to_test)} cidades...")
    print(f"Atenção: vou buscar a página WU history de cada cidade (pode demorar).")

    session = make_session()
    all_results = {}
    for city in cities_to_test:
        result = discover_for_city(session, city)
        all_results[city.name] = result
        time.sleep(2)  # rate limit friendly

    # Resumo
    print(f"\n{'='*70}")
    print(f"  RESUMO FINAL")
    print(f"{'='*70}")
    n_ok = 0
    n_fail = 0
    n_suspicious = 0
    for city_name, info in all_results.items():
        sid = info.get("pws_station_id")
        test = info.get("test", {}) or {}
        ok = test.get("ok", False)
        country_match = info.get("country_match", True)
        sanity = info.get("sanity_check", {}) or {}
        sanity_ok = sanity.get("ok", False)

        if sid and ok and country_match and sanity_ok:
            loc = info.get("pws_location_name", "?") or "?"
            n_obs = test.get("n_obs", 0)
            print(f"  ✓ {city_name:18s} → {sid} ({loc}, {n_obs} obs)")
            n_ok += 1
        elif sid and (not country_match or not sanity_ok):
            reasons = []
            if not country_match:
                reasons.append("país errado")
            if not sanity_ok:
                reasons.append(sanity.get("msg", "sanity fail"))
            print(f"  🚨 {city_name:18s} → {sid} SUSPEITO ({'; '.join(reasons)})")
            n_suspicious += 1
        elif sid and not ok:
            print(f"  ⚠ {city_name:18s} → {sid} (sem dados: {test.get('error', '?')})")
            n_fail += 1
        else:
            print(f"  ✗ {city_name:18s} → sem stationId extraído")
            n_fail += 1
    print(f"\n  Total: {n_ok} OK, {n_suspicious} suspeitos, {n_fail} falharam")

    if n_suspicious > 0:
        print(f"\n  ⚠ Cidades suspeitas NÃO vão ser aplicadas automaticamente.")
        print(f"  ⚠ Verifica manualmente as regras do Polymarket para essas cidades.")

    # Gravar JSON
    out_path = Path("pws_stations_official.json")
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n  Detalhes: {out_path}")

    if args.apply and n_ok > 0:
        print(f"\n{'='*70}")
        print(f"  A actualizar cities/config.py...")
        print(f"{'='*70}")
        update_config_py(all_results)
    elif n_ok > 0 and not args.apply:
        print(f"\n  Para aplicar a cities/config.py:")
        print(f"    python discover_pws_from_wu_pages.py --apply")


if __name__ == "__main__":
    main()
