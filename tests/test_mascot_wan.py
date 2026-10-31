"""姿勢の切り替えを Wan2.2 の First-Last-Frame で動かす（config.interp.engine: "wan"、opt-in）。
純関数（設定・崩れたコマの見つけ方・動きの量での割り付け・端の重ね・下半身の横の固定）と、ComfyUI と RIFE を差し替えた wanflf.dense_paths、
合成のマスコットでの vm render の書き出し。ComfyUI・GPU・RIFE はここでは使わない。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import lib  # noqa: E402
import synth_mascot as sm  # noqa: E402
import wanflf  # noqa: E402

RENDER = ROOT / "skills/video-mascot/scripts/render.py"


# ---------- 設定 ----------
def test_interp_config_wan_fills_defaults():
    c = lib.interp_config({"engine": "wan"})
    assert c["engine"] == "wan" and c["wan"] == lib.WAN_DEFAULTS
    c = lib.interp_config({"engine": "wan", "wan": {"length": 17, "rife_pairs": ["home>nod"], "head_poses": ["look_l"]}})
    assert c["wan"]["length"] == 17 and c["wan"]["rife_pairs"] == ["home>nod"] and c["wan"]["width"] == 704


def test_interp_flag_wan_switches_engine_and_keeps_other_items():
    c = lib.interp_config({"dur": 0.8}, "wan")
    assert c["engine"] == "wan" and c["dur"] == 0.8 and c["wan"]["length"] == 13
    assert lib.interp_config(None, "wan")["engine"] == "wan"
    assert lib.interp_config({"engine": "wan"}, "rife")["wan"] is None           # --interp rife で RIFE に戻せる
    assert lib.interp_config({"engine": "wan"}, "off") is None


@pytest.mark.parametrize("bad", [
    {"nope": 1}, {"width": 700}, {"height": 32}, {"length": 12}, {"length": 3}, {"rife_mult": 0}, {"cut_tol": -1}, {"edge": 0.5},
    {"rife_pairs": "home>nod"}, {"rife_pairs": ["home"]}, {"head_poses": "look_l"}, {"width": True},
])
def test_wan_config_rejects(bad):
    with pytest.raises(ValueError):
        lib.interp_config({"engine": "wan", "wan": bad})


def test_interp_engine_rejects_unknown():
    with pytest.raises(ValueError): lib.interp_config({"engine": "film"})
    with pytest.raises(ValueError): lib.interp_config(None, "film")


# ---------- 純関数 ----------
def test_wan_cut_drops_from_the_first_drifted_frame():
    assert lib.wan_cut([253, 253, 252, 251, 250, 244, 232, 239], 5) == 5     # 244 で 1 コマ目から 9 ずれる
    assert lib.wan_cut([253, 252, 253], 5) == 3
    assert lib.wan_cut([253], 5) == 1


def test_motion_positions_follow_the_motion():
    p = lib.motion_positions([1, 1, 1, 1], 5)                                   # 同じ動き: 等間隔
    assert np.allclose(p, [0, 1, 2, 3, 4])
    p = lib.motion_positions([0, 0, 0, 10], 11)                                 # 動きが最後に詰まっている: 位置もそこへ寄る
    assert p[0] == 0 and p[-1] == 4 and np.all(np.diff(p) >= 0)
    assert (p > 3).sum() >= 8                                                   # 11 個のうち大半が最後の区間
    with pytest.raises(ValueError): lib.motion_positions([1], 1)


def test_edge_weight():
    assert lib.edge_weight(0.0, 0.15) == (1.0, 0.0) and lib.edge_weight(1.0, 0.15) == (0.0, 1.0)
    assert lib.edge_weight(0.5, 0.15) == (0.0, 0.0) and lib.edge_weight(0.3, 0) == (0.0, 0.0)
    wa, _ = lib.edge_weight(0.1, 0.15); assert 0 < wa < 1


def test_legs_config_fix_x():
    poses = {"home": {}, "point": {}}
    assert lib.legs_config(True, poses, "home")["fix_x"] is False
    assert lib.legs_config({"fix_x": True}, poses, "home")["fix_x"] is True
    with pytest.raises(ValueError): lib.legs_config({"fix_x": "yes"}, poses, "home")


def test_lock_legs_fixed_dx_does_not_search():
    canon = np.ascontiguousarray(np.array(sm.figure(0))[:, :, ::-1])
    img = np.roll(canon, 12, axis=1)                                            # 体ごと 12px 右にずれた絵
    _, searched = lib.lock_legs(img, canon)
    _, fixed = lib.lock_legs(img, canon, dx=0)
    assert searched["dx"] != 0 and fixed["dx"] == 0


# ---------- wanflf.dense_paths（ComfyUI と RIFE は差し替え） ----------
def bgr(im): return np.ascontiguousarray(np.array(im)[:, :, ::-1])


@pytest.fixture()
def proj(tmp_path):
    return lib.Proj(sm.make(str(tmp_path / "proj")))


def fake_gen(calls, dark_tail=4):
    """姿勢 a→b を直線で溶かした 13 コマ。最後の dark_tail コマは暗くする（Wan の FLF の崩れを真似る）。"""
    def gen(P, a, b, wan, raw_dir, log=None):
        calls.append((a, b))
        A = cv2.resize(P.read_pose(a), (wan["width"], wan["height"])); B = cv2.resize(P.read_pose(b), (wan["width"], wan["height"]))
        os.makedirs(raw_dir, exist_ok=True)
        for i in range(wan["length"]):
            u = i / (wan["length"] - 1); im = cv2.addWeighted(A, 1 - u, B, u, 0)
            if i >= wan["length"] - dark_tail: im = (im * 0.85).astype(np.uint8)
            cv2.imwrite(os.path.join(raw_dir, f"w{i + 1:02d}.png"), im)
    return gen


def fake_rife(frames, mult, icfg, tag):
    out = []
    for a, b in zip(frames, frames[1:]):
        out += [cv2.addWeighted(a, 1 - j / mult, b, j / mult, 0) for j in range(mult)]
    return out + [frames[-1]]


def test_dense_paths_cuts_dark_tail_and_lands_on_the_poses(proj):
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 4}})
    calls = []
    paths = wanflf.dense_paths(proj, "home", "point", 47, icfg, gen=fake_gen(calls), rife=fake_rife)
    assert len(paths) == 47 and all(os.path.exists(p) for p in paths) and calls == [("home", "point")]
    A, B = proj.read_pose("home").astype(int), proj.read_pose("point").astype(int)
    first, last = cv2.imread(paths[0]).astype(int), cv2.imread(paths[-1]).astype(int)
    assert np.abs(first - A).mean() < np.abs(first - B).mean()                  # 始まりは a に近く
    assert np.abs(last - B).mean() < 3                                          # 終わりは b の絵に着く（暗いコマは捨てた）
    levels = [wanflf.bg_level(cv2.imread(p)) for p in paths]
    assert min(levels) > wanflf.bg_level(proj.read_pose("home")) - 5            # 暗くなったコマが混ざらない


def test_dense_paths_reuses_the_cache(proj):
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2}})
    calls = []
    p1 = wanflf.dense_paths(proj, "home", "point", 11, icfg, gen=fake_gen(calls), rife=fake_rife)
    p2 = wanflf.dense_paths(proj, "home", "point", 11, icfg, gen=fake_gen(calls), rife=fake_rife)
    assert p1 == p2 and calls == [("home", "point")]                           # 2 回目は作り直さない
    icfg2 = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2, "seed": 7}})
    wanflf.dense_paths(proj, "home", "point", 11, icfg2, gen=fake_gen(calls), rife=fake_rife)
    assert len(calls) == 2                                                      # 生成に効く値が変われば作り直す


def test_dense_paths_regenerates_when_the_mascot_description_changes(proj):
    """interp.wan.style を書かない時は config.mascot.description が描かせる文に入る。説明を直したら作り直す。"""
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2}})
    calls = []
    wanflf.dense_paths(proj, "home", "point", 11, icfg, gen=fake_gen(calls), rife=fake_rife)
    proj.cfg["mascot"] = {"description": "a different mascot with a red scarf"}
    wanflf.dense_paths(proj, "home", "point", 11, icfg, gen=fake_gen(calls), rife=fake_rife)
    assert len(calls) == 2


def test_prompt_of_head_poses():
    cfg = {"mascot": {"description": "a mascot"}, "poses": {"home": {"desc": "standing"}, "look_l": {"desc": "looks left"}}}
    wan = lib.wan_config({"head_poses": ["look_l"]})
    t = wanflf.prompt_of(cfg, wan, "home", "look_l")
    assert "turns only her head" in t and "head stays still" not in t and "looks left" in t
    t = wanflf.prompt_of(cfg, lib.wan_config({}), "home", "look_l")
    assert "head stays still" in t


# ---------- vm render の書き出し（Wan の列は先にためておく） ----------
@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


MAGENTA = (255, 0, 255)


def marked_gen(P, a, b, wan, raw_dir, log=None):
    """姿勢の間を溶かしたコマの胴に、マゼンタの印を描く（書き出しに Wan の列が使われたかを見分ける）。"""
    A = cv2.resize(P.read_pose(a), (wan["width"], wan["height"])); B = cv2.resize(P.read_pose(b), (wan["width"], wan["height"]))
    os.makedirs(raw_dir, exist_ok=True)
    for i in range(wan["length"]):
        u = i / (wan["length"] - 1); im = cv2.addWeighted(A, 1 - u, B, u, 0)
        if 0 < i < wan["length"] - 1:
            h, w = im.shape[:2]; cv2.rectangle(im, (int(w * 0.40), int(h * 0.45)), (int(w * 0.58), int(h * 0.58)), MAGENTA, -1)
        cv2.imwrite(os.path.join(raw_dir, f"w{i + 1:02d}.png"), im)


def read_frames(path):
    cap = cv2.VideoCapture(str(path)); out = []
    while True:
        ok, f = cap.read()
        if not ok: break
        out.append(f)
    return out


def magenta_px(f):
    b, g, r = f[:, :, 0].astype(int), f[:, :, 1].astype(int), f[:, :, 2].astype(int)
    return int(((r > 150) & (b > 150) & (g < 110)).sum())


def test_render_engine_wan_wins_over_transition_fade(tmp_path, env):
    """config.transition（中割りの無い組を溶かす）を書いていても、engine: wan の組は Wan の列で動く。events の via は優先のまま。"""
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj"))
    cfgp = os.path.join(root, "config.json"); cfg = json.load(open(cfgp))
    cfg["pairs"] = []                                                           # 中割りを描いていない組
    cfg["transition"] = {"mode": "fade", "dur": 0.5}
    cfg["interp"] = {"engine": "wan", "mult": 4, "wan": {"width": 240, "height": 384, "rife_mult": 1, "edge": 0.05}}
    json.dump(cfg, open(cfgp, "w"))
    P = lib.Proj(root); icfg = lib.interp_config(cfg["interp"])
    n = P.ib_div * icfg["mult"] - 1
    for a, b in (("home", "point"), ("point", "home")):
        wanflf.dense_paths(P, a, b, n, icfg, gen=marked_gen, rife=fake_rife)
    out = tmp_path / "w.mp4"
    r = subprocess.run([sys.executable, "-B", str(RENDER), root, "--mode", "white", "--out", str(out)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert max(magenta_px(f) for f in read_frames(out)) > 30                    # 溶かしでなく Wan の列が出た

    cfg["events"][0]["via"] = "cut"                                             # via を書いた切り替えは via が優先
    cfg["events"] = cfg["events"][:1]
    json.dump(cfg, open(cfgp, "w"))
    out2 = tmp_path / "w2.mp4"
    r = subprocess.run([sys.executable, "-B", str(RENDER), root, "--mode", "white", "--out", str(out2)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert max(magenta_px(f) for f in read_frames(out2)) <= 30


def test_render_with_engine_wan(tmp_path, env):
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj"))
    cfgp = os.path.join(root, "config.json"); cfg = json.load(open(cfgp))
    cfg["interp"] = {"engine": "wan", "mult": 4, "wan": {"width": 240, "height": 384, "rife_mult": 1}}
    cfg["legs_lock"] = {"fix_x": True}
    json.dump(cfg, open(cfgp, "w"))
    P = lib.Proj(root); icfg = lib.interp_config(cfg["interp"])
    n = P.ib_div * icfg["mult"] - 1
    for a, b in (("home", "point"), ("point", "home")):                         # render が使う組を先にためる（ComfyUI は呼ばない）
        wanflf.dense_paths(P, a, b, n, icfg, gen=fake_gen([]), rife=fake_rife)
    out = tmp_path / "w.mp4"
    r = subprocess.run([sys.executable, "-B", str(RENDER), root, "--mode", "white", "--out", str(out)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert out.exists() and out.stat().st_size > 0
