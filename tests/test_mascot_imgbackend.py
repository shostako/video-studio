"""vm poses の描く道具の選び方（--img codex|chat|chat+codex）。本物の /img・ブラウザの代わりに、合成の小さなスクリプトを使う。"""
import os
import stat

import pytest

import poses

FAKE = r"""#!/usr/bin/env bash
# 合成の描く道具: -o の先にファイルを書く。呼ばれた順を LOG に、名前を中身に残す。
out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift 2;; *) shift;; esac; done
n=$(cat "$COUNT" 2>/dev/null || echo 0); echo $((n+1)) > "$COUNT"
echo "start {name} $(basename "$out")" >> "$LOG"
if [ -n "{limit_after}" ] && [ "$n" -ge "{limit_after}" ]; then echo "end {name}" >> "$LOG"; exit {limit_rc}; fi
sleep {sleep}
echo "{name}" > "$out"
echo "end {name}" >> "$LOG"
"""


def fake(tmp_path, name, limit_after="", limit_rc=4, sleep=0):
    p = tmp_path / f"fake_{name}.sh"
    p.write_text(FAKE.format(name=name, limit_after=limit_after, limit_rc=limit_rc, sleep=sleep), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG", str(tmp_path / "log.txt"))
    monkeypatch.setenv("COUNT", str(tmp_path / "count_chat"))
    monkeypatch.setattr(poses.time, "sleep", lambda s: None)
    poses.LIMIT.clear()
    poses.FELL_BACK.clear()
    yield tmp_path
    poses.LIMIT.clear()
    poses.FELL_BACK.clear()


def jobs(tmp_path, n):
    return [(str(tmp_path / "out" / f"p{k}.png"), "prompt", []) for k in range(n)]


def log(tmp_path):
    return (tmp_path / "log.txt").read_text(encoding="utf-8").split("\n")[:-1]


def test_backend_default_is_codex():
    assert poses.img_backend(["vm", "w", "poses"], {}) == "codex"
    assert poses.img_backend(["vm", "w", "poses"], {"img": "chat+codex"}) == "chat+codex"
    assert poses.img_backend(["vm", "w", "poses", "--img", "chat"], {"img": "codex"}) == "chat"   # 引数が config より優先
    with pytest.raises(SystemExit):
        poses.img_backend(["vm", "w", "poses", "--img", "dalle"], {})
    for argv in (["vm", "w", "poses", "--img"], ["vm", "w", "poses", "--img", "--dry-run"]):   # 値が無いのに codex に落ちない
        with pytest.raises(SystemExit):
            poses.img_backend(argv, {"img": "chat"})


def test_tool_choice():
    assert poses.img_tool("codex", False) == (poses.IMG, True)
    assert poses.img_tool("chat", False) == (poses.CHATIMG, False)
    assert poses.img_tool("chat", True) == (poses.CHATIMG, False)          # chat だけなら切り替えない
    assert poses.img_tool("chat+codex", False) == (poses.CHATIMG, False)
    assert poses.img_tool("chat+codex", True) == (poses.IMG, True)
    assert poses.chat_should_fall_back("chat+codex", 4) and poses.chat_should_fall_back("chat+codex", 3)
    assert not poses.chat_should_fall_back("chat+codex", 1) and not poses.chat_should_fall_back("chat", 4)


def test_codex_default_never_touches_chat(env, monkeypatch):
    monkeypatch.setattr(poses, "IMG", fake(env, "codex"))
    monkeypatch.setattr(poses, "CHATIMG", fake(env, "chat"))
    assert poses.run_jobs(jobs(env, 3), 4, False)
    assert {open(j[0]).read().strip() for j in jobs(env, 3)} == {"codex"}
    assert not any("chat" in l for l in log(env))


def test_chat_is_serial(env, monkeypatch):
    monkeypatch.setattr(poses, "IMG", fake(env, "codex"))
    monkeypatch.setattr(poses, "CHATIMG", fake(env, "chat", sleep=0.2))
    assert poses.run_jobs(jobs(env, 3), 4, False, backend="chat")
    L = log(env)
    assert all(l.split()[1] == "chat" for l in L)
    # start と end が交互（同時に2枚描いていない）
    assert [l.split()[0] for l in L] == ["start", "end"] * 3


def test_chat_limit_stops_without_codex(env, monkeypatch):
    monkeypatch.setattr(poses, "IMG", fake(env, "codex"))
    monkeypatch.setattr(poses, "CHATIMG", fake(env, "chat", limit_after=1))
    assert not poses.run_jobs(jobs(env, 3), 4, False, backend="chat")
    assert poses.LIMIT.is_set() and not poses.FELL_BACK.is_set()
    assert not any("codex" in l for l in log(env))
    assert sum(os.path.exists(j[0]) for j in jobs(env, 3)) == 1


@pytest.mark.parametrize("rc", [4, 3])
def test_chat_plus_codex_falls_back(env, monkeypatch, rc):
    monkeypatch.setattr(poses, "IMG", fake(env, "codex"))
    monkeypatch.setattr(poses, "CHATIMG", fake(env, "chat", limit_after=2, limit_rc=rc))
    J = jobs(env, 5)
    assert poses.run_jobs(J, 4, False, backend="chat+codex")
    who = [open(j[0]).read().strip() for j in J]
    assert who[:2] == ["chat", "chat"] and set(who[2:]) == {"codex"}     # 上限の後は全部 /img
    assert poses.FELL_BACK.is_set() and not poses.LIMIT.is_set()
    assert sum(l == "start chat p2.png" for l in log(env)) == 1          # 上限を返した枚は chat で何度も試さない
