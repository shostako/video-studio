#!/usr/bin/env bash
# setup.sh — video-scene の道具一式を入れる（機体ごとに初回だけ。何度実行してもよい）
#   setup.sh          足りないものを入れる
#   setup.sh --check  確かめるだけ（入れない）。足りなければ終了コード 1
set -uo pipefail

VS_HOME="${VIDEO_SCENE_HOME:-$HOME/.local/share/video-scene}"
VENV="$VS_HOME/venv"
HF_VER="0.8.146"
PY_PKGS=(opencv-python-headless numpy pillow google-genai faster-whisper)
CHECK=0; [ "${1-}" = "--check" ] && CHECK=1
ok=1
say() { printf '%s\n' "$*"; }

# Node 22 以上（HyperFrames の要件）
if command -v node >/dev/null 2>&1; then
  major="$(node -p 'process.versions.node.split(".")[0]')"
  if [ "$major" -ge 22 ]; then say "ok   node $(node --version)"; else say "NG   node $(node --version)（22 以上が要る）"; ok=0; fi
else say "NG   node が無い（22 以上を入れる）"; ok=0; fi

for t in ffmpeg ffprobe python3; do
  if command -v "$t" >/dev/null 2>&1; then say "ok   $t"; else say "NG   $t が無い"; ok=0; fi
done

# Python の道具（同期しない場所に置く）
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import cv2, numpy, PIL, google.genai, faster_whisper" 2>/dev/null; then
  say "ok   python venv ($VENV)"
elif [ $CHECK -eq 1 ]; then
  say "NG   python venv が無いか不完全 ($VENV)"; ok=0
else
  say "..   python venv を作る ($VENV)"
  mkdir -p "$VS_HOME"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV" || { say "NG   venv を作れない"; exit 1; }
  "$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  "$VENV/bin/pip" install -q "${PY_PKGS[@]}" || { say "NG   pip install に失敗"; exit 1; }
  say "ok   python venv"
fi

# HyperFrames（版を固定。使い方の統計は送らない。AI 用スキルの自動導入はしない）
export HYPERFRAMES_SKIP_SKILLS=1
if [ $CHECK -eq 0 ]; then
  npx --yes "hyperframes@$HF_VER" telemetry disable >/dev/null 2>&1 && say "ok   hyperframes telemetry 無効"
  npx --yes "hyperframes@$HF_VER" browser ensure >/dev/null 2>&1 && say "ok   hyperframes 用ブラウザ" || { say "NG   hyperframes browser ensure に失敗"; ok=0; }
else
  if npx --yes "hyperframes@$HF_VER" --version >/dev/null 2>&1; then say "ok   hyperframes@$HF_VER"; else say "NG   hyperframes を呼べない"; ok=0; fi
fi

# Gemini の鍵（Veo・解析で使う。値は表示しない）
if "$VENV/bin/python" "$(dirname "$0")/common.py" --check-key 2>/dev/null; then say "ok   Gemini API キー"; else say "--   Gemini API キーが見つからない（veo / analyze / ear の Gemini 部分が使えない）"; fi

# /img（flipbook の素材づくり。ChatGPT のサブスク枠）
if [ -x "$HOME/.claude/skills/img/scripts/img.sh" ] && command -v codex >/dev/null 2>&1; then say "ok   /img（codex）"; else say "--   /img が使えない（flipbook の素材は別途用意）"; fi

# H3（この PC の ComfyUI。入れるのは手作業: references/h3.md の「入れ方」。約 44GB）
CR="${VS_COMFY_ROOT:-/mnt/c/ComfyUI/ComfyUI_windows_portable}"
if [ -x "$CR/python_embeded/python.exe" ] && [ -f "$CR/ComfyUI/models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors" ]; then
  say "ok   H3（ComfyUI: $CR）"
else say "--   H3 が使えない（ComfyUI か重みが無い。references/h3.md の「入れ方」）"; fi

[ $ok -eq 1 ] && { [ $CHECK -eq 0 ] && date -Is > "$VS_HOME/.setup-ok"; exit 0; } || exit 1
