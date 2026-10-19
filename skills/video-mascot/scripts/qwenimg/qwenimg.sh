#!/usr/bin/env bash
# qwenimg.sh — 手元の ComfyUI の Qwen-Image-Edit-2511 で参照画像を描き変えて1枚作る。/img（img.sh）と同じ引数・終了コード。中身は qwenimg.py
set -uo pipefail
VS_HOME="${VIDEO_SCENE_HOME:-$HOME/.local/share/video-scene}"
PY="$VS_HOME/venv/bin/python"
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
[ -x "$PY" ] || { echo "ERROR: 道具が入ってない（video-scene の setup.sh）" >&2; exit 2; }
exec "$PY" -B "$DIR/qwenimg.py" "$@"
