#!/usr/bin/env python3
"""
test_live_bot_modes.py
======================
Teste rápido para verificar se o live_bot funciona com diferentes modos.
"""

import sys
sys.path.insert(0, '.')

from cities.config import get_city
from modules.strategy_factory import create_strategy


def test_modes():
    """Testa todos os modos de estratégia."""
    city = get_city("munich")

    print("Testing strategy factory...")
    print("=" * 60)

    modes = ["single", "dual", "phased"]

    for mode in modes:
        try:
            # Criar estratégia
            strategy = create_strategy(city, mode=mode, parcel_size=5.0)

            print(f"\n{mode.upper()} mode:")
            print(f"  Strategy: {type(strategy).__name__}")
            print(f"  Instance: OK")

            # Verificar se tem os métodos necessários
            methods = ["evaluate", "reset", "total_invested", "n_parcels_bought"]
            for method in methods:
                if hasattr(strategy, method):
                    print(f"  ✓ has '{method}'")
                else:
                    print(f"  ✗ missing '{method}'")

        except Exception as e:
            print(f"\n{mode.upper()} mode:")
            print(f"  ✗ ERROR: {e}")
            return False

    print("\n" + "=" * 60)
    print("✅ All modes tested successfully!")
    return True


if __name__ == "__main__":
    success = test_modes()
    sys.exit(0 if success else 1)
