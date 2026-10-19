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


def test_staged_references_are_removed_even_on_failure(tmp_path, monkeypatch):
    """ComfyUI に渡す参照の写しは、失敗しても消す。h3 は合成のもの（ComfyUI を起こせない）。"""
    import types
    root = tmp_path / "comfy"
    for sub in ("unet", "text_encoders", "vae", "loras"): (root / "ComfyUI/models" / sub).mkdir(parents=True)
    for kind, sub in (("unet", "unet"), ("clip", "text_encoders"), ("vae", "vae"), ("lora", "loras")):
        (root / "ComfyUI/models" / sub / qwenimg.MODELS[kind]).write_bytes(b"")
    fake = types.SimpleNamespace(ROOT=str(root), VS_DIR=str(tmp_path / "vs"), SERVER_ARGS=[], winpath=lambda p: p, client=lambda *a, **k: 1)
    monkeypatch.setitem(sys.modules, "h3", fake)
    ref = tmp_path / "r.png"; ref.write_bytes(b"x")
    monkeypatch.setattr(sys, "argv", ["qwenimg.py", "-p", "x", "-o", str(tmp_path / "o.png"), "-r", str(ref), "-r", str(ref)])
    with pytest.raises(SystemExit) as e:
        qwenimg.main()
    assert e.value.code == 2
    assert list((root / "ComfyUI/input/vm").iterdir()) == []


def test_attempt_files_are_removed_on_failure(tmp_path, monkeypatch):
    """ComfyUI が失敗を返しても、ジョブ・結果・GPU の記録・出た絵を残さない。"""
    import json as _json
    import types
    root = tmp_path / "comfy"; vs = tmp_path / "vs"; vs.mkdir(); (root / "ComfyUI/output/vm").mkdir(parents=True)
    for sub in ("unet", "text_encoders", "vae", "loras"): (root / "ComfyUI/models" / sub).mkdir(parents=True)
    for kind, sub in (("unet", "unet"), ("clip", "text_encoders"), ("vae", "vae"), ("lora", "loras")):
        (root / "ComfyUI/models" / sub / qwenimg.MODELS[kind]).write_bytes(b"")
    def client(cmd, *args):
        if cmd == "run":
            rp = Path(args[1]); (root / "ComfyUI/output/vm/x.png").write_bytes(b"png")
            Path(str(rp)[:-5] + "_gpu.csv").write_text("gpu")
            rp.write_text(_json.dumps({"status": "error", "outputs": [{"filename": "x.png", "subfolder": "vm"}]}))
        return 0
    monkeypatch.setitem(sys.modules, "h3", types.SimpleNamespace(ROOT=str(root), VS_DIR=str(vs), SERVER_ARGS=[], winpath=lambda p: p, client=client))
    ref = tmp_path / "r.png"; ref.write_bytes(b"x")
    monkeypatch.setattr(sys, "argv", ["qwenimg.py", "-p", "x", "-o", str(tmp_path / "o.png"), "-r", str(ref)])
    with pytest.raises(SystemExit) as e:
        qwenimg.main()
    assert e.value.code == 1
    assert list(vs.iterdir()) == [] and list((root / "ComfyUI/output/vm").iterdir()) == []


def test_qwen_refuses_jobs_with_more_than_three_references(tmp_path, capsys):
    for i in range(4): (tmp_path / f"r{i}.png").write_bytes(b"x")
    jobs = [(str(tmp_path / "a.png"), "x", [str(tmp_path / f"r{i}.png") for i in range(4)])]
    assert poses.run_jobs(jobs, 1, False, backend="qwen") is False
    assert "3枚まで" in capsys.readouterr().out and not (tmp_path / "a.png").exists()
