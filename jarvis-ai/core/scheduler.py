"""
Jarvis Scheduler — APScheduler wrapper for daily briefings and portfolio snapshots.
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config.settings import settings

logger = logging.getLogger(__name__)


class JarvisScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._briefing_callback = None

    def set_briefing_callback(self, callback):
        """Set async function to call when briefing is ready. Receives (text: str)."""
        self._briefing_callback = callback

    def start(self):
        hour, minute = settings.briefing_time.split(":")

        # Daily morning briefing
        self.scheduler.add_job(
            self._run_briefing,
            CronTrigger(hour=int(hour), minute=int(minute)),
            id="daily_briefing",
            name="Daily Morning Briefing",
            replace_existing=True,
        )

        # Portfolio snapshot every 4 hours during market hours
        self.scheduler.add_job(
            self._snapshot_portfolios,
            CronTrigger(hour="9,13,17,21", minute="0"),
            id="portfolio_snapshot",
            name="Portfolio Snapshot",
            replace_existing=True,
        )

        # Weekly summary every Monday at 8am
        self.scheduler.add_job(
            self._run_weekly_summary,
            CronTrigger(day_of_week="mon", hour=8, minute=0),
            id="weekly_summary",
            name="Weekly Summary",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(f"Scheduler started. Daily briefing at {settings.briefing_time}.")

    def stop(self):
        self.scheduler.shutdown()

    async def _run_briefing(self):
        logger.info("Running daily briefing...")
        try:
            from agents.briefing import generate_daily_briefing
            text = await generate_daily_briefing()
            if self._briefing_callback:
                await self._briefing_callback(text)
            await self._send_email_briefing(text, subject="Jarvis Morning Briefing")
        except Exception as e:
            logger.error(f"Briefing failed: {e}")

    async def _run_weekly_summary(self):
        logger.info("Running weekly summary...")
        try:
            from agents.briefing import generate_weekly_summary
            text = await generate_weekly_summary()
            if self._briefing_callback:
                await self._briefing_callback(text)
            await self._send_email_briefing(text, subject="Jarvis Weekly Summary")
        except Exception as e:
            logger.error(f"Weekly summary failed: {e}")

    async def _snapshot_portfolios(self):
        logger.info("Taking portfolio snapshot...")
        try:
            from agents.portfolio import get_portfolio_summary
            from core.memory import memory
            data = await get_portfolio_summary()
            await memory.save_snapshot("all", data)
        except Exception as e:
            logger.error(f"Snapshot failed: {e}")

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

            # Plain text version
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
