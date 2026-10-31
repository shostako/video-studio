"""頭の向きの列（config.head、opt-in）と、Wan の勝手な瞬きを捨てる処理（interp.wan.blink_tol）。
純関数・合成のマスコットでの vm render（RIFE の列は先にためておく）。RIFE・ComfyUI・GPU はここでは使わない。"""
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
import interp  # noqa: E402
import lib  # noqa: E402
import synth_mascot as sm  # noqa: E402
import wanflf  # noqa: E402

RENDER = ROOT / "skills/video-mascot/scripts/render.py"
POSES = {"home": {}, "look_l": {}, "look_r": {}, "point": {}}


# ---------- head_config / head_pos ----------
def test_head_config():
    assert lib.head_config(None, POSES) is None and lib.head_config(False, POSES) is None
    c = lib.head_config({"chain": ["look_r", "home", "look_l"], "events": [{"at": 1.0, "pose": "look_l"}]}, POSES)
    assert c["mult"] == 6 and c["chain"] == ["look_r", "home", "look_l"]


@pytest.mark.parametrize("bad", [
    {"chain": ["home"]}, {"chain": "home"}, {"chain": ["home", "home"]}, {"chain": ["home", "nope"]},
    {"chain": ["home", "look_l"], "events": [{"at": 1.0, "pose": "point"}]}, {"chain": ["home", "look_l"], "events": "x"},
    {"chain": ["home", "look_l"], "mult": 0}, {"chain": ["home", "look_l"], "mult": True}, {"chain": ["home", "look_l"], "nope": 1}, "on",
])
def test_head_config_rejects(bad):
    with pytest.raises(ValueError):
        lib.head_config(bad, POSES)


def test_head_pos_moves_between_keys_and_eases():
    idx = {"look_r": 0, "home": 36, "look_l": 72}
    keys = [(1.0, "home"), (2.0, "look_l"), (3.0, "look_r")]
    assert lib.head_pos(0.5, keys, idx) is None and lib.head_pos(3.0, keys, idx) is None   # 外
    assert lib.head_pos(1.0, keys, idx) == 36 and lib.head_pos(2.0, keys, idx) == 72
    assert lib.head_pos(1.5, keys, idx) == pytest.approx(54)                    # 真ん中
    assert lib.head_pos(1.1, keys, idx) - 36 < 0.1 * 36                         # 動き出しは緩やか
    assert lib.head_pos(2.5, keys, idx) == pytest.approx(36)                    # look_l→look_r の真ん中は home
    assert lib.head_pos(1.0, [(1.0, "home")], idx) is None


# ---------- 瞬きのコマ ----------
@pytest.fixture()
def proj(tmp_path):
    return lib.Proj(sm.make(str(tmp_path / "proj")))


def with_part(P, pose, key):
    img = P.read_pose(pose).copy(); x, y = json.load(open(P.p(f"parts_{pose}", "parts.json")))[key]
    part = cv2.imread(P.p(f"parts_{pose}", f"{key}.png"), cv2.IMREAD_UNCHANGED); h, w = part.shape[:2]; al = part[:, :, 3:] / 255.0
    img[y:y + h, x:x + w] = (part[:, :, :3] * al + img[y:y + h, x:x + w] * (1 - al)).astype(np.uint8)
    return img


def test_blink_frames_finds_closed_eyes(proj):
    size = (240, 384)
    pats = [wanflf.eye_patches(proj, "home", size)]
    assert pats[0] is not None
    op = cv2.resize(proj.read_pose("home"), size, interpolation=cv2.INTER_AREA)
    cl = cv2.resize(with_part(proj, "home", "e2"), size, interpolation=cv2.INTER_AREA)
    frames = [op, op, cl, cl, op, op]
    assert wanflf.blink_frames(frames, pats, 0.05) == [2, 3]
    assert wanflf.blink_frames([cl, cl, op], pats, 0.05) == [1]                 # 1 コマ目（始点の絵）は見ない
    assert wanflf.blink_frames(frames, [], 0.05) == []


def test_eye_patches_none_without_parts(proj):
    shutil.rmtree(proj.p("parts_point"))
    assert wanflf.eye_patches(proj, "point", (240, 384)) is None


