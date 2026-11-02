"""声のエンジンの選択肢 VOICEVOX。本物のエンジンの代わりに、同じ HTTP の形の小さなサーバーで確かめる。"""
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
import voice_voicevox as vv


@pytest.fixture
def engine():
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, body, code=200):
            self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            self._send(json.dumps([{"name": "テスト", "styles": [{"id": 3, "name": "ふつう"}]}]).encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0)); seen.append((self.path, body))
            self._send(json.dumps({"accent_phrases": []}).encode() if self.path.startswith("/audio_query") else b"RIFFwav")

    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


def test_synth_writes_each_line_with_the_settings(engine, tmp_path):
    host, seen = engine; out = tmp_path / "l1.wav"
    vv.synth_jobs([{"text": "こんにちは", "out": str(out)}], {"host": host, "speaker": 3, "speed": 1.2})
    assert out.read_bytes() == b"RIFFwav" and not (tmp_path / "l1.wav.part").exists()
    q = json.loads(seen[1][1])
    assert q["speedScale"] == 1.2 and q["pitchScale"] == 0.0 and q["outputSamplingRate"] == vv.SAMPLE_RATE and q["outputStereo"] is False
    assert seen[1][0] == "/synthesis?speaker=3"


@pytest.mark.parametrize("voice", [{}, {"speaker": 99}])
def test_speaker_is_required_and_lists_the_choices(engine, capsys, voice, tmp_path):
    host, _ = engine
    with pytest.raises(SystemExit):
        vv.synth_jobs([{"text": "x", "out": str(tmp_path / "a.wav")}], {"host": host, **voice})
    assert "3: テスト（ふつう）" in capsys.readouterr().err


def test_no_engine_says_how_to_fix(capsys, tmp_path):
    with pytest.raises(SystemExit):
        vv.synth_jobs([{"text": "x", "out": str(tmp_path / "a.wav")}], {"host": "http://127.0.0.1:9", "speaker": 3})
    assert "VOICEVOX ENGINE に繋がらない" in capsys.readouterr().err


def test_voice_py_only_uses_it_when_asked():
    src = (ROOT / "skills/video-mascot/scripts/voice.py").read_text(encoding="utf-8")
    assert 'if cmd == "synth" and V.get("engine") == "voicevox":' in src and src.count("voice_voicevox") == 2     # import と呼び出しだけ（外すのが簡単）


def _fake_whisper(tmp_path, monkeypatch, fail_after=None):
    """本物の聞き取りの代わりに、呼ばれた回数を記録する偽物を子プロセスに読ませる。"""
    import voice
    (tmp_path / "common.py").write_text("def read_audio(p): return p\n", encoding="utf-8")
    (tmp_path / "faster_whisper.py").write_text(f"""
import os, sys
class X:
    def __init__(self, text): self.text = text
class WhisperModel:
    n = 0
    def __init__(self, *a, **k):
        with open(os.environ["LOADS"], "a") as f: f.write("x")
    def transcribe(self, path, **k):
        WhisperModel.n += 1
        if {fail_after!r} is not None and WhisperModel.n > {fail_after!r}: raise RuntimeError("こわれた")
        print("ライブラリの独り言")
        return [X("聞いた "), X(os.path.basename(path))], None
""", encoding="utf-8")
    monkeypatch.setattr(voice, "SCENE_SCRIPTS", str(tmp_path)); monkeypatch.setattr(voice, "WS", sys.executable)
    monkeypatch.setenv("LOADS", str(tmp_path / "loads")); monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    return voice


def test_hear_all_loads_model_once_and_keeps_order(tmp_path, monkeypatch):
    voice = _fake_whisper(tmp_path, monkeypatch)
    assert list(voice.hear_all(["a/l1.wav", "a/l2.wav", "a/l3.wav"])) == ["聞いた l1.wav", "聞いた l2.wav", "聞いた l3.wav"]
    assert (tmp_path / "loads").read_text() == "x"


