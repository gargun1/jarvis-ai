"""
Text-to-Speech via ElevenLabs streaming API.
"""
import asyncio
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import stream as el_stream
from config.settings import settings


class TextToSpeech:
    def __init__(self):
        self.client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
        self.voice_id = settings.elevenlabs_voice_id

    async def speak(self, text: str):
        """Stream TTS audio directly to speakers."""
        audio = await self.client.generate(
            text=text,
            voice=self.voice_id,
            model="eleven_turbo_v2_5",  # lowest latency
            stream=True,
        )
        el_stream(audio)

    async def speak_chunked(self, text: str, chunk_size: int = 150):
        """Split long text into chunks for lower perceived latency."""
        words = text.split()
        chunks = []
        current = []
        for word in words:
            current.append(word)
            if len(" ".join(current)) >= chunk_size and word.endswith((".", "!", "?")):
                chunks.append(" ".join(current))
                current = []
        if current:
            chunks.append(" ".join(current))

        for chunk in chunks:
            await self.speak(chunk)


tts = TextToSpeech()
