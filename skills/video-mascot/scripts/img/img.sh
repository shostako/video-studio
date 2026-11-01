#!/usr/bin/env bash
# img.sh — ChatGPT のサブスク枠（Codex CLI 組み込みの image_gen）で画像を1枚作る。
# API キーは使わない。課金は ChatGPT Plus の Codex 枠から出る。
# vm poses・vm hands が絵を描くときの既定の道具。別の道具に替えるときは、同じ引数と終了コードの
# コマンドを環境変数 VM_IMG_CMD に書く（references/new-character.md）。
#
# 使い方:
#   img.sh -p "プロンプト" [-o 出力パス | -n 名前] [-r 参照画像]... [--force]
#
#   -p, --prompt  作る画像の説明（必須）
#   -o, --out     出力パス。省略時は ~/Pictures/generated/<日時>[_名前].png
#   -n, --name    既定の保存先を使うときのファイル名の後ろに付ける名前
#   -r, --ref     参照画像（繰り返し可）。編集の元にも、画風の参考にもなる
#   --force       同じ名前があっても上書きする（既定は -v2, -v3 … を付けて別名で置く）
#
# 終了コード:
#   0 成功（標準出力に保存先の絶対パスを1行）
#   2 引数の誤り / codex が無い
#   3 Codex のログイン切れ（codex login をやり直す）
#   4 使用量の上限
#   5 タイムアウト
#   6 画像が出てこなかった（拒否されたか、ツールが使われなかった）
set -uo pipefail

DEFAULT_DIR="$HOME/Pictures/generated"
TIMEOUT_SEC="${IMG_TIMEOUT:-600}"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

PROMPT=""; OUT=""; NAME=""; FORCE=0; EXPLICIT=0; REFS=()
while [ $# -gt 0 ]; do
  case "$1" in
    -p|--prompt) PROMPT="${2-}"; shift 2 || { usage >&2; exit 2; } ;;
    -o|--out)    OUT="${2-}";    shift 2 || { usage >&2; exit 2; } ;;
    -n|--name)   NAME="${2-}";   shift 2 || { usage >&2; exit 2; } ;;
    -r|--ref)    REFS+=("${2-}"); shift 2 || { usage >&2; exit 2; } ;;
    --force)     FORCE=1; shift ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "ERROR: 知らない引数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$PROMPT" ] || { echo "ERROR: -p（プロンプト）が要る" >&2; exit 2; }
command -v codex >/dev/null 2>&1 || { echo "ERROR: codex CLI が見つからない" >&2; exit 2; }
for r in ${REFS[@]+"${REFS[@]}"}; do
  [ -f "$r" ] || { echo "ERROR: 参照画像が無い: $r" >&2; exit 2; }
done

# 保存先を決める
if [ -n "$OUT" ]; then EXPLICIT=1; fi
if [ -z "$OUT" ]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  safe_name="$(printf '%s' "$NAME" | tr '/\\:*?"<>| ' '__________')"
  OUT="$DEFAULT_DIR/${stamp}${safe_name:+_$safe_name}.png"
