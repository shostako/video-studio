#!/usr/bin/env python3
"""PR をマージしてよいかの門。ci が緑、かつ Codex のレビューが PR の先頭コミットに対して完了していて、未解決の指摘が無いときだけ 0 を返す。

使い方: python3 scripts/pr_gate.py <PR番号> [--repo shostako/video-studio]
終了コード: 0=マージしてよい / 1=だめ（理由を表示） / 2=まだ待つ（ci か Codex が走行中・未着手）
"""
import json
import re
import subprocess
import sys

MARK = "codex-pull-request-review-summary"
STATE_RE = re.compile(r"<!--\s*codex-review-state:v1\s*(\{.*?\})\s*-->", re.S)


def evaluate(summaries, head_sha, inline_comment_count=0):
    """Codex の要約コメント本文のリスト（古い順）と PR の先頭 SHA から (コード, 理由) を返す。コード 0/1/2 は上の終了コード。"""
    bodies = [b for b in summaries if MARK in b]
    if not bodies:
        return 2, "Codex の要約コメントがまだ無い"
    m = STATE_RE.search(bodies[-1])
    if not m:
        return 2, "Codex の要約に状態（codex-review-state）が無い"
    try:
        cr = json.loads(m.group(1)).get("code_review") or {}
    except json.JSONDecodeError:
        return 1, "Codex の状態が読めない"
    if cr.get("status") != "completed":
        return 2, f"Codex のレビューが終わっていない（status={cr.get('status')}）"
    sha = cr.get("commit_sha") or ""
    if not sha or not head_sha.startswith(sha[:7]) or not sha.startswith(head_sha[:7]):
        return 2, f"Codex のレビューが先頭コミットのものではない（レビュー={sha[:7]}, 先頭={head_sha[:7]}）。再レビューを待つ"
    if cr.get("has_unresolved_findings") is not False:
        return 1, f"Codex の未解決の指摘がある（has_unresolved_findings={cr.get('has_unresolved_findings')}）"
    return 0, "Codex のレビューは先頭コミットに対して完了し、未解決の指摘は無い"


def _gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh 失敗: {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout


def main(argv):
    repo = "shostako/video-studio"
    args = list(argv)
    if "--repo" in args:
        i = args.index("--repo")
        repo = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or not args[0].isdigit():
        print(__doc__)
        return 1
    n = args[0]
    head = _gh("pr", "view", n, "-R", repo, "--json", "headRefOid", "-q", ".headRefOid").strip()
    # ci
    checks = _gh("pr", "checks", n, "-R", repo)
    ci = [ln.split("\t") for ln in checks.splitlines() if ln.split("\t")[0] == "ci"]
    if not ci:
        print("待つ: ci がまだ無い"); return 2
    if ci[0][1] == "pending":
        print("待つ: ci が走行中"); return 2
    if ci[0][1] != "pass":
        print(f"だめ: ci が {ci[0][1]}"); return 1
    bodies = json.loads(_gh("api", f"repos/{repo}/issues/{n}/comments", "--paginate", "--jq", "[.[].body]") or "[]")
    code, why = evaluate(bodies, head)
    print(("OK: " if code == 0 else "待つ: " if code == 2 else "だめ: ") + why)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
