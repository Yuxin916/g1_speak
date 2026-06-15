#!/usr/bin/env bash
# One-command launcher for G1 voice chat. Sources the API keys, then runs chat.py.
# Usage:
#   ./talk.sh                 # Chinese STT (default)
#   ./talk.sh --lang en       # English STT
#   ./talk.sh --stt openai    # cloud Whisper (better Chinese, costs+needs net)
#   ./talk.sh --seconds 8     # longer recording window per turn
# Any chat.py flag passes straight through.
set -a
source "$HOME/.unitree_g1.env"
set +a
# Make sure the DJI mic capture switch is on (it defaults muted on this card).
amixer -c 2 sset 'Mic' cap >/dev/null 2>&1 || true
cd "$HOME/projects/g1_speak"
exec python3 chat.py --mic plughw:2,0 "$@"
