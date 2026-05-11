"""
cities/config.py
================
Configuração de cidades para sistema multi-cidade.

Contém CityConfig dataclass e CITIES dict com configuração das cidades.

Última calibração: 2026-05-11 (mode=full, 7 anos de dados)
threshold e hour_min reflectem os valores dos strategy_config_{city}.json.
Em runtime o live_bot lê os JSONs directamente via city.strategy_config_path.
Os valores aqui servem como documentação e fallback de emergência.
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
#  Valores de threshold e hour_min: calibração 2026-05-11, mode=full, 7 anos.
#  Score/win/trades referem-se ao período de selection do calibrate_all.
# ══════════════════════════════════════════════════════════════════════════════

CITIES = {

    # ─────────────────────────────────────────────────────────────
    #  CIDADES ORIGINAIS
    # ─────────────────────────────────────────────────────────────

    "munich": CityConfig(
        name="munich",
        icao="EDDM",
        timezone="Europe/Berlin",
        latitude=48.14,
        longitude=11.58,
        polymarket_slug_pfx="highest-temperature-in-munich-on",
        wu_history_path="de/munich/EDDM",
        csv_path="historic/munich.csv",
        model_dir="cities/munich/munich_peak_model",
        unit="celsius",
        temp_range=range(-17, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=97.68% score=204.2 trades/y=122 val_win=100.0%
        hour_min=8,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 3.0,  2: 5.0,  3: 10.0, 4: 15.0, 5: 20.0, 6: 23.0,
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
        wu_history_path=None,
        csv_path="historic/dallas.csv",
        model_dir="cities/dallas/dallas_peak_model",
        unit="celsius",
        temp_range=range(-15, 46),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=96.23% score=227.9 trades/y=232
        hour_min=10,
        bot_timezone="Europe/Lisbon",
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
        wu_history_path=None,
        csv_path="historic/ankara.csv",
        model_dir="cities/ankara/ankara_peak_model",
        unit="celsius",
        temp_range=range(-25, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.425,  # win=94.83% score=224.5 trades/y=232
        hour_min=10,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 4.0,  2: 6.0,  3: 11.0, 4: 16.0, 5: 21.0, 6: 25.0,
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
        wu_history_path="sg/singapore/WSSS",
        csv_path="historic/singapore.csv",
        model_dir="cities/singapore/singapore_peak_model",
        unit="celsius",
        temp_range=range(20, 37),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=96.35% score=222.2 trades/y=201
        hour_min=14,
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
        wu_history_path=None,
        csv_path="historic/jakarta.csv",
        model_dir="cities/jakarta/jakarta_peak_model",
        unit="celsius",
        temp_range=range(20, 37),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.400,  # win=95.20% score=215.1 trades/y=181
        hour_min=12,
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
        model_dir="cities/kuala_lumpur/kuala_lumpur_peak_model",
        unit="celsius",
        temp_range=range(20, 37),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=97.85% score=214.6 trades/y=155 val_win=96.83%
        hour_min=8,
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
        model_dir="cities/lagos/lagos_peak_model",
        unit="celsius",
        temp_range=range(18, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.375,  # win=96.25% score=227.8 trades/y=232
        hour_min=14,
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
        wu_history_path="tw/taipei/RCSS",
        csv_path="historic/taipei.csv",
        model_dir="cities/taipei/taipei_peak_model",
        unit="celsius",
        temp_range=range(5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=87.59% score=175.6 trades/y=100 ⚠ win baixo
        hour_min=12,
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
        wu_history_path=None,
        csv_path="historic/miami.csv",
        model_dir="cities/miami/miami_peak_model",
        unit="celsius",
        temp_range=range(5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.525,  # win=97.07% score=227.5 trades/y=220
        hour_min=14,
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
        model_dir="cities/karachi/karachi_peak_model",
        unit="celsius",
        temp_range=range(5, 48),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.400,  # win=97.06% score=232.9 trades/y=250
        hour_min=14,
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
        model_dir="cities/moscow/moscow_peak_model",
        unit="celsius",
        temp_range=range(-30, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=80.59% score=177.0 trades/y=156 ⚠ não lançar
        hour_min=14,
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
        model_dir="cities/warsaw/warsaw_peak_model",
        unit="celsius",
        temp_range=range(-20, 36),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.375,  # win=82.57% score=188.4 trades/y=190 ⚠ não lançar
        hour_min=14,
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
        model_dir="cities/beijing/beijing_peak_model",
        unit="celsius",
        temp_range=range(-20, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=98.64% score=231.2 trades/y=220 val_win=98.67%
        hour_min=15,
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
        model_dir="cities/chicago/chicago_peak_model",
        unit="celsius",
        temp_range=range(-25, 38),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=94.31% score=210.6 trades/y=170 val_win=86.54% ⚠ overfitting
        hour_min=8,
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
        model_dir="cities/madrid/madrid_peak_model",
        unit="celsius",
        temp_range=range(-10, 42),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=97.69% score=224.0 trades/y=195 val_win=94.12%
        hour_min=8,
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
        model_dir="cities/tel_aviv/tel_aviv_peak_model",
        unit="celsius",
        temp_range=range(10, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=93.98% score=210.4 trades/y=172
        hour_min=14,
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
        model_dir="cities/phoenix/phoenix_peak_model",
        unit="celsius",
        temp_range=range(-2, 48),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=98.55% score=244.1 trades/y=299 val_win=99.07% ⭐ melhor
        hour_min=8,
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
        model_dir="cities/las_vegas/las_vegas_peak_model",
        unit="celsius",
        temp_range=range(-5, 47),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.725,  # win=95.09% score=231.7 trades/y=272
        hour_min=14,
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
        model_dir="cities/buenos_aires/buenos_aires_peak_model",
        unit="celsius",
        temp_range=range(-5, 40),
        max_daily_loss=20.0,
        max_per_trade=5.0,
        extra_features=[],
        threshold=0.350,  # win=98.04% score=236.1 trades/y=255 val_win=96.55%
        hour_min=8,
        bot_timezone="Europe/Lisbon",
        climatology={
            1: 30.0, 2: 29.0, 3: 26.0, 4: 22.0, 5: 18.0, 6: 15.0,
            7: 14.0, 8: 16.0, 9: 19.0, 10: 23.0, 11: 27.0, 12: 29.0
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
