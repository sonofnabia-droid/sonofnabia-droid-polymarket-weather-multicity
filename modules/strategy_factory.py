"""
modules/strategy_factory.py
===========================
Factory para criar a estratégia correcta.

Modos disponíveis (via CLI --mode):
- single: SingleEntry (1 compra + stop-loss)
- dual: DualStrategy (Forecast Early + Peak Detection)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cities.config import CityConfig
from modules.single_entry import SingleEntry
from modules.dual_strategy import DualStrategy


def create_strategy(city_config: CityConfig, mode: str = "single", **kwargs):
    """Cria a estratégia baseada no modo especificado."""
    mode = mode.lower()

    if mode == "single":
        return SingleEntry(city_config, **kwargs)
    elif mode == "dual":
        return DualStrategy(city_config, **kwargs)
    else:
        raise ValueError(f"Modo desconhecido: {mode}. Disponíveis: single, dual")


def get_strategy_name(mode: str) -> str:
    mode = mode.lower()
    if mode == "single":
        return "SingleEntry"
    elif mode == "dual":
        return "DualStrategy"
    return "Unknown"


if __name__ == "__main__":
    from cities.config import get_city

    print("=" * 60)
    print(" modules/strategy_factory.py — self-test")
    print("=" * 60)

    city = get_city("munich")
    print(f"\nCity: {city.name}")

    for mode in ["single", "dual"]:
        strategy = create_strategy(city, mode)
        print(f"\n  Mode: {mode}")
        print(f"  Strategy: {get_strategy_name(mode)}")
        print(f"  Instance: {type(strategy).__name__}")

    print("\nOK")