fi
mkdir -p "$(dirname "$OUT")" || { echo "ERROR: 保存先のフォルダを作れない: $(dirname "$OUT")" >&2; exit 2; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/img.XXXXXX")"
LOG="$WORK/codex.log"
touch "$WORK/.marker"

REF_ARGS=()
for r in ${REFS[@]+"${REFS[@]}"}; do REF_ARGS+=(-i "$r"); done
REF_NOTE=""
if [ ${#REF_ARGS[@]} -gt 0 ]; then
  REF_NOTE="添付画像は、指示が編集なら編集の元として、そうでなければ構図や画風の参考として使って。"
fi

INSTR="imagegen スキルの組み込み image_gen ツールで画像を1枚だけ生成して。CLI フォールバックや API キーを使う経路は使わないで。${REF_NOTE}
内容: ${PROMPT}
生成したら最終画像を作業ディレクトリの out.png にコピーして、元ファイルの絶対パスだけを1行で返して。"

# プロンプトは -i より前に置く（-i は複数値を取るので、後ろに置くとプロンプトが画像扱いされる）
timeout "$TIMEOUT_SEC" codex exec --skip-git-repo-check --sandbox workspace-write \
  -C "$WORK" -o "$WORK/last.txt" "$INSTR" ${REF_ARGS[@]+"${REF_ARGS[@]}"} \
  < /dev/null > "$LOG" 2>&1
rc=$?

fail() { echo "$1" >&2; echo "ログ: $LOG" >&2; exit "$2"; }

# 出来た画像を探す: out.png → 最終メッセージのパス → marker 以降の最新ファイル
# 画像が出ていれば、ログに別件のエラー（Codex 側の MCP の認証切れ等）があっても成功とみなす
SRC=""
if [ -s "$WORK/out.png" ]; then
  SRC="$WORK/out.png"
fi
if [ -z "$SRC" ] && [ -s "$WORK/last.txt" ]; then
  cand="$(grep -oE '/[^[:space:]]+\.(png|jpg|jpeg|webp)' "$WORK/last.txt" | tail -1)"
  [ -n "$cand" ] && [ -s "$cand" ] && SRC="$cand"
fi
# 最後の手段は、この回の Codex セッションの置き場（generated_images/<session id>/）に限る。
# 置き場全体の最新を拾うと、並列で動いている別の回の絵を自分の成果として返してしまう
# （2026-10-12、上限で描けなかった回が隣の回の絵を拾い、同じ絵が2つの名前で保存された）
if [ -z "$SRC" ]; then
  SID="$(grep -m1 -oE 'session id: [0-9a-f-]+' "$LOG" | awk '{print $3}')"
  if [ -n "$SID" ] && [ -d "$CODEX_HOME_DIR/generated_images/$SID" ]; then
    SRC="$(find "$CODEX_HOME_DIR/generated_images/$SID" -type f \( -name '*.png' -o -name '*.jpg' -o -name '*.webp' \) \
            -newer "$WORK/.marker" -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"
  fi
fi
if [ -z "$SRC" ]; then
  [ $rc -eq 124 ] && fail "ERROR(timeout): ${TIMEOUT_SEC} 秒で終わらなかった" 5
  # ログにはプロンプト本文も載るので、エラー行だけを見て判定する
  errs="$(grep -E '^ERROR|Z +ERROR ' "$LOG")"
  if printf '%s' "$errs" | grep -qE 'access token could not be refreshed|responses_websocket.*401|backend-api.*401'; then
    fail "ERROR(auth): Codex のログインが切れてる。別のペインで codex login をやり直す" 3
  fi
  if printf '%s' "$errs" | grep -qiE 'HTTP 429|429 Too Many|usage limit|rate limit'; then
    fail "ERROR(limit): Codex の使用量の上限に当たった" 4
  fi
  msg="$(cat "$WORK/last.txt" 2>/dev/null)"
  fail "ERROR(no-image): 画像が出てこなかった。Codex の最後の返事: ${msg:-（なし）}" 6
fi

# 中身の形式を先頭のバイトで見る（file コマンドは最小の環境に無いことがある）
magic="$(head -c 12 "$SRC" | od -An -tx1 | tr -d ' \n')"
case "$magic" in
  89504e470d0a1a0a*)      ext=png ;;
  ffd8ff*)                ext=jpg ;;
  52494646????????57454250*) ext=webp ;;
  *) fail "ERROR(no-image): 画像ではないファイルが出てきた: $SRC" 6 ;;
esac
# -o で頼まれたパスは変えない（呼び出し側はそのパスを見る）。形式が違えば ffmpeg で変換する。
# -o が無いときは中身の形式に拡張子をそろえる
want="$ext"
if [ "$EXPLICIT" -eq 1 ]; then
  req="$(printf '%s' "${OUT##*.}" | tr '[:upper:]' '[:lower:]')"
  case "$req" in png|webp) want="$req" ;; jpg|jpeg) want="jpg" ;; *) fail "ERROR: -o の拡張子は png・jpg・webp のどれか: $OUT" 2 ;; esac
else
  OUT="${OUT%.*}.$ext"
fi

# 上書きしない（--force の時だけ上書き）
if [ -e "$OUT" ] && [ "$FORCE" -eq 0 ]; then
  base="${OUT%.*}"; oext="${OUT##*.}"; i=2
  while [ -e "${base}-v${i}.${oext}" ]; do i=$((i+1)); done
  OUT="${base}-v${i}.${oext}"
fi

# 同じフォルダに一時名で書いてから rename する（途中で落ちても壊れたファイルを残さない）
tmp="$(dirname "$OUT")/.img-tmp-$$.$want"
if [ "$want" = "$ext" ]; then
  cp "$SRC" "$tmp"
else
  ffmpeg -y -loglevel error -i "$SRC" -frames:v 1 -update 1 "$tmp" >> "$LOG" 2>&1
fi && mv -f "$tmp" "$OUT" || { rm -f "$tmp"; fail "ERROR: 保存に失敗した: $OUT" 2; }

rm -rf "$WORK"
echo "$OUT"
