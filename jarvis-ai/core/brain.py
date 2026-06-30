"""
Jarvis Brain — Claude API wrapper with conversation memory, tool routing,
and durable long-term memory via facts store.
"""
import json
import logging
from typing import AsyncGenerator, Optional
import anthropic
from config.settings import settings

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT = """You are Jarvis, Garrett's personal AI assistant.
You have live access to his investment portfolios (Interactive Brokers, Binance, Bitget),
market data, and business deal pipeline.

Your personality:
- Warm, direct, and conversational — like a smart colleague who knows his finances
- Use plain language even for complex data ("you're up about 4% on BTC this week" not "Δ +4.12% 7d")
- Lead with what matters, then offer detail if he asks
- Keep it brief unless he wants depth
- Never make trade recommendations — give him the picture and let him decide
- If you don't have data, say so and tell him how to get it
- When you notice something interesting or unusual in the data, mention it naturally

You can call tools to get live data and to remember things between conversations.
Always pull live data before answering portfolio or market questions — never guess at numbers.

{facts_section}"""

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# Tool definitions for Claude
TOOLS = [
    {
        "name": "get_portfolio_summary",
        "description": "Get a full summary of all investment positions across IBKR, Binance, and Bitget including current values and P&L. Use this whenever Garrett asks how his portfolio is doing, what he's holding, or wants an overview of his investments.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_market_data",
        "description": "Get current price, 24h change, and volume for a specific ticker symbol. Use for stocks (e.g. AAPL, TSLA) or crypto (e.g. BTC, ETH).",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL or BTC"},
                "asset_type": {"type": "string", "enum": ["stock", "crypto"], "description": "Whether this is a stock or crypto asset"},
            },
            "required": ["symbol", "asset_type"],
        },
    },
    {
        "name": "get_crypto_balances",
        "description": "Get crypto balances and values from Binance and/or Bitget. Use when Garrett asks about his crypto holdings specifically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["binance", "bitget", "all"], "default": "all", "description": "Which exchange(s) to check"},
            },
            "required": [],
        },
    },
    {
        "name": "get_ibkr_positions",
        "description": "Get current Interactive Brokers equity and options positions with unrealized P&L. Use when Garrett asks about his stocks, options, or IBKR account.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_open_orders",
        "description": "Get all open orders across trading platforms. Use when Garrett asks what orders are pending or waiting to fill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "enum": ["ibkr", "binance", "bitget", "all"], "default": "all"},
            },
            "required": [],
        },
    },
    {
        "name": "remember_fact",
        "description": "Store a durable fact about Garrett or his preferences that should persist across conversations. Use when he tells you something worth remembering — a preference, a goal, a regular commitment, a piece of context about his life or business. Key should be short and descriptive (e.g. 'preferred_briefing_format', 'risk_tolerance', 'home_timezone'). Value should be a clear plain-language statement.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short descriptive key for this fact"},
                "value": {"type": "string", "description": "The fact to remember, as a plain statement"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget_fact",
        "description": "Remove a previously stored fact that is no longer accurate or relevant. Use when Garrett corrects something you remembered wrong, or explicitly asks you to forget something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The key of the fact to remove"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "list_facts",
        "description": "Show all facts currently stored in long-term memory. Use when Garrett asks what you remember about him, or to audit the memory store.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
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
        self._facts_text: str = ""

    async def load_memory(self):
        """Load durable facts from DB into the system prompt. Call once at session start."""
        try:
            from core.memory import memory
            self._facts_text = await memory.get_facts_as_text()
        except Exception as e:
            logger.warning(f"Could not load facts from memory: {e}")
            self._facts_text = ""

    def _build_system_prompt(self) -> str:
        facts_section = self._facts_text if self._facts_text else ""
        return _BASE_SYSTEM_PROMPT.format(facts_section=facts_section).strip()

    async def chat(self, user_message: str) -> str:
        """Single-turn chat with tool use support."""
        self.conversation_history.append({"role": "user", "content": user_message})
        response_text = await self._run_with_tools(self.conversation_history)
        self.conversation_history.append({"role": "assistant", "content": response_text})
        return response_text

    async def chat_stream(self, user_message: str) -> AsyncGenerator[str, None]:
        """Streaming chat — yields text tokens as they arrive.
        Note: tool calls during streaming are handled non-streamingly for simplicity.
        If the model wants to call a tool, we fall back to the non-streaming path.
        """
        self.conversation_history.append({"role": "user", "content": user_message})

        # First check if we need tools (non-streaming probe)
        response = await client.messages.create(
            model=settings.model_name,
            max_tokens=256,  # Short — just checking stop_reason
            system=self._build_system_prompt(),
            messages=self.conversation_history,
            tools=TOOLS,
        )

        if response.stop_reason == "tool_use":
            # Run full agentic loop, then stream the final text word by word
            full_response = await self._run_with_tools(self.conversation_history[:-1] + [
                {"role": "user", "content": user_message}
            ])
            # Yield word by word so the UI still gets streaming feel
            for word in full_response.split(" "):
                yield word + " "
            self.conversation_history.append({"role": "assistant", "content": full_response})
        else:
            # No tools needed — stream directly
            full_response = ""
            async with client.messages.stream(
                model=settings.model_name,
                max_tokens=2048,
                system=self._build_system_prompt(),
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
                model=settings.model_name,
                max_tokens=4096,
                system=self._build_system_prompt(),
                messages=messages,
                tools=TOOLS,
            )

            if response.stop_reason == "end_turn":
                return "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"Tool call: {block.name}({block.input})")
                        result = await self._execute_tool(block.name, block.input)
                        # Log to audit trail
                        try:
                            from core.memory import memory
                            await memory.log_action(
                                action_type="tool_call",
                                action=block.name,
                                detail=block.input,
                                result=str(result)[:500],
                            )
                        except Exception:
                            pass
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                break

        return "I ran into an issue processing that — give it another go."

    async def _execute_tool(self, name: str, input_data: dict) -> dict:
        """Route tool calls: memory tools are handled here; others via injected executor."""
        # Memory tools are self-contained — no executor needed
        if name == "remember_fact":
            try:
                from core.memory import memory
                await memory.save_fact(input_data["key"], input_data["value"])
                # Refresh the in-session facts text
                self._facts_text = await memory.get_facts_as_text()
                return {"status": "remembered", "key": input_data["key"]}
            except Exception as e:
                return {"error": str(e)}

        if name == "forget_fact":
            try:
                from core.memory import memory
                await memory.delete_fact(input_data["key"])
                self._facts_text = await memory.get_facts_as_text()
                return {"status": "forgotten", "key": input_data["key"]}
            except Exception as e:
                return {"error": str(e)}

        if name == "list_facts":
            try:
                from core.memory import memory
                facts = await memory.get_all_facts()
                return {"facts": facts}
            except Exception as e:
                return {"error": str(e)}

        # All other tools go through the injected executor
        if self.tool_executor is None:
            return {"error": f"No tool executor configured for '{name}'"}
        try:
            return await self.tool_executor(name, input_data)
        except Exception as e:
            return {"error": str(e)}

    def reset(self):
        """Clear conversation history (keeps long-term facts)."""
        self.conversation_history = []

    async def one_shot(self, prompt: str) -> str:
        """Single message without history — for briefings and reports."""
        response = await client.messages.create(
            model=settings.model_name,
            max_tokens=4096,
            system=self._build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
            tools=TOOLS,
        )
        if response.stop_reason == "tool_use":
            return await self._run_with_tools([{"role": "user", "content": prompt}])
        return "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