def test_hear_all_failure_keeps_going_and_says_why(tmp_path, monkeypatch, capsys):
    voice = _fake_whisper(tmp_path, monkeypatch, fail_after=1)
    assert list(voice.hear_all(["a/l1.wav", "a/l2.wav", "a/l3.wav"])) == ["聞いた l1.wav", "", ""]
    out = capsys.readouterr().out
    assert "2 件できなかった" in out and "こわれた" in out


def test_scene_scripts_points_at_the_sibling_skill():
    import voice
    assert os.path.exists(os.path.join(voice.SCENE_SCRIPTS, "common.py"))


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")


def _empty_proj(tmp_path, n=2):
    """声のファイルが要らないテスト用の作業フォルダ。"""
    import voice
    from lib import Proj
    w = tmp_path / "w"; w.mkdir()
    lines = [{"text": f"だい{i}ぎょう"} for i in range(1, n + 1)]
    (w / "config.json").write_text(json.dumps({"poses": {"a": "a.png"}, "voice": {"caption": "x", "lines": lines}}), encoding="utf-8")
    return voice, Proj(str(w)), lines


def _proj(tmp_path, n=2):
    """本物の ffmpeg で行の声を作った作業フォルダ。"""
    import subprocess
    import voice
    from lib import Proj
    w = tmp_path / "w"; (w / "voice").mkdir(parents=True)
    lines = [{"text": f"だい{i}ぎょう"} for i in range(1, n + 1)]
    (w / "config.json").write_text(json.dumps({"poses": {"a": "a.png"}, "voice": {"caption": "x", "lines": lines}}), encoding="utf-8")
    for i in range(1, n + 1):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-ac", "1", str(w / "voice" / f"l{i}.wav")], check=True)
    return voice, Proj(str(w)), lines


def _fake_words(tmp_path, monkeypatch):
    (tmp_path / "faster_whisper.py").write_text("""
import os
class W:
    def __init__(self, word, start, end): self.word, self.start, self.end = word, start, end
class S:
    text = ""
    words = [W("だい1", 0.1, 0.5), W("ぎょう", 0.5, 0.9), W("幻", 1.5, 1.52), W("だい2", 2.0, 2.4), W("ぎょう", 2.4, 2.8)]
class WhisperModel:
    def __init__(self, *a, **k):
        with open(os.environ["LOADS"], "a") as f: f.write("x")
    def transcribe(self, audio, **k):
        assert k["word_timestamps"] and k["condition_on_previous_text"] is False
        return [S()], None
""", encoding="utf-8")
    monkeypatch.setenv("LOADS", str(tmp_path / "loads")); monkeypatch.setenv("PYTHONPATH", str(tmp_path))


@needs_ffmpeg
def test_full_synth_listens_once_and_reuses_words_for_render(tmp_path, monkeypatch, capsys):
    voice, P, lines = _proj(tmp_path); _fake_words(tmp_path, monkeypatch)
    monkeypatch.setattr(voice, "WS", sys.executable)
    voice.report_match(P, lines, [1, 2], P.cfg["voice"], 1.0)
    out = capsys.readouterr().out
    assert "行1 台本との一致 1.00: だい1ぎょう" in out and "行2 台本との一致 1.00: だい2ぎょう" in out
    assert (tmp_path / "loads").read_text() == "x"
    wav, words = P.p("voice", "master.wav"), P.p("voice", "master.words.json")
    before = os.path.getmtime(wav)
    os.utime(words, (before + 5, before + 5))
    voice.build_master(P, P.cfg["voice"], lines, 1.0)    # vm voice master を流しても
    assert os.path.getmtime(wav) == before and os.path.getmtime(words) > os.path.getmtime(wav)    # 書き出しは聞き直さない


