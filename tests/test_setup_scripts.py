"""setup.sh と入口（vm・vs）のシェルの部品。venv の Python の探し方（Linux・WSL は bin/python、Windows は Scripts/python.exe）と構文。
vpy() が自分を呼んで止まらなくなった事故（2026-11-01、Windows への移植の途中）を繰り返さないよう、時間の上限を付けて呼ぶ。"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCENE_SETUP = ROOT / "skills/video-scene/scripts/setup.sh"
SHELL_SCRIPTS = [SCENE_SETUP, ROOT / "skills/video-mascot/scripts/setup.sh", ROOT / "skills/video-mascot/scripts/vm",
                 ROOT / "skills/video-scene/scripts/vs", ROOT / "scripts/link-skills.sh"]


def vpy(home):
    """setup.sh の VS_HOME・VENV・vpy() だけを取り出して呼ぶ。"""
    lines = [l for l in SCENE_SETUP.read_text(encoding="utf-8").splitlines() if l.startswith(("VS_HOME=", "VENV=", "vpy()"))]
    assert len(lines) == 3, lines
    assert "$(vpy)" not in lines[2], "vpy() が自分を呼んでいる（呼ぶとシェルが増え続ける）"   # 呼ぶ前に止める
    r = subprocess.run(["bash", "-c", "\n".join(lines) + '\nvpy'], env=dict(os.environ, VIDEO_SCENE_HOME=str(home)),
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
    return r.stdout


def make_exe(p):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text("#!/bin/sh\n"); p.chmod(0o755)


def test_vpy_finds_linux_and_windows_venv(tmp_path):
    assert vpy(tmp_path) == ""                                        # venv が無い
    make_exe(tmp_path / "venv/Scripts/python.exe")
    assert vpy(tmp_path) == str(tmp_path / "venv/Scripts/python.exe")   # Windows の venv
    make_exe(tmp_path / "venv/bin/python")
    assert vpy(tmp_path) == str(tmp_path / "venv/bin/python")           # bin/python があればそちら


def test_vpy_does_not_call_itself():
    body = next(l for l in SCENE_SETUP.read_text(encoding="utf-8").splitlines() if l.startswith("vpy()"))
    assert "$(vpy)" not in body


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_shell_syntax(script):
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("smi, want", [("exit 0", "cu128"), ("exit 9", "cpu"), (None, "cpu")])
def test_irodori_extra_follows_the_gpu(tmp_path, smi, want):
    lines = (ROOT / "skills/video-mascot/scripts/setup.sh").read_text(encoding="utf-8").splitlines()
    fn = next(l for l in lines if l.startswith("irodori_extra()"))
    bindir = tmp_path / "bin"; bindir.mkdir()
    if smi: (bindir / "nvidia-smi").write_text(f"#!/bin/sh\n{smi}\n"); (bindir / "nvidia-smi").chmod(0o755)
    r = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-c", fn + "\nirodori_extra"], env={"PATH": str(bindir)}, capture_output=True, text=True, timeout=10)
    assert r.stdout.strip() == want


def test_explain_runs_the_precheck_before_compose():
    src = (ROOT / "skills/video-mascot/scripts/explain.py").read_text(encoding="utf-8")
    assert src.index('step("マスコットの下見"') < src.index('compose_step(f"画面の組み立て（余白あり')
