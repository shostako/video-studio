#!/usr/bin/env python3
"""PR をマージしてよいかの門。ci が緑、かつ Codex のレビューが PR の先頭コミットに対して完了していて、未解決の指摘が無いときだけ 0 を返す。

使い方: python3 scripts/pr_gate.py <PR番号> [--repo shostako/video-studio]
終了コード: 0=マージしてよい（判定した先頭 SHA を表示。マージは `--match-head-commit <SHA>` で縛る） / 1=だめ（理由を表示） / 2=まだ待つ（ci か Codex が走行中・未着手・通信失敗）
"""
import json
import re
import subprocess
import sys

MARK = "codex-pull-request-review-summary"
STATE_RE = re.compile(r"<!--\s*codex-review-state:v1\s*(\{.*?\})\s*-->", re.S)
# 指摘が無いとき、Codex は要約の状態を running のまま、別のコメントで結果を返すことがある（2026-11-01 の #70）
CLEAN_RE = re.compile(r"Codex Review:\s*Didn't find any major issues", re.I)
REVIEWED_RE = re.compile(r"Reviewed commit:\**\s*`([0-9a-fA-F]{7,40})`")


def codex_summaries(comments):
    """PR のコメント（GitHub API の形）から、Codex の bot が書いた要約の本文だけを古い順に取り出す。
    公開リポでは誰でもコメントできる。マーカーを真似た偽の要約で門を通さないよう、書いた人を見る。"""
    out = []
    for c in comments:
        u = c.get("user") or {}
        if u.get("type") == "Bot" and "codex" in (u.get("login") or "").lower():
            out.append(c.get("body") or "")
    return out


def flatten_pages(pages):
    """`gh api --paginate --slurp` の出力（ページごとの配列の配列）を1本の配列にする。"""
    return [c for page in pages for c in (page if isinstance(page, list) else [page])]


def evaluate(summaries, head_sha, unresolved_threads=0):
    """Codex の要約コメント本文のリスト（古い順）、PR の先頭 SHA、未解決のレビュースレッド数から (コード, 理由) を返す。

    要約の has_unresolved_findings は「レビューしたときの写し」で、指摘を直してスレッドを解決しても更新されない。
    そのため、未解決かどうかは GitHub 上のスレッドの解決状態（unresolved_threads）で見る。要約からは
    「先頭コミットに対して完了したレビューがあること」だけを使う。"""
    bodies = [b for b in summaries if MARK in b]
    if not bodies:
        return 2, "Codex の要約コメントがまだ無い"
    last = max(i for i, b in enumerate(summaries) if MARK in b)
    later = summaries[last + 1:]                     # 最後の要約より後の、Codex のボットのほかのコメント
    m = STATE_RE.search(bodies[-1])
    if not m:
        return 2, "Codex の要約に状態（codex-review-state）が無い"
    try:
        cr = json.loads(m.group(1)).get("code_review") or {}
    except json.JSONDecodeError:
        return 1, "Codex の状態が読めない"
    if cr.get("status") == "running" and (cr.get("commit_sha") or "").lower() == head_sha.lower():
        # 要約が先頭コミット（SHA の全体）を running と書いたまま、その後に「大きな問題は見つからない」と、先頭の接頭辞の
        # 「Reviewed commit」を返していれば、完了とみなす（指摘があればスレッドが残るので下で止まる）
        for b in later:
            r = REVIEWED_RE.search(b)
            if CLEAN_RE.search(b) and r and head_sha.lower().startswith(r.group(1).lower()):
                if unresolved_threads > 0:
                    return 1, f"未解決のレビュースレッドが {unresolved_threads} 件ある。直して返信し、解決済みにする"
                return 0, "Codex のレビューは先頭コミットに対して完了し（要約は running のまま、結果は別のコメントで「指摘なし」）、未解決のスレッドは無い"
    if cr.get("status") != "completed":
        return 2, f"Codex のレビューが終わっていない（status={cr.get('status')}）"
    sha = cr.get("commit_sha") or ""
    if not sha or sha.lower() != head_sha.lower():  # 接頭辞でなく SHA の全体を比べる（短い接頭辞を揃えた別のコミットで通さない）
        return 2, f"Codex のレビューが先頭コミットのものではない（レビュー={sha[:7]}, 先頭={head_sha[:7]}）。`@codex review` で再レビューを頼む"
    if unresolved_threads > 0:
        return 1, f"未解決のレビュースレッドが {unresolved_threads} 件ある。直して返信し、解決済みにする"
    return 0, "Codex のレビューは先頭コミットに対して完了し、未解決のスレッドは無い"


class GhError(Exception):
    """gh の呼び出しが失敗した（通信の瞬断など）。「だめ」ではなく「待つ」として扱う。"""


def _gh(*args, ok_codes=(0,)):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode not in ok_codes:
        raise GhError(f"gh 失敗: {' '.join(args)}: {r.stderr.strip()[:200]}")
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
    # gh pr checks は、走行中だと 8、失敗があると 1 を返す。どちらも出力は読めるので、出力で判断する
    checks = _gh("pr", "checks", n, "-R", repo, ok_codes=(0, 1, 8))
    ci = [ln.split("\t") for ln in checks.splitlines() if ln.split("\t")[0] == "ci"]
    if not ci:
        print("待つ: ci がまだ無い"); return 2
    if ci[0][1] == "pending":
        print("待つ: ci が走行中"); return 2
    if ci[0][1] != "pass":
        print(f"だめ: ci が {ci[0][1]}"); return 1
    pages = json.loads(_gh("api", f"repos/{repo}/issues/{n}/comments", "--paginate", "--slurp") or "[]")
    owner, name = repo.split("/")
    q = ("query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){"
         "reviewThreads(first:100){pageInfo{hasNextPage} nodes{isResolved}}}}}")
    th = json.loads(_gh("api", "graphql", "-f", f"query={q}", "-F", f"o={owner}", "-F", f"n={name}", "-F", f"p={n}"))
    rt = th["data"]["repository"]["pullRequest"]["reviewThreads"]
    if rt["pageInfo"]["hasNextPage"]:
        print("だめ: レビュースレッドが100件を超えている。人が見る"); return 1
    unresolved = sum(1 for x in rt["nodes"] if not x["isResolved"])
    code, why = evaluate(codex_summaries(flatten_pages(pages)), head, unresolved)
    if code == 0:
        # 判定している間に push が入っていないことを確かめ、判定した SHA を出す（マージはこの SHA に縛る）
        now = _gh("pr", "view", n, "-R", repo, "--json", "headRefOid", "-q", ".headRefOid").strip()
        if now != head:
            print(f"待つ: 判定の途中で先頭コミットが変わった（{head[:7]} → {now[:7]}）。もう一度流す")
            return 2
        print(f"OK: {why}\nマージは判定した SHA に縛る: gh pr merge {n} -R {repo} --merge --match-head-commit {head}")
        return 0
    print(("待つ: " if code == 2 else "だめ: ") + why)
    return code


def run(argv):
    try:
        return main(argv)
    except GhError as e:
        print(f"待つ: 通信に失敗した。もう一度流す（{e}）")
        return 2


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