def test_full_synth_builds_master_before_listening(tmp_path, monkeypatch, capsys):
    voice, P, lines = _empty_proj(tmp_path); order = []
    info = [{"n": 1, "start": 0.0, "dur": 1.0}, {"n": 2, "start": 2.0, "dur": 1.0}]
    monkeypatch.setattr(voice, "build_master", lambda *a: order.append("build") or info)
    monkeypatch.setattr(voice, "hear_master", lambda P: order.append("hear") or [["だい1ぎょう", 0.1, 0.9], ["だい2ぎょう", 2.1, 2.9]])
    monkeypatch.setattr(voice, "hear_all", lambda paths: pytest.fail("全行のときは行ごとに聞かない"))
    voice.report_match(P, lines, [1, 2], P.cfg["voice"], 1.0)
    assert order == ["build", "hear"]
    out = capsys.readouterr().out
    assert "行1 台本との一致 1.00" in out and "行2 台本との一致 1.00" in out


def test_partial_synth_hears_only_those_lines(tmp_path, monkeypatch):
    voice, P, lines = _empty_proj(tmp_path, 3)
    monkeypatch.setattr(voice, "build_master", lambda *a: pytest.fail("一部の行ではつながない"))
    monkeypatch.setattr(voice, "hear_all", lambda paths: ["x" for _ in paths])
    monkeypatch.setattr(voice, "hear_master", lambda P: pytest.fail("一部の行では全体を聞かない"))
    voice.report_match(P, lines, [2], P.cfg["voice"], 0.5)


@needs_ffmpeg
def test_changed_voice_changes_master_so_render_listens_again(tmp_path):
    import subprocess
    voice, P, lines = _proj(tmp_path)
    voice.build_master(P, P.cfg["voice"], lines, 0.5); a = open(P.p("voice", "master.wav"), "rb").read()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1", "-ac", "1", P.p("voice", "l2.wav")], check=True)
    voice.build_master(P, P.cfg["voice"], lines, 0.5)
    assert open(P.p("voice", "master.wav"), "rb").read() != a


def test_heard_by_line_drops_words_in_the_silence():
    import voice
    info = [{"n": 1, "start": 0.0, "dur": 1.0}, {"n": 2, "start": 2.0, "dur": 1.0}]
    words = [["あ", 0.1, 0.5], ["幻", 1.5, 1.6], ["い", 2.1, 2.5], ["う", 1.25, 1.27]]
    assert voice.heard_by_line(words, info) == {1: "あう", 2: "い"}


@needs_ffmpeg
def test_listening_failure_keeps_the_voice_and_says_why(tmp_path, monkeypatch, capsys):
    voice, P, lines = _proj(tmp_path)
    (tmp_path / "faster_whisper.py").write_text("class WhisperModel:\n    def __init__(self, *a, **k): raise RuntimeError('こわれた')\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path)); monkeypatch.setattr(voice, "WS", sys.executable)
    voice.report_match(P, lines, [1, 2], P.cfg["voice"], 1.0)
    out = capsys.readouterr().out
    assert "聞き取りができなかった" in out and "こわれた" in out
    assert os.path.exists(P.p("voice", "master.wav")) and not os.path.exists(P.p("voice", "master.words.json"))


def test_irodori_model_defaults_to_meanflow_and_can_be_changed(tmp_path, monkeypatch):
    import subprocess
    import voice
    seen = {}

    def fake_run(cmd, **k):
        seen["src"] = open(cmd[4], encoding="utf-8").read()
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(voice, "IRO", str(tmp_path)); monkeypatch.setattr(voice.subprocess, "run", fake_run)
    voice.run_irodori([{"text": "x"}], str(tmp_path))
    assert 'download_hf_checkpoint("Aratako/Irodori-TTS-v4.1-Small-MF")' in seen["src"]
    voice.run_irodori([{"text": "x"}], str(tmp_path), "Aratako/Irodori-TTS-v4.1-Small")
    assert 'download_hf_checkpoint("Aratako/Irodori-TTS-v4.1-Small")' in seen["src"]
