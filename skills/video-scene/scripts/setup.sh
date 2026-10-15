#!/usr/bin/env bash
# setup.sh — video-scene の道具一式を入れる（機体ごとに初回だけ。何度実行してもよい）
#   setup.sh          足りないものを入れる
#   setup.sh --check  確かめるだけ（入れない）。足りなければ終了コード 1
set -uo pipefail

VS_HOME="${VIDEO_SCENE_HOME:-$HOME/.local/share/video-scene}"
VENV="$VS_HOME/venv"
HF_VER="0.8.146"
PY_PKGS=(opencv-python-headless numpy pillow google-genai faster-whisper pykakasi)  # pykakasi は video-mascot が使う（venv を共用するので、作り直しても消えないよう同じ所で入れる）
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
# スクリプトは Python 3.12 の構文（f-string の式の中のバックスラッシュ）を使う。venv も 3.12 以上にする
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import sys, cv2, numpy, PIL, google.genai, faster_whisper; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
  say "ok   python venv ($VENV, $("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])'))"
elif [ $CHECK -eq 1 ]; then
  say "NG   python venv が無いか不完全、または Python 3.12 未満 ($VENV)。setup.sh を引数なしで流すと作り直す"; ok=0
else
  say "..   python venv を作る ($VENV)"
  mkdir -p "$VS_HOME"
  # 3.12 未満の venv は退避して作り直す（戻すときは venv.bak を venv に戻す）
  if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    bak="$VENV.py$("$VENV/bin/python" -c 'import sys; print("%d%d" % sys.version_info[:2])').bak"
    [ -e "$bak" ] && bak="$bak.$(date +%Y%m%d%H%M%S)"
    mv "$VENV" "$bak" && say "..   古い venv を退避した: $bak"
  fi
  if [ ! -x "$VENV/bin/python" ]; then
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      python3 -m venv "$VENV" || { say "NG   venv を作れない"; exit 1; }
    elif command -v uv >/dev/null 2>&1; then
      # システムの Python（apt 管理）には触らない。uv がユーザー領域に持つ 3.12 で作る
      uv venv -q --seed --python 3.12 "$VENV" || { say "NG   uv で 3.12 の venv を作れない"; exit 1; }
    else
      say "NG   Python 3.12 以上が無く、uv も無い（uv を入れる: https://docs.astral.sh/uv/）"; exit 1
    fi
  fi
  "$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  "$VENV/bin/pip" install -q "${PY_PKGS[@]}" || { say "NG   pip install に失敗"; exit 1; }
  say "ok   python venv"
fi

# parselmouth（vs accent の F0 計測。無くても他は動くので、必須の一括インストールには入れずここで足す）
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import parselmouth" 2>/dev/null; then say "ok   parselmouth"
elif [ $CHECK -eq 1 ]; then say "--   parselmouth が無い（vs accent が使えない。setup.sh を引数なしで流すと入る）"
elif [ -x "$VENV/bin/python" ]; then say "..   parselmouth を入れる"; "$VENV/bin/pip" install -q praat-parselmouth && say "ok   parselmouth" || say "--   parselmouth を入れられない（vs accent が使えない）"; fi

# PyYAML（vs terms の用語辞書の読み込み。parselmouth と同じく、必須の一括インストールには入れずここで足す）
if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import yaml" 2>/dev/null; then say "ok   pyyaml"
elif [ $CHECK -eq 1 ]; then say "--   pyyaml が無い（vs terms が使えない。setup.sh を引数なしで流すと入る）"
elif [ -x "$VENV/bin/python" ]; then say "..   pyyaml を入れる"; "$VENV/bin/pip" install -q pyyaml && say "ok   pyyaml" || say "--   pyyaml を入れられない（vs terms が使えない）"; fi

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
