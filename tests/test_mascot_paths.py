"""手元の PC だけの決め打ちを外した所: RIFE・ComfyUI・一時フォルダの場所を環境変数で変えられ、Windows の無い所でも置き場が決まる。"""
import os
import subprocess
import sys
from pathlib import Path

import lib

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "video-mascot" / "scripts"


def test_rife_tmp_precedence(monkeypatch, tmp_path):
    assert lib.rife_tmp({"tmp": "/x/y"}) == "/x/y"                          # config.interp.tmp が勝つ
    monkeypatch.setattr(lib, "_WIN_HOME", str(tmp_path / "win"))
    assert lib.rife_tmp({"tmp": None}) == str(tmp_path / "win" / "AppData" / "Local" / "Temp" / "vm_rife")
    monkeypatch.setattr(lib, "_WIN_HOME", "")                               # Windows が無い（CI など）
    assert lib.rife_tmp({}).endswith("vm_rife") and not lib.rife_tmp({}).startswith("/mnt/c")


def test_env_overrides_defaults(tmp_path):
    env = dict(os.environ, VM_RIFE_EXE="/opt/rife/rife.exe", VM_RIFE_TMP=str(tmp_path / "t"), VM_COMFY_ROOT="/opt/comfy", VM_WIN_HOME="/mnt/x/Users/u")
    code = ("import lib; print(lib.INTERP_DEFAULTS['exe']); print(lib.rife_tmp(lib.INTERP_DEFAULTS)); "
            "print(lib.WAN_DEFAULTS['comfy']); print(lib.win_home())")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(SCRIPTS), env=env).stdout.split()
    assert out == ["/opt/rife/rife.exe", str(tmp_path / "t"), "/opt/comfy", "/mnt/x/Users/u"]


def test_no_user_name_is_hardcoded():
    """スキルのスクリプトに、特定の Windows のユーザー名のパスを書かない。"""
    bad = []
    for p in (SCRIPTS.parent.parent).rglob("*.py"):
        if "assets" in p.parts or "qwenimg" in p.parts: continue
        t = p.read_text(encoding="utf-8", errors="ignore")
        if "/mnt/c/Users/shost" in t or "C:\\\\Users\\\\shost" in t: bad.append(str(p))
    assert bad == []
