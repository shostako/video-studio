#!/usr/bin/env bash
# PR ごとの検査。.github/workflows/ci.yml の ci ジョブがこれを呼ぶ。
# 検査を増やすときはこのファイルか requirements-ci.txt を書き換える。ワークフローの YAML は触らない。
# GPU・Irodori・Gemini の鍵・/img を使う処理はここでは動かさない（テストは純関数と、ffmpeg・OpenCV で済む範囲）。
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install -q -r requirements-ci.txt

# 構文: 全スクリプトが読めること
python3 -m compileall -q skills scripts research tests
# 拡張子が .sh のものに加えて、拡張子なしの起動スクリプト（vm / vs）も、先頭行が bash なら検査する
git ls-files -z | while IFS= read -r -d '' f; do
  [ -f "$f" ] && [ ! -L "$f" ] || continue
  case "$f" in
    *.sh) bash -n "$f" ;;
    *.*) ;;
    *) if head -c 64 "$f" | head -1 | grep -qE '^#!.*\b(ba)?sh\b'; then bash -n "$f"; fi ;;
  esac
done

# テスト
python3 -m pytest -q tests
echo "ci: ok"
