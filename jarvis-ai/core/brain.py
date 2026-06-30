"""
Jarvis Brain — Claude API wrapper with conversation memory and tool routing.
"""
import json
from typing import AsyncGenerator, Optional
import anthropic
from config.settings import settings

SYSTEM_PROMPT = """You are Jarvis, a personal AI financial and business advisor.
You have live access to the user's investment portfolios (Interactive Brokers, Binance, Bitget),
market data, and business metrics.

Your style:
- Concise and direct. No padding.
- Data-first. Lead with numbers, follow with insight.
- Flag risks clearly. Flag opportunities clearly.
- Never make trade recommendations — present data and let the user decide.
- When you don't have data, say so and explain how to get it.

You have access to the following tools which you can call to get live data:
- get_portfolio_summary: Returns holdings across all connected brokers
- get_market_data: Returns price/volume/change for a symbol
- get_crypto_balances: Returns crypto holdings across Binance and Bitget
- get_ibkr_positions: Returns IBKR positions and P&L
- get_open_orders: Returns open orders across all platforms

Always check live data before answering portfolio or market questions."""

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# Tool definitions for Claude
TOOLS = [
    {
        "name": "get_portfolio_summary",
        "description": "Get a full summary of all investment positions across IBKR, Binance, and Bitget including current values and P&L",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_market_data",
        "description": "Get current price, 24h change, volume for a specific ticker symbol",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol e.g. AAPL, BTC, ETH"},
                "asset_type": {"type": "string", "enum": ["stock", "crypto"], "description": "Asset type"},
            },
            "required": ["symbol", "asset_type"],
        },
    },
    {
        "name": "get_crypto_balances",
        "description": "Get crypto balances from Binance and Bitget",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["binance", "bitget", "all"], "default": "all"},
            },
            "required": [],
        },
    },
    {
        "name": "get_ibkr_positions",
        "description": "Get current IBKR equity/options positions with unrealized P&L",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_open_orders",
        "description": "Get all open orders across trading platforms",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["ibkr", "binance", "bitget", "all"], "default": "all"},
            },
            "required": [],
        },
    },
]


class JarvisBrain:
    def __init__(self, tool_executor=None):
        """
        tool_executor: async callable(tool_name, tool_input) -> dict
        Injected at runtime so brain stays decoupled from connectors.
        """
        self.tool_executor = tool_executor
        self.conversation_history: list[dict] = []

    async def chat(self, user_message: str) -> str:
        """Single-turn chat with tool use support."""
        self.conversation_history.append({"role": "user", "content": user_message})

        response_text = await self._run_with_tools(self.conversation_history)

        self.conversation_history.append({"role": "assistant", "content": response_text})
        return response_text

    async def chat_stream(self, user_message: str) -> AsyncGenerator[str, None]:
        """Streaming chat — yields text tokens as they arrive."""
        self.conversation_history.append({"role": "user", "content": user_message})

        full_response = ""
        async with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=self.conversation_history,
            tools=TOOLS,
        ) as stream:
            async for text in stream.text_stream:
                full_response += text
                yield text

        self.conversation_history.append({"role": "assistant", "content": full_response})

    async def _run_with_tools(self, messages: list[dict]) -> str:
        """Agentic loop: run Claude, handle tool calls, repeat until done."""
        while True:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
            )

            if response.stop_reason == "end_turn":
                return "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )

            if response.stop_reason == "tool_use":
                # Add assistant message with tool calls
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
                # Loop — Claude will now process tool results
            else:
                # Unexpected stop reason
                break

        return "I encountered an issue processing your request."

    async def _execute_tool(self, name: str, input_data: dict) -> dict:
        """Route tool calls to the injected executor."""
        if self.tool_executor is None:
            return {"error": f"No tool executor configured for '{name}'"}
        try:
            return await self.tool_executor(name, input_data)
        except Exception as e:
            return {"error": str(e)}

    def reset(self):
        """Clear conversation history."""
        self.conversation_history = []

    async def one_shot(self, prompt: str) -> str:
        """Single message without history — for briefings and reports."""
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=TOOLS,
        )
        return "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
