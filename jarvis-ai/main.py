#!/usr/bin/env python3
"""
Jarvis AI — Entry point.

Usage:
  python main.py serve          # Start web server (default)
  python main.py chat           # Terminal chat mode
  python main.py voice          # Voice mode (requires audio hardware)
  python main.py briefing       # Run morning briefing now
"""
import asyncio
import logging
import sys
import uvicorn
import typer
from rich.console import Console
from rich.markdown import Markdown

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("jarvis")
console = Console()
app_cli = typer.Typer()


@app_cli.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Auto-reload on code change"),
):
    """Start the Jarvis web server."""
    console.print("[bold green]Starting Jarvis...[/bold green]")
    uvicorn.run("api.app:app", host=host, port=port, reload=reload, log_level="info")


@app_cli.command()
def chat():
    """Interactive terminal chat with Jarvis."""
    asyncio.run(_terminal_chat())


@app_cli.command()
def voice():
    """Voice mode — speak to Jarvis, Jarvis speaks back."""
    asyncio.run(_voice_mode())


@app_cli.command()
def briefing():
    """Run the morning briefing right now and print it."""
    asyncio.run(_run_briefing())


async def _terminal_chat():
    from core.brain import JarvisBrain
    from agents.portfolio import tool_executor
    from core.memory import memory

    await memory.connect()
    brain = JarvisBrain(tool_executor=tool_executor)

    console.print("[bold]Jarvis[/bold] — type [dim]exit[/dim] to quit, [dim]reset[/dim] to clear history\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() == "exit":
            break
        if user_input.lower() == "reset":
            brain.reset()
            console.print("[dim]Conversation reset.[/dim]")
            continue

        console.print("\n[bold green]Jarvis:[/bold green]")
        response = await brain.chat(user_input)
        console.print(Markdown(response))
        console.print()

    await memory.disconnect()


async def _voice_mode():
    from core.brain import JarvisBrain
    from agents.portfolio import tool_executor
    from voice.stt import SpeechToText
    from voice.tts import tts

    brain = JarvisBrain(tool_executor=tool_executor)
    stt = SpeechToText()

    async def on_transcript(text: str):
        console.print(f"\n[cyan]You:[/cyan] {text}")
        response = await brain.chat(text)
        console.print(f"[green]Jarvis:[/green] {response}\n")
        await tts.speak_chunked(response)

    stt.set_callback(on_transcript)
    console.print("[bold]Voice mode active.[/bold] Speak to Jarvis. Ctrl+C to stop.\n")
    await stt.stream()


async def _run_briefing():
    from agents.briefing import generate_daily_briefing
    console.print("[bold]Running morning briefing...[/bold]\n")
    text = await generate_daily_briefing()
    console.print(Markdown(text))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Default: serve
        sys.argv.append("serve")
    app_cli()
