"""
Interactive Brokers connector via ib_insync.
Requires TWS or IB Gateway running locally (or tunneled from VPS via SSH).
"""
import asyncio
from typing import Optional
from ib_insync import IB, Stock, util
from config.settings import settings

util.startLoop()  # needed outside Jupyter


class IBKRConnector:
    def __init__(self):
        self.ib = IB()
        self._connected = False

    async def connect(self):
        if not self._connected:
            await self.ib.connectAsync(
                host=settings.ibkr_host,
                port=settings.ibkr_port,
                clientId=settings.ibkr_client_id,
            )
            self._connected = True

    async def disconnect(self):
        if self._connected:
            self.ib.disconnect()
            self._connected = False

    async def _ensure_connected(self):
        if not self._connected or not self.ib.isConnected():
            await self.connect()

    async def get_positions(self) -> list[dict]:
        await self._ensure_connected()
        positions = await self.ib.reqPositionsAsync()
        result = []
        for pos in positions:
            result.append({
                "account": pos.account,
                "symbol": pos.contract.symbol,
                "sec_type": pos.contract.secType,
                "exchange": pos.contract.exchange,
                "currency": pos.contract.currency,
                "quantity": float(pos.position),
                "avg_cost": float(pos.avgCost),
                "market_value": None,  # filled below
                "unrealized_pnl": None,
            })
        return result

    async def get_portfolio(self) -> list[dict]:
        """Full portfolio with market values and P&L."""
        await self._ensure_connected()
        account = settings.ibkr_account_id or ""
        portfolio = self.ib.portfolio(account) if account else self.ib.portfolio()
        result = []
        for item in portfolio:
            result.append({
                "symbol": item.contract.symbol,
                "sec_type": item.contract.secType,
                "position": float(item.position),
                "market_price": float(item.marketPrice),
                "market_value": float(item.marketValue),
                "avg_cost": float(item.averageCost),
                "unrealized_pnl": float(item.unrealizedPNL),
                "realized_pnl": float(item.realizedPNL),
                "currency": item.contract.currency,
            })
        return result

    async def get_account_summary(self) -> dict:
        """Net liquidation, cash, buying power, etc."""
        await self._ensure_connected()
        summary = await self.ib.reqAccountSummaryAsync()
        return {
            item.tag: item.value
            for item in summary
            if item.account == (settings.ibkr_account_id or item.account)
        }

    async def get_open_orders(self) -> list[dict]:
        await self._ensure_connected()
        trades = self.ib.openTrades()
        result = []
        for trade in trades:
            result.append({
                "symbol": trade.contract.symbol,
                "action": trade.order.action,
                "order_type": trade.order.orderType,
                "quantity": trade.order.totalQuantity,
                "limit_price": trade.order.lmtPrice,
                "status": trade.orderStatus.status,
                "filled": trade.orderStatus.filled,
                "remaining": trade.orderStatus.remaining,
            })
        return result

    def is_connected(self) -> bool:
        return self._connected and self.ib.isConnected()


ibkr = IBKRConnector()
