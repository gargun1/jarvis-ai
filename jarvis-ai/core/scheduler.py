"""
Jarvis Scheduler — APScheduler wrapper with:
  - Daily briefings and portfolio snapshots
  - Heartbeat checks (deal pipeline, market alerts)
  - Quiet window enforcement (12am–6am by default)
  - Notice queue: holds notices during quiet window, delivers on next check
  - Kill switch: pause/resume all proactive behavior at runtime
  - Overlapping-run prevention per job
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings

logger = logging.getLogger(__name__)

# Runtime kill switch — toggled via POST /api/kill-switch
_heartbeat_paused = False

# Per-job running-lock set — prevents overlapping runs
_running_jobs: set[str] = set()


def _load_config() -> dict:
    """Load agent_config.yaml, with safe fallback defaults."""
    config_path = Path(__file__).parent.parent / "config" / "agent_config.yaml"
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("agent_config.yaml not found — using defaults")
        return {}


def _in_quiet_window(config: dict) -> bool:
    """Return True if current server time falls in the configured quiet window."""
    qw = config.get("quiet_window", {})
    start = qw.get("start_hour", 0)
    end = qw.get("end_hour", 6)
    hour = datetime.now().hour
    if start <= end:
        return start <= hour < end
    # Wraps midnight (e.g. 22–6)
    return hour >= start or hour < end


def set_paused(paused: bool):
    global _heartbeat_paused
    _heartbeat_paused = paused
    state = "paused" if paused else "resumed"
    logger.info(f"Heartbeat {state} via kill switch")


def is_paused() -> bool:
    return _heartbeat_paused


class JarvisScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    def start(self):
        cfg = _load_config()
        briefing = cfg.get("briefing", {})
        portfolio = cfg.get("portfolio", {})

        hour, minute = settings.briefing_time.split(":")

        # Daily morning briefing
        self.scheduler.add_job(
            self._run_briefing,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_briefing",
            name="Daily Morning Briefing",
            replace_existing=True,
        )

        # Portfolio snapshot at configured hours
        snapshot_hours = ",".join(str(h) for h in portfolio.get("snapshot_hours", [9, 13, 17, 21]))
        self.scheduler.add_job(
            self._snapshot_portfolios,
            CronTrigger(hour=snapshot_hours, minute="0"),
            id="portfolio_snapshot",
            name="Portfolio Snapshot",
            replace_existing=True,
        )

        # Weekly summary
        weekly_day = briefing.get("weekly_day", "monday")
        weekly_hour = briefing.get("weekly_hour", 8)
        self.scheduler.add_job(
            self._run_weekly_summary,
            CronTrigger(day_of_week=weekly_day, hour=weekly_hour, minute=0),
            id="weekly_summary",
            name="Weekly Summary",
            replace_existing=True,
        )

        # Deal pipeline heartbeat
        deals_cfg = cfg.get("deals", {})
        if deals_cfg.get("check_enabled", True):
            deal_hours = deals_cfg.get("check_interval_hours", 12)
            self.scheduler.add_job(
                self._check_deals,
                IntervalTrigger(hours=deal_hours),
                id="deal_heartbeat",
                name="Deal Pipeline Check",
                replace_existing=True,
            )

        # Market alert heartbeat
        market_cfg = cfg.get("market", {})
        if market_cfg.get("check_enabled", True):
            market_hours = market_cfg.get("check_interval_hours", 4)
            self.scheduler.add_job(
                self._check_market_alerts,
                IntervalTrigger(hours=market_hours),
                id="market_heartbeat",
                name="Market Alert Check",
                replace_existing=True,
            )

        self.scheduler.start()
        logger.info(f"Scheduler started. Briefing at {settings.briefing_time}. Heartbeat active.")

    def stop(self):
        self.scheduler.shutdown()

    # ── Job Helpers ──────────────────────────────────────────

    async def _guard(self, job_id: str, coro) -> bool:
        """Run coro only if: heartbeat not paused AND job not already running.
        Returns True if the job ran, False if skipped."""
        if _heartbeat_paused and job_id not in ("daily_briefing", "weekly_summary"):
            logger.debug(f"Skipping {job_id} — heartbeat paused")
            return False
        if job_id in _running_jobs:
            logger.warning(f"Skipping {job_id} — previous run still active")
            return False
        _running_jobs.add(job_id)
        try:
            await coro
            return True
        finally:
            _running_jobs.discard(job_id)

    async def _queue_notice(self, title: str, body: str, priority: str = "low",
                             source: str = None, break_quiet: bool = False):
        """Queue a proactive notice. Respects quiet window unless break_quiet=True."""
        try:
            from core.memory import memory
            cfg = _load_config()
            if not break_quiet and _in_quiet_window(cfg):
                logger.debug(f"Notice held (quiet window): {title}")
                # Still save to DB — it'll appear when the UI next opens
            await memory.add_notice(title=title, body=body, priority=priority, source=source)
            await memory.log_action(
                action_type="heartbeat",
                action="notice_queued",
                detail={"title": title, "priority": priority},
            )
        except Exception as e:
            logger.error(f"Failed to queue notice: {e}")

    # ── Scheduled Jobs ───────────────────────────────────────

    async def _run_briefing(self):
        async def _inner():
            logger.info("Running daily briefing...")
            try:
                from agents.briefing import generate_daily_briefing
                text = await generate_daily_briefing()
                await self._queue_notice(
                    title="Morning Briefing Ready",
                    body=text[:300] + ("…" if len(text) > 300 else ""),
                    priority="low",
                    source="daily_briefing",
                )
                await self._send_email_briefing(text, subject="Jarvis Morning Briefing")
            except Exception as e:
                logger.error(f"Briefing failed: {e}")

        await self._guard("daily_briefing", _inner())

    async def _run_weekly_summary(self):
        async def _inner():
            logger.info("Running weekly summary...")
            try:
                from agents.briefing import generate_weekly_summary
                text = await generate_weekly_summary()
                await self._queue_notice(
                    title="Weekly Summary Ready",
                    body=text[:300] + ("…" if len(text) > 300 else ""),
                    priority="low",
                    source="weekly_summary",
                )
                await self._send_email_briefing(text, subject="Jarvis Weekly Summary")
            except Exception as e:
                logger.error(f"Weekly summary failed: {e}")

        await self._guard("weekly_summary", _inner())

    async def _snapshot_portfolios(self):
        async def _inner():
            logger.info("Taking portfolio snapshot...")
            try:
                from agents.portfolio import get_portfolio_summary
                from core.memory import memory
                data = await get_portfolio_summary()
                await memory.save_snapshot("all", data)
                await memory.log_action(action_type="heartbeat", action="portfolio_snapshot",
                                        result="ok")
            except Exception as e:
                logger.error(f"Snapshot failed: {e}")

        await self._guard("portfolio_snapshot", _inner())

    async def _check_deals(self):
        async def _inner():
            cfg = _load_config()
            if _in_quiet_window(cfg):
                return
            logger.debug("Checking deal pipeline...")
            try:
                from core.memory import memory
                from datetime import date, timedelta
                deals_cfg = cfg.get("deals", {})
                lookahead = deals_cfg.get("upcoming_action_days", 2)

                all_deals = await memory.get_deals()
                today = date.today()
                threshold = today + timedelta(days=lookahead)

                upcoming = [
                    d for d in all_deals
                    if d.get("next_action_date") and d["next_action_date"] <= threshold
                    and d.get("stage") not in ("closed_won", "closed_lost")
                ]
                for deal in upcoming:
                    days_away = (deal["next_action_date"] - today).days
                    when = "today" if days_away == 0 else f"in {days_away} day{'s' if days_away != 1 else ''}"
                    await self._queue_notice(
                        title=f"Deal action due {when}: {deal['name']}",
                        body=deal.get("next_action", "No action note recorded"),
                        priority="low",
                        source="deal_heartbeat",
                    )
            except Exception as e:
                logger.error(f"Deal check failed: {e}")

        await self._guard("deal_heartbeat", _inner())

    async def _check_market_alerts(self):
        async def _inner():
            cfg = _load_config()
            if _in_quiet_window(cfg):
                return
            logger.debug("Checking market alerts...")
            try:
                from core.memory import memory
                market_cfg = cfg.get("market", {})
                threshold = market_cfg.get("large_move_pct", 8.0)

                # Check latest snapshot for large moves
                snapshot = await memory.get_latest_snapshot("all")
                if not snapshot:
                    return

                data = snapshot.get("data", {})
                positions = data.get("positions", []) or []
                for pos in positions:
                    change_pct = abs(float(pos.get("change_pct_24h", 0) or 0))
                    if change_pct >= threshold:
                        direction = "up" if float(pos.get("change_pct_24h", 0)) > 0 else "down"
                        await self._queue_notice(
                            title=f"{pos.get('symbol', 'Unknown')} moved {direction} {change_pct:.1f}% today",
                            body=f"Current value: {pos.get('value', 'unknown')}",
                            priority="high",
                            source="market_heartbeat",
                        )
            except Exception as e:
                logger.error(f"Market alert check failed: {e}")

        await self._guard("market_heartbeat", _inner())

    async def _send_email_briefing(self, text: str, subject: str):
        if not settings.briefing_email or not settings.smtp_host:
            return
        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_user
            msg["To"] = settings.briefing_email
            msg.attach(MIMEText(text, "plain"))

            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user,
                password=settings.smtp_password,
                use_tls=True,
            )
            logger.info(f"Briefing email sent to {settings.briefing_email}")
        except Exception as e:
            logger.error(f"Email failed: {e}")


scheduler = JarvisScheduler()
