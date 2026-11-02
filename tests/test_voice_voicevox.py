"""声のエンジンの選択肢 VOICEVOX。本物のエンジンの代わりに、同じ HTTP の形の小さなサーバーで確かめる。"""
import json
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
