"""
cities/config.py
================
Configuração de cidades para sistema multi-cidade.

Contém CityConfig dataclass e CITIES dict com configuração das cidades.
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
    pws_station_id: str = ""                # PWS station ID (WU v2)
    market_unit: str = "celsius"         # Unidade no Polymarket (celsius/fahrenheit)
    day_start: int = 6                   # Hora início do dia (hora local)
    day_end: int = 21                    # Hora fim do dia (hora local)
    bot_timezone: str = "Europe/Lisbon"  # Timezone do bot
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
#  CITIES — 34 cidades
#  Valores activos de threshold e hour_min vêm dos strategy_config_{city}.json.
# ══════════════════════════════════════════════════════════════════════════════

CITIES = {

    # ── EUROPA ─────────────────────────────────────────────────

    "amsterdam": CityConfig(
        name="amsterdam",
        icao="EHAM",
        timezone="Europe/Amsterdam",
        latitude=52.31,
        longitude=4.77,
        polymarket_slug_pfx="highest-temperature-in-amsterdam-on",
        wu_history_path="nl/schiphol/EHAM",
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
        climatology={1: 6.0, 2: 7.0, 3: 10.0, 4: 14.0, 5: 18.0, 6: 21.0,
                     7: 23.0, 8: 23.0, 9: 19.0, 10: 15.0, 11: 10.0, 12: 7.0},
    ),

    "helsinki": CityConfig(
        name="helsinki",
        icao="EFHK",
        timezone="Europe/Helsinki",
        latitude=60.32,
        longitude=24.97,
        polymarket_slug_pfx="highest-temperature-in-helsinki-on",
        wu_history_path="fi/vantaa/EFHK",
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
        climatology={1: -2.0, 2: -2.0, 3: 2.0, 4: 8.0, 5: 15.0, 6: 20.0,
                     7: 22.0, 8: 20.0, 9: 15.0, 10: 8.0, 11: 2.0, 12: -1.0},
    ),

    "istanbul": CityConfig(
        name="istanbul",
        icao="LTFM",
        timezone="Europe/Istanbul",
        latitude=41.28,
        longitude=28.73,
        polymarket_slug_pfx="highest-temperature-in-istanbul-on",
        wu_history_path="tr/istanbul/LTFM",
        pws_station_id="IISTANBUL",
        csv_path="historic/istanbul.csv",
        model_dir="cities/istanbul/istanbul_peak_model",
        unit="celsius",
        temp_range=range(-5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 8.0, 2: 9.0, 3: 12.0, 4: 17.0, 5: 22.0, 6: 27.0,
                     7: 29.0, 8: 29.0, 9: 25.0, 10: 20.0, 11: 14.0, 12: 10.0},
    ),

    "london": CityConfig(
        name="london",
        icao="EGLC",
        timezone="Europe/London",
        latitude=51.51,
        longitude=0.05,
        polymarket_slug_pfx="highest-temperature-in-london-on",
        wu_history_path="gb/london/EGLC",
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
        climatology={1: 8.0, 2: 9.0, 3: 12.0, 4: 15.0, 5: 18.0, 6: 21.0,
                     7: 23.0, 8: 23.0, 9: 20.0, 10: 16.0, 11: 12.0, 12: 9.0},
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
        climatology={1: 10.0, 2: 12.0, 3: 16.0, 4: 18.0, 5: 23.0, 6: 28.0,
                     7: 33.0, 8: 32.0, 9: 27.0, 10: 20.0, 11: 14.0, 12: 10.0},
    ),

    "milan": CityConfig(
        name="milan",
        icao="LIMC",
        timezone="Europe/Rome",
        latitude=45.46,
        longitude=9.28,
        polymarket_slug_pfx="highest-temperature-in-milan-on",
        wu_history_path="it/milan/LIMC",
        pws_station_id="IMILAN55",
        csv_path="historic/milan.csv",
        model_dir="cities/milan/milan_peak_model",
        unit="celsius",
        temp_range=range(-10, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 6.0, 2: 9.0, 3: 14.0, 4: 18.0, 5: 23.0, 6: 27.0,
                     7: 30.0, 8: 29.0, 9: 24.0, 10: 18.0, 11: 11.0, 12: 7.0},
    ),

    "moscow": CityConfig(
        name="moscow",
        icao="UUWW",
        timezone="Europe/Moscow",
        latitude=55.59,
        longitude=37.27,
        polymarket_slug_pfx="highest-temperature-in-moscow-on",
        wu_history_path="ru/moscow/UUWW",
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
        climatology={1: -4.0, 2: -3.0, 3: 4.0, 4: 12.0, 5: 20.0, 6: 23.0,
                     7: 26.0, 8: 24.0, 9: 17.0, 10: 9.0, 11: 1.0, 12: -3.0},
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
        climatology={1: 3.0, 2: 5.0, 3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
                     7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 7.0, 12: 4.0},
    ),

    "paris": CityConfig(
        name="paris",
        icao="LFPB",
        timezone="Europe/Paris",
        latitude=48.97,
        longitude=2.44,
        polymarket_slug_pfx="highest-temperature-in-paris-on",
        wu_history_path="fr/bonneuil-en-france/LFPB",
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
        climatology={1: 7.0, 2: 9.0, 3: 13.0, 4: 16.0, 5: 20.0, 6: 24.0,
                     7: 26.0, 8: 25.0, 9: 21.0, 10: 16.0, 11: 11.0, 12: 8.0},
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
        climatology={1: 1.0, 2: 3.0, 3: 8.0, 4: 14.0, 5: 20.0, 6: 23.0,
                     7: 25.0, 8: 24.0, 9: 18.0, 10: 12.0, 11: 5.0, 12: 2.0},
    ),

    # ── ÁSIA — LESTE / SUL / SUDESTE ──────────────────────────

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
        climatology={1: 1.0, 2: 5.0, 3: 12.0, 4: 20.0, 5: 26.0, 6: 31.0,
                     7: 31.0, 8: 29.0, 9: 23.0, 10: 16.0, 11: 7.0, 12: 2.0},
    ),

    "busan": CityConfig(
        name="busan",
        icao="RKPK",
        timezone="Asia/Seoul",
        latitude=35.18,
        longitude=128.94,
        polymarket_slug_pfx="highest-temperature-in-busan-on",
        wu_history_path="kr/busan/RKPK",
        pws_station_id="IBUSAN55",
        csv_path="historic/busan.csv",
        model_dir="cities/busan/busan_peak_model",
        unit="celsius",
        temp_range=range(-10, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 6.0, 2: 8.0, 3: 12.0, 4: 17.0, 5: 21.0, 6: 24.0,
                     7: 27.0, 8: 29.0, 9: 25.0, 10: 20.0, 11: 14.0, 12: 8.0},
    ),

    "chengdu": CityConfig(
        name="chengdu",
        icao="ZUUU",
        timezone="Asia/Shanghai",
        latitude=30.58,
        longitude=103.95,
        polymarket_slug_pfx="highest-temperature-in-chengdu-on",
        wu_history_path="cn/chengdu/ZUUU",
        pws_station_id="ICHENGDU55",
        csv_path="historic/chengdu.csv",
        model_dir="cities/chengdu/chengdu_peak_model",
        unit="celsius",
        temp_range=range(-5, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 9.0, 2: 12.0, 3: 17.0, 4: 22.0, 5: 26.0, 6: 28.0,
                     7: 30.0, 8: 30.0, 9: 26.0, 10: 21.0, 11: 16.0, 12: 10.0},
    ),

    "chongqing": CityConfig(
        name="chongqing",
        icao="ZUCK",
        timezone="Asia/Shanghai",
        latitude=29.72,
        longitude=106.64,
        polymarket_slug_pfx="highest-temperature-in-chongqing-on",
        wu_history_path="cn/chongqing/ZUCK",
        pws_station_id="ICHONGQ55",
        csv_path="historic/chongqing.csv",
        model_dir="cities/chongqing/chongqing_peak_model",
        unit="celsius",
        temp_range=range(0, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 10.0, 2: 13.0, 3: 18.0, 4: 23.0, 5: 27.0, 6: 30.0,
                     7: 33.0, 8: 34.0, 9: 29.0, 10: 23.0, 11: 17.0, 12: 11.0},
    ),

    "guangzhou": CityConfig(
        name="guangzhou",
        icao="ZGGG",
        timezone="Asia/Shanghai",
        latitude=23.39,
        longitude=113.30,
        polymarket_slug_pfx="highest-temperature-in-guangzhou-on",
        wu_history_path="cn/guangzhou/ZGGG",
        pws_station_id="IGUANGZ55",
        csv_path="historic/guangzhou.csv",
        model_dir="cities/guangzhou/guangzhou_peak_model",
        unit="celsius",
        temp_range=range(5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 18.0, 2: 19.0, 3: 22.0, 4: 26.0, 5: 30.0, 6: 32.0,
                     7: 33.0, 8: 33.0, 9: 32.0, 10: 29.0, 11: 24.0, 12: 20.0},
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
        climatology={1: 25.0, 2: 27.0, 3: 32.0, 4: 35.0, 5: 36.0, 6: 35.0,
                     7: 33.0, 8: 32.0, 9: 33.0, 10: 35.0, 11: 32.0, 12: 27.0},
    ),

    "kuala_lumpur": CityConfig(
        name="kuala_lumpur",
        icao="WMKK",
        timezone="Asia/Kuala_Lumpur",
        latitude=2.75,
        longitude=101.71,
        polymarket_slug_pfx="highest-temperature-in-kuala-lumpur-on",
        wu_history_path="my/sepang-district/WMKK",
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
        climatology={1: 32.0, 2: 33.0, 3: 33.0, 4: 33.0, 5: 33.0, 6: 33.0,
                     7: 32.0, 8: 32.0, 9: 32.0, 10: 32.0, 11: 32.0, 12: 32.0},
    ),

    "lucknow": CityConfig(
        name="lucknow",
        icao="VILK",
        timezone="Asia/Kolkata",
        latitude=26.76,
        longitude=80.89,
        polymarket_slug_pfx="highest-temperature-in-lucknow-on",
        wu_history_path="in/lucknow/VILK",
        pws_station_id="ILUCKNO55",
        csv_path="historic/lucknow.csv",
        model_dir="cities/lucknow/lucknow_peak_model",
        unit="celsius",
        temp_range=range(5, 45),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 20.0, 2: 24.0, 3: 30.0, 4: 37.0, 5: 40.0, 6: 38.0,
                     7: 33.0, 8: 32.0, 9: 33.0, 10: 32.0, 11: 27.0, 12: 22.0},
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
        climatology={1: 30.0, 2: 31.0, 3: 32.0, 4: 34.0, 5: 34.0, 6: 33.0,
                     7: 32.0, 8: 32.0, 9: 32.0, 10: 32.0, 11: 31.0, 12: 30.0},
    ),

    "qingdao": CityConfig(
        name="qingdao",
        icao="ZSQD",
        timezone="Asia/Shanghai",
        latitude=36.27,
        longitude=120.38,
        polymarket_slug_pfx="highest-temperature-in-qingdao-on",
        wu_history_path="cn/qingdao/ZSQD",
        pws_station_id="IQINGDA55",
        csv_path="historic/qingdao.csv",
        model_dir="cities/qingdao/qingdao_peak_model",
        unit="celsius",
        temp_range=range(-10, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 3.0, 2: 5.0, 3: 10.0, 4: 16.0, 5: 21.0, 6: 25.0,
                     7: 28.0, 8: 29.0, 9: 26.0, 10: 20.0, 11: 12.0, 12: 5.0},
    ),

    "seoul": CityConfig(
        name="seoul",
        icao="RKSI",
        timezone="Asia/Seoul",
        latitude=37.47,
        longitude=126.45,
        polymarket_slug_pfx="highest-temperature-in-seoul-on",
        wu_history_path="kr/incheon/RKSI",
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
        climatology={1: 2.0, 2: 5.0, 3: 10.0, 4: 17.0, 5: 23.0, 6: 27.0,
                     7: 29.0, 8: 30.0, 9: 26.0, 10: 20.0, 11: 12.0, 12: 4.0},
    ),

    "shanghai": CityConfig(
        name="shanghai",
        icao="ZSPD",
        timezone="Asia/Shanghai",
        latitude=31.14,
        longitude=121.81,
        polymarket_slug_pfx="highest-temperature-in-shanghai-on",
        wu_history_path="cn/shanghai/ZSPD",
        pws_station_id="ISHANGH55",
        csv_path="historic/shanghai.csv",
        model_dir="cities/shanghai/shanghai_peak_model",
        unit="celsius",
        temp_range=range(-5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 8.0, 2: 10.0, 3: 14.0, 4: 20.0, 5: 25.0, 6: 28.0,
                     7: 33.0, 8: 32.0, 9: 28.0, 10: 23.0, 11: 17.0, 12: 11.0},
    ),

    "shenzhen": CityConfig(
        name="shenzhen",
        icao="ZGSZ",
        timezone="Asia/Shanghai",
        latitude=22.64,
        longitude=113.81,
        polymarket_slug_pfx="highest-temperature-in-shenzhen-on",
        wu_history_path="cn/shenzhen/ZGSZ",
        pws_station_id="ISHENZH55",
        csv_path="historic/shenzhen.csv",
        model_dir="cities/shenzhen/shenzhen_peak_model",
        unit="celsius",
        temp_range=range(5, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 19.0, 2: 20.0, 3: 23.0, 4: 26.0, 5: 29.0, 6: 31.0,
                     7: 32.0, 8: 32.0, 9: 31.0, 10: 29.0, 11: 25.0, 12: 21.0},
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
        climatology={1: 31.0, 2: 32.0, 3: 32.0, 4: 32.0, 5: 32.0, 6: 32.0,
                     7: 31.0, 8: 31.0, 9: 31.0, 10: 31.0, 11: 31.0, 12: 30.0},
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
        climatology={1: 19.0, 2: 20.0, 3: 23.0, 4: 26.0, 5: 30.0, 6: 32.0,
                     7: 34.0, 8: 33.0, 9: 31.0, 10: 28.0, 11: 25.0, 12: 21.0},
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
        climatology={1: 17.0, 2: 18.0, 3: 20.0, 4: 24.0, 5: 27.0, 6: 30.0,
                     7: 31.0, 8: 32.0, 9: 30.0, 10: 27.0, 11: 22.0, 12: 18.0},
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
        climatology={1: 10.0, 2: 11.0, 3: 14.0, 4: 19.0, 5: 23.0, 6: 26.0,
                     7: 30.0, 8: 31.0, 9: 27.0, 10: 22.0, 11: 17.0, 12: 12.0},
    ),

    "wuhan": CityConfig(
        name="wuhan",
        icao="ZHHH",
        timezone="Asia/Shanghai",
        latitude=30.78,
        longitude=114.21,
        polymarket_slug_pfx="highest-temperature-in-wuhan-on",
        wu_history_path="cn/wuhan/ZHHH",
        pws_station_id="IWUHAN55",
        csv_path="historic/wuhan.csv",
        model_dir="cities/wuhan/wuhan_peak_model",
        unit="celsius",
        temp_range=range(-5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 8.0, 2: 11.0, 3: 16.0, 4: 22.0, 5: 27.0, 6: 30.0,
                     7: 33.0, 8: 33.0, 9: 29.0, 10: 23.0, 11: 16.0, 12: 10.0},
    ),

    # ── MÉDIO ORIENTE ─────────────────────────────────────────

    "jeddah": CityConfig(
        name="jeddah",
        icao="OEJN",
        timezone="Asia/Riyadh",
        latitude=21.68,
        longitude=39.15,
        polymarket_slug_pfx="highest-temperature-in-jeddah-on",
        wu_history_path="sa/jeddah/OEJN",
        pws_station_id="IJEDDAH55",
        csv_path="historic/jeddah.csv",
        model_dir="cities/jeddah/jeddah_peak_model",
        unit="celsius",
        temp_range=range(20, 50),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 29.0, 2: 29.0, 3: 31.0, 4: 33.0, 5: 35.0, 6: 37.0,
                     7: 38.0, 8: 38.0, 9: 37.0, 10: 35.0, 11: 32.0, 12: 30.0},
    ),

    # ── ÁFRICA ────────────────────────────────────────────────

    "cape_town": CityConfig(
        name="cape_town",
        icao="FACT",
        timezone="Africa/Johannesburg",
        latitude=-33.97,
        longitude=18.60,
        polymarket_slug_pfx="highest-temperature-in-cape-town-on",
        wu_history_path="za/matroosfontein/FACT",
        pws_station_id="ICAPETO55",
        csv_path="historic/cape_town.csv",
        model_dir="cities/cape_town/cape_town_peak_model",
        unit="celsius",
        temp_range=range(5, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 26.0, 2: 27.0, 3: 26.0, 4: 23.0, 5: 20.0, 6: 18.0,
                     7: 17.0, 8: 18.0, 9: 20.0, 10: 22.0, 11: 24.0, 12: 25.0},
    ),

    # ── AMÉRICAS ──────────────────────────────────────────────

    "buenos_aires": CityConfig(
        name="buenos_aires",
        icao="SAEZ",
        timezone="America/Argentina/Buenos_Aires",
        latitude=-34.56,
        longitude=-58.41,
        polymarket_slug_pfx="highest-temperature-in-buenos-aires-on",
        wu_history_path="ar/ezeiza/SAEZ",
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
        climatology={1: 30.0, 2: 29.0, 3: 26.0, 4: 22.0, 5: 18.0, 6: 15.0,
                     7: 14.0, 8: 16.0, 9: 19.0, 10: 23.0, 11: 27.0, 12: 29.0},
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
        climatology={1: 22.0, 2: 24.0, 3: 26.0, 4: 27.0, 5: 27.0, 6: 25.0,
                     7: 24.0, 8: 24.0, 9: 23.0, 10: 23.0, 11: 22.0, 12: 21.0},
    ),

    "panama_city": CityConfig(
        name="panama_city",
        icao="MPMG",
        timezone="America/Panama",
        latitude=9.07,
        longitude=-79.38,
        polymarket_slug_pfx="highest-temperature-in-panama-city-on",
        wu_history_path="pa/panama-city/MPMG",
        pws_station_id="IPANAMA55",
        csv_path="historic/panama_city.csv",
        model_dir="cities/panama_city/panama_city_peak_model",
        unit="celsius",
        temp_range=range(20, 35),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 31.0, 2: 32.0, 3: 32.0, 4: 32.0, 5: 31.0, 6: 30.0,
                     7: 30.0, 8: 30.0, 9: 30.0, 10: 30.0, 11: 30.0, 12: 30.0},
    ),

    "sao_paulo": CityConfig(
        name="sao_paulo",
        icao="SBGR",
        timezone="America/Sao_Paulo",
        latitude=-23.43,
        longitude=-46.47,
        polymarket_slug_pfx="highest-temperature-in-sao-paulo-on",
        wu_history_path="br/guarulhos/SBGR",
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
        climatology={1: 28.0, 2: 28.0, 3: 27.0, 4: 25.0, 5: 23.0, 6: 21.0,
                     7: 21.0, 8: 23.0, 9: 24.0, 10: 25.0, 11: 26.0, 12: 27.0},
    ),

    "toronto": CityConfig(
        name="toronto",
        icao="CYYZ",
        timezone="America/Toronto",
        latitude=43.68,
        longitude=-79.63,
        polymarket_slug_pfx="highest-temperature-in-toronto-on",
        wu_history_path="ca/mississauga/CYYZ",
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
        climatology={1: -1.0, 2: 1.0, 3: 7.0, 4: 14.0, 5: 20.0, 6: 26.0,
                     7: 29.0, 8: 28.0, 9: 23.0, 10: 16.0, 11: 7.0, 12: 1.0},
    ),

    # ── OCEANIA ───────────────────────────────────────────────

    "wellington": CityConfig(
        name="wellington",
        icao="NZWN",
        timezone="Pacific/Auckland",
        latitude=-41.33,
        longitude=174.81,
        polymarket_slug_pfx="highest-temperature-in-wellington-on",
        wu_history_path="nz/wellington/NZWN",
        pws_station_id="IWELLIN55",
        csv_path="historic/wellington.csv",
        model_dir="cities/wellington/wellington_peak_model",
        unit="celsius",
        temp_range=range(5, 30),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        climatology={1: 20.0, 2: 20.0, 3: 19.0, 4: 17.0, 5: 15.0, 6: 13.0,
                     7: 12.0, 8: 13.0, 9: 14.0, 10: 16.0, 11: 17.0, 12: 19.0},
    ),

}


def apply_strategy_configs() -> None:
    """
    Aplica threshold/hour_min dos strategy_config_{city}.json em memória.
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
