"""
Binance connector via python-binance.
Uses async client for non-blocking operation.
"""
from binance import AsyncClient, BinanceAPIException
from config.settings import settings


class BinanceConnector:
    def __init__(self):
        self._client: AsyncClient | None = None

    async def connect(self):
        self._client = await AsyncClient.create(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
            testnet=settings.binance_testnet,
        )

    async def disconnect(self):
        if self._client:
            await self._client.close_connection()
            self._client = None

    async def _ensure_connected(self):
        if self._client is None:
            await self.connect()

    async def get_balances(self, hide_zero: bool = True) -> list[dict]:
        """All spot wallet balances."""
        await self._ensure_connected()
        account = await self._client.get_account()
        balances = account["balances"]
        result = []
        for b in balances:
            free = float(b["free"])
            locked = float(b["locked"])
            total = free + locked
            if hide_zero and total == 0:
                continue
            result.append({
                "asset": b["asset"],
                "free": free,
                "locked": locked,
                "total": total,
            })
        return result

    async def get_balance_with_values(self) -> list[dict]:
        """Balances enriched with current USDT values."""
        await self._ensure_connected()
        balances = await self.get_balances()
        prices = await self._client.get_all_tickers()
        price_map = {p["symbol"]: float(p["price"]) for p in prices}

        result = []
        for b in balances:
            asset = b["asset"]
            usdt_value = None
            if asset == "USDT":
                usdt_value = b["total"]
            elif f"{asset}USDT" in price_map:
                usdt_value = b["total"] * price_map[f"{asset}USDT"]
            elif f"{asset}BTC" in price_map and "BTCUSDT" in price_map:
                usdt_value = b["total"] * price_map[f"{asset}BTC"] * price_map["BTCUSDT"]
            result.append({**b, "usdt_value": usdt_value})

        return sorted(result, key=lambda x: x["usdt_value"] or 0, reverse=True)

    async def get_open_orders(self) -> list[dict]:
        await self._ensure_connected()
        orders = await self._client.get_open_orders()
        return [
            {
                "symbol": o["symbol"],
                "side": o["side"],
                "type": o["type"],
                "price": float(o["price"]),
                "quantity": float(o["origQty"]),
                "filled": float(o["executedQty"]),
                "status": o["status"],
                "time": o["time"],
            }
            for o in orders
        ]

    async def get_ticker(self, symbol: str) -> dict:
        await self._ensure_connected()
        ticker = await self._client.get_ticker(symbol=symbol)
        return {
            "symbol": ticker["symbol"],
            "price": float(ticker["lastPrice"]),
            "change_24h_pct": float(ticker["priceChangePercent"]),
            "volume_24h": float(ticker["volume"]),
            "high_24h": float(ticker["highPrice"]),
            "low_24h": float(ticker["lowPrice"]),
        }

    async def get_futures_positions(self) -> list[dict]:
        """USD-M futures positions."""
        await self._ensure_connected()
        positions = await self._client.futures_position_information()
        return [
            {
                "symbol": p["symbol"],
                "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                "size": abs(float(p["positionAmt"])),
                "entry_price": float(p["entryPrice"]),
                "mark_price": float(p["markPrice"]),
                "unrealized_pnl": float(p["unRealizedProfit"]),
                "leverage": int(p["leverage"]),
                "margin_type": p["marginType"],
            }
            for p in positions
            if float(p["positionAmt"]) != 0
        ]


binance = BinanceConnector()
