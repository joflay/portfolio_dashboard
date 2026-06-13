import json
import os
import sys
import time
from typing import Any

from dotenv import load_dotenv
from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient


def response_json(response) -> Any:
    """Safely convert SDK response to JSON."""
    try:
        return response.json()
    except Exception:
        return {"raw_text": getattr(response, "text", str(response))}


def print_response_debug(name: str, response) -> Any:
    """Print status and return parsed JSON."""
    print(f"\n===== {name} =====")
    status = getattr(response, "status_code", "UNKNOWN")
    print("Status:", status)

    data = response_json(response)

    if status != 200:
        print(json.dumps(data, indent=2))
        return data

    return data


def extract_accounts(account_data: Any) -> list[dict]:
    """
    Handles common shapes:
    - list of accounts
    - {"data": [...]}
    - {"accounts": [...]}
    - {"data": {"accounts": [...]}}
    """
    if isinstance(account_data, list):
        return account_data

    if isinstance(account_data, dict):
        for key in ("data", "accounts", "result"):
            value = account_data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                for nested_key in ("accounts", "accountList", "list"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return nested

    return []


def get_account_id(account: dict) -> str | None:
    """Try likely account id field names."""
    for key in (
        "account_id",
        "accountId",
        "accountNo",
        "account_number",
        "accountNumber",
        "id",
    ):
        value = account.get(key)
        if value:
            return str(value)
    return None


def first_present(d: dict, keys: tuple[str, ...], default=""):
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


def print_cash_summary(balance_data: Any):
    print("\n--- Cash / Buying Power Summary ---")

    # Print full JSON first because field names can vary by account type.
    print(json.dumps(balance_data, indent=2))

    # Best-effort compact summary if it is dict-like.
    if isinstance(balance_data, dict):
        root = balance_data.get("data", balance_data)
        if isinstance(root, dict):
            cash = first_present(root, ("cashBalance", "cash", "settledCash", "availableCash"))
            buying_power = first_present(root, ("buyingPower", "stockBuyingPower", "optionBuyingPower"))
            net_liq = first_present(root, ("netLiquidation", "netLiquidationValue", "accountValue", "totalAsset"))

            if cash or buying_power or net_liq:
                print("\nCompact:")
                print(f"  Cash:          {cash}")
                print(f"  Buying Power:  {buying_power}")
                print(f"  Net Liq/Value: {net_liq}")


def print_positions_summary(positions_data: Any):
    print("\n--- Positions Summary ---")

    # Print full JSON first so you can see exact field names.
    print(json.dumps(positions_data, indent=2))

    positions = []

    if isinstance(positions_data, list):
        positions = positions_data
    elif isinstance(positions_data, dict):
        root = positions_data.get("data", positions_data)

        if isinstance(root, list):
            positions = root
        elif isinstance(root, dict):
            for key in ("positions", "positionList", "list"):
                if isinstance(root.get(key), list):
                    positions = root[key]
                    break

    if not positions:
        print("\nNo positions found or response shape is different.")
        return

    print("\nCompact:")
    print(f"{'Symbol':<12} {'Qty':>12} {'Mkt Value':>15} {'Unreal P/L':>15}")

    for p in positions:
        if not isinstance(p, dict):
            continue

        symbol = first_present(
            p,
            ("symbol", "ticker", "instrumentSymbol", "displaySymbol", "name"),
            "?",
        )
        qty = first_present(
            p,
            ("quantity", "qty", "position", "holdingQuantity"),
            "",
        )
        market_value = first_present(
            p,
            ("marketValue", "mktValue", "totalMarketValue"),
            "",
        )
        unreal_pl = first_present(
            p,
            ("unrealizedProfitLoss", "unrealizedPnl", "unrealizedPL", "unrealizedProfit"),
            "",
        )

        print(f"{str(symbol):<12} {str(qty):>12} {str(market_value):>15} {str(unreal_pl):>15}")


def main():
    load_dotenv()

    app_key = os.getenv("WEBULL_APP_KEY")
    app_secret = os.getenv("WEBULL_APP_SECRET")
    region = os.getenv("WEBULL_REGION", "us")
    endpoint = os.getenv("WEBULL_ENDPOINT", "api.webull.com")

    if not app_key or not app_secret:
        print("Missing WEBULL_APP_KEY or WEBULL_APP_SECRET in .env")
        sys.exit(1)

    api_client = ApiClient(app_key, app_secret, region)
    api_client.add_endpoint(region, endpoint)

    trade_client = TradeClient(api_client)

    account_response = trade_client.account_v2.get_account_list()
    account_data = print_response_debug("Account List", account_response)

    accounts = extract_accounts(account_data)

    if not accounts:
        print("\nCould not extract accounts from response. Full account response:")
        print(json.dumps(account_data, indent=2))
        sys.exit(1)

    for i, account in enumerate(accounts, start=1):
        account_id = get_account_id(account)

        print(f"\n================ ACCOUNT {i} ================")
        print("Account object:")
        print(json.dumps(account, indent=2))

        if not account_id:
            print("Could not find account_id field for this account.")
            continue

        print("Using account_id:", account_id)

        # Webull account endpoints are rate-limited, so avoid rapid-fire calls.
        time.sleep(1.1)

        balance_response = trade_client.account_v2.get_account_balance(account_id=account_id)
        balance_data = print_response_debug("Account Balance", balance_response)
        print_cash_summary(balance_data)

        time.sleep(1.1)

        positions_response = trade_client.account_v2.get_account_positions(account_id=account_id)
        positions_data = print_response_debug("Account Positions", positions_response)
        print_positions_summary(positions_data)


if __name__ == "__main__":
    main()