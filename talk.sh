#!/usr/bin/env bash
# One-command launcher for G1 voice chat. Sources the API keys, unmutes the mic,
# then runs chat.py.
# Usage:
#   ./talk.sh                      # push-to-talk, Chinese STT (press Enter to talk)
#   ./talk.sh --conversation       # hands-free continuous conversation
#   ./talk.sh --lang en            # English STT
#   ./talk.sh --stt openai         # cloud Whisper (better Chinese, costs + needs net)
#   ./talk.sh --seconds 8          # longer recording window (push-to-talk mode)
# Any chat.py flag passes straight through.
set -a
source "$HOME/.unitree_g1.env"
set +a
# The DJI mic's capture switch defaults to muted. Find its card by NAME (the card
# number is not stable across replug) and turn capture on.
CARD=$(arecord -l 2>/dev/null | grep -iE 'DJI|MINI|USB Audio' | grep -oE 'card [0-9]+' | grep -oE '[0-9]+' | head -1)
[ -n "$CARD" ] && amixer -c "$CARD" sset 'Mic' cap >/dev/null 2>&1
cd "$HOME/projects/g1_speak"
exec python3 chat.py "$@"   # chat.py auto-detects the mic device by name
