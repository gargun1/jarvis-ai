"""
Jarvis Memory — PostgreSQL-backed state: portfolio snapshots, deal pipeline, chat history.
"""
from datetime import datetime
from typing import Optional
import asyncpg
from config.settings import settings


class Memory:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(settings.database_url)
        await self._init_schema()

    async def disconnect(self):
        if self.pool:
            await self.pool.close()

    async def _init_schema(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id SERIAL PRIMARY KEY,
                    snapshot_time TIMESTAMPTZ DEFAULT NOW(),
                    platform TEXT NOT NULL,
                    data JSONB NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deals (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    name TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'prospect',
                    value NUMERIC,
                    currency TEXT DEFAULT 'USD',
                    notes TEXT,
                    next_action TEXT,
                    next_action_date DATE,
                    tags TEXT[]
                );

                CREATE TABLE IF NOT EXISTS kpis (
                    id SERIAL PRIMARY KEY,
                    recorded_at TIMESTAMPTZ DEFAULT NOW(),
                    metric TEXT NOT NULL,
                    value NUMERIC NOT NULL,
                    unit TEXT,
                    source TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT UNIQUE NOT NULL,
                    started_at TIMESTAMPTZ DEFAULT NOW(),
                    messages JSONB DEFAULT '[]'
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_time ON portfolio_snapshots(snapshot_time DESC);
                CREATE INDEX IF NOT EXISTS idx_kpis_metric ON kpis(metric, recorded_at DESC);
            """)

    # ── Portfolio Snapshots ──────────────────────────────────

    async def save_snapshot(self, platform: str, data: dict):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO portfolio_snapshots (platform, data) VALUES ($1, $2)",
                platform, data,
            )

    async def get_latest_snapshot(self, platform: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT data, snapshot_time FROM portfolio_snapshots WHERE platform=$1 ORDER BY snapshot_time DESC LIMIT 1",
                platform,
            )
            return dict(row) if row else None

    async def get_snapshot_history(self, platform: str, days: int = 30) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT data, snapshot_time FROM portfolio_snapshots
                   WHERE platform=$1 AND snapshot_time > NOW() - INTERVAL '$2 days'
                   ORDER BY snapshot_time DESC""",
                platform, days,
            )
            return [dict(r) for r in rows]

    # ── Deal Pipeline ────────────────────────────────────────

    async def add_deal(self, name: str, stage: str = "prospect", value: float = None,
                       currency: str = "USD", notes: str = None, next_action: str = None,
                       next_action_date=None, tags: list = None) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO deals (name, stage, value, currency, notes, next_action, next_action_date, tags)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
                name, stage, value, currency, notes, next_action, next_action_date, tags or [],
            )
            return row["id"]

    async def update_deal(self, deal_id: int, **kwargs):
        fields = {k: v for k, v in kwargs.items() if v is not None}
        fields["updated_at"] = datetime.utcnow()
        set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(fields))
        values = list(fields.values())
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"UPDATE deals SET {set_clause} WHERE id=$1",
                deal_id, *values,
            )

    async def get_deals(self, stage: str = None) -> list[dict]:
        async with self.pool.acquire() as conn:
            if stage:
                rows = await conn.fetch("SELECT * FROM deals WHERE stage=$1 ORDER BY updated_at DESC", stage)
            else:
                rows = await conn.fetch("SELECT * FROM deals ORDER BY updated_at DESC")
            return [dict(r) for r in rows]

    # ── KPI Tracking ─────────────────────────────────────────

    async def record_kpi(self, metric: str, value: float, unit: str = None, source: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO kpis (metric, value, unit, source) VALUES ($1,$2,$3,$4)",
                metric, value, unit, source,
            )

    async def get_kpi_history(self, metric: str, limit: int = 30) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM kpis WHERE metric=$1 ORDER BY recorded_at DESC LIMIT $2",
                metric, limit,
            )
            return [dict(r) for r in rows]


# Singleton
memory = Memory()
