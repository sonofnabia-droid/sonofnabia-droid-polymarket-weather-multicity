import os
from polymarket_clob import ClobClient, TradingMode
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

c = ClobClient(os.environ["POLY_PRIVATE_KEY"], TradingMode.REAL)

print("Balances por sig_type:")
for sig in [0, 1, 2]:
    info = c._client.get_balance_allowance(
        params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig)
    )
    bal = int(info.get("balance", "0")) / 1e6
    print(f"  sig={sig}: ${bal:.2f}")

best = c.get_usdc_balance()
print(f"\nMelhor saldo: ${best:.2f}")
