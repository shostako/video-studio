"""vm explain: 合成の撮影・声・マスコットで、3 つの型（cursor・wipe・full）を 1 本に組めるか。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/video-mascot/scripts"
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import synth_mascot as sm  # noqa: E402

FONTS = [os.environ.get("SCREEN_EXPLAINER_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONT = next((p for p in FONTS if p and os.path.exists(p)), None)
pytestmark = pytest.mark.skipif(FONT is None, reason="太字のフォントが無い")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ, SCREEN_EXPLAINER_FONT=FONT or "")
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def inputs(tmp_path):
    pytest.importorskip("pykakasi")
    work = Path(sm.make(str(tmp_path / "work")))
    shots = tmp_path / "shots"; shots.mkdir(); rects = {}
    for name in ("s01", "s02"):
        im = Image.new("RGB", (1920, 1020), (245, 245, 245)); ImageDraw.Draw(im).rectangle([300, 400, 520, 450], fill=(60, 90, 160)); im.save(shots / f"{name}.png")
        rects[name] = {"box": [300, 400, 520, 450]}
    (shots / "rects.json").write_text(json.dumps(rects))
    sc = tmp_path / "scenes.py"
    sc.write_text('add(imgs=[(0, "s01")], cam=[(0, FULL)], cur=[(0, (900, 500)), (.5, ctr("s01", "box"))], hl=[(.3, 1, rc("s01", "box"))])\n'
                  'add(imgs=[(0, "s02")], cam=[(0, FULL)], cur=[(0, ctr("s02", "box"))], click=[.4])\n', encoding="utf-8")
    ch = tmp_path / "ch.json"; ch.write_text(json.dumps({"chapters": [{"line": 1, "title": "はじめ"}, {"line": 2, "title": "つぎ"}]}, ensure_ascii=False), encoding="utf-8")
    return work, shots, sc, ch


def explain(env, work, shots, sc, out, style, *extra):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "explain.py"), str(work), "--shots", str(shots), "--scenes", str(sc),
                           "--style", style, "--out", str(out), *extra], capture_output=True, text=True, env=env, timeout=600)


def frame(path, t, env):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, env=env).stdout
    return np.frombuffer(raw, np.uint8).reshape(1080, 1920, 3).astype(int)


@pytest.mark.parametrize("style", ["cursor", "wipe", "full"])
def test_explain_makes_each_style(tmp_path, env, style):
    work, shots, sc, ch = inputs(tmp_path); out = tmp_path / f"{style}.mp4"
    r = explain(env, work, shots, sc, out, style, "--chapters", ch)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert out.exists() and out.stat().st_size > 0 and not list(tmp_path.glob(f"{style}_work_*"))
    f = frame(out, 2.5, env)
    if style == "cursor":
        assert (np.abs(f[600, 100] - (245, 245, 245)) <= 8).all()          # 画面が全面（左端まで撮影の地）
    else:
        assert (np.abs(f[300, 100] - (247, 246, 244)) <= 6).all()          # 左に余白（見出しの下・マスコットの上）
        if style == "wipe": assert f[1080 - 48 - 2, 248][0] > 150 and f[1080 - 48 - 2, 248][2] < 120   # 余白の左下にワイプの橙の縁
    if style == "full": assert "身振りが出たかの測定" in r.stdout


def test_explain_rejects_bad_style_and_missing_voice(tmp_path, env):
    work, shots, sc, ch = inputs(tmp_path)
    r = explain(env, work, shots, sc, tmp_path / "x.mp4", "dance")
    assert r.returncode != 0 and "style" in r.stderr
    os.remove(work / "voice" / "master.wav")
    r = explain(env, work, shots, sc, tmp_path / "x.mp4", "cursor")
    assert r.returncode != 0 and "声が無い" in r.stderr


def test_explain_never_deletes_an_existing_folder_named_like_work(tmp_path, env):
    """出力の名前の _work と同じ名前のフォルダ（作業フォルダなど）があっても、消さない（Codex の指摘）。"""
    work, shots, sc, ch = inputs(tmp_path)
    keep = tmp_path / "demo_work"; keep.mkdir(); (keep / "大事.txt").write_text("x")
    r = explain(env, work, shots, sc, tmp_path / "demo.mp4", "cursor")
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    assert (keep / "大事.txt").exists()


def test_compose_stops_at_video_length_when_voice_is_short(tmp_path, env):
    """声が絵より短くても、出力は絵の長さで終わる（無音を書き続けない）。"""
    work, shots, sc, ch = inputs(tmp_path); out = tmp_path / "c.mp4"
    r = explain(env, work, shots, sc, out, "cursor")
    assert r.returncode == 0, r.stderr[-1500:]
    import re
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out)], capture_output=True, text=True, env=env).stderr
    h, m, s_ = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p).groups()
    assert abs(int(h) * 3600 + int(m) * 60 + float(s_) - (sm.END + 0.8)) < 0.3


def test_explain_positional_work_survives_same_named_options(tmp_path, env):
    """撮影を作業フォルダの中に置いて --shots に同じ名前を渡しても、作業フォルダの引数を落とさない（Codex の指摘）。"""
    work, shots, sc, ch = inputs(tmp_path)
    for f in shots.iterdir(): shutil.copy(f, work / f.name)
    r = explain(env, work, work, sc, tmp_path / "same.mp4", "cursor")
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]


def test_full_style_settings(tmp_path):
    import json
    import explain
    c = tmp_path / "config.json"
    c.write_text(json.dumps({"poses": {}}), encoding="utf-8")
    assert explain.full_args(str(c)) == ["--out-height", "720", "--work-scale", "0.64", "--fps", "30"]
    assert explain.full_args(str(c), fine=True) == []
    c.write_text(json.dumps({"out_height": 1000}), encoding="utf-8")
    assert explain.full_args(str(c)) == ["--work-scale", "0.64", "--fps", "30"]


def test_wipe_style_settings(tmp_path):
    import json
    import explain
    c = tmp_path / "config.json"
    c.write_text(json.dumps({"poses": {}}), encoding="utf-8")
    assert explain.wipe_args(str(c)) == ["--out-height", "1070", "--work-scale", "0.64", "--fps", "30"]
    assert explain.wipe_args(str(c), fine=True) == []
    c.write_text(json.dumps({"out_height": 1000}), encoding="utf-8")
    assert explain.wipe_args(str(c)) == ["--work-scale", "0.64", "--fps", "30"]


def test_explain_uses_a_lossless_intermediate():
    src = (ROOT / "skills/video-mascot/scripts/explain.py").read_text(encoding="utf-8")
    assert 'face = os.path.join(tmp, "mascot.mkv")' in src
    layout = (ROOT / "skills/video-mascot/scripts/layout.py").read_text(encoding="utf-8")
    assert 'return mp.endswith((".webm", ".mkv"))' in layout    # mkv も透明として読む（読まないと白地の乗算になる）
    render = (ROOT / "skills/video-mascot/scripts/render.py").read_text(encoding="utf-8")
    assert 'if OUTF.endswith(".mkv"):' in render and '"ffv1"' in render
