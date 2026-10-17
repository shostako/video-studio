"""vm hands（opt-in）: 手のアップを描いて元の姿勢にはめ込む。合成のマスコット（tests/fixtures/synth_mascot.py）の home の右手の所に
「描いた手」（四角い印を足した切り抜き）を置き、はめた絵が box の外では元の絵のまま・box の中では手の絵になること、
描く仕事が base の切り抜きを参照に渡すこと、vm poses がその姿勢を全身の絵として描かないことを確かめる。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
HANDS = ROOT / "skills/video-mascot/scripts/hands.py"
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import synth_mascot  # noqa: E402

BOX = [250, 380, 330, 480]          # 合成のマスコットの向かって右の腕の先のあたり


def proj(tmp_path):
    p = Path(synth_mascot.make(str(tmp_path / "proj")))
    cfg = json.loads((p / "config.json").read_text(encoding="utf-8"))
    cfg["poses"]["count_3"] = {"desc": "three fingers", "refs": ["home"]}
    cfg["mascot"] = {"description": "a synthetic figure"}
    cfg["hands"] = {"count_3": {"base": "home", "box": BOX, "desc": "the hand shows three. Count check: 3 + 1 + thumb."}}
    (p / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


def run(*args):
    return subprocess.run([sys.executable, "-B", str(HANDS), *map(str, args)], capture_output=True, text=True, timeout=120)


def drawn_hand(p):
    """描いた手の代わり: base の切り抜きを2倍にし、真ん中に指の代わりの四角を描く。"""
    base = cv2.imread(str(p / "poses/pose_home.png")); x0, y0, x1, y1 = BOX
    h = cv2.resize(base[y0:y1, x0:x1], ((x1 - x0) * 2, (y1 - y0) * 2))
    cy, cx = h.shape[0] // 2, h.shape[1] // 2; h[cy - 30:cy + 30, cx - 20:cx + 20] = (0, 0, 255)
    (p / "hands").mkdir(exist_ok=True); cv2.imwrite(str(p / "hands/count_3.png"), h)


def test_place_changes_only_inside_the_box(tmp_path):
    p = proj(tmp_path); drawn_hand(p)
    r = run(p, "place")
    assert r.returncode == 0, r.stdout + r.stderr
    base = cv2.imread(str(p / "poses/pose_home.png")).astype(int); out = cv2.imread(str(p / "poses/pose_count_3.png")).astype(int)
    x0, y0, x1, y1 = BOX
    outside = np.ones(base.shape[:2], bool); outside[y0:y1, x0:x1] = False
    assert np.abs(out - base)[outside].max() == 0                     # 体は base のまま
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    assert tuple(out[cy, cx]) == (0, 0, 255)                         # 手の絵の印が入った
    e = max(2, min(x1 - x0, y1 - y0) // 20)
    assert np.abs(out - base)[y0, x0:x1].max() == 0                   # box の縁は元の絵（四角い継ぎ目を出さない）


def test_place_does_not_overwrite_without_force(tmp_path):
    p = proj(tmp_path); drawn_hand(p)
    assert run(p, "place").returncode == 0
    before = (p / "poses/pose_count_3.png").read_bytes()
    r = run(p, "place")
    assert "--force" in r.stdout and (p / "poses/pose_count_3.png").read_bytes() == before


def test_draw_jobs_pass_the_base_crop_and_vm_poses_skips_the_pose(tmp_path):
    p = proj(tmp_path)
    sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
    from lib import Proj
    import hands
    import poses
    P = Proj(str(p))
    (out, prompt, refs), = hands.jobs_draw(P, ["count_3"])
    assert out.endswith("hands/count_3.png") and "Count check" in prompt and "do NOT draw any extra finger" in prompt
    ref = cv2.imread(refs[0]); x0, y0, x1, y1 = BOX
    assert ref.shape[:2] == ((y1 - y0) * hands.SCALE, (x1 - x0) * hands.SCALE)
    assert not any(os.path.basename(j[0]) == "pose_count_3.png" for j in poses.jobs_poses(P))


def test_without_hands_config_vm_poses_is_unchanged(tmp_path):
    p = Path(synth_mascot.make(str(tmp_path / "proj2")))
    cfg = json.loads((p / "config.json").read_text(encoding="utf-8")); cfg["mascot"] = {"description": "a synthetic figure"}
    (p / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
    from lib import Proj
    import poses
    assert sorted(os.path.basename(j[0]) for j in poses.jobs_poses(Proj(str(p)))) == ["pose_home.png", "pose_point.png"]
