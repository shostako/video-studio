import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("pr_gate", Path(__file__).resolve().parent.parent / "scripts" / "pr_gate.py")
pr_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_gate)

HEAD = "ab80b937ff13f1ca70a1ff62b66b72e604fca4d6"


def body(status="completed", sha=HEAD, unresolved=False):
    import json
    st = {"code_review": {"commit_sha": sha, "has_any_findings": unresolved, "has_unresolved_findings": unresolved, "status": status}}
    return f"<!-- codex-pull-request-review-summary -->\n<!-- codex-review-state:v1 {json.dumps(st)} -->\ntext"


def test_clean_on_head_passes():
    assert pr_gate.evaluate([body()], HEAD)[0] == 0


def test_clean_on_old_commit_waits():
    # clean なレビューのあとに push された先頭は、前の要約で通さない
    assert pr_gate.evaluate([body(sha="3740a55" + "0" * 33)], HEAD)[0] == 2


def test_unresolved_threads_block():
    assert pr_gate.evaluate([body()], HEAD, unresolved_threads=1)[0] == 1


def test_stale_flag_does_not_block_when_threads_are_resolved():
    # 要約の has_unresolved_findings は、直して解決したあとも true のまま残る。スレッドが全部解決済みなら通す
    assert pr_gate.evaluate([body(unresolved=True)], HEAD, unresolved_threads=0)[0] == 0


def test_running_waits():
    assert pr_gate.evaluate([body(status="running", unresolved=None)], HEAD)[0] == 2


def test_no_summary_waits():
    assert pr_gate.evaluate(["ふつうのコメント"], HEAD)[0] == 2


def test_latest_summary_wins():
    assert pr_gate.evaluate([body(unresolved=True), body()], HEAD)[0] == 0


def test_gh_failure_means_wait(monkeypatch):
    def boom(*a, **k):
        raise pr_gate.GhError("TLS handshake timeout")
    monkeypatch.setattr(pr_gate, "_gh", boom)
    assert pr_gate.run(["8"]) == 2


def _c(login, typ, text):
    return {"user": {"login": login, "type": typ}, "body": text}


def test_forged_summary_by_human_is_ignored():
    # マーカーを真似た偽の「clean」要約は、Codex の bot が書いたものでなければ数えない
    forged = _c("someone", "User", body())
    real = _c("chatgpt-codex-connector[bot]", "Bot", body(unresolved=True))
    assert pr_gate.evaluate(pr_gate.codex_summaries([real, forged]), HEAD, unresolved_threads=1)[0] == 1
    assert pr_gate.evaluate(pr_gate.codex_summaries([forged]), HEAD)[0] == 2


def test_forged_summary_by_other_bot_is_ignored():
    assert pr_gate.codex_summaries([_c("github-actions[bot]", "Bot", body())]) == []


def test_flatten_pages():
    assert pr_gate.flatten_pages([[1, 2], [3]]) == [1, 2, 3]


def test_same_prefix_different_commit_waits():
    # 先頭7文字だけ同じ別のコミットを、レビュー済みとして通さない
    forged_head = HEAD[:7] + "f" * 33
    assert pr_gate.evaluate([body()], forged_head)[0] == 2



CLEAN = "Codex Review: Didn't find any major issues. Bravo.\n\n**Reviewed commit:** `{}`"


def to_head(abbr):
    return HEAD if HEAD.startswith(abbr) else None


def test_running_summary_with_later_clean_comment_on_head_passes():
    """要約は running のまま、別のコメントで「指摘なし」と先頭の接頭辞を返したら完了とみなす（#70 で起きた）。"""
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format(HEAD[:10])], HEAD, resolve=to_head)[0] == 0
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format(HEAD)], HEAD)[0] == 0        # SHA の全体なら引かなくてよい


def test_clean_comment_with_ambiguous_or_other_commit_waits():
    """短い SHA が先頭のコミットに引けない（曖昧・別のコミット・引けない）なら待つ（Codex の指摘）。"""
    older = HEAD[:7] + "f" * 33
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format(HEAD[:7])], HEAD, resolve=lambda a: older)[0] == 2
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format(HEAD[:7])], HEAD, resolve=lambda a: None)[0] == 2
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format(HEAD[:7])], HEAD)[0] == 2


def test_clean_comment_needs_running_summary_on_full_head_sha():
    other = HEAD[:10] + "f" * 30                                     # 接頭辞は同じでも、要約の SHA の全体が先頭と違えば通さない
    assert pr_gate.evaluate([body(status="running", sha=other, unresolved=None), CLEAN.format(HEAD[:10])], HEAD, resolve=to_head)[0] == 2
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format("3740a55aaa")], HEAD, resolve=to_head)[0] == 2   # 別のコミットへの結果
    assert pr_gate.evaluate([CLEAN.format(HEAD[:10]), body(status="running", unresolved=None)], HEAD, resolve=to_head)[0] == 2      # 要約より前の結果は使わない
    assert pr_gate.evaluate([body(status="running", unresolved=None), "Codex Review: found issues\n**Reviewed commit:** `%s`" % HEAD[:10]], HEAD)[0] == 2


def test_clean_comment_still_blocked_by_unresolved_threads():
    assert pr_gate.evaluate([body(status="running", unresolved=None), CLEAN.format(HEAD[:10])], HEAD, unresolved_threads=1, resolve=to_head)[0] == 1
