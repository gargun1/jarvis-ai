"""
Daily Briefing Agent — composes morning report from all data sources.
"""
import json
from datetime import datetime
from core.brain import JarvisBrain
from agents.portfolio import tool_executor, get_portfolio_summary
from connectors.market import market


BRIEFING_PROMPT = """Generate a concise daily briefing for today ({date}).

Pull live portfolio data and market data, then structure your response as:

## Morning Briefing — {date}

**Portfolio Overview**
- Total estimated value across IBKR, Binance, Bitget
- Biggest movers since yesterday
- Any positions needing attention (large drawdowns, margin calls, expiring options)

**Open Orders**
- Any open orders that haven't filled

**Market Pulse**
- Top 3 crypto movers (24h)
- Key macro context if relevant

**Action Items**
- 2-3 things that actually need my attention today, prioritized

Keep it tight. No padding. Flag risks in bold."""


async def generate_daily_briefing() -> str:
    brain = JarvisBrain(tool_executor=tool_executor)
    date_str = datetime.now().strftime("%A, %B %d %Y")
    prompt = BRIEFING_PROMPT.format(date=date_str)
    return await brain._run_with_tools([{"role": "user", "content": prompt}])


async def generate_weekly_summary() -> str:
    brain = JarvisBrain(tool_executor=tool_executor)
    date_str = datetime.now().strftime("Week ending %B %d %Y")
    prompt = f"""Generate a weekly portfolio and business summary for {date_str}.

Include:
- Portfolio performance vs prior week (pull current data)
- Top performing and worst performing positions
- Deals closed or advanced in pipeline
- Key decisions made this week
- What to focus on next week

Be direct. Numbers first."""
    return await brain._run_with_tools([{"role": "user", "content": prompt}])
