"""
modules/strategy_factory.py
===========================
Factory para criar a estratégia correcta.

Modos disponíveis (via CLI --mode):
- single: SingleEntry (1 compra + stop-loss)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cities.config import CityConfig
from modules.single_entry import SingleEntry
from cassiopeia_entry import CassiopeiaEntry


def _calipso_entry(city_name: str, **kwargs):
    # §90/§91: C (Calipso) morto desde 03/10; o módulo vive em
    # archive_legacy_20261107/. Import lazy + erro claro se alguém pedir.
    try:
        from calipso_entry import CalipsoEntry
    except ModuleNotFoundError:
        raise ValueError(
            "Modo 'calipso' removido (C morto 03/10, §90). "
            "Módulo em archive_legacy_20261107/ se algum dia for ressuscitado."
        )
    return CalipsoEntry(city_name, **kwargs)


def create_strategy(city_config: CityConfig, mode: str = "single", **kwargs):
    """Cria a estratégia baseada no modo especificado."""
    mode = mode.lower()

    if mode == "single":
        return SingleEntry(city_config, **kwargs)
    if mode == "cassiopeia":
        return CassiopeiaEntry(city_config.name, **kwargs)
    if mode == "calipso":
        return _calipso_entry(city_config.name, **kwargs)
    raise ValueError(f"Modo desconhecido: {mode}. Disponível: single, cassiopeia")


def get_strategy_name(mode: str) -> str:
    mode = mode.lower()
    if mode == "single":
        return "SingleEntry"
    if mode == "cassiopeia":
        return "CassiopeiaEntry"
    if mode == "calipso":
        return "CalipsoEntry"
    return "Unknown"


if __name__ == "__main__":
    from cities.config import get_city

    print("=" * 60)
    print(" modules/strategy_factory.py — self-test")
    print("=" * 60)

    city = get_city("munich")
    print(f"\nCity: {city.name}")

    strategy = create_strategy(city, "single")
    print("\n  Mode: single")
    print(f"  Strategy: {get_strategy_name('single')}")
    print(f"  Instance: {type(strategy).__name__}")

    print("\nOK")
