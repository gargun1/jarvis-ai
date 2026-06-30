"""
Speech-to-Text via Deepgram streaming API.
"""
import asyncio
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
from config.settings import settings


class SpeechToText:
    def __init__(self):
        self.client = DeepgramClient(settings.deepgram_api_key)
        self._transcript_callback = None

    def set_callback(self, callback):
        """Callback receives (transcript: str) when speech is detected."""
        self._transcript_callback = callback

    async def stream(self):
        """Start streaming microphone input to Deepgram."""
        connection = self.client.listen.asynclive.v("1")

        async def on_message(self_inner, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if sentence and self._transcript_callback:
                await self._transcript_callback(sentence)

        connection.on(LiveTranscriptionEvents.Transcript, on_message)

        options = LiveOptions(
            model="nova-2",
            language="en-US",
            smart_format=True,
            interim_results=False,
            utterance_end_ms="1000",
            vad_events=True,
            endpointing=300,
        )

        await connection.start(options)

        # Stream microphone
        import pyaudio
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                        input=True, frames_per_buffer=1024)

        try:
            while True:
                data = stream.read(1024, exception_on_overflow=False)
                await connection.send(data)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            await connection.finish()
