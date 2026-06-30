"""
Jarvis Memory — PostgreSQL-backed state: portfolio snapshots, deal pipeline,
durable facts (long-term memory), proactive notices, and audit log.
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

                CREATE TABLE IF NOT EXISTS facts (
                    id SERIAL PRIMARY KEY,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS notices (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    priority TEXT NOT NULL DEFAULT 'low',
                    title TEXT NOT NULL,
                    body TEXT,
                    source TEXT,
                    dismissed BOOLEAN DEFAULT FALSE,
                    dismissed_at TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    occurred_at TIMESTAMPTZ DEFAULT NOW(),
                    action_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail JSONB,
                    result TEXT,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_time ON portfolio_snapshots(snapshot_time DESC);
                CREATE INDEX IF NOT EXISTS idx_kpis_metric ON kpis(metric, recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_notices_undismissed ON notices(dismissed, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(occurred_at DESC);
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


    # ── Durable Facts (long-term memory) ─────────────────────

    async def save_fact(self, key: str, value: str):
        """Store or update a named fact. Key should be short and descriptive."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO facts (key, value, updated_at)
                   VALUES ($1, $2, NOW())
                   ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=NOW()""",
                key, value,
            )

    async def delete_fact(self, key: str):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM facts WHERE key=$1", key)

    async def get_all_facts(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value, updated_at FROM facts ORDER BY key")
            return [dict(r) for r in rows]

    async def get_facts_as_text(self) -> str:
        """Return facts formatted for injection into the system prompt."""
        facts = await self.get_all_facts()
        if not facts:
            return ""
        lines = [f"- {f['key']}: {f['value']}" for f in facts]
        return "Things I know about Garrett:\n" + "\n".join(lines)

    # ── Notices (proactive surface) ───────────────────────────

    async def add_notice(self, title: str, body: str = None, priority: str = "low",
                         source: str = None) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO notices (title, body, priority, source)
                   VALUES ($1, $2, $3, $4) RETURNING id""",
                title, body, priority, source,
            )
            return row["id"]

    async def get_pending_notices(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM notices WHERE dismissed=FALSE ORDER BY created_at DESC",
            )
            return [dict(r) for r in rows]

    async def dismiss_notice(self, notice_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE notices SET dismissed=TRUE, dismissed_at=NOW() WHERE id=$1",
                notice_id,
            )

    # ── Audit Log ─────────────────────────────────────────────

    async def log_action(self, action_type: str, action: str,
                         detail: dict = None, result: str = None, error: str = None):
        """Log a tool call, heartbeat event, or any notable action."""
        import json
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log (action_type, action, detail, result, error)
                   VALUES ($1, $2, $3, $4, $5)""",
                action_type, action,
                json.dumps(detail) if detail else None,
                result, error,
            )

    async def get_audit_log(self, limit: int = 50) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM audit_log ORDER BY occurred_at DESC LIMIT $1", limit,
            )
            return [dict(r) for r in rows]


# Singleton
memory = Memory()
