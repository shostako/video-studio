"""Chat 画面で描く経路（vm poses --img chat）の切り替えを、偽の img.sh / img_chat.sh で確かめる。本物の ChatGPT・Codex は呼ばない。"""
import io
import os
import stat
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
import chat_img  # noqa: E402
import poses  # noqa: E402


def test_backend_now_default_is_codex():
    assert poses.backend_now("codex", False) == "codex"
    assert poses.backend_now("codex", True) == "codex"
    assert poses.backend_now("chat", False) == "chat"
    assert poses.backend_now("chat", True) == "codex"     # Chat が上限を返した後は codex


def test_after_rc():
    assert poses.after_rc("chat", 0) == "done"
    assert poses.after_rc("chat", 4) == "fallback"         # Chat の上限は codex に切り替える
    assert poses.after_rc("codex", 4) == "stop"            # codex の上限は今まで通り止める
    assert poses.after_rc("chat", 3) == "retry"
    assert poses.after_rc("codex", 6) == "retry"


def test_img_cmd_picks_script():
    c = poses.img_cmd("codex", "p", ["a.png", "b.png"], "o.png")
    assert c == [poses.IMG, "-p", "p", "-r", "a.png", "-r", "b.png", "-o", "o.png"]
    assert poses.img_cmd("chat", "p", [], "o.png")[0] == poses.IMG_CHAT


def _fake(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


# 引数の -o の次を出力として、白い PNG を書く（成功）か、終了コード $RC で落ちる。呼ばれた名前を log に足す
FAKE = """out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done
echo "{name} $(basename "$out")" >> "{log}"
{rule}
python3 -c "from PIL import Image; Image.new('RGB', (8, 8), 'white').save('$out')"; echo "$out"
"""


@pytest.fixture
def fresh(monkeypatch):
    for e in (poses.LIMIT, poses.CHAT_OFF): e.clear()
    yield
    for e in (poses.LIMIT, poses.CHAT_OFF): e.clear()


@pytest.mark.skipif(os.name == "nt", reason="偽の img を bash で動かす")
def test_chat_limit_falls_back_to_codex(tmp_path, monkeypatch, fresh):
    log = tmp_path / "log"
    # Chat は2枚目で上限（4）。codex は全部描ける
    chat = _fake(tmp_path / "chat.sh", FAKE.format(name="chat", log=log, rule='n=$(grep -c ^chat "' + str(log) + '"); [ "$n" -ge 2 ] && exit 4'))
    codex = _fake(tmp_path / "codex.sh", FAKE.format(name="codex", log=log, rule=""))
    monkeypatch.setattr(poses, "IMG_CHAT", chat); monkeypatch.setattr(poses, "IMG", codex)
    monkeypatch.setattr(poses.time, "sleep", lambda s: None)
    jobs = [(str(tmp_path / f"o{i}.png"), "p", []) for i in range(4)]
    assert poses.run_jobs(jobs, 1, False, want="chat")
    calls = log.read_text().split("\n")
    assert calls[0] == "chat o0.png" and calls[1] == "chat o1.png" and calls[2] == "codex o1.png"   # 上限の枚を codex で描き直す
    assert [c.split()[0] for c in calls[3:] if c] == ["codex", "codex"]                           # 残りは codex
    assert poses.CHAT_OFF.is_set() and not poses.LIMIT.is_set()


@pytest.mark.skipif(os.name == "nt", reason="偽の img を bash で動かす")
def test_default_never_calls_chat(tmp_path, monkeypatch, fresh):
    log = tmp_path / "log"
    chat = _fake(tmp_path / "chat.sh", FAKE.format(name="chat", log=log, rule=""))
    codex = _fake(tmp_path / "codex.sh", FAKE.format(name="codex", log=log, rule=""))
    monkeypatch.setattr(poses, "IMG_CHAT", chat); monkeypatch.setattr(poses, "IMG", codex)
    jobs = [(str(tmp_path / f"o{i}.png"), "p", []) for i in range(3)]
    assert poses.run_jobs(jobs, 2, False)
    assert all(c.startswith("codex") for c in log.read_text().split("\n") if c)


@pytest.mark.skipif(os.name == "nt", reason="偽の img を bash で動かす")
def test_codex_limit_after_chat_limit_stops(tmp_path, monkeypatch, fresh):
    log = tmp_path / "log"
    chat = _fake(tmp_path / "chat.sh", FAKE.format(name="chat", log=log, rule="exit 4"))
    codex = _fake(tmp_path / "codex.sh", FAKE.format(name="codex", log=log, rule="exit 4"))
    monkeypatch.setattr(poses, "IMG_CHAT", chat); monkeypatch.setattr(poses, "IMG", codex)
    jobs = [(str(tmp_path / f"o{i}.png"), "p", []) for i in range(3)]
    assert not poses.run_jobs(jobs, 1, False, want="chat")
    assert poses.LIMIT.is_set()                              # 両方の上限なら今まで通り終了コード 4 の扱い


def _img_bytes(fmt):
    b = io.BytesIO(); Image.new("RGBA" if fmt != "JPEG" else "RGB", (20, 10), (200, 10, 10)).save(b, fmt); return b.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "WEBP", "JPEG"])
def test_save_as_keeps_requested_name_and_format(tmp_path, fmt):
    out = tmp_path / "x.png"                                 # Chat が webp や jpeg で返しても、頼まれた名前の PNG を作る
    assert chat_img.save_as(_img_bytes(fmt), str(out)) == str(out)
    with Image.open(out) as im: assert im.format == "PNG" and im.size == (20, 10)
    assert not [p for p in tmp_path.iterdir() if ".tmp" in p.name]


def test_save_as_rejects_non_image(tmp_path):
    with pytest.raises(chat_img.Fail) as e: chat_img.save_as(b"<html>nope</html>", str(tmp_path / "x.png"))
    assert e.value.code == 6


@pytest.mark.parametrize("text,hit", [
    ("You've hit the Plus plan limit for image generations requests. You can create more images when the limit resets in 3 hours.", True),
    ("画像生成の上限に達しました。しばらくしてから、もう一度お試しください。", True),
    ("はい、画像を作りました。", False),
])
def test_limit_re(text, hit):
    assert bool(chat_img.LIMIT_RE.search(text)) is hit
