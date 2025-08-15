from __future__ import annotations

import argparse
import asyncio
from typing import Optional

import numpy as np
import sounddevice as sd

from agents.voice import AudioInput, SingleAgentVoiceWorkflow, VoicePipeline
from src.agent.edxo_agent import build_agents


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        "edxo-voice",
        description="Run the EDxo agent with voice (STT -> agent -> TTS)",
    )
    p.add_argument(
        "--seconds",
        type=int,
        default=3,
        help="Duration to record from microphone (seconds)",
    )
    p.add_argument(
        "--samplerate",
        type=int,
        default=24000,
        help="Audio sample rate for input/output",
    )
    p.add_argument(
        "--silence",
        action="store_true",
        help="Send silence instead of recording from the microphone",
    )
    return p


async def run_voice(seconds: int, samplerate: int, use_silence: bool = False) -> int:
    agent = build_agents()
    pipeline = VoicePipeline(workflow=SingleAgentVoiceWorkflow(agent))

    if use_silence:
        buffer = np.zeros(samplerate * seconds, dtype=np.int16)
    else:
        # Record mono audio from the default input device
        print(f"Recording {seconds}s at {samplerate} Hz...")
        rec = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1, dtype=np.int16)
        sd.wait()
        buffer = rec.reshape(-1)

    audio_input = AudioInput(buffer=buffer)

    print("Sending audio to the agent... (transcribe -> think -> speak)")
    result = await pipeline.run(audio_input)

    # Stream TTS audio to default output device
    player = sd.OutputStream(samplerate=samplerate, channels=1, dtype=np.int16)
    player.start()

    try:
        async for event in result.stream():
            if event.type == "voice_stream_event_audio":
                player.write(event.data)
    finally:
        player.stop()
        player.close()

    # Optionally, you could also inspect the final text output
    # print("Agent said:", result.text)

    return 0


async def main_async(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return await run_voice(args.seconds, args.samplerate, use_silence=args.silence)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        return asyncio.run(main_async(argv))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

