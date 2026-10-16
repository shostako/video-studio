#!/usr/bin/env bash
# setup.sh — video-mascot の道具一式を入れる（機体ごとに初回だけ。何度実行してもよい）
#   setup.sh          足りないものを入れる
#   setup.sh --check  確かめるだけ（入れない）。足りなければ終了コード 1
# 要るもの: video-scene の setup（Python の道具・ffmpeg）、Irodori-TTS（声）、/img スキル（絵）。pykakasi を video-scene の Python に足す。
set -uo pipefail
VS_HOME="${VIDEO_SCENE_HOME:-$HOME/.local/share/video-scene}"; PY="$VS_HOME/venv/bin/python"
IRO="${IRODORI_DIR:-$HOME/.local/share/voice-engines/Irodori-TTS}"
CHECK=0; [ "${1-}" = "--check" ] && CHECK=1; ok=1; say() { printf '%s\n' "$*"; }
if [ -x "$PY" ] && "$PY" -c "import cv2, numpy, faster_whisper" 2>/dev/null; then say "ok   video-scene の Python"
else say "NG   video-scene の Python が無い（~/.claude/skills/video-scene/scripts/setup.sh を先に）"; ok=0; fi
if [ -x "$PY" ] && "$PY" -c "import pykakasi" 2>/dev/null; then say "ok   pykakasi"
elif [ $CHECK -eq 1 ]; then say "NG   pykakasi が無い"; ok=0
else say "..   pykakasi を入れる"; "$PY" -m pip install -q pykakasi && say "ok   pykakasi" || { say "NG   pykakasi を入れられない"; ok=0; }; fi
for t in ffmpeg ffprobe uv git; do command -v "$t" >/dev/null 2>&1 && say "ok   $t" || { say "NG   $t が無い"; ok=0; }; done
ENC="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
if printf "%s" "$ENC" | grep -q libvpx-vp9; then say "ok   ffmpeg libvpx-vp9（透明つき動画）"; else say "NG   ffmpeg に libvpx-vp9 が無い"; ok=0; fi
if [ -d "$IRO" ] && (cd "$IRO" && uv run --no-sync python -c "import torch" 2>/dev/null); then say "ok   Irodori-TTS ($IRO)"
elif [ $CHECK -eq 1 ]; then say "NG   Irodori-TTS が無い（$IRO）"; ok=0
else
  say "..   Irodori-TTS を入れる（git clone と uv sync。数GB。モデルは初回の声の生成で落ちる）"
  mkdir -p "$(dirname "$IRO")"
  [ -d "$IRO" ] || git clone --depth 1 https://github.com/Aratako/Irodori-TTS.git "$IRO" || { say "NG   clone に失敗"; exit 1; }
  (cd "$IRO" && uv sync --extra cu128) && say "ok   Irodori-TTS" || { say "NG   uv sync に失敗（GPU が無ければ --extra cpu）"; ok=0; }
fi
[ -x "$HOME/.claude/skills/img/scripts/img.sh" ] && say "ok   img スキル（ChatGPT の枠で絵を描く）" || { say "NG   img スキルが無い"; ok=0; }
# /img は codex（node）で動く。WSL で Windows 側の codex・node（/mnt/c/...）を拾うと、絵を出さずに落ちる（bash -lc で PATH の順が変わる時など）
for t in codex node; do
  p_="$(command -v "$t" 2>/dev/null || true)"
  case "$p_" in
    "") say "NG   $t が無い（/img が動かない）"; ok=0 ;;
    /mnt/*) say "NG   $t が Windows 側を指している（$p_）。WSL の node（nvm など）の bin を PATH の先頭に足す"; ok=0 ;;
    *) say "ok   $t ($p_)" ;;
  esac
done
[ $ok -eq 1 ] && say "全部そろっている" || say "足りないものがある"; [ $ok -eq 1 ]
