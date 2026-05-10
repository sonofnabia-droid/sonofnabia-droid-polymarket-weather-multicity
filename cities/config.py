"""
cities/config.py
================
Configuração de cidades para sistema multi-cidade.

Contém CityConfig dataclass, StrategyConfig, ForecastConfidenceConfig
e CITIES dict com configuração de Munich, Dallas e Ankara.
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class ForecastConfidenceConfig:
    """Configuração do Forecast Confidence por cidade."""
    enabled: bool = False
    accuracy_by_month: dict[int, float] = field(default_factory=dict)
    margin: float = 0.05

    def __post_init__(self):
        if not self.accuracy_by_month and self.enabled:
            # Valores padrão baseados em POLY-IRIS
            self.accuracy_by_month = {
                1: 0.72, 2: 0.75, 3: 0.78, 4: 0.82, 5: 0.85, 6: 0.83,
                7: 0.80, 8: 0.80, 9: 0.82, 10: 0.78, 11: 0.74, 12: 0.71,
            }


@dataclass
class DualStrategyConfig:
    """Configuração do Dual Strategy por cidade."""
    enabled: bool = False
    parcel_size: float = 5.0
    fc_hour_min: int = 10
    fc_hour_max: int = 14
    fc_p_min: float = 0.75
    fc_ev_margin: float = 0.05
    pk_threshold: float = 0.650
    pk_hour_min: int = 11
    stop_loss_delta: float = 1.0


@dataclass
class SingleEntryConfig:
    """Configuração do Single Entry por cidade."""
    enabled: bool = True
    parcel_size: float = 5.0
    threshold: float = 0.650
    hour_min: int = 11
    stop_loss_delta: float = 1.0


@dataclass
class StrategyConfig:
    """Configuração de estratégias por cidade."""
    mode: str = "single"  # "single", "dual"
    single: SingleEntryConfig = field(default_factory=SingleEntryConfig)
    dual: DualStrategyConfig = field(default_factory=DualStrategyConfig)
    forecast_confidence: ForecastConfidenceConfig = field(default_factory=ForecastConfidenceConfig)


@dataclass
class CityConfig:
    """Configuração completa de uma cidade."""
    name: str
    icao: str                          # Código ICAO do aeroporto
    timezone: str                      # Timezone (ex: Europe/Berlin)
    latitude: float                    # Latitude Open-Meteo
    longitude: float                   # Longitude Open-Meteo
    polymarket_slug_pfx: str           # Prefixo do slug Polymarket
    wu_history_path: Optional[str]     # Caminho WU (se aplicável)
    csv_path: str                      # Caminho do CSV histórico
    model_dir: str                     # Diretório do modelo treinado
    unit: str                          # Unidade de temperatura (celsius)
    temp_range: range                  # Range válido de temperaturas
    max_daily_loss: float              # Máxima perda diária ($)
    max_per_trade: float               # Máximo por trade ($)
    extra_features: list[str]          # Features específicas da cidade
    threshold: Optional[float]         # Threshold de decisão (calibrado)
    hour_min: Optional[int]            # Hora mínima para entrada (calibrado)
    day_start: int = 6                 # Hora início do dia
    day_end: int = 21                  # Hora fim do dia
    bot_timezone: str = "Europe/Lisbon"  # Timezone do bot (onde corre)
    climatology: dict[int, float] | None = None  # Climatologia mensal (media max mensal)


# Configurações por cidade
CITIES = {
    "munich": CityConfig(
        name="munich",
        icao="EDDM",
        timezone="Europe/Berlin",
        latitude=48.14,
        longitude=11.58,
        polymarket_slug_pfx="highest-temperature-in-munich-on",
        wu_history_path="de/munich/EDDM",
        csv_path="historic/munich.csv",
        model_dir="munich_peak_model",
        unit="celsius",
        temp_range=range(-17, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.55,
        hour_min=15,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 3.0, 2: 5.0, 3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
            7: 25.0, 8: 25.0, 9: 20.0, 10: 14.0, 11: 7.0, 12: 4.0
        },
    ),
    "dallas": CityConfig(
        name="dallas",
        icao="KDFW",
        timezone="America/Chicago",
        latitude=32.90,
        longitude=-97.04,
        polymarket_slug_pfx="highest-temperature-in-dallas-on",
        wu_history_path=None,  # Não tem WU, usar Open-Meteo
        csv_path="historic/dallas.csv",
        model_dir="dallas_peak_model",
        unit="celsius",
        temp_range=range(-15, 46),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # Calibrado: 232 trades/ano, win=96.2%, ROI=+79.5%
        hour_min=17,      # Calibrado
        bot_timezone="America/Chicago",
        climatology={
            1: 13.0, 2: 16.0, 3: 21.0, 4: 26.0, 5: 30.0, 6: 34.0,
            7: 36.0, 8: 36.0, 9: 32.0, 10: 26.0, 11: 19.0, 12: 14.0
        },
    ),
    "ankara": CityConfig(
        name="ankara",
        icao="LTAC",
        timezone="Europe/Istanbul",
        latitude=40.125,
        longitude=32.993,
        polymarket_slug_pfx="highest-temperature-in-ankara-on",
        wu_history_path=None,  # Não tem WU, usar Open-Meteo
        csv_path="historic/ankara.csv",
        model_dir="ankara_peak_model",
        unit="celsius",
        temp_range=range(-25, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # Calibrado: 281 trades/ano, win=89.9%, ROI=+106.8%
        hour_min=15,      # Calibrado
        bot_timezone="Europe/Istanbul",
        climatology={
            1: 4.0, 2: 6.0, 3: 11.0, 4: 16.0, 5: 21.0, 6: 25.0,
            7: 29.0, 8: 29.0, 9: 24.0, 10: 18.0, 11: 11.0, 12: 6.0
        },
    ),

    # ─────────────────────────────────────────────────────────────
    #  CIDADES TROPICAIS / EQUATORIAIS
    #  Aviso: variação diária pequena (5-8°C) → peak detection desafiante
    # ─────────────────────────────────────────────────────────────

    "singapore": CityConfig(
        name="singapore",
        icao="WSSS",
        timezone="Asia/Singapore",
        latitude=1.3502,
        longitude=103.9940,
        polymarket_slug_pfx="highest-temperature-in-singapore-on",
        wu_history_path="sg/singapore/WSSS",  # Polymarket usa WU
        csv_path="historic/singapore.csv",
        model_dir="singapore_peak_model",
        unit="celsius",
        temp_range=range(20, 37),  # Equatorial — variação muito pequena
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,    # A calibrar
        hour_min=None,     # A calibrar
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 31.0, 2: 32.0, 3: 32.0, 4: 32.0, 5: 32.0, 6: 32.0,
            7: 31.0, 8: 31.0, 9: 31.0, 10: 31.0, 11: 31.0, 12: 30.0
        },
    ),

    "jakarta": CityConfig(
        name="jakarta",
        icao="WIII",
        timezone="Asia/Jakarta",
        latitude=-6.1256,
        longitude=106.6560,
        polymarket_slug_pfx="highest-temperature-in-jakarta-on",
        wu_history_path=None,  # A confirmar fonte Polymarket
        csv_path="historic/jakarta.csv",
        model_dir="jakarta_peak_model",
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

    "kuala_lumpur": CityConfig(
        name="kuala_lumpur",
        icao="WMKK",
        timezone="Asia/Kuala_Lumpur",
        latitude=2.7456,
        longitude=101.7100,
        polymarket_slug_pfx="highest-temperature-in-kuala-lumpur-on",
        wu_history_path=None,
        csv_path="historic/kuala_lumpur.csv",
        model_dir="kuala_lumpur_peak_model",
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

    "lagos": CityConfig(
        name="lagos",
        icao="DNMM",
        timezone="Africa/Lagos",
        latitude=6.5774,
        longitude=3.3212,
        polymarket_slug_pfx="highest-temperature-in-lagos-on",
        wu_history_path=None,
        csv_path="historic/lagos.csv",
        model_dir="lagos_peak_model",
        unit="celsius",
        temp_range=range(18, 38),  # Tropical húmido — Mar/Abr são os mais quentes
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

    # ─────────────────────────────────────────────────────────────
    #  CIDADES SUBTROPICAIS / TEMPERADAS
    #  Variação anual e diária maiores → melhor sinal para o modelo
    # ─────────────────────────────────────────────────────────────

    "taipei": CityConfig(
        name="taipei",
        icao="RCSS",
        timezone="Asia/Taipei",
        latitude=25.0694,
        longitude=121.5517,
        polymarket_slug_pfx="highest-temperature-in-taipei-on",
        wu_history_path="tw/taipei/RCSS",  # Polymarket usa WU/RCSS (Songshan)
        csv_path="historic/taipei.csv",
        model_dir="taipei_peak_model",
        unit="celsius",
        temp_range=range(5, 40),  # Subtropical — bom range
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

    "miami": CityConfig(
        name="miami",
        icao="KMIA",
        timezone="America/New_York",
        latitude=25.7954,
        longitude=-80.2901,
        polymarket_slug_pfx="highest-temperature-in-miami-on",
        wu_history_path=None,  # A confirmar (provavelmente NOAA/KMIA)
        csv_path="historic/miami.csv",
        model_dir="miami_peak_model",
        unit="celsius",
        temp_range=range(5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 25.0, 2: 26.0, 3: 28.0, 4: 29.0, 5: 31.0, 6: 32.0,
            7: 33.0, 8: 33.0, 9: 32.0, 10: 30.0, 11: 28.0, 12: 26.0
        },
    ),

    "karachi": CityConfig(
        name="karachi",
        icao="OPKC",
        timezone="Asia/Karachi",
        latitude=24.9008,
        longitude=67.1681,
        polymarket_slug_pfx="highest-temperature-in-karachi-on",
        wu_history_path=None,
        csv_path="historic/karachi.csv",
        model_dir="karachi_peak_model",
        unit="celsius",
        temp_range=range(5, 48),  # Subtropical árido — pode chegar aos 45°C+
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

    # ─────────────────────────────────────────────────────────────
    #  CIDADES CONTINENTAIS / FRIAS
    #  Forte variação anual → bom sinal para o modelo
    # ─────────────────────────────────────────────────────────────

    "moscow": CityConfig(
        name="moscow",
        icao="UUEE",
        timezone="Europe/Moscow",
        latitude=55.9736,
        longitude=37.4125,
        polymarket_slug_pfx="highest-temperature-in-moscow-on",
        wu_history_path=None,
        csv_path="historic/moscow.csv",
        model_dir="moscow_peak_model",
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
            7: 26.0, 8: 24.0, 9: 17.0, 10: 9.0,  11: 1.0, 12: -3.0
        },
    ),

    "warsaw": CityConfig(
        name="warsaw",
        icao="EPWA",
        timezone="Europe/Warsaw",
        latitude=52.1657,
        longitude=20.9671,
        polymarket_slug_pfx="highest-temperature-in-warsaw-on",
        wu_history_path=None,
        csv_path="historic/warsaw.csv",
        model_dir="warsaw_peak_model",
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
            7: 25.0, 8: 24.0, 9: 18.0, 10: 12.0, 11: 5.0, 12: 2.0
        },
    ),

    "beijing": CityConfig(
        name="beijing",
        icao="ZBAA",
        timezone="Asia/Shanghai",
        latitude=40.0799,
        longitude=116.6031,
        polymarket_slug_pfx="highest-temperature-in-beijing-on",
        wu_history_path=None,
        csv_path="historic/beijing.csv",
        model_dir="beijing_peak_model",
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
            7: 31.0, 8: 29.0, 9: 23.0, 10: 16.0, 11: 7.0, 12: 2.0
        },
    ),

    "chicago": CityConfig(
        name="chicago",
        icao="KORD",
        timezone="America/Chicago",
        latitude=41.9742,
        longitude=-87.9073,
        polymarket_slug_pfx="highest-temperature-in-chicago-on",
        wu_history_path=None,
        csv_path="historic/chicago.csv",
        model_dir="chicago_peak_model",
        unit="celsius",
        temp_range=range(-25, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: -1.0, 2: 1.0,  3: 7.0,  4: 14.0, 5: 20.0, 6: 26.0,
            7: 29.0, 8: 28.0, 9: 23.0, 10: 16.0, 11: 7.0, 12: 1.0
        },
    ),

    # ─────────────────────────────────────────────────────────────
    #  CIDADES MEDITERRÂNEAS / SEMIÁRIDAS TEMPERADAS
    # ─────────────────────────────────────────────────────────────

    "madrid": CityConfig(
        name="madrid",
        icao="LEMD",
        timezone="Europe/Madrid",
        latitude=40.4719,
        longitude=-3.5626,
        polymarket_slug_pfx="highest-temperature-in-madrid-on",
        wu_history_path=None,
        csv_path="historic/madrid.csv",
        model_dir="madrid_peak_model",
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

    "tel_aviv": CityConfig(
        name="tel_aviv",
        icao="LLBG",
        timezone="Asia/Jerusalem",
        latitude=32.0115,
        longitude=34.8867,
        polymarket_slug_pfx="highest-temperature-in-tel-aviv-on",
        wu_history_path=None,
        csv_path="historic/tel_aviv.csv",
        model_dir="tel_aviv_peak_model",
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
    #  CIDADES ÁRIDAS / DESÉRTICAS
    #  Picos de calor extremos no verão → alta variância no range
    # ─────────────────────────────────────────────────────────────

    "phoenix": CityConfig(
        name="phoenix",
        icao="KPHX",
        timezone="America/Phoenix",  # UTC-7 fixo, sem DST
        latitude=33.4373,
        longitude=-112.0078,
        polymarket_slug_pfx="highest-temperature-in-phoenix-on",
        wu_history_path=None,
        csv_path="historic/phoenix.csv",
        model_dir="phoenix_peak_model",
        unit="celsius",
        temp_range=range(-2, 48),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 19.0, 2: 22.0, 3: 26.0, 4: 31.0, 5: 36.0, 6: 41.0,
            7: 40.0, 8: 38.0, 9: 36.0, 10: 30.0, 11: 23.0, 12: 19.0
        },
    ),

    "las_vegas": CityConfig(
        name="las_vegas",
        icao="KLAS",
        timezone="America/Los_Angeles",
        latitude=36.0840,
        longitude=-115.1537,
        polymarket_slug_pfx="highest-temperature-in-las-vegas-on",
        wu_history_path=None,
        csv_path="historic/las_vegas.csv",
        model_dir="las_vegas_peak_model",
        unit="celsius",
        temp_range=range(-5, 47),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=None,
        hour_min=None,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 13.0, 2: 17.0, 3: 22.0, 4: 27.0, 5: 33.0, 6: 39.0,
            7: 41.0, 8: 39.0, 9: 34.0, 10: 27.0, 11: 18.0, 12: 13.0
        },
    ),

    # ─────────────────────────────────────────────────────────────
    #  HEMISFÉRIO SUL
    #  Sazonalidade invertida — pico no verão austral (Dez–Fev)
    # ─────────────────────────────────────────────────────────────

    "buenos_aires": CityConfig(
        name="buenos_aires",
        icao="SAEZ",
        timezone="America/Argentina/Buenos_Aires",  # UTC-3, sem DST
        latitude=-34.5597,
        longitude=-58.4116,
        polymarket_slug_pfx="highest-temperature-in-buenos-aires-on",
        wu_history_path=None,
        csv_path="historic/buenos_aires.csv",
        model_dir="buenos_aires_peak_model",
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
}


def get_city(name: str) -> CityConfig:
    """Retorna a configuração da cidade pelo nome."""
    if name not in CITIES:
        raise ValueError(f"Cidade desconhecida: {name}. Disponíveis: {list(CITIES.keys())}")
    return CITIES[name]


def get_all_cities() -> list[CityConfig]:
    """Retorna lista de todas as cidades configuradas."""
    return list(CITIES.values())