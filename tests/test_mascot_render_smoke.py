"""vm render の書き出しスモーク。tests/fixtures/synth_mascot.py が描いた合成のマスコットで、
既定（二次運動なし）と --motion on を白背景の mp4・透明の webm に書き出し、コマ数と中身を確かめる。
ffmpeg が無い機体（CI）では imageio-ffmpeg の ffmpeg を使う。"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "skills/video-mascot/scripts/render.py"
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import synth_mascot  # noqa: E402

pytest.importorskip("pykakasi")
FPS, OH = 30, 384
NALL = int(np.ceil(synth_mascot.END * FPS))


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    return Path(synth_mascot.make(str(tmp_path_factory.mktemp("synth") / "proj")))


def render(proj, env, out, *args):
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(proj), "--out", str(out), *args], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert out.exists() and out.stat().st_size > 0
    return r.stderr


def frames(path, env, rgba):
    dec = ["-c:v", "libvpx-vp9"] if rgba else []                    # 透明を読むには libvpx で開く
    raw = subprocess.run(["ffmpeg", "-v", "error", *dec, "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba" if rgba else "rgb24", "-"],
                         env=env, capture_output=True, check=True).stdout
    ow = 2 * round(OH * (synth_mascot.W + 2 * 40) / synth_mascot.H / 2)
    return np.frombuffer(raw, np.uint8).reshape(-1, OH, ow, 4 if rgba else 3)


def test_render_white_default_and_motion(proj, env, tmp_path):
    off, on = tmp_path / "off.mp4", tmp_path / "on.mp4"
    log = render(proj, env, off, "--mode", "white")
    assert "軸足" in log
    render(proj, env, on, "--mode", "white", "--motion", "on")
    a, b = frames(off, env, False), frames(on, env, False)
    assert len(a) == len(b) == NALL
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).mean(axis=(1, 2, 3))
    assert (d > 0.05).sum() > NALL // 2                              # 二次運動で動きが変わる
    assert d.max() < 12                                               # でも絵が崩れるほどではない
    assert subprocess.run(["ffmpeg", "-v", "error", "-i", str(on), "-map", "0:a", "-f", "null", "-"], env=env).returncode == 0   # 声が入っている


def test_render_alpha_motion_keeps_transparency(proj, env, tmp_path):
    out = tmp_path / "on.webm"
    render(proj, env, out, "--motion", "on", "--lipsync", "mora")
    f = frames(out, env, True)
    assert len(f) == NALL
    al = f[..., 3]
    assert (al[:, :4, :] < 8).all()                                   # 上の端は透明（背景）
    assert (al > 247).mean(axis=(1, 2)).min() > 0.05                   # 体は不透明で残る


def test_render_motion_typo_is_an_error(proj, env, tmp_path):
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(proj), "--out", str(tmp_path / "x.mp4"), "--motion", "yes"],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "--motion" in r.stderr
