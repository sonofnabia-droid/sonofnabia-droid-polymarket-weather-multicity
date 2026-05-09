"""
modules/forecast_confidence.py
===============================
Heurística genérica para estimar P(forecast correcto) por cidade.

Calcula a probabilidade de o forecast diário acertar o max real
do dia (arredondado ao inteiro, como o Polymarket resolve).

Mecânica de "correcto":
  Se forecast=20°C e actual=19.5°C → round(19.5)=20 → correcto
  Se forecast=20°C e actual=19.4°C → round(19.4)=19 → errado
  Janela efectiva: ±0.5°C à volta do forecast

Versão: 1.0 — 2026-04-29
Genérico para multi-cidade
"""

import sys
from pathlib import Path

# Adicionar diretório raiz ao sys.path para imports funcionarem
sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import Optional
from cities.config import CityConfig


# Valores padrão de accuracy por mês (baseados em POLY-IRIS)
_DEFAULT_FORECAST_ACCURACY_BY_MONTH: dict[int, float] = {
    1: 0.72, 2: 0.75, 3: 0.78, 4: 0.82, 5: 0.85, 6: 0.83,
    7: 0.80, 8: 0.80, 9: 0.82, 10: 0.78, 11: 0.74, 12: 0.71,
}


def p_forecast_correct(
    month: int,
    cloud_cover: float,
    humidity: float,
    om_agrees: bool | None,
    temp_gap: float,
    uv_index: float | None = None,
    accuracy_by_month: dict[int, float] | None = None,
) -> float:
    """
    Estima P(o forecast vai acertar o max do dia, ±0.5°C).

    Parâmetros
    ----------
    month : int
        Mês actual (1-12).
    cloud_cover : float
        Cobertura de nuvens (0-100). 0=ceu limpo, 100=nublado.
    humidity : float
        Humidade relativa (%).
    om_agrees : bool | None
        True se |WU_max - OM_max| <= 1°C.
        None se não há forecast OM disponível.
    temp_gap : float
        Diferença forecast_max - current_temp (°C).
    uv_index : float | None
        Índice UV actual. None se não disponível.
    accuracy_by_month : dict[int, float] | None
        Tabela de accuracy por mês. Se None, usa defaults.

    Retorna
    -------
    float
        Probabilidade estimada (0.0 - 1.0).
    """
    if accuracy_by_month is None:
        accuracy_by_month = _DEFAULT_FORECAST_ACCURACY_BY_MONTH

    # Base por mês
    base = accuracy_by_month.get(month, 0.78)
    p = base

    # Ajuste: cobertura de nuvens
    if cloud_cover < 25:
        p += 0.05
    elif cloud_cover < 50:
        p += 0.02
    elif cloud_cover < 75:
        p -= 0.03
    else:
        p -= 0.08

    # Ajuste: consenso OM
    if om_agrees is True:
        p += 0.03
    elif om_agrees is False:
        pass  # sem ajuste para discordância genérica

    # Ajuste: distância ao forecast (temp_gap)
    if temp_gap <= 2:
        p += 0.04
    elif temp_gap <= 5:
        p += 0.02
    elif temp_gap <= 8:
        p -= 0.02
    else:
        p -= 0.10

    # Ajuste: humidade
    if humidity < 40:
        p += 0.02
    elif humidity > 80:
        p -= 0.03

    # Ajuste: UV
    if uv_index is not None and uv_index >= 6:
        p += 0.02

    # Clamp
    return max(0.25, min(0.95, round(p, 3)))


def max_ask_for_ev_positive(p_forecast: float, margin: float = 0.05) -> float:
    """
    Ask máximo que dá EV ≥ 0 para dado P(forecast correcto).

    EV = P × (1/ask - 1) - (1 - P) × 1
    EV = 0 quando ask = P (break-even exacto).
    Com margem: max_ask = P - margin

    Parâmetros
    ----------
    p_forecast : float
        P(forecast correcto) estimada.
    margin : float
        Margem de segurança (default 5pp = 0.05).

    Retorna
    -------
    float
        Ask máximo aceitável. 0.0 se não há edge.
    """
    if p_forecast <= margin:
        return 0.0
    return round(p_forecast - margin, 3)


