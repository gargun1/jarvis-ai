"""
Market data connector — stocks via yfinance, crypto via CoinGecko (free tier).
Also handles TradingView webhook ingestion.
"""
import httpx
import yfinance as yf
from typing import Optional


class MarketConnector:
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10)
        # Map common symbols to CoinGecko IDs
        self._cg_id_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
            "SOL": "solana", "ADA": "cardano", "DOT": "polkadot",
            "AVAX": "avalanche-2", "MATIC": "matic-network", "LINK": "chainlink",
            "XRP": "ripple", "DOGE": "dogecoin", "SHIB": "shiba-inu",
        }

    async def get_stock_quote(self, symbol: str) -> dict:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        hist = ticker.history(period="2d")
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else None
        current = float(info.last_price)
        change_pct = ((current - prev_close) / prev_close * 100) if prev_close else None
        return {
            "symbol": symbol.upper(),
            "type": "stock",
            "price": current,
            "change_24h_pct": round(change_pct, 2) if change_pct else None,
            "market_cap": getattr(info, "market_cap", None),
            "volume": getattr(info, "three_month_average_volume", None),
            "currency": getattr(info, "currency", "USD"),
        }

    async def get_crypto_quote(self, symbol: str) -> dict:
        cg_id = self._cg_id_map.get(symbol.upper(), symbol.lower())
        resp = await self._client.get(
            f"{self.COINGECKO_BASE}/simple/price",
            params={
                "ids": cg_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
        )
        resp.raise_for_status()
        data = resp.json().get(cg_id, {})
        return {
            "symbol": symbol.upper(),
            "type": "crypto",
            "price": data.get("usd"),
            "change_24h_pct": data.get("usd_24h_change"),
            "market_cap": data.get("usd_market_cap"),
            "volume_24h": data.get("usd_24h_vol"),
            "currency": "USD",
        }

    async def get_quote(self, symbol: str, asset_type: str = "auto") -> dict:
        """Get quote for any asset — auto-detects crypto vs stock."""
        if asset_type == "crypto" or symbol.upper() in self._cg_id_map:
            return await self.get_crypto_quote(symbol)
        return await self.get_stock_quote(symbol)

    async def get_top_movers(self) -> dict:
        """Top crypto gainers/losers from CoinGecko."""
        resp = await self._client.get(
            f"{self.COINGECKO_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 50,
                "price_change_percentage": "24h",
            },
        )
        resp.raise_for_status()
        coins = resp.json()
        sorted_by_change = sorted(
            coins, key=lambda x: x.get("price_change_percentage_24h") or 0
        )
        return {
            "top_gainers": [
                {"symbol": c["symbol"].upper(), "change_24h": c["price_change_percentage_24h"], "price": c["current_price"]}
                for c in sorted_by_change[-5:][::-1]
            ],
            "top_losers": [
                {"symbol": c["symbol"].upper(), "change_24h": c["price_change_percentage_24h"], "price": c["current_price"]}
                for c in sorted_by_change[:5]
            ],
        }

    async def close(self):
        await self._client.aclose()


market = MarketConnector()
