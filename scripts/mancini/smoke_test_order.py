"""
Smoke-test del OrderExecutor en modo dry-run.

Lanza una orden LONG de mercado en /ES en dry-run y un stop GTC,
e imprime el resultado del SDK. No ejecuta nada real.

Uso:
    uv run python scripts/mancini/smoke_test_order.py
"""
from __future__ import annotations

import os
import sys

from tastytrade import Account

from scripts.tastytrade_client import TastyTradeClient
from scripts.mancini.order_executor import OrderExecutor


def main() -> None:
    client = TastyTradeClient()

    es_symbol = client.get_front_month_symbol("ES")
    if not es_symbol:
        print("❌ No se pudo resolver /ES front-month")
        sys.exit(1)
    print(f"✅ Símbolo resuelto: {es_symbol}")

    accounts = Account.get_accounts(client.session)
    if not accounts:
        print("❌ No se encontraron cuentas TastyTrade")
        sys.exit(1)
    account = accounts[0]
    print(f"✅ Cuenta: {account.account_number}")

    executor = OrderExecutor(
        session=client.session,
        account=account,
        dry_run=True,
        contracts=1,
    )

    quote = client.get_future_quote("/ES")
    if not quote or not quote.get("mark"):
        print("❌ No se pudo obtener precio /ES")
        sys.exit(1)
    price = float(quote["mark"])
    stop = round(price - 15, 2)
    print(f"✅ Precio /ES: {price} | Stop simulado: {stop}")

    print("\n--- Orden ENTRY (dry-run) ---")
    entry = executor.place_entry("LONG", es_symbol)
    print(f"  success  : {entry.success}")
    print(f"  order_id : {entry.order_id}")
    print(f"  dry_run  : {entry.dry_run}")
    print(f"  error    : {entry.error}")
    if entry.details:
        bp = entry.details.get("buying_power_effect")
        if bp:
            print(f"  buying_power_effect: {bp}")

    print("\n--- Orden STOP GTC (dry-run) ---")
    stop_result = executor.place_stop("LONG", es_symbol, stop)
    print(f"  success  : {stop_result.success}")
    print(f"  order_id : {stop_result.order_id}")
    print(f"  error    : {stop_result.error}")

    ok = entry.success and stop_result.success
    print(f"\n{'✅ Smoke-test OK' if ok else '❌ Smoke-test FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
