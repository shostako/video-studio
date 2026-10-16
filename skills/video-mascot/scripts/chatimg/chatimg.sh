#!/usr/bin/env bash
# chatimg.sh — ChatGPT の通常 Chat 画面（ブラウザ）で画像を1枚描く。/img（img.sh）と同じ引数・終了コード。
# Codex の枠を使わない代わりに、Chat 側の画像の上限に当たる。規約上グレーなので、自分の作業用に低頻度で使う。
#
# 使い方:
#   chatimg.sh -p "プロンプト" -o 出力パス [-r 参照画像]...
#
# 終了コード（img.sh と同じ意味）:
#   0 成功（標準出力に保存先の絶対パスを1行）
#   2 引数の誤り / node・依存が無い
#   3 ログイン切れ（login.mjs で専用プロファイルにログインし直す）
#   4 使用量の上限（Chat 側の上限の表示を見つけた）
#   5 タイムアウト
#   1 その他
#
# 動かし方は skills/video-mascot/references/chatgpt-chat.md。WSL から呼ぶと Windows 側の node.exe と Chrome を使う。
set -uo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
TIMEOUT_SEC="${CHATIMG_TIMEOUT:-420}"

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

PROMPT=""; OUT=""; REFS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -p|--prompt) PROMPT="${2-}"; shift 2 || { usage >&2; exit 2; } ;;
    -o|--out)    OUT="${2-}";    shift 2 || { usage >&2; exit 2; } ;;
    -r|--ref)    REFS+=("${2-}"); shift 2 || { usage >&2; exit 2; } ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "ERROR: 知らない引数: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$PROMPT" ] || { echo "ERROR: -p（プロンプト）が要る" >&2; exit 2; }
[ -n "$OUT" ] || { echo "ERROR: -o（出力パス）が要る" >&2; exit 2; }
for r in ${REFS[@]+"${REFS[@]}"}; do
  [ -f "$r" ] || { echo "ERROR: 参照画像が無い: $r" >&2; exit 2; }
done
[ -d "$DIR/node_modules/playwright-core" ] || { echo "ERROR: 依存が無い。cd $DIR && npm install" >&2; exit 2; }
mkdir -p "$(dirname "$OUT")" || { echo "ERROR: 保存先のフォルダを作れない" >&2; exit 2; }
OUT_ABS="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

# WSL なら Windows 側の node.exe（Chrome とログインしたプロファイルは Windows 側にある）にパスを渡す
if grep -qi microsoft /proc/version 2>/dev/null; then
  NODE="${CHATIMG_NODE:-node.exe}"
  winpath() { wslpath -w "$1"; }
  winout() { printf '%s\\%s' "$(wslpath -w "$(dirname "$1")")" "$(basename "$1")"; }
else
  NODE="${CHATIMG_NODE:-node}"
  winpath() { printf '%s' "$1"; }
  winout() { printf '%s' "$1"; }
fi
command -v "$NODE" >/dev/null 2>&1 || { echo "ERROR: $NODE が見つからない" >&2; exit 2; }

ARGS=(--prompt "$PROMPT" --out "$(winout "$OUT_ABS")" --timeout "$TIMEOUT_SEC" --minimized)
for r in ${REFS[@]+"${REFS[@]}"}; do ARGS+=(--ref "$(winpath "$(cd "$(dirname "$r")" && pwd)/$(basename "$r")")"); done

# 画面は1枚ずつしか扱えないので、同時に呼ばれても順に通す。
# 待つ時間と描く時間には上限を付ける（既定 180 + 420 + 60 秒。vm poses は1回の呼び出しを 700 秒で打ち切る）
LOCK="${TMPDIR:-/tmp}/chatimg.lock"
LOCK_WAIT="${CHATIMG_LOCK_WAIT:-180}"
exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
  flock -w "$LOCK_WAIT" 9 || { echo "ERROR: 別の chatimg が ${LOCK_WAIT} 秒たっても終わらない" >&2; exit 1; }
fi
HARD=()
command -v timeout >/dev/null 2>&1 && HARD=(timeout -k 10 "$((TIMEOUT_SEC + 60))")

LOG="$(${HARD[@]+"${HARD[@]}"} "$NODE" "$(winpath "$DIR/generate.mjs")" "${ARGS[@]}" 2>&1)"; rc=$?
[ "$rc" -eq 124 ] && rc=5   # timeout に打ち切られたらタイムアウト扱い
if [ "$rc" -eq 0 ] && [ -f "$OUT_ABS" ]; then echo "$OUT_ABS"; exit 0; fi
echo "$LOG" | tail -5 >&2
case "$rc" in 2|3|4|5) exit "$rc" ;; 0) exit 1 ;; *) exit 1 ;; esac
