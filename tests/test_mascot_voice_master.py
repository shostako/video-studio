"""vm voice master が各行を config の開始時刻どおりに置くか（1行目の前の無音を捨てない）。声は合成のサイン波。"""
import json, os, re, shutil, subprocess, sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
VOICE = os.path.join(HERE, "..", "skills", "video-mascot", "scripts", "voice.py")
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が無い")


def _onsets(wav):
    e = subprocess.run(["ffmpeg", "-i", wav, "-af", "silencedetect=noise=-40dB:d=0.3", "-f", "null", "-"], capture_output=True, text=True).stderr
    return [float(x) for x in re.findall(r"silence_end: ([\d.]+)", e)]


def _dur(wav):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav], capture_output=True, text=True).stdout)


@pytest.mark.parametrize("first", [0.0, 1.5])
def test_master_keeps_line_starts(tmp_path, first):
    os.makedirs(tmp_path / "voice")
    for n, f in ((1, 440), (2, 660)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f={f}:d=1", "-ar", "24000", str(tmp_path / "voice" / f"l{n}.wav")], check=True)
    cfg = {"name": "t", "poses": {"home": {}}, "voice": {"lines": [{"text": "あ", "start": first}, {"text": "い", "start": first + 3.0}], "end": first + 5.0}}
    json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    subprocess.run([sys.executable, VOICE, str(tmp_path), "master"], check=True, capture_output=True)
    m = str(tmp_path / "voice" / "master.wav")
    assert abs(_dur(m) - (first + 5.0)) < 0.02
    ons = _onsets(m)
    if first > 0: assert abs(ons[0] - first) < 0.1          # 1行目の前の無音が残る
    assert any(abs(t - (first + 3.0)) < 0.1 for t in ons)   # 2行目も開始時刻どおり
