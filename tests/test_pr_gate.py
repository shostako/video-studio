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


def test_unresolved_blocks():
    assert pr_gate.evaluate([body(unresolved=True)], HEAD)[0] == 1


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
    assert pr_gate.evaluate(pr_gate.codex_summaries([real, forged]), HEAD)[0] == 1
    assert pr_gate.evaluate(pr_gate.codex_summaries([forged]), HEAD)[0] == 2


def test_forged_summary_by_other_bot_is_ignored():
    assert pr_gate.codex_summaries([_c("github-actions[bot]", "Bot", body())]) == []


def test_flatten_pages():
    assert pr_gate.flatten_pages([[1, 2], [3]]) == [1, 2, 3]
