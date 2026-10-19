"""qwenimg（vm poses / vm hands の --img qwen）: ComfyUI に渡すつなぎ方、左右が反転した絵の見分け、引数と環境の誤りで終了コード 2 を返すこと。
GPU と ComfyUI は CI に無いので、実際に描くところは手元で確かめる。"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
QDIR = ROOT / "skills/video-mascot/scripts/qwenimg"
sys.path.insert(0, str(QDIR))
import qwenimg  # noqa: E402
import poses  # noqa: E402


def test_graph_wires_all_references():
    g = qwenimg.graph("make three fingers", ["vm/a.png", "vm/b.png"], seed=7, prefix="t")
    loads = [v["inputs"]["image"] for v in g.values() if v["class_type"] == "LoadImage"]
    assert loads == ["vm/a.png", "vm/b.png"]
    enc = [v for v in g.values() if v["class_type"] == "TextEncodeQwenImageEditPlus"]
    assert len(enc) == 2 and all("image1" in e["inputs"] and "image2" in e["inputs"] for e in enc)
    assert {e["inputs"]["prompt"] for e in enc} == {"make three fingers", ""}
    ks = next(v for v in g.values() if v["class_type"] == "KSampler")["inputs"]
    assert ks["seed"] == 7 and ks["steps"] == 4 and ks["cfg"] == 1.0
    assert any(v["class_type"] == "LoraLoaderModelOnly" for v in g.values())
    with pytest.raises(ValueError):
        qwenimg.graph("x", ["1", "2", "3", "4"])


def test_flipped_detects_mirrored_output():
    rng = np.random.default_rng(0)
    ref = np.zeros((200, 200, 3), np.uint8); ref[:, :70] = 220; ref[40:160, 120:180] = 90
    ref = np.clip(ref.astype(int) + rng.integers(-5, 5, ref.shape), 0, 255).astype(np.uint8)
    same = ref.copy(); same[90:110, 130:170] = 30                      # 指を描き足した程度の違い
    assert not qwenimg.flipped(same, ref)
    assert qwenimg.flipped(same[:, ::-1].copy(), ref)


def run(*args, env=None):
    return subprocess.run([sys.executable, "-B", str(QDIR / "qwenimg.py"), *map(str, args)], capture_output=True, text=True, timeout=60, env=env)


def test_argument_and_environment_errors_exit_2(tmp_path):
    assert run("-p", "x", "-o", tmp_path / "o.png").returncode == 2          # 参照なし
    ref = tmp_path / "r.png"; ref.write_bytes(b"x")
    assert run("-p", "x", "-o", tmp_path / "o.png", "-r", tmp_path / "missing.png").returncode == 2
    assert run("-p", "x", "-o", tmp_path / "o.png", *sum([["-r", ref]] * 4, [])).returncode == 2
    env = dict(os.environ, VS_COMFY_ROOT=str(tmp_path / "nocomfy"))
    r = run("-p", "x", "-o", tmp_path / "o.png", "-r", ref, env=env)
    assert r.returncode == 2 and "ComfyUI" in r.stderr


def test_backend_qwen_is_serial():
    assert poses.img_backend(["--img", "qwen"], {}) == "qwen"
    assert poses.img_backend([], {"img": "qwen"}) == "qwen"
    tool, parallel = poses.img_tool("qwen", False)
    assert tool.endswith("qwenimg.sh") and parallel is False
    assert os.access(tool, os.X_OK)
