"""
cities/config.py
================
Configuração de cidades para sistema multi-cidade.

Contém CityConfig dataclass e CITIES dict com configuração
de Munich, Dallas e Ankara.
"""

from dataclasses import dataclass
from typing import Optional
from pathlib import Path


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
        threshold=0.350,  # Balanceado (novo CSV): 232 trades/ano, win=96.2%, ROI=+79.5%
        hour_min=17,      # Balanceado
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
        threshold=0.350,  # Balanceado (novo CSV): 281 trades/ano, win=89.9%, ROI=+106.8%
        hour_min=15,      # Balanceado
        bot_timezone="Europe/Istanbul",
        climatology={
            1: 4.0, 2: 6.0, 3: 11.0, 4: 16.0, 5: 21.0, 6: 25.0,
            7: 29.0, 8: 29.0, 9: 24.0, 10: 18.0, 11: 11.0, 12: 6.0
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
