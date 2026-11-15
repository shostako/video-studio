"""声の確認の止まり所（voice_gate.py と vm voice review・approve）の試験。ffmpeg と聞き取りは偽物に替える。"""
import json, os, sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "video-mascot", "scripts"))
import voice_gate as G  # noqa: E402


def _work(tmp_path, review=None, master=b"RIFF0000"):
    os.makedirs(tmp_path / "voice", exist_ok=True)
    V = {"caption": "c", "lines": [{"text": "一"}, {"text": "二"}]}
    if review is not None: V["review"] = review
    cfg = {"name": "t", "poses": {"home": {}}, "voice": V}
    json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    if master is not None: open(tmp_path / "voice" / "master.wav", "wb").write(master)
    return str(tmp_path), cfg


def test_level():
    assert G.level({}) is None and G.level({"voice": {"review": False}}) is None
    assert G.level({"voice": {"review": "all"}}) == "all"
    with pytest.raises(ValueError): G.level({"voice": {"review": "yes"}})


def test_default_does_not_stop(tmp_path):
    root, cfg = _work(tmp_path)
    assert G.problem(root, cfg) is None                      # voice.review が無ければ今までどおり


def test_stops_until_approved_and_after_voice_changes(tmp_path):
    root, cfg = _work(tmp_path, "suspects")
    assert "確認待ち" in G.problem(root, cfg)
    G.approve(root)
    assert G.problem(root, cfg) is None
    open(tmp_path / "voice" / "master.wav", "wb").write(b"RIFF1111")    # 承認のあとで声が変わった
    assert "変わった" in G.problem(root, cfg)
    with pytest.raises(SystemExit) as e: G.check(root)
    assert e.value.code == 7


def test_bad_level_stops(tmp_path):
    root, cfg = _work(tmp_path, "yes")
    assert "suspects・all" in G.problem(root, cfg)


def test_review_and_approve_commands(tmp_path, monkeypatch, capsys):
    import voice, ojt, phonemes, voice_retry as VR
    root, _ = _work(tmp_path, "all")
    for n in (1, 2): open(tmp_path / "voice" / f"l{n}.wav", "wb").write(b"RIFF%d" % n)
    monkeypatch.setattr(voice, "build_master", lambda P, V, lines, gap: [{"n": 1, "start": 0.0, "dur": 1.0}, {"n": 2, "start": 1.5, "dur": 1.0}])
    monkeypatch.setattr(voice, "ff", lambda *a: open(a[-1], "wb").write(b"mp3"))
    monkeypatch.setattr(ojt, "available", lambda: True)
    monkeypatch.setattr(phonemes, "hear", lambda ps: [{"path": p, "phones": [["a", 0.1, 0.2]]} for p in ps])
    monkeypatch.setattr(VR, "warnings", lambda *a, **k: [])
    monkeypatch.setattr(sys, "argv", ["voice.py", root, "review"]); voice.main()
    md = open(tmp_path / "voice" / "review" / "聞き取り.md", encoding="utf-8").read()
    assert os.path.exists(tmp_path / "voice" / "review" / "全部.mp3")
    assert "行2（1.5 秒）: 二" in md and "疑い所は無い" in md
    assert "確認待ち" in G.problem(root, json.load(open(tmp_path / "config.json", encoding="utf-8")))
    monkeypatch.setattr(sys, "argv", ["voice.py", root, "approve"]); voice.main()
    assert G.problem(root, json.load(open(tmp_path / "config.json", encoding="utf-8"))) is None
    assert "声を承認した" in capsys.readouterr().out


def test_compose_and_explain_stop_before_work(tmp_path):
    """書き出しの入口が、声の承認の無いときに中身の処理より先に止まる（終了コード 7）。"""
    import subprocess
    root, _ = _work(tmp_path / "w", "suspects")
    S = os.path.join(HERE, "..", "skills")
    shots = tmp_path / "shots"; os.makedirs(shots); scenes = tmp_path / "scenes.py"; scenes.write_text("")
    r = subprocess.run([sys.executable, f"{S}/video-mascot/scripts/explain.py", root, "--shots", str(shots), "--scenes", str(scenes), "--style", "cursor", "--out", str(tmp_path / "o.mp4"), "--jobs", "1"],
                       capture_output=True, text=True)
    assert r.returncode == 7 and "確認待ち" in r.stderr
    r = subprocess.run([sys.executable, f"{S}/screen-explainer/scripts/compose.py", "--shots", str(shots), "--voice", root, "--scenes", str(scenes), "--out", str(tmp_path / "o.mp4")],
                       capture_output=True, text=True)
    if "フォント" in r.stderr: pytest.skip("日本語の太字フォントが無い")
    assert r.returncode == 7 and "確認待ち" in r.stderr


def test_review_drops_stale_files_and_keeps_untimed_warnings(tmp_path, monkeypatch):
    import voice, ojt, phonemes, voice_retry as VR, accent_check
    root, _ = _work(tmp_path, "suspects")
    for n in (1, 2): open(tmp_path / "voice" / f"l{n}.wav", "wb").write(b"RIFF%d" % n)
    rd = tmp_path / "voice" / "review"; os.makedirs(rd)
    for f in ("全部.mp3", "疑い所.mp3", "疑い所.md"): (rd / f).write_text("old")         # 前の声の物
    monkeypatch.setattr(voice, "build_master", lambda P, V, lines, gap: [{"n": 1, "start": 0.0, "dur": 1.0}, {"n": 2, "start": 1.5, "dur": 1.0}])
    monkeypatch.setattr(voice, "ff", lambda *a: open(a[-1], "wb").write(b"mp3"))
    monkeypatch.setattr(ojt, "available", lambda: True)
    monkeypatch.setattr(phonemes, "hear", lambda ps: [{"path": p, "phones": [["a", 0.1, 0.2]]} for p in ps])
    monkeypatch.setattr(VR, "warnings", lambda line, *a, **k: [{"kind": "reading", "word": "二", "t": None, "end": None, "why": "w"}] if line["text"] == "二" else [])
    monkeypatch.setattr(accent_check, "make_clips", lambda *a, **k: (_ for _ in ()).throw(AssertionError("時刻の無い疑いだけなら切り出さない")))
    monkeypatch.setattr(sys, "argv", ["voice.py", root, "review"]); voice.main()
    assert sorted(os.listdir(rd)) == ["聞き取り.md", "行2.mp3"]                          # 前の 全部・疑い所 は消えた
    md = (rd / "聞き取り.md").read_text(encoding="utf-8")
    assert "時刻の取れない疑い（1 か所" in md and "行2（行2.mp3）【二】" in md and "疑い所は無い" not in md


def test_review_imports_work_without_test_paths(tmp_path):
    """vm から呼んだときと同じく、voice.py の置き場だけが sys.path にある状態で review が ojt を読める（conftest の足すパスに頼らない）。"""
    import subprocess
    root, _ = _work(tmp_path, "suspects")
    S = os.path.join(HERE, "..", "skills", "video-mascot", "scripts", "voice.py")
    r = subprocess.run([sys.executable, "-I", S, root, "review"], capture_output=True, text=True, cwd=str(tmp_path))
    assert "No module named" not in r.stderr, r.stderr[-400:]
