"""
cities/config.py
================
Configuração de cidades para sistema multi-cidade.

Contém CityConfig dataclass e CITIES dict com configuração das cidades.

Última calibração: 2026-07-18 (todas as cidades, modo full, 5-7 anos)
Os valores activos de threshold/hour_min vêm dos strategy_config_{city}.json.
Em runtime o live_bot lê os JSONs directamente via city.strategy_config_path.
Os valores aqui servem só como fallback neutro de emergência.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SingleEntryConfig:
    """Configuração do Single Entry por cidade."""
    enabled: bool = True
    parcel_size: float = 5.0
    threshold: float = 0.650
    hour_min: int = 11
    stop_loss_delta: float = 1.0
    min_buy_ask: float = 0.20
    max_buy_ask: float = 0.85


@dataclass
class StrategyConfig:
    """Configuração de estratégia por cidade."""
    mode: str = "single"
    single: SingleEntryConfig = field(default_factory=SingleEntryConfig)


@dataclass
class CityConfig:
    """Configuração completa de uma cidade."""
    name: str
    icao: str                            # Código ICAO do aeroporto
    timezone: str                        # Timezone (ex: Europe/Berlin)
    latitude: float                      # Latitude Open-Meteo
    longitude: float                     # Longitude Open-Meteo
    polymarket_slug_pfx: str             # Prefixo do slug Polymarket
    wu_history_path: Optional[str]       # Caminho WU (se aplicável)
    csv_path: str                        # Caminho do CSV histórico
    model_dir: str                       # Diretório do modelo treinado
    unit: str                            # Unidade de temperatura (celsius)
    temp_range: range                    # Range válido de temperaturas
    max_daily_loss: float                # Máxima perda diária ($)
    max_per_trade: float                 # Máximo por trade ($)
    extra_features: list[str]            # Features específicas da cidade
    threshold: Optional[float]           # Threshold (fallback — runtime usa JSON)
    hour_min: Optional[int]              # Hora mínima (fallback — runtime usa JSON)
    pws_station_id: str = ""                # PWS station ID (WU v2) — mesma que Polymarket usa
    market_unit: str = "celsius"         # Unidade no Polymarket (celsius/fahrenheit)
    day_start: int = 6                   # Hora início do dia (hora local)
    day_end: int = 21                    # Hora fim do dia (hora local)
    bot_timezone: str = "Europe/Lisbon"  # Timezone do bot (CASSIOPEIA = Lisboa)
    climatology: dict[int, float] | None = None  # Média mensal da máxima diária

    def __post_init__(self) -> None:
        model_path = Path(self.model_dir)
        if not model_path.is_absolute():
            self.model_dir = str(self.city_dir / model_path.name)

    @property
    def city_dir(self) -> Path:
        return Path("cities") / self.name

    @property
    def strategy_config_path(self) -> Path:
        return self.city_dir / f"strategy_config_{self.name}.json"


# ══════════════════════════════════════════════════════════════════════════════
#  CITIES
#  Valores activos de threshold e hour_min vêm dos strategy_config_{city}.json.
#  Os defaults aqui são neutros para não atrapalhar novas calibrações.
#  NOTA: Todas as cidades usam CELSIUS (sem fahrenheit).
# ══════════════════════════════════════════════════════════════════════════════

CITIES = {

    # ─────────────────────────────────────────────────────────────
    #  EUROPA — NORTE / CENTRO / OESTE
    # ─────────────────────────────────────────────────────────────

    "amsterdam": CityConfig(
        name="amsterdam",
        icao="EHAM",
        timezone="Europe/Amsterdam",
        latitude=52.31,
        longitude=4.77,
        polymarket_slug_pfx="highest-temperature-in-amsterdam-on",
        wu_history_path="nl/amsterdam/EHAM",
        pws_station_id="IAMSTERD35",
        csv_path="historic/amsterdam.csv",
        model_dir="cities/amsterdam/amsterdam_peak_model",
        unit="celsius",
        temp_range=range(-10, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 6.0,  2: 7.0,  3: 10.0, 4: 14.0, 5: 18.0, 6: 21.0,
            7: 23.0, 8: 23.0, 9: 19.0, 10: 15.0, 11: 10.0, 12: 7.0
        },
    ),

    "athens": CityConfig(
        name="athens",
        icao="LGAV",
        timezone="Europe/Athens",
        latitude=37.94,
        longitude=23.64,
        polymarket_slug_pfx="highest-temperature-in-athens-on",
        wu_history_path="gr/athens/LGAV",
        pws_station_id="IATHEN61",
        csv_path="historic/athens.csv",
        model_dir="cities/athens/athens_peak_model",
        unit="celsius",
        temp_range=range(0, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 13.0, 2: 14.0, 3: 17.0, 4: 21.0, 5: 26.0, 6: 31.0,
            7: 34.0, 8: 34.0, 9: 29.0, 10: 24.0, 11: 18.0, 12: 14.0
        },
    ),

    "berlin": CityConfig(
        name="berlin",
        icao="EDDB",
        timezone="Europe/Berlin",
        latitude=52.37,
        longitude=13.50,
        polymarket_slug_pfx="highest-temperature-in-berlin-on",
        wu_history_path="de/berlin/EDDB",
        pws_station_id="IBERLI723",
        csv_path="historic/berlin.csv",
        model_dir="cities/berlin/berlin_peak_model",
        unit="celsius",
        temp_range=range(-15, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 3.0,  2: 5.0,  3: 9.0,  4: 15.0, 5: 20.0, 6: 23.0,
            7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 8.0,  12: 4.0
        },
    ),

    "brussels": CityConfig(
        name="brussels",
        icao="EBBR",
        timezone="Europe/Brussels",
        latitude=50.90,
        longitude=4.48,
        polymarket_slug_pfx="highest-temperature-in-brussels-on",
        wu_history_path="be/brussels/EBBR",
        pws_station_id="IBRUSS19",
        csv_path="historic/brussels.csv",
        model_dir="cities/brussels/brussels_peak_model",
        unit="celsius",
        temp_range=range(-8, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 6.0,  2: 7.0,  3: 10.0, 4: 14.0, 5: 18.0, 6: 21.0,
            7: 23.0, 8: 23.0, 9: 19.0, 10: 15.0, 11: 10.0, 12: 7.0
        },
    ),

    "bucharest": CityConfig(
        name="bucharest",
        icao="LROP",
        timezone="Europe/Bucharest",
        latitude=44.57,
        longitude=26.08,
        polymarket_slug_pfx="highest-temperature-in-bucharest-on",
        wu_history_path="ro/bucharest/LROP",
        pws_station_id="IBUCHAR22",
        csv_path="historic/bucharest.csv",
        model_dir="cities/bucharest/bucharest_peak_model",
        unit="celsius",
        temp_range=range(-15, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 2.0,  2: 5.0,  3: 11.0, 4: 17.0, 5: 23.0, 6: 27.0,
            7: 29.0, 8: 29.0, 9: 24.0, 10: 17.0, 11: 9.0,  12: 3.0
        },
    ),

    "budapest": CityConfig(
        name="budapest",
        icao="LHBP",
        timezone="Europe/Budapest",
        latitude=47.43,
        longitude=19.26,
        polymarket_slug_pfx="highest-temperature-in-budapest-on",
        wu_history_path="hu/budapest/LHBP",
        pws_station_id="IBUDAP603",
        csv_path="historic/budapest.csv",
        model_dir="cities/budapest/budapest_peak_model",
        unit="celsius",
        temp_range=range(-15, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 2.0,  2: 5.0,  3: 10.0, 4: 16.0, 5: 21.0, 6: 25.0,
            7: 27.0, 8: 27.0, 9: 22.0, 10: 16.0, 11: 8.0,  12: 3.0
        },
    ),

    "copenhagen": CityConfig(
        name="copenhagen",
        icao="EKCH",
        timezone="Europe/Copenhagen",
        latitude=55.62,
        longitude=12.65,
        polymarket_slug_pfx="highest-temperature-in-copenhagen-on",
        wu_history_path="dk/copenhagen/EKCH",
        pws_station_id="ICOPENHA111",
        csv_path="historic/copenhagen.csv",
        model_dir="cities/copenhagen/copenhagen_peak_model",
        unit="celsius",
        temp_range=range(-12, 30),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 2.0,  2: 3.0,  3: 6.0,  4: 11.0, 5: 16.0, 6: 20.0,
            7: 22.0, 8: 21.0, 9: 17.0, 10: 12.0, 11: 7.0,  12: 3.0
        },
    ),

    "dublin": CityConfig(
        name="dublin",
        icao="EIDW",
        timezone="Europe/Dublin",
        latitude=53.43,
        longitude=-6.25,
        polymarket_slug_pfx="highest-temperature-in-dublin-on",
        wu_history_path="ie/dublin/EIDW",
        pws_station_id="IDUBLIN55",
        csv_path="historic/dublin.csv",
        model_dir="cities/dublin/dublin_peak_model",
        unit="celsius",
        temp_range=range(-5, 28),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 8.0,  2: 8.0,  3: 10.0, 4: 12.0, 5: 15.0, 6: 18.0,
            7: 20.0, 8: 19.0, 9: 17.0, 10: 14.0, 11: 10.0, 12: 8.0
        },
    ),

    "helsinki": CityConfig(
        name="helsinki",
        icao="EFHK",
        timezone="Europe/Helsinki",
        latitude=60.32,
        longitude=24.97,
        polymarket_slug_pfx="highest-temperature-in-helsinki-on",
        wu_history_path="fi/helsinki/EFHK",
        pws_station_id="IHELSIN55",
        csv_path="historic/helsinki.csv",
        model_dir="cities/helsinki/helsinki_peak_model",
        unit="celsius",
        temp_range=range(-25, 30),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: -2.0, 2: -2.0, 3: 2.0,  4: 8.0,  5: 15.0, 6: 20.0,
            7: 22.0, 8: 20.0, 9: 15.0, 10: 8.0,  11: 2.0,  12: -1.0
        },
    ),

    "lisbon": CityConfig(
        name="lisbon",
        icao="LPPT",
        timezone="Europe/Lisbon",
        latitude=38.78,
        longitude=-9.13,
        polymarket_slug_pfx="highest-temperature-in-lisbon-on",
        wu_history_path="pt/lisbon/LPPT",
        pws_station_id="ILISBOA72",
        csv_path="historic/lisbon.csv",
        model_dir="cities/lisbon/lisbon_peak_model",
        unit="celsius",
        temp_range=range(5, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 15.0, 2: 16.0, 3: 18.0, 4: 20.0, 5: 22.0, 6: 26.0,
            7: 28.0, 8: 28.0, 9: 26.0, 10: 22.0, 11: 18.0, 12: 15.0
        },
    ),

    "london": CityConfig(
        name="london",
        icao="EGLL",
        timezone="Europe/London",
        latitude=51.47,
        longitude=-0.46,
        polymarket_slug_pfx="highest-temperature-in-london-on",
        wu_history_path="gb/london/EGLL",
        pws_station_id="ILONDON123",
        csv_path="historic/london.csv",
        model_dir="cities/london/london_peak_model",
        unit="celsius",
        temp_range=range(-8, 32),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 8.0,  2: 9.0,  3: 12.0, 4: 15.0, 5: 18.0, 6: 21.0,
            7: 23.0, 8: 23.0, 9: 20.0, 10: 16.0, 11: 12.0, 12: 9.0
        },
    ),

    "madrid": CityConfig(
        name="madrid",
        icao="LEMD",
        timezone="Europe/Madrid",
        latitude=40.47,
        longitude=-3.56,
        polymarket_slug_pfx="highest-temperature-in-madrid-on",
        wu_history_path="es/madrid/LEMD",
        pws_station_id="IMADRI133",
        csv_path="historic/madrid.csv",
        model_dir="cities/madrid/madrid_peak_model",
        unit="celsius",
        temp_range=range(-10, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 10.0, 2: 12.0, 3: 16.0, 4: 18.0, 5: 23.0, 6: 28.0,
            7: 33.0, 8: 32.0, 9: 27.0, 10: 20.0, 11: 14.0, 12: 10.0
        },
    ),

    "moscow": CityConfig(
        name="moscow",
        icao="UUEE",
        timezone="Europe/Moscow",
        latitude=55.97,
        longitude=37.41,
        polymarket_slug_pfx="highest-temperature-in-moscow-on",
        wu_history_path="ru/moscow/UUEE",
        pws_station_id="IMOSCO234",
        csv_path="historic/moscow.csv",
        model_dir="cities/moscow/moscow_peak_model",
        unit="celsius",
        temp_range=range(-30, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: -4.0, 2: -3.0, 3: 4.0,  4: 12.0, 5: 20.0, 6: 23.0,
            7: 26.0, 8: 24.0, 9: 17.0, 10: 9.0,  11: 1.0,  12: -3.0
        },
    ),

    "munich": CityConfig(
        name="munich",
        icao="EDDM",
        timezone="Europe/Berlin",
        latitude=48.14,
        longitude=11.58,
        polymarket_slug_pfx="highest-temperature-in-munich-on",
        wu_history_path="de/munich/EDDM",
        pws_station_id="IOBERD38",
        csv_path="historic/munich.csv",
        model_dir="cities/munich/munich_peak_model",
        unit="celsius",
        temp_range=range(-17, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 3.0,  2: 5.0,  3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
            7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 7.0,  12: 4.0
        },
    ),

    "oslo": CityConfig(
        name="oslo",
        icao="ENGM",
        timezone="Europe/Oslo",
        latitude=60.20,
        longitude=11.08,
        polymarket_slug_pfx="highest-temperature-in-oslo-on",
        wu_history_path="no/oslo/ENGM",
        pws_station_id="IOSLO123",
        csv_path="historic/oslo.csv",
        model_dir="cities/oslo/oslo_peak_model",
        unit="celsius",
        temp_range=range(-20, 28),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: -1.0, 2: 0.0,  3: 4.0,  4: 10.0, 5: 16.0, 6: 20.0,
            7: 22.0, 8: 20.0, 9: 15.0, 10: 9.0,  11: 3.0,  12: 0.0
        },
    ),

    "paris": CityConfig(
        name="paris",
        icao="LFPG",
        timezone="Europe/Paris",
        latitude=49.01,
        longitude=2.55,
        polymarket_slug_pfx="highest-temperature-in-paris-on",
        wu_history_path="fr/paris/LFPG",
        pws_station_id="IPARIS18204",
        csv_path="historic/paris.csv",
        model_dir="cities/paris/paris_peak_model",
        unit="celsius",
        temp_range=range(-8, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 7.0,  2: 9.0,  3: 13.0, 4: 16.0, 5: 20.0, 6: 24.0,
            7: 26.0, 8: 25.0, 9: 21.0, 10: 16.0, 11: 11.0, 12: 8.0
        },
    ),

    "prague": CityConfig(
        name="prague",
        icao="LKPR",
        timezone="Europe/Prague",
        latitude=50.10,
        longitude=14.26,
        polymarket_slug_pfx="highest-temperature-in-prague-on",
        wu_history_path="cz/prague/LKPR",
        pws_station_id="IPRAGUE55",
        csv_path="historic/prague.csv",
        model_dir="cities/prague/prague_peak_model",
        unit="celsius",
        temp_range=range(-18, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 2.0,  2: 4.0,  3: 9.0,  4: 15.0, 5: 20.0, 6: 23.0,
            7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 7.0,  12: 3.0
        },
    ),

    "rome": CityConfig(
        name="rome",
        icao="LIRF",
        timezone="Europe/Rome",
        latitude=41.80,
        longitude=12.25,
        polymarket_slug_pfx="highest-temperature-in-rome-on",
        wu_history_path="it/rome/LIRF",
        pws_station_id="IROME123",
        csv_path="historic/rome.csv",
        model_dir="cities/rome/rome_peak_model",
        unit="celsius",
        temp_range=range(-2, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 12.0, 2: 13.0, 3: 16.0, 4: 19.0, 5: 24.0, 6: 29.0,
            7: 32.0, 8: 32.0, 9: 27.0, 10: 22.0, 11: 17.0, 12: 13.0
        },
    ),

    "stockholm": CityConfig(
        name="stockholm",
        icao="ESSA",
        timezone="Europe/Stockholm",
        latitude=59.65,
        longitude=17.93,
        polymarket_slug_pfx="highest-temperature-in-stockholm-on",
        wu_history_path="se/stockholm/ESSA",
        pws_station_id="ISTOCKH123",
        csv_path="historic/stockholm.csv",
        model_dir="cities/stockholm/stockholm_peak_model",
        unit="celsius",
        temp_range=range(-20, 30),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 0.0,  2: 1.0,  3: 5.0,  4: 11.0, 5: 17.0, 6: 21.0,
            7: 23.0, 8: 21.0, 9: 16.0, 10: 10.0, 11: 4.0,  12: 1.0
        },
    ),

    "vienna": CityConfig(
        name="vienna",
        icao="LOWW",
        timezone="Europe/Vienna",
        latitude=48.11,
        longitude=16.57,
        polymarket_slug_pfx="highest-temperature-in-vienna-on",
        wu_history_path="at/vienna/LOWW",
        pws_station_id="IVIENNA55",
        csv_path="historic/vienna.csv",
        model_dir="cities/vienna/vienna_peak_model",
        unit="celsius",
        temp_range=range(-15, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 3.0,  2: 5.0,  3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
            7: 26.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 8.0,  12: 4.0
        },
    ),

    "warsaw": CityConfig(
        name="warsaw",
        icao="EPWA",
        timezone="Europe/Warsaw",
        latitude=52.17,
        longitude=20.97,
        polymarket_slug_pfx="highest-temperature-in-warsaw-on",
        wu_history_path="pl/warsaw/EPWA",
        pws_station_id="IWARSA531",
        csv_path="historic/warsaw.csv",
        model_dir="cities/warsaw/warsaw_peak_model",
        unit="celsius",
        temp_range=range(-20, 36),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 1.0,  2: 3.0,  3: 8.0,  4: 14.0, 5: 20.0, 6: 23.0,
            7: 25.0, 8: 24.0, 9: 18.0, 10: 12.0, 11: 5.0,  12: 2.0
        },
    ),

    "zurich": CityConfig(
        name="zurich",
        icao="LSZH",
        timezone="Europe/Zurich",
        latitude=47.46,
        longitude=8.55,
        polymarket_slug_pfx="highest-temperature-in-zurich-on",
        wu_history_path="ch/zurich/LSZH",
        pws_station_id="IZURICH55",
        csv_path="historic/zurich.csv",
        model_dir="cities/zurich/zurich_peak_model",
        unit="celsius",
        temp_range=range(-15, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 3.0,  2: 5.0,  3: 10.0, 4: 14.0, 5: 19.0, 6: 22.0,
            7: 25.0, 8: 24.0, 9: 19.0, 10: 14.0, 11: 8.0,  12: 4.0
        },
    ),

    # ─────────────────────────────────────────────────────────────
    #  EUROPA — MEDITERRÂNEO / ORIENTE MÉDIO
    # ─────────────────────────────────────────────────────────────

    "ankara": CityConfig(
        name="ankara",
        icao="LTAC",
        timezone="Europe/Istanbul",
        latitude=40.13,
        longitude=32.99,
        polymarket_slug_pfx="highest-temperature-in-ankara-on",
        wu_history_path="tr/ankara/LTAC",
        pws_station_id="IANKARA25",
        csv_path="historic/ankara.csv",
        model_dir="cities/ankara/ankara_peak_model",
        unit="celsius",
        temp_range=range(-25, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 4.0,  2: 6.0,  3: 11.0, 4: 16.0, 5: 21.0, 6: 25.0,
            7: 29.0, 8: 29.0, 9: 24.0, 10: 18.0, 11: 11.0, 12: 6.0
        },
    ),

    "tel_aviv": CityConfig(
        name="tel_aviv",
        icao="LLBG",
        timezone="Asia/Jerusalem",
        latitude=32.01,
        longitude=34.89,
        polymarket_slug_pfx="highest-temperature-in-tel-aviv-on",
        wu_history_path="il/tel-aviv/LLBG",
        pws_station_id="ICENTRAL248",
        csv_path="historic/tel_aviv.csv",
        model_dir="cities/tel_aviv/tel_aviv_peak_model",
        unit="celsius",
        temp_range=range(10, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 17.0, 2: 18.0, 3: 20.0, 4: 24.0, 5: 27.0, 6: 30.0,
            7: 31.0, 8: 32.0, 9: 30.0, 10: 27.0, 11: 22.0, 12: 18.0
        },
    ),

    # ─────────────────────────────────────────────────────────────
    #  ÁSIA — SUL / SUDESTE / LESTE
    # ─────────────────────────────────────────────────────────────

    "bangkok": CityConfig(
        name="bangkok",
        icao="VTBS",
        timezone="Asia/Bangkok",
        latitude=13.69,
        longitude=100.75,
        polymarket_slug_pfx="highest-temperature-in-bangkok-on",
        wu_history_path="th/bangkok/VTBS",
        pws_station_id="IBANGKOK255",
        csv_path="historic/bangkok.csv",
        model_dir="cities/bangkok/bangkok_peak_model",
        unit="celsius",
        temp_range=range(20, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 32.0, 2: 33.0, 3: 34.0, 4: 35.0, 5: 34.0, 6: 33.0,
            7: 32.0, 8: 32.0, 9: 32.0, 10: 32.0, 11: 31.0, 12: 31.0
        },
    ),

    "beijing": CityConfig(
        name="beijing",
        icao="ZBAA",
        timezone="Asia/Shanghai",
        latitude=40.08,
        longitude=116.60,
        polymarket_slug_pfx="highest-temperature-in-beijing-on",
        wu_history_path="cn/beijing/ZBAA",
        pws_station_id="IBEJING55",
        csv_path="historic/beijing.csv",
        model_dir="cities/beijing/beijing_peak_model",
        unit="celsius",
        temp_range=range(-20, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 1.0,  2: 5.0,  3: 12.0, 4: 20.0, 5: 26.0, 6: 31.0,
            7: 31.0, 8: 29.0, 9: 23.0, 10: 16.0, 11: 7.0,  12: 2.0
        },
    ),

    "delhi": CityConfig(
        name="delhi",
        icao="VIDP",
        timezone="Asia/Kolkata",
        latitude=28.57,
        longitude=77.10,
        polymarket_slug_pfx="highest-temperature-in-delhi-on",
        wu_history_path="in/delhi/VIDP",
        pws_station_id="INEWDEL55",
        csv_path="historic/delhi.csv",
        model_dir="cities/delhi/delhi_peak_model",
        unit="celsius",
        temp_range=range(5, 48),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 20.0, 2: 24.0, 3: 30.0, 4: 37.0, 5: 40.0, 6: 39.0,
            7: 35.0, 8: 34.0, 9: 34.0, 10: 33.0, 11: 28.0, 12: 22.0
        },
    ),

    "dubai": CityConfig(
        name="dubai",
        icao="OMDB",
        timezone="Asia/Dubai",
        latitude=25.25,
        longitude=55.36,
        polymarket_slug_pfx="highest-temperature-in-dubai-on",
        wu_history_path="ae/dubai/OMDB",
        pws_station_id="IDUBAI55",
        csv_path="historic/dubai.csv",
        model_dir="cities/dubai/dubai_peak_model",
        unit="celsius",
        temp_range=range(15, 50),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 24.0, 2: 26.0, 3: 29.0, 4: 34.0, 5: 39.0, 6: 41.0,
            7: 41.0, 8: 41.0, 9: 39.0, 10: 35.0, 11: 30.0, 12: 26.0
        },
    ),

    "hong_kong": CityConfig(
        name="hong_kong",
        icao="VHHH",
        timezone="Asia/Hong_Kong",
        latitude=22.31,
        longitude=113.91,
        polymarket_slug_pfx="highest-temperature-in-hong-kong-on",
        wu_history_path="hk/hong-kong/VHHH",
        pws_station_id="IHONGKO55",
        csv_path="historic/hong_kong.csv",
        model_dir="cities/hong_kong/hong_kong_peak_model",
        unit="celsius",
        temp_range=range(10, 36),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 18.0, 2: 19.0, 3: 21.0, 4: 25.0, 5: 28.0, 6: 30.0,
            7: 31.0, 8: 31.0, 9: 30.0, 10: 27.0, 11: 23.0, 12: 19.0
        },
    ),

    "jakarta": CityConfig(
        name="jakarta",
        icao="WIII",
        timezone="Asia/Jakarta",
        latitude=-6.13,
        longitude=106.66,
        polymarket_slug_pfx="highest-temperature-in-jakarta-on",
        wu_history_path="id/jakarta/WIII",
        pws_station_id="IJAKAR14",
        csv_path="historic/jakarta.csv",
        model_dir="cities/jakarta/jakarta_peak_model",
        unit="celsius",
        temp_range=range(20, 37),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 30.0, 2: 30.0, 3: 31.0, 4: 32.0, 5: 32.0, 6: 32.0,
            7: 32.0, 8: 32.0, 9: 33.0, 10: 33.0, 11: 32.0, 12: 31.0
        },
    ),

    "karachi": CityConfig(
        name="karachi",
        icao="OPKC",
        timezone="Asia/Karachi",
        latitude=24.90,
        longitude=67.17,
        polymarket_slug_pfx="highest-temperature-in-karachi-on",
        wu_history_path="pk/karachi/OPKC",
        pws_station_id="IKARAC56",
        csv_path="historic/karachi.csv",
        model_dir="cities/karachi/karachi_peak_model",
        unit="celsius",
        temp_range=range(5, 48),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 25.0, 2: 27.0, 3: 32.0, 4: 35.0, 5: 36.0, 6: 35.0,
            7: 33.0, 8: 32.0, 9: 33.0, 10: 35.0, 11: 32.0, 12: 27.0
        },
    ),

    "kuala_lumpur": CityConfig(
        name="kuala_lumpur",
        icao="WMKK",
        timezone="Asia/Kuala_Lumpur",
        latitude=2.75,
        longitude=101.71,
        polymarket_slug_pfx="highest-temperature-in-kuala-lumpur-on",
        wu_history_path="my/kuala-lumpur/WMKK",
        pws_station_id="IDENGK2",
        csv_path="historic/kuala_lumpur.csv",
        model_dir="cities/kuala_lumpur/kuala_lumpur_peak_model",
        unit="celsius",
        temp_range=range(20, 37),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 32.0, 2: 33.0, 3: 33.0, 4: 33.0, 5: 33.0, 6: 33.0,
            7: 32.0, 8: 32.0, 9: 32.0, 10: 32.0, 11: 32.0, 12: 32.0
        },
    ),

    "manila": CityConfig(
        name="manila",
        icao="RPLL",
        timezone="Asia/Manila",
        latitude=14.51,
        longitude=121.02,
        polymarket_slug_pfx="highest-temperature-in-manila-on",
        wu_history_path="ph/manila/RPLL",
        pws_station_id="IMANILA55",
        csv_path="historic/manila.csv",
        model_dir="cities/manila/manila_peak_model",
        unit="celsius",
        temp_range=range(20, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 30.0, 2: 31.0, 3: 32.0, 4: 34.0, 5: 34.0, 6: 33.0,
            7: 32.0, 8: 32.0, 9: 32.0, 10: 32.0, 11: 31.0, 12: 30.0
        },
    ),

    "mumbai": CityConfig(
        name="mumbai",
        icao="VABB",
        timezone="Asia/Kolkata",
        latitude=19.09,
        longitude=72.87,
        polymarket_slug_pfx="highest-temperature-in-mumbai-on",
        wu_history_path="in/mumbai/VABB",
        pws_station_id="IMUMBAI55",
        csv_path="historic/mumbai.csv",
        model_dir="cities/mumbai/mumbai_peak_model",
        unit="celsius",
        temp_range=range(20, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 30.0, 2: 31.0, 3: 33.0, 4: 33.0, 5: 33.0, 6: 31.0,
            7: 29.0, 8: 29.0, 9: 30.0, 10: 33.0, 11: 33.0, 12: 31.0
        },
    ),

    "seoul": CityConfig(
        name="seoul",
        icao="RKSI",
        timezone="Asia/Seoul",
        latitude=37.47,
        longitude=126.45,
        polymarket_slug_pfx="highest-temperature-in-seoul-on",
        wu_history_path="kr/seoul/RKSI",
        pws_station_id="ISEOUL55",
        csv_path="historic/seoul.csv",
        model_dir="cities/seoul/seoul_peak_model",
        unit="celsius",
        temp_range=range(-15, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 2.0,  2: 5.0,  3: 10.0, 4: 17.0, 5: 23.0, 6: 27.0,
            7: 29.0, 8: 30.0, 9: 26.0, 10: 20.0, 11: 12.0, 12: 4.0
        },
    ),

    "singapore": CityConfig(
        name="singapore",
        icao="WSSS",
        timezone="Asia/Singapore",
        latitude=1.35,
        longitude=103.99,
        polymarket_slug_pfx="highest-temperature-in-singapore-on",
        wu_history_path="sg/singapore/WSSS",
        pws_station_id="ISINGA249",
        csv_path="historic/singapore.csv",
        model_dir="cities/singapore/singapore_peak_model",
        unit="celsius",
        temp_range=range(20, 37),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 31.0, 2: 32.0, 3: 32.0, 4: 32.0, 5: 32.0, 6: 32.0,
            7: 31.0, 8: 31.0, 9: 31.0, 10: 31.0, 11: 31.0, 12: 30.0
        },
    ),

    "taipei": CityConfig(
        name="taipei",
        icao="RCSS",
        timezone="Asia/Taipei",
        latitude=25.07,
        longitude=121.55,
        polymarket_slug_pfx="highest-temperature-in-taipei-on",
        wu_history_path="tw/taipei/RCSS",
        pws_station_id="ITAIPE22",
        csv_path="historic/taipei.csv",
        model_dir="cities/taipei/taipei_peak_model",
        unit="celsius",
        temp_range=range(5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 19.0, 2: 20.0, 3: 23.0, 4: 26.0, 5: 30.0, 6: 32.0,
            7: 34.0, 8: 33.0, 9: 31.0, 10: 28.0, 11: 25.0, 12: 21.0
        },
    ),

    "tokyo": CityConfig(
        name="tokyo",
        icao="RJTT",
        timezone="Asia/Tokyo",
        latitude=35.55,
        longitude=139.78,
        polymarket_slug_pfx="highest-temperature-in-tokyo-on",
        wu_history_path="jp/tokyo/RJTT",
        pws_station_id="ITOKYO55",
        csv_path="historic/tokyo.csv",
        model_dir="cities/tokyo/tokyo_peak_model",
        unit="celsius",
        temp_range=range(-5, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 10.0, 2: 11.0, 3: 14.0, 4: 19.0, 5: 23.0, 6: 26.0,
            7: 30.0, 8: 31.0, 9: 27.0, 10: 22.0, 11: 17.0, 12: 12.0
        },
    ),

    # ─────────────────────────────────────────────────────────────
    #  ÁFRICA / AMÉRICA LATINA / OUTROS
    # ─────────────────────────────────────────────────────────────

    "cairo": CityConfig(
        name="cairo",
        icao="HECA",
        timezone="Africa/Cairo",
        latitude=30.12,
        longitude=31.41,
        polymarket_slug_pfx="highest-temperature-in-cairo-on",
        wu_history_path="eg/cairo/HECA",
        pws_station_id="ICAIRO55",
        csv_path="historic/cairo.csv",
        model_dir="cities/cairo/cairo_peak_model",
        unit="celsius",
        temp_range=range(10, 45),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 19.0, 2: 21.0, 3: 24.0, 4: 29.0, 5: 33.0, 6: 35.0,
            7: 35.0, 8: 35.0, 9: 33.0, 10: 30.0, 11: 25.0, 12: 20.0
        },
    ),

    "lagos": CityConfig(
        name="lagos",
        icao="DNMM",
        timezone="Africa/Lagos",
        latitude=6.58,
        longitude=3.32,
        polymarket_slug_pfx="highest-temperature-in-lagos-on",
        wu_history_path="ng/lagos/DNMM",
        pws_station_id="ILAGOS81",
        csv_path="historic/lagos.csv",
        model_dir="cities/lagos/lagos_peak_model",
        unit="celsius",
        temp_range=range(18, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 32.0, 2: 33.0, 3: 33.0, 4: 32.0, 5: 31.0, 6: 29.0,
            7: 28.0, 8: 28.0, 9: 29.0, 10: 30.0, 11: 31.0, 12: 32.0
        },
    ),

    "bogota": CityConfig(
        name="bogota",
        icao="SKBO",
        timezone="America/Bogota",
        latitude=4.70,
        longitude=-74.15,
        polymarket_slug_pfx="highest-temperature-in-bogota-on",
        wu_history_path="co/bogota/SKBO",
        pws_station_id="IBOGOTA55",
        csv_path="historic/bogota.csv",
        model_dir="cities/bogota/bogota_peak_model",
        unit="celsius",
        temp_range=range(10, 28),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 20.0, 2: 20.0, 3: 20.0, 4: 20.0, 5: 20.0, 6: 19.0,
            7: 18.0, 8: 18.0, 9: 19.0, 10: 19.0, 11: 19.0, 12: 19.0
        },
    ),

    "buenos_aires": CityConfig(
        name="buenos_aires",
        icao="SAEZ",
        timezone="America/Argentina/Buenos_Aires",
        latitude=-34.56,
        longitude=-58.41,
        polymarket_slug_pfx="highest-temperature-in-buenos-aires-on",
        wu_history_path="ar/buenos-aires/SAEZ",
        pws_station_id="IMONTEGR27",
        csv_path="historic/buenos_aires.csv",
        model_dir="cities/buenos_aires/buenos_aires_peak_model",
        unit="celsius",
        temp_range=range(-5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 30.0, 2: 29.0, 3: 26.0, 4: 22.0, 5: 18.0, 6: 15.0,
            7: 14.0, 8: 16.0, 9: 19.0, 10: 23.0, 11: 27.0, 12: 29.0
        },
    ),

    "mexico_city": CityConfig(
        name="mexico_city",
        icao="MMMX",
        timezone="America/Mexico_City",
        latitude=19.43,
        longitude=-99.07,
        polymarket_slug_pfx="highest-temperature-in-mexico-city-on",
        wu_history_path="mx/mexico-city/MMMX",
        pws_station_id="IMEXICO55",
        csv_path="historic/mexico_city.csv",
        model_dir="cities/mexico_city/mexico_city_peak_model",
        unit="celsius",
        temp_range=range(10, 32),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 22.0, 2: 24.0, 3: 26.0, 4: 27.0, 5: 27.0, 6: 25.0,
            7: 24.0, 8: 24.0, 9: 23.0, 10: 23.0, 11: 22.0, 12: 21.0
        },
    ),

    "montreal": CityConfig(
        name="montreal",
        icao="CYUL",
        timezone="America/Montreal",
        latitude=45.47,
        longitude=-73.74,
        polymarket_slug_pfx="highest-temperature-in-montreal-on",
        wu_history_path="ca/montreal/CYUL",
        pws_station_id="IMONTRE55",
        csv_path="historic/montreal.csv",
        model_dir="cities/montreal/montreal_peak_model",
        unit="celsius",
        temp_range=range(-25, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: -4.0, 2: -2.0, 3: 3.0,  4: 11.0, 5: 19.0, 6: 24.0,
            7: 27.0, 8: 26.0, 9: 21.0, 10: 14.0, 11: 6.0,  12: -1.0
        },
    ),

    "santiago": CityConfig(
        name="santiago",
        icao="SCEL",
        timezone="America/Santiago",
        latitude=-33.39,
        longitude=-70.79,
        polymarket_slug_pfx="highest-temperature-in-santiago-on",
        wu_history_path="cl/santiago/SCEL",
        pws_station_id="ISANTIAGO55",
        csv_path="historic/santiago.csv",
        model_dir="cities/santiago/santiago_peak_model",
        unit="celsius",
        temp_range=range(-5, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 29.0, 2: 29.0, 3: 27.0, 4: 23.0, 5: 19.0, 6: 16.0,
            7: 14.0, 8: 16.0, 9: 19.0, 10: 23.0, 11: 26.0, 12: 28.0
        },
    ),

    "sao_paulo": CityConfig(
        name="sao_paulo",
        icao="SBGR",
        timezone="America/Sao_Paulo",
        latitude=-23.43,
        longitude=-46.47,
        polymarket_slug_pfx="highest-temperature-in-sao-paulo-on",
        wu_history_path="br/sao-paulo/SBGR",
        pws_station_id="ISAOPAU55",
        csv_path="historic/sao_paulo.csv",
        model_dir="cities/sao_paulo/sao_paulo_peak_model",
        unit="celsius",
        temp_range=range(5, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 28.0, 2: 28.0, 3: 27.0, 4: 25.0, 5: 23.0, 6: 21.0,
            7: 21.0, 8: 23.0, 9: 24.0, 10: 25.0, 11: 26.0, 12: 27.0
        },
    ),

    "toronto": CityConfig(
        name="toronto",
        icao="CYYZ",
        timezone="America/Toronto",
        latitude=43.68,
        longitude=-79.63,
        polymarket_slug_pfx="highest-temperature-in-toronto-on",
        wu_history_path="ca/toronto/CYYZ",
        pws_station_id="ITORONT55",
        csv_path="historic/toronto.csv",
        model_dir="cities/toronto/toronto_peak_model",
        unit="celsius",
        temp_range=range(-25, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: -1.0, 2: 1.0,  3: 7.0,  4: 14.0, 5: 20.0, 6: 26.0,
            7: 29.0, 8: 28.0, 9: 23.0, 10: 16.0, 11: 7.0,  12: 1.0
        },
    ),

    "vancouver": CityConfig(
        name="vancouver",
        icao="CYVR",
        timezone="America/Vancouver",
        latitude=49.20,
        longitude=-123.18,
        polymarket_slug_pfx="highest-temperature-in-vancouver-on",
        wu_history_path="ca/vancouver/CYVR",
        pws_station_id="IVANCOU55",
        csv_path="historic/vancouver.csv",
        model_dir="cities/vancouver/vancouver_peak_model",
        unit="celsius",
        temp_range=range(-10, 30),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 7.0,  2: 8.0,  3: 10.0, 4: 13.0, 5: 17.0, 6: 20.0,
            7: 22.0, 8: 22.0, 9: 19.0, 10: 14.0, 11: 9.0,  12: 6.0
        },
    ),

}


def apply_strategy_configs() -> None:
    """
    Aplica threshold/hour_min dos strategy_config_{city}.json em memória.

    O ficheiro cities/config.py mantém defaults e documentação. Em runtime,
    os JSONs calibrados são a fonte mais recente para a estratégia.
    """
    for city in CITIES.values():
        cfg_path = city.strategy_config_path
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception:
            continue

        single = cfg.get("single", {})
        threshold = single.get("threshold")
        hour_min = single.get("hour_min")
        if threshold is not None:
            city.threshold = float(threshold)
        if hour_min is not None:
            city.hour_min = int(hour_min)


apply_strategy_configs()


def get_city(name: str) -> CityConfig:
    """Retorna a configuração da cidade pelo nome."""
    if name not in CITIES:
        raise ValueError(f"Cidade desconhecida: {name}. Disponíveis: {list(CITIES.keys())}")
    return CITIES[name]


def get_all_cities() -> list[CityConfig]:
    """Retorna lista de todas as cidades configuradas."""
    return list(CITIES.values())
