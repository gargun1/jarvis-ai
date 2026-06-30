"""
Portfolio Agent — aggregates data from all brokers and executes Claude tool calls.
This is the tool_executor injected into JarvisBrain.
"""
from connectors.ibkr import ibkr
from connectors.binance import binance
from connectors.bitget import bitget
from connectors.market import market


async def tool_executor(tool_name: str, tool_input: dict) -> dict:
    """Route Claude tool calls to the right connector."""
    try:
        if tool_name == "get_portfolio_summary":
            return await get_portfolio_summary()
        elif tool_name == "get_market_data":
            return await market.get_quote(
                tool_input["symbol"], tool_input.get("asset_type", "auto")
            )
        elif tool_name == "get_crypto_balances":
            platform = tool_input.get("platform", "all")
            return await get_crypto_balances(platform)
        elif tool_name == "get_ibkr_positions":
            return await get_ibkr_positions()
        elif tool_name == "get_open_orders":
            platform = tool_input.get("platform", "all")
            return await get_open_orders(platform)
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": str(e), "tool": tool_name}


async def get_portfolio_summary() -> dict:
    results = {"ibkr": None, "binance": None, "bitget": None, "errors": []}

    try:
        results["ibkr"] = {
            "portfolio": await ibkr.get_portfolio(),
            "account_summary": await ibkr.get_account_summary(),
        }
    except Exception as e:
        results["errors"].append(f"IBKR: {e}")

    try:
        results["binance"] = await binance.get_balance_with_values()
    except Exception as e:
        results["errors"].append(f"Binance: {e}")

    try:
        results["bitget"] = {
            "spot": await bitget.get_spot_balances(),
            "futures": await bitget.get_futures_positions(),
        }
    except Exception as e:
        results["errors"].append(f"Bitget: {e}")

    return results


async def get_crypto_balances(platform: str = "all") -> dict:
    result = {}
    if platform in ("binance", "all"):
        try:
            result["binance"] = await binance.get_balance_with_values()
        except Exception as e:
            result["binance_error"] = str(e)
    if platform in ("bitget", "all"):
        try:
            result["bitget_spot"] = await bitget.get_spot_balances()
            result["bitget_futures"] = await bitget.get_futures_positions()
        except Exception as e:
            result["bitget_error"] = str(e)
    return result


async def get_ibkr_positions() -> dict:
    try:
        return {
            "portfolio": await ibkr.get_portfolio(),
            "open_orders": await ibkr.get_open_orders(),
            "account": await ibkr.get_account_summary(),
        }
    except Exception as e:
        return {"error": str(e)}


async def get_open_orders(platform: str = "all") -> dict:
    result = {}
    if platform in ("ibkr", "all"):
        try:
            result["ibkr"] = await ibkr.get_open_orders()
        except Exception as e:
            result["ibkr_error"] = str(e)
    if platform in ("binance", "all"):
        try:
            result["binance"] = await binance.get_open_orders()
        except Exception as e:
            result["binance_error"] = str(e)
    if platform in ("bitget", "all"):
        try:
            result["bitget"] = await bitget.get_open_orders()
        except Exception as e:
            result["bitget_error"] = str(e)
    return result