def p_forecast_correct_with_om_penalty(
    month: int,
    cloud_cover: float,
    humidity: float,
    wu_max: int,
    om_max: int | None,
    temp_gap: float,
    uv_index: float | None = None,
    accuracy_by_month: dict[int, float] | None = None,
) -> float:
    """
    Versão completa que distingue discordância de 1°C vs ≥2°C.

    Parâmetros
    ----------
    month : int
        Mês actual (1-12).
    wu_max : int
        Forecast WU (temperatura máxima prevista).
    om_max : int | None
        Forecast Open-Meteo. None se não disponível.
    """
    if om_max is None:
        om_agrees = None
    else:
        diff = abs(wu_max - om_max)
        om_agrees = diff <= 1

    p = p_forecast_correct(
        month=month,
        cloud_cover=cloud_cover,
        humidity=humidity,
        om_agrees=om_agrees,
        temp_gap=temp_gap,
        uv_index=uv_index,
        accuracy_by_month=accuracy_by_month,
    )

    # Penalização extra para discordância ≥2°C
    if om_max is not None and abs(wu_max - om_max) >= 2:
        p -= 0.05

    return max(0.25, min(0.95, round(p, 3)))


def get_forecast_accuracy_table(
    accuracy_by_month: dict[int, float] | None = None
) -> dict[int, float]:
    """
    Retorna a tabela de accuracy do forecast por mês.

    Parâmetros
    ----------
    accuracy_by_month : dict[int, float] | None
        Tabela de accuracy. Se None, usa defaults.

    Retorna
    -------
    dict[int, float]
        Accuracy por mês (1-12).
    """
    if accuracy_by_month is None:
        accuracy_by_month = _DEFAULT_FORECAST_ACCURACY_BY_MONTH

    return accuracy_by_month.copy()


if __name__ == "__main__":
    from cities.config import get_city

    print("=" * 60)
    print(" modules/forecast_confidence.py — self-test")
    print("=" * 60)

    # Teste 1
    p1 = p_forecast_correct(
        month=4, cloud_cover=0, humidity=39,
        om_agrees=False, temp_gap=3,
    )
    print(f"\n[1] Céu limpo, temp_gap=3, OM discorda")
    print(f"    P(fc correct) = {p1:.3f}")
    print(f"    Max ask (EV+) = {max_ask_for_ev_positive(p1):.3f}")

    # Teste 2
    p2 = p_forecast_correct(
        month=4, cloud_cover=90, humidity=85,
        om_agrees=False, temp_gap=5,
    )
    print(f"\n[2] Nublado, temp_gap=5")
    print(f"    P(fc correct) = {p2:.3f}")

    # Teste 3
    p3 = p_forecast_correct_with_om_penalty(
        month=4, cloud_cover=0, humidity=39,
        wu_max=20, om_max=19, temp_gap=3,
    )
    p4 = p_forecast_correct_with_om_penalty(
        month=4, cloud_cover=0, humidity=39,
        wu_max=20, om_max=18, temp_gap=3,
    )
    print(f"\n[3] Discordância OM:")
    print(f"    WU=20, OM=19 (diff=1) → P = {p3:.3f}")
    print(f"    WU=20, OM=18 (diff=2) → P = {p4:.3f}")

    # Teste 4: Tabela de accuracy
    accuracy_table = get_forecast_accuracy_table()
    print(f"\n[4] Tabela de accuracy por mês (primeiros 3 meses):")
    for month in range(1, 4):
        print(f"    {month}: {accuracy_table[month]:.2f}")

    print("\nOK")