def test_wan_config_blink_tol():
    assert lib.interp_config({"engine": "wan"})["wan"]["blink_tol"] == 0.05
    assert lib.interp_config({"engine": "wan", "wan": {"blink_tol": None}})["wan"]["blink_tol"] is None
    for bad in (-0.1, True, "x"):
        with pytest.raises(ValueError): lib.interp_config({"engine": "wan", "wan": {"blink_tol": bad}})


def test_dense_paths_drops_blink_frames(proj):
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 1, "edge": 0.0}})
    cl = with_part(proj, "home", "e2")

    def gen(P, a, b, wan, raw_dir, log=None):
        A = cv2.resize(P.read_pose(a), (wan["width"], wan["height"])); C = cv2.resize(cl, (wan["width"], wan["height"]))
        os.makedirs(raw_dir, exist_ok=True)
        for i in range(wan["length"]):
            cv2.imwrite(os.path.join(raw_dir, f"w{i + 1:04d}.png"), C if i in (3, 4, 5) else A)

    def rife(frames, mult, cfg, tag): return list(frames)
    logs = []
    paths = wanflf.dense_paths(proj, "home", "home", 11, icfg, log=logs.append, gen=gen, rife=rife)
    pats = [wanflf.eye_patches(proj, "home", (proj.read_pose("home").shape[1], proj.read_pose("home").shape[0]))]
    assert all(wanflf.blink_score(cv2.cvtColor(cv2.imread(p), cv2.COLOR_BGR2GRAY), pats) <= 0.05 for p in paths)   # 閉じた目が混ざらない
    assert any("瞬き [4, 5, 6]" in m for m in logs)


# ---------- vm render の書き出し ----------
@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def fill_direct(P, pa, pb, mult):
    """interp.dense_paths（direct）がためる列を、RIFE の代わりに直線の溶かしで作っておく。"""
    cfg = dict(lib.INTERP_DEFAULTS); cfg["mult"] = mult; div = P.ib_div; tot = mult * div
    srcs = [P.pose_path(pa), P.pose_path(pb)]
    out = P.p("ib_interp", f"{pa}_{pb}_direct_x{tot}_{cfg['model']}"); os.makedirs(out, exist_ok=True)
    A, B = P.read_pose(pa), P.read_pose(pb)
    for j in range(1, tot):
        cv2.imwrite(os.path.join(out, f"f{j}.png"), cv2.addWeighted(A, 1 - j / tot, B, j / tot, 0))
    json.dump(interp._stamp(srcs, cfg), open(os.path.join(out, "stamp.json"), "w"))


def read_frames(path):
    cap = cv2.VideoCapture(str(path)); out = []
    while True:
        ok, f = cap.read()
        if not ok: break
        out.append(f)
    return out


def test_render_head_chain_overrides_the_pose(tmp_path, env):
    """events では home のままでも、head の要所に合わせて頭の向きの列（ここでは home↔point）が動く。外では今までどおり。"""
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj"))
    cfgp = os.path.join(root, "config.json"); cfg = json.load(open(cfgp))
    cfg["events"] = []; cfg["idle"] = False                                   # 息づかいを止めて比べる
    cfg["head"] = {"chain": ["home", "point"], "mult": 2, "events": [{"at": 0.8, "pose": "home"}, {"at": 1.4, "pose": "point"}, {"at": 2.0, "pose": "home"}]}
    json.dump(cfg, open(cfgp, "w"))
    P = lib.Proj(root); fill_direct(P, "home", "point", 2)
    out = tmp_path / "h.mp4"
    r = subprocess.run([sys.executable, "-B", str(RENDER), root, "--mode", "white", "--out", str(out)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "頭の動きの要所" in r.stderr
    fr = read_frames(out); fps = 30
    still, peak, after = fr[int(0.4 * fps)], fr[int(1.4 * fps)], fr[int(2.6 * fps)]
    assert np.abs(peak.astype(int) - still).mean() > 1.0                       # 1.4 秒は point の向き（腕が出ている）
    assert np.abs(after.astype(int) - still).mean() < 0.3 * np.abs(peak.astype(int) - still).mean()   # 動きの後は home に戻る（口の違いだけ）


def test_render_without_head_is_unchanged(tmp_path, env):
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj"))
    out = tmp_path / "n.mp4"
    r = subprocess.run([sys.executable, "-B", str(RENDER), root, "--mode", "white", "--out", str(out)], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "頭の動きの要所" not in r.stderr
