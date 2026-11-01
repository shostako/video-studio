#!/usr/bin/env bash
# このリポの skills/<名前> を ~/.claude/skills/<名前> から symlink（Windows の Git Bash ではジャンクション）で指す。何度実行してもよい。
#   scripts/link-skills.sh           リンクを張る（済んでいれば何もしない）
#   scripts/link-skills.sh --check   確かめるだけ（張っていない・ずれているものがあれば終了コード 1）
# 置き換えてよいのは「リポに無い内容を持たない」ディレクトリだけ（同期で中身が消えた跡、リポと同じ中身）。
# 置き換えたディレクトリは ~/.local/share/video-studio/replaced/<日時>/ に移す（消さない）。
set -uo pipefail

CHECK=0
case "${1:-}" in
  --check) CHECK=1 ;;
  "") ;;
  *) echo "使い方: $0 [--check]" >&2; exit 2 ;;
esac

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
DEST="${VIDEO_STUDIO_SKILLS_DEST:-$HOME/.claude/skills}"
BACKUP="$HOME/.local/share/video-studio/replaced/$(date +%Y%m%d-%H%M%S)"
rc=0
say() { printf '%s\n' "$*"; }
# Windows（Git Bash）の ln -s は、既定では中身を写すだけで、リポを更新してもスキルが古いまま残る。
# Windows ではジャンクション（フォルダのリンク。管理者権限も開発者モードも要らない）を張る
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) WIN=1 ;; *) WIN=0 ;; esac
link_dir() {   # link_dir <元> <置く所>
  if [ "$WIN" = 1 ]; then MSYS2_ARG_CONV_EXCL='*' cmd /c mklink /J "$(cygpath -w "$2")" "$(cygpath -w "$1")" >/dev/null
  else ln -s "$1" "$2"; fi
}
ng()  { say "NG   $*"; rc=1; }

# worktree から張ると、worktree を片付けた時にリンクが切れる。本体のチェックアウトから張る
if [ "$(git -C "$REPO" rev-parse --path-format=absolute --git-dir)" != "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)" ]; then
  say "NG   $REPO は worktree。リポ本体（main をチェックアウトしている所）から実行する"
  exit 1
fi
branch="$(git -C "$REPO" branch --show-current)"
[ "$branch" = "main" ] || say "注意 リポ本体が main ではなく「${branch:-detached}」。動くスキルはこのブランチの中身になる"

[ -d "$DEST" ] || { say "NG   リンクを置く場所が無い: $DEST"; exit 1; }
in_git=0; git -C "$DEST" rev-parse --git-dir >/dev/null 2>&1 && in_git=1

for src in "$REPO"/skills/*/; do
  src="${src%/}"; name="$(basename "$src")"; dst="$DEST/$name"
  [ -f "$src/SKILL.md" ] || continue

  # ~/.claude は git-sync が add -A で自動コミットする。外していないとリンクがコミットされる
  # 末尾が / のパターンはディレクトリにしか効かず、symlink に置き換えると外れる
  if [ "$in_git" = 1 ]; then
    if [ -n "$(git -C "$DEST" ls-files -- "$name")" ]; then
      ng "$name: $DEST の git にまだ登録されている。先に git rm -r --cached と .gitignore への追加をする"; continue
    fi
    if ! git -C "$DEST" check-ignore -q -- "$name"; then
      ng "$name: $DEST の .gitignore で外れていない（skills/$name を末尾の / 無しで足す。/ 付きはリンクに効かない）"; continue
    fi
  fi

  if [ -L "$dst" ]; then
    if [ "$(readlink -f "$dst")" = "$src" ]; then say "ok   $name -> $src"
    else ng "$name: 別の所を指すリンク（$(readlink "$dst")）。確かめてから消す"; fi
    continue
  fi
  if [ -e "$dst" ] && [ ! -d "$dst" ]; then ng "$name: ディレクトリでもリンクでもないものがある: $dst"; continue; fi

  if [ -d "$dst" ]; then
    # リポに無い内容（リポに無いファイル、中身の違うファイル）を持っていれば置き換えない
    extra="$(diff -rq -x __pycache__ "$dst" "$src" 2>&1 | grep -vF "Only in $src")"
    if [ -n "$extra" ]; then
      ng "$name: $dst にリポと違う内容がある。リポに取り込むか片付けてから実行する"
      printf '%s\n' "$extra" | head -10 | sed 's/^/       /'
      continue
    fi
    if [ "$CHECK" = 1 ]; then ng "$name: まだディレクトリのまま（実行すれば置き換えられる）"; continue; fi
    mkdir -p "$BACKUP" && mv -- "$dst" "$BACKUP/$name" || { ng "$name: 退避に失敗"; continue; }
    say "退避 $dst -> $BACKUP/$name"
  elif [ "$CHECK" = 1 ]; then
    ng "$name: リンクが無い"; continue
  fi

  tmp="$DEST/.$name.link.$$"
  if link_dir "$src" "$tmp" && mv -T -- "$tmp" "$dst"; then say "張った $name -> $src"
  else rm -f -- "$tmp"; ng "$name: リンクを張れなかった"; fi
done

exit "$rc"
