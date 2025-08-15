from __future__ import annotations

import argparse
import asyncio
from typing import Optional

from agents.realtime import RealtimeAgent, RealtimeRunner
import numpy as np
import sounddevice as sd
import asyncio
import contextlib


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        "edxo-realtime",
        description="Continuous French conversation using OpenAI Realtime API",
    )
    p.add_argument("--model", default="gpt-4o-realtime-preview")
    p.add_argument("--voice", default="alloy")
    p.add_argument("--no-greeting", action="store_true", help="Do not send initial greeting message")
    p.add_argument("--api-key", default=None, help="Override OPENAI_API_KEY for this run")
    p.add_argument("--vad-threshold", type=float, default=0.5)
    p.add_argument("--silence-ms", type=int, default=200)
    p.add_argument("--prefix-padding-ms", type=int, default=300)
    p.add_argument("--mic", action="store_true", help="Capture microphone and stream PCM16 to the realtime session")
    p.add_argument("--samplerate", type=int, default=24000, help="Microphone sample rate (Hz)")
    return p


async def main_async(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    agent = RealtimeAgent(
        name="Assistant FR",
        instructions=(
            "Tu es un assistant vocal utile. Réponds en français,"
            " de manière concise, naturelle et conversationnelle."
        ),
    )

    runner = RealtimeRunner(
        starting_agent=agent,
        config={
            "model_settings": {
                "model_name": args.model,
                "voice": args.voice,
                "modalities": ["text", "audio"],
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": args.vad_threshold,
                    "prefix_padding_ms": args.prefix_padding_ms,
                    "silence_duration_ms": args.silence_ms,
                },
            }
        },
    )

    model_config = {"api_key": args.api_key} if args.api_key else None
    session = await runner.run(model_config=model_config) if model_config else await runner.run()

    async with session:
        if not args.no_greeting:
            await session.send_message("Bonjour ! Comment puis-je vous aider aujourd'hui ?")

        print("Session démarrée — conversation audio en temps réel.")

        mic_task = None

        if args.mic:
            # Choose a method exposed by the session for streaming input audio.
            # We try a few common names used by the Agents SDK; if none exist, we warn and continue without mic.
            send_audio = None
            for name in (
                "send_input_audio",  # likely high-level API
                "send_audio",         # alternative naming
                "append_input_audio", # buffer-append style
            ):
                candidate = getattr(session, name, None)
                if callable(candidate):
                    send_audio = candidate
                    break

            if send_audio is None:
                print("Avertissement: l'API Realtime fournie ne supporte pas l'envoi audio direct depuis Python (méthode introuvable).")
            else:
                q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)

                def on_audio(indata, frames, time, status):  # sounddevice callback (in a separate thread)
                    if status:
                        # Drop frame on overflow/underflow but keep running
                        pass
                    # Flatten to int16 mono bytes
                    b = indata.reshape(-1).astype(np.int16).tobytes()
                    try:
                        q.put_nowait(b)
                    except asyncio.QueueFull:
                        # Drop if congested
                        pass

                async def pump_microphone():
                    stream = sd.InputStream(samplerate=args.samplerate, channels=1, dtype=np.int16, callback=on_audio)
                    stream.start()
                    try:
                        while True:
                            chunk = await q.get()
                            try:
                                await send_audio(chunk)
                            except Exception:
                                # If sending fails, attempt to continue; session may be closing
                                break
                    finally:
                        stream.stop()
                        stream.close()

                mic_task = asyncio.create_task(pump_microphone())

        try:
            async for event in session:
                if event.type == "response.audio_transcript.done":
                    print(f"Assistant: {event.transcript}")
                elif event.type == "conversation.item.input_audio_transcription.completed":
                    print(f"Vous: {event.transcript}")
                elif event.type == "error":
                    print(f"Erreur: {event.error}")
                    break
        finally:
            if mic_task is not None:
                mic_task.cancel()
                with contextlib.suppress(Exception):
                    await mic_task

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
