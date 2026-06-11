#!/usr/bin/env python3
"""Make a Unitree G1 speak through its onboard speaker.

Why not the SDK's TtsMaker? On this robot the onboard TTS engine is dead:
TtsMaker() returns 0 but no audio comes out (LED/volume control on the same
service DO work, so it's the synth stage that's broken). Instead we synthesize
speech on the Jetson with edge-tts (Microsoft neural voices), decode it to
16 kHz/16-bit/mono PCM, and push it to the speaker with AudioClient.PlayStream —
which is verified working on this robot.

    python3 speak.py "hello this is Alex speaking"
    python3 speak.py --file script.txt
    python3 speak.py --zh "你好，我是 G1"
    python3 speak.py "faster" --voice en-US-GuyNeural --rate +15%

Needs: internet on the Jetson (edge-tts hits a Microsoft endpoint) and mpg123.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient

SR = 16000          # robot speaker expects 16 kHz / 16-bit / mono
CHUNK = SR * 2      # 1 second of audio per PlayStream chunk
APP = "speak"


def synth_pcm(text: str, voice: str, rate: str) -> bytes:
    """edge-tts -> mp3 -> 16 kHz mono s16le PCM bytes."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as mp3:
        r = subprocess.run(
            ["python3", "-m", "edge_tts", "--voice", voice, f"--rate={rate}",
             "--text", text, "--write-media", mp3.name],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0 or Path(mp3.name).stat().st_size == 0:
            raise RuntimeError("edge-tts produced no audio (internet? voice name?)\n"
                               + r.stderr.decode(errors="ignore"))
        dec = subprocess.run(
            ["mpg123", "-q", "-m", "-r", str(SR), "-s", mp3.name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if dec.returncode != 0 or not dec.stdout:
            raise RuntimeError("mpg123 decode failed\n" + dec.stderr.decode(errors="ignore"))
        return dec.stdout


def play(client: AudioClient, pcm: bytes) -> None:
    for n, i in enumerate(range(0, len(pcm), CHUNK)):
        chunk = pcm[i:i + CHUNK]
        client.PlayStream(APP, f"s{n:04d}", chunk)
        time.sleep(len(chunk) / CHUNK)   # pace at real-time so we don't overrun


def main() -> int:
    ap = argparse.ArgumentParser(description="Make Unitree G1 speak (edge-tts + PlayStream).")
    ap.add_argument("text", nargs="?", help="Text to speak (omit when using --file).")
    ap.add_argument("--file", help="Read the text to speak from a file.")
    ap.add_argument("--iface", default="eth0",
                    help="NIC that reaches the robot DDS (default: eth0).")
    ap.add_argument("--volume", type=int, default=100, help="Speaker volume 0-100.")
    ap.add_argument("--voice", default="en-US-AriaNeural",
                    help="edge-tts voice (default en-US-AriaNeural). "
                         "List all: python3 -m edge_tts --list-voices")
    ap.add_argument("--zh", action="store_true",
                    help="Shortcut for --voice zh-CN-XiaoxiaoNeural (Chinese).")
    ap.add_argument("--rate", default="-25%",
                    help="Speech rate, e.g. -10%%, +20%% (default -25%%, a relaxed pace).")
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8").strip()
    elif args.text:
        text = args.text
    else:
        ap.error("provide a positional text argument or --file")
    if not text:
        print("[error] nothing to speak", file=sys.stderr)
        return 1

    voice = "zh-CN-XiaoxiaoNeural" if args.zh else args.voice

    print(f"[tts] synthesizing ({voice}, {len(text)} chars)...")
    pcm = synth_pcm(text, voice, args.rate)
    print(f"[tts] {len(pcm)} bytes -> {len(pcm)/2/SR:.1f}s of audio")

    ChannelFactoryInitialize(0, args.iface)
    client = AudioClient()
    client.SetTimeout(10.0)
    client.Init()
    client.PlayStop(APP)          # clear any leftover stream from a previous run
    client.SetVolume(args.volume)

    play(client, pcm)
    time.sleep(0.5)
    client.PlayStop(APP)
    print("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
