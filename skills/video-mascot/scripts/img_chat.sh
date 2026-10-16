#!/usr/bin/env bash
# img_chat.sh — /img（img.sh）と同じ使い方で、ChatGPT の通常の Chat 画面（chatgpt.com）に絵を1枚描かせる。Codex の枠は使わない。
# WSL から Windows 側の Python（Playwright 入りの専用 venv）で chat_img.py を動かす。手順は references/chat-img.md。
#
# 使い方:
#   img_chat.sh -p "プロンプト" -o 出力パス [-r 参照画像]...
#
# 要るもの: 環境変数 VM_CHAT_IMG_PY（Windows 側の venv の python.exe。WSL から見たパス、例 /mnt/c/Users/<名前>/.local/share/video-scene/chatimg-venv/Scripts/python.exe）
# 終了コードは img.sh と同じ: 0 成功（標準出力に保存先を1行） / 2 引数の誤り・道具が無い / 3 ログインしていない / 4 上限 / 5 タイムアウト / 6 画像が出ない
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${VM_CHAT_IMG_PY:-}"
[ -n "$PY" ] && [ -x "$PY" ] || { echo "ERROR: VM_CHAT_IMG_PY（Windows 側の venv の python.exe）が無い: ${PY:-未設定}" >&2; exit 2; }
command -v wslpath >/dev/null 2>&1 || { echo "ERROR: wslpath が無い（WSL の中で動かす）" >&2; exit 2; }

PROMPT=""; OUT=""; REFS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -p|--prompt) PROMPT="${2-}"; shift 2 || exit 2 ;;
    -o|--out)    OUT="${2-}";    shift 2 || exit 2 ;;
    -r|--ref)    REFS+=("${2-}"); shift 2 || exit 2 ;;
    -h|--help)   sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ERROR: 知らない引数: $1" >&2; exit 2 ;;
  esac
done
[ -n "$PROMPT" ] && [ -n "$OUT" ] || { echo "ERROR: -p と -o が要る" >&2; exit 2; }
mkdir -p "$(dirname "$OUT")" || exit 2
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

ARGS=(gen -p "$PROMPT" -o "$(wslpath -w "$OUT")")
for r in ${REFS[@]+"${REFS[@]}"}; do
  [ -f "$r" ] || { echo "ERROR: 参照画像が無い: $r" >&2; exit 2; }
  ARGS+=(-r "$(wslpath -w "$(cd "$(dirname "$r")" && pwd)/$(basename "$r")")")
done

# Windows の Python に UTF-8 で話させる（既定のコードページだと日本語のエラーが化ける）
PYTHONIOENCODING=utf-8 WSLENV="${WSLENV:+$WSLENV:}PYTHONIOENCODING" "$PY" "$(wslpath -w "$DIR/chat_img.py")" "${ARGS[@]}" >/dev/null
rc=$?
[ $rc -eq 0 ] && [ -s "$OUT" ] && { echo "$OUT"; exit 0; }
[ $rc -eq 0 ] && { echo "ERROR(no-image): 保存先に絵が無い: $OUT" >&2; exit 6; }
exit $rc
