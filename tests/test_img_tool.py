"""同梱の img.sh を、絵を出す偽の codex で動かす。形式の判定と、-o で頼まれたパスを変えないこと。"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np

IMG = Path(__file__).resolve().parent.parent / "skills/video-mascot/scripts/img/img.sh"
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg が要る")


def script(p, body):
    p.write_text("#!/bin/bash\n" + body); p.chmod(0o755)


@pytest.fixture
def run(tmp_path):
    bindir = tmp_path / "bin"; bindir.mkdir()
    # 偽の codex: -C の作業フォルダの out.png に、環境変数で指定された中身を置く
    script(bindir / "codex", 'while [ $# -gt 0 ]; do [ "$1" = "-C" ] && d="$2"; shift; done; cp "$IMG_SRC" "$d/out.png"\n')
    script(bindir / "file", 'echo "file を呼んだ" >&2; exit 1\n')      # file に頼っていたら落ちる
    def go(src, *args):
        env = dict(os.environ, PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", IMG_SRC=str(src), HOME=str(tmp_path), TMPDIR=str(tmp_path))
        return subprocess.run(["bash", str(IMG), "-p", "x", *args], env=env, capture_output=True, text=True, timeout=60)
    return go


def picture(p):
    assert cv2.imwrite(str(p), np.full((16, 16, 3), 200, np.uint8)); return p


@pytest.mark.parametrize("name", ["a.png", "a.jpg", "a.webp"])
def test_explicit_output_is_a_real_png_at_the_requested_path(run, tmp_path, name):
    out = tmp_path / "o" / "pose.png"
    r = run(picture(tmp_path / name), "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(out)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert [p.name for p in out.parent.iterdir()] == ["pose.png"]     # 一時ファイル・別の拡張子を残さない


def test_default_path_follows_the_format(run, tmp_path):
    r = run(picture(tmp_path / "a.jpg"), "-n", "x")
    assert r.returncode == 0, r.stderr
    got = Path(r.stdout.strip())
    assert got.suffix == ".jpg" and got.parent == tmp_path / "Pictures" / "generated" and got.exists()


def test_not_an_image_is_rejected(run, tmp_path):
    src = tmp_path / "a.txt"; src.write_text("hello, this is not an image")
    r = run(src, "-o", str(tmp_path / "o.png"))
    assert r.returncode == 6 and not (tmp_path / "o.png").exists()


def test_existing_output_gets_a_new_name_with_the_same_extension(run, tmp_path):
    out = tmp_path / "o.png"; out.write_bytes(b"old")
    r = run(picture(tmp_path / "a.jpg"), "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(tmp_path / "o-v2.png") and out.read_bytes() == b"old"
