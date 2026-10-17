"""home 経由の切り替え（config.via_home、opt-in）。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
sys.path.insert(0, str(ROOT / "tests/fixtures"))
from lib import via_home_config, home_route, split_via_home, plan_at  # noqa: E402
import synth_mascot  # noqa: E402

PAIRS = {("home", "open"), ("home", "span"), ("open", "point")}
def has(x, y): return (x, y) in PAIRS or (y, x) in PAIRS


def test_config_off_by_default_and_defaults():
    assert via_home_config(None) is None and via_home_config(False) is None
    assert via_home_config(True) == {"hold": 0.0} == via_home_config({})
    assert via_home_config({"hold": 0.2}) == {"hold": 0.2}


@pytest.mark.parametrize("bad", [{"hold": -0.1}, {"hold": True}, {"hold": float("nan")}, {"hold": "0.1"}, {"wait": 1}, "yes", 1])
def test_config_rejects(bad):
    with pytest.raises(ValueError): via_home_config(bad)


def test_home_route_only_when_both_legs_are_drawn():
    assert home_route("open", "span", "home", has)                     # 中割りが無く、どちらも home との組がある
    assert not home_route("open", "point", "home", has)                # 中割りがある組はそのまま
    assert not home_route("point", "span", "home", has)                # point→home の中割りが無い
    assert not home_route("home", "span", "home", has) and not home_route("span", "home", "home", has)
    assert not home_route("span", "span", "home", has)


def test_split_puts_home_between_and_keeps_others():
    ev = [(1.0, "home", "open"), (2.0, "open", "span"), (4.0, "span", "home")]
    out = split_via_home(ev, "home", lambda a, b, v: home_route(a, b, "home", has), lambda a, b: 0.4, 0.1)
    assert out == [(1.0, "home", "open"), (2.0, "open", "home"), (2.5, "home", "span"), (4.0, "span", "home")]
    assert ev[1] == (2.0, "open", "span")                               # 元のリストは書き換えない


def test_split_keeps_via_slot_and_skips_when_next_is_too_close():
    ev = [(2.0, "open", "span", None), (2.3, "span", "home", None)]   # home に着く前に次が始まる
    r = lambda a, b, v: v is None and home_route(a, b, "home", has)
    assert split_via_home(ev, "home", r, lambda a, b: 0.4, 0.0) == ev
    ev = [(2.0, "open", "span", None), (3.0, "span", "home", "fade")]
    out = split_via_home(ev, "home", r, lambda a, b: 0.4, 0.0)
    assert out[:2] == [(2.0, "open", "home", None), (2.4, "home", "span", None)] and out[2] == ev[1]


def test_plan_at_walks_through_home():
    ib = lambda a, b: [(f"{a}-{b}", k) for k in range(5)] if has(a, b) else None
    ev = split_via_home([(1.0, "home", "open"), (2.0, "open", "span")], "home",
                        lambda a, b, v: home_route(a, b, "home", has), lambda a, b: 5 / 15, 0.0)
    seen = [plan_at(t, ev, "home", ib, 15, 5) for t in np.arange(1.95, 2.8, 1 / 30)]
    names = [p[1][0] if p[0] == "ib" else p[1] for p in seen]
    assert names[0] == "open" and names[-1] == "span"
    assert "open-home" in names and "home-span" in names
    assert names.index("open-home") < names.index("home-span")
    assert "span" not in names[:names.index("home-span")]               # 一瞬で span に跳ばない


# ---------- 書き出し（合成のマスコット）----------
RENDER = ROOT / "skills/video-mascot/scripts/render.py"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    pytest.importorskip("pykakasi")
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    """home・point と、腕を半分だけ出した point2（home との中割りだけ）。point→point2 の中割りは無い。"""
    root = Path(synth_mascot.make(str(tmp_path_factory.mktemp("vh") / "proj")))
    synth_mascot.figure(0.5).save(root / "poses/pose_point2.png")
    for k in range(1, 6): synth_mascot.figure(k / 12).save(root / f"ib/ib_home_point2_{k}.png")
    shutil.copytree(root / "parts_point", root / "parts_point2")
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    cfg["poses"]["point2"] = {"desc": "left arm out"}; cfg["pairs"].append(["home", "point2"])
    cfg["events"] = [{"at": 0.4, "pose": "point"}, {"at": 1.4, "pose": "point2"}, {"line_start": 2, "offset": 0.6, "pose": "home"}]
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return root


def _render(proj, env, out, via_home):
    cfg = json.loads((proj / "config.json").read_text(encoding="utf-8"))
    if via_home is None: cfg.pop("via_home", None)
    else: cfg["via_home"] = via_home
    (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(proj), "--out", str(out), "--mode", "white"],
                       env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "gray", "-"], env=env, capture_output=True, check=True).stdout
    ow = 2 * round(384 * (synth_mascot.W + 80) / synth_mascot.H / 2)
    return np.frombuffer(raw, np.uint8).reshape(-1, 384, ow).astype(np.int16)


def test_render_via_home_passes_home_only_when_on(proj, env, tmp_path):
    off, on = _render(proj, env, tmp_path / "off.mp4", None), _render(proj, env, tmp_path / "on.mp4", True)
    assert len(off) == len(on)
    f0 = int(1.4 * 30)
    assert np.abs(off[:f0 - 1] - on[:f0 - 1]).mean() < 0.5               # 切り替えの前は同じ
    jump = lambda v: np.abs(np.diff(v[f0 - 2:f0 + 14], axis=0)).mean(axis=(1, 2)).max()
    assert jump(on) < jump(off) * 0.85                                    # 一瞬で跳ばず、中割りを通って移る
    to_home = lambda v: min(np.abs(v[f] - off[5]).mean() for f in range(f0, f0 + 14))   # off[5] は最初の切り替えの前（home）
    assert to_home(on) < 0.7 * to_home(off)                               # 途中で home の近くを通る（off は point から point2 へ直に跳ぶ）
    assert np.abs(on[f0 + 30] - off[f0 + 30]).mean() < 0.5                 # 着いた先は同じ point2
