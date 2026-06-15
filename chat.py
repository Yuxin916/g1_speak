#!/usr/bin/env python3
"""Talk WITH the G1: record -> speech-to-text -> LLM -> speak back.

The robot's onboard mic stream is dead (same half-dead `voice` service that makes
TtsMaker silent), so audio input comes from a USB mic on the Jetson — here a
DJI Mic Mini receiver, which shows up as an ALSA USB sound card. Output reuses
speak.py (edge-tts + PlayStream).

Pipeline:
    arecord (DJI mic)  ->  STT  ->  LLM  ->  speak.py
       listen          transcribe  think     speak

STT backends:
    vosk   (default) small offline model (~40 MB), fast and light on CPU. Picked
           over Whisper because this Jetson (Py3.8, ffmpeg 4.2, no Rust) can't
           build the modern Whisper stack. Models in ./models, pick with --lang.
           Loaded ONCE and reused every turn. Chinese small model is a bit rough.
    openai cloud Whisper via the OpenAI API — far better Chinese accuracy, but
           costs per call and needs internet. Uses OPENAI_API_KEY.

LLM backends:
    openai (default) GPT via the OpenAI API. Uses OPENAI_API_KEY.
    anthropic        Claude via the Anthropic API. Uses ANTHROPIC_API_KEY.

Put whichever key(s) you use in ~/.unitree_g1.env and `source` it:
    export OPENAI_API_KEY=sk-...
    export ANTHROPIC_API_KEY=sk-ant-...

Quick tests (no mic needed):
    python3 chat.py --text "你好，你是谁？"      # skip STT, test LLM + speak
    python3 chat.py --audio clip.wav             # test STT on a wav file

Live (DJI mic on card 2 -> plughw:2,0):
    python3 chat.py --mic plughw:2,0 --lang zh
    python3 chat.py --mic plughw:2,0 --lang en
    python3 chat.py --mic plughw:2,0 --stt openai      # cloud STT, better Chinese

Env vars:
    OPENAI_API_KEY      for --llm openai  and/or  --stt openai
    ANTHROPIC_API_KEY   for --llm anthropic
    LLM_MODEL           override model (default gpt-4o-mini / claude-opus-4-8)
    STT_MODEL           override OpenAI STT model (default whisper-1)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"
MODEL_DIRS = {
    "zh": MODELS / "vosk-model-small-cn-0.22",
    "en": MODELS / "vosk-model-small-en-us-0.15",
}
SYSTEM_PROMPT = (
    "You are G1, a friendly Unitree humanoid robot having a spoken conversation. "
    "Reply in the SAME language the person used (Chinese or English). "
    "Keep replies short and conversational — one or two sentences, suitable for "
    "speaking aloud. No markdown, no emoji, no lists."
)


# ---------- listen ----------
def record_wav(path: str, mic: str, seconds: int) -> None:
    print(f"[mic] recording {seconds}s from {mic} ... speak now")
    subprocess.run(["arecord", "-D", mic, "-f", "S16_LE", "-r", "16000",
                    "-c", "1", "-d", str(seconds), path],
                   check=True, stderr=subprocess.DEVNULL)


# ---------- transcribe: Vosk (local) ----------
def load_vosk(lang: str) -> dict:
    """Return {lang: Model}. lang 'both' loads zh+en; else just that one."""
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)
    langs = ["zh", "en"] if lang == "both" else [lang]
    models = {}
    for la in langs:
        d = MODEL_DIRS[la]
        if not d.is_dir():
            sys.exit(f"[error] missing Vosk model for '{la}': {d}\n"
                     f"        download it into {MODELS}/")
        print(f"[stt] loading vosk model '{la}' ...")
        models[la] = Model(str(d))
    return models


def _vosk_one(model, wav: str) -> tuple:
    """Return (text, confidence). confidence = mean per-word conf, 0 if empty."""
    from vosk import KaldiRecognizer
    w = wave.open(wav, "rb")
    rec = KaldiRecognizer(model, w.getframerate())
    rec.SetWords(True)
    words = []
    texts = []

    def absorb(res: dict) -> None:
        if res.get("text"):
            texts.append(res["text"])
        words.extend(res.get("result", []))

    while True:
        data = w.readframes(4000)
        if not data:
            break
        if rec.AcceptWaveform(data):
            absorb(json.loads(rec.Result()))
    absorb(json.loads(rec.FinalResult()))
    text = " ".join(texts).strip()
    conf = sum(x.get("conf", 0.0) for x in words) / len(words) if words else 0.0
    return text, conf


def transcribe_vosk(models: dict, wav: str) -> str:
    """One model -> its text. Multiple -> highest mean word confidence."""
    scored = {la: _vosk_one(m, wav) for la, m in models.items()}
    best_lang = max(scored, key=lambda la: scored[la][1], default=None)
    if best_lang is None:
        return ""
    if len(models) > 1:
        print("[stt] " + "  ".join(f"{la}:{scored[la][1]:.2f}" for la in scored)
              + f"  -> chose {best_lang}")
    return scored[best_lang][0].strip()


# ---------- transcribe: OpenAI Whisper (cloud) ----------
def transcribe_openai(wav: str) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("[error] OPENAI_API_KEY not set (needed for --stt openai).")
    base = os.environ.get("STT_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("STT_MODEL", "whisper-1")
    boundary = "----g1chatboundary"
    body = bytearray()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{model}\r\n".encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"a.wav\"\r\n").encode()
    body += b"Content-Type: audio/wav\r\n\r\n" + Path(wav).read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{base}/audio/transcriptions", data=bytes(body),
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["text"].strip()


# ---------- think ----------
def llm_openai(history: list) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("[error] OPENAI_API_KEY not set (put it in ~/.unitree_g1.env "
                 "and `source` it, or export it).")
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    payload = {"model": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
               "max_tokens": 200,
               "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + history}
    req = urllib.request.Request(f"{base}/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def llm_anthropic(history: list) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("[error] ANTHROPIC_API_KEY not set (needed for --llm anthropic).")
    payload = {"model": os.environ.get("LLM_MODEL", "claude-opus-4-8"),
               "max_tokens": 200, "system": SYSTEM_PROMPT, "messages": history}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                                 data=json.dumps(payload).encode(),
                                 headers={"x-api-key": key,
                                          "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    return "".join(b["text"] for b in body["content"]
                   if b.get("type") == "text").strip()


def think(history: list, backend: str) -> str:
    return llm_anthropic(history) if backend == "anthropic" else llm_openai(history)


# ---------- speak (auto-pick voice by reply language) ----------
def has_cjk(s: str) -> bool:
    return any("一" <= c <= "鿿" for c in s)


def speak(text: str, iface: str) -> None:
    cmd = [sys.executable, str(HERE / "speak.py"), text, "--iface", iface]
    if has_cjk(text):
        cmd.append("--zh")
    subprocess.run(cmd, check=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice conversation with the G1.")
    ap.add_argument("--text", help="Skip mic+STT, send this text straight to the LLM.")
    ap.add_argument("--audio", help="Skip the mic, transcribe this wav file.")
    ap.add_argument("--mic", default="plughw:2,0", help="arecord device (default DJI mic plughw:2,0).")
    ap.add_argument("--seconds", type=int, default=6, help="Seconds to record per turn.")
    ap.add_argument("--stt", choices=["vosk", "openai"], default="vosk",
                    help="STT backend (default vosk, local/offline/low-CPU).")
    ap.add_argument("--lang", choices=["zh", "en", "both"], default="zh",
                    help="Vosk language model(s). 'both' tries each, keeps the better.")
    ap.add_argument("--llm", choices=["openai", "anthropic"], default="openai",
                    help="LLM backend (default openai).")
    ap.add_argument("--iface", default="eth0", help="NIC to the robot DDS.")
    ap.add_argument("--once", action="store_true", help="One turn then exit.")
    args = ap.parse_args()

    history: list = []

    def one_turn(user_text: str) -> None:
        print(f"[you] {user_text}")
        history.append({"role": "user", "content": user_text})
        reply = think(history, args.llm)
        history.append({"role": "assistant", "content": reply})
        print(f"[g1]  {reply}")
        speak(reply, args.iface)

    # Text-only test path: no STT needed.
    if args.text:
        one_turn(args.text)
        return 0

    # Load Vosk only if we'll actually use it.
    models = load_vosk(args.lang) if args.stt == "vosk" else None

    def stt(wav: str) -> str:
        return transcribe_vosk(models, wav) if args.stt == "vosk" else transcribe_openai(wav)

    if args.audio:
        one_turn(stt(args.audio))
        return 0

    print("Press Enter to talk, Ctrl-C to quit.")
    wav = "/tmp/g1_chat_in.wav"
    try:
        while True:
            input()
            record_wav(wav, args.mic, args.seconds)
            t0 = time.time()
            text = stt(wav)
            print(f"[stt] {time.time()-t0:.1f}s")
            if not text:
                print("[stt] (heard nothing)")
                continue
            one_turn(text)
            if args.once:
                break
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
