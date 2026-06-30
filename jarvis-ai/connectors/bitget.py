"""
Bitget connector via pybitget SDK.
"""
import hashlib
import hmac
import time
import httpx
from config.settings import settings


class BitgetConnector:
    BASE_URL = "https://api.bitget.com"

    def __init__(self):
        self.api_key = settings.bitget_api_key
        self.api_secret = settings.bitget_api_secret
        self.passphrase = settings.bitget_passphrase
        self._client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=10)

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = f"{timestamp}{method.upper()}{path}{body}"
        return hmac.new(
            self.api_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        ts = str(int(time.time() * 1000))
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": self._sign(ts, method, path, body),
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict = None) -> dict:
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        headers = self._headers("GET", path + query)
        resp = await self._client.get(path + query, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def get_spot_balances(self) -> list[dict]:
        data = await self._get("/api/v2/spot/account/assets")
        result = []
        for asset in data.get("data", []):
            available = float(asset.get("available", 0))
            frozen = float(asset.get("frozen", 0))
            total = available + frozen
            if total == 0:
                continue
            result.append({
                "asset": asset["coin"],
                "available": available,
                "frozen": frozen,
                "total": total,
                "usdt_value": float(asset.get("usdtAmount", 0)),
            })
        return sorted(result, key=lambda x: x["usdt_value"], reverse=True)

    async def get_futures_positions(self, product_type: str = "USDT-FUTURES") -> list[dict]:
        data = await self._get("/api/v2/mix/position/all-position", {"productType": product_type})
        result = []
        for pos in data.get("data", []):
            size = float(pos.get("total", 0))
            if size == 0:
                continue
            result.append({
                "symbol": pos["symbol"],
                "side": pos["holdSide"].upper(),
                "size": size,
                "entry_price": float(pos.get("openPriceAvg", 0)),
                "mark_price": float(pos.get("markPrice", 0)),
                "unrealized_pnl": float(pos.get("unrealizedPL", 0)),
                "leverage": int(pos.get("leverage", 1)),
                "margin_mode": pos.get("marginMode", ""),
                "liquidation_price": float(pos.get("liquidationPrice", 0)),
            })
        return result

    async def get_open_orders(self, symbol: str = None) -> list[dict]:
        params = {"productType": "USDT-FUTURES"}
        if symbol:
            params["symbol"] = symbol
        data = await self._get("/api/v2/mix/order/orders-pending", params)
        return [
            {
                "symbol": o["symbol"],
                "side": o["side"],
                "order_type": o["orderType"],
                "price": float(o.get("price", 0)),
                "size": float(o.get("size", 0)),
                "filled": float(o.get("filledQty", 0)),
                "status": o["status"],
            }
            for o in data.get("data", {}).get("entrustedList", [])
        ]

    async def close(self):
        await self._client.aclose()


bitget = BitgetConnector()
