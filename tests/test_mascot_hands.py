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


def test_existing_full_body_pose_needs_force_and_is_moved_aside(tmp_path):
    p = proj(tmp_path); drawn_hand(p)
    old = cv2.imread(str(p / "poses/pose_point.png")); cv2.imwrite(str(p / "poses/pose_count_3.png"), old)   # 全身で描いた古い絵
    cv2.imwrite(str(p / "parts/count_3_m1.png"), old); (p / "parts_count_3").mkdir(); (p / "parts_count_3/parts.json").write_text("{}")   # その差分と部品
    before = (p / "poses/pose_count_3.png").read_bytes()
    r = run(p, "place")
    assert r.returncode == 3 and "--force" in r.stdout                       # 黙って成功にしない
    assert (p / "poses/pose_count_3.png").read_bytes() == before
    r = run(p, "place", "--force")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (p / "poses/pose_count_3.png").read_bytes() != before
    moved = list((p / "reject/hands_replaced").glob("count_3_*/poses/pose_count_3.png"))
    assert len(moved) == 1 and moved[0].read_bytes() == before
    assert not (p / "parts/count_3_m1.png").exists() and not (p / "parts_count_3").exists()      # 古い差分・部品も移った
    r = subprocess.run([sys.executable, "-B", str(ROOT / "skills/video-mascot/scripts/parts.py"), str(p), "--borrow", "home", "count_3"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr                                                 # 手順書どおり --borrow が通る


def test_pose_made_by_place_is_replaced_after_redrawing_the_hand(tmp_path):
    p = proj(tmp_path); drawn_hand(p)
    assert run(p, "place").returncode == 0
    h = cv2.imread(str(p / "hands/count_3.png")); cy, cx = h.shape[0] // 2, h.shape[1] // 2
    h[cy - 30:cy + 30, cx - 20:cx + 20] = (0, 255, 0); cv2.imwrite(str(p / "hands/count_3.png"), h)   # 手を描き直した
    cfg = json.loads((p / "config.json").read_text(encoding="utf-8")); cfg["pairs"].append(["home", "count_3"])
    (p / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    for k in (1, 2): cv2.imwrite(str(p / f"ib/ib_home_count_3_{k}.png"), h)              # 古い手で描いた中割り
    cv2.imwrite(str(p / "ib/ib_home_count_3_3_12.png"), h)                                 # 分割数が既定でない中割り
    cv2.imwrite(str(p / "parts/count_2_m1.png"), h)                                        # 名前が似た別の姿勢の差分
    r = run(p, "place")
    assert r.returncode == 0, r.stdout + r.stderr
    x0, y0, x1, y1 = BOX
    assert tuple(cv2.imread(str(p / "poses/pose_count_3.png"))[(y0 + y1) // 2, (x0 + x1) // 2]) == (0, 255, 0)
    assert not list((p / "ib").glob("ib_home_count_3_*.png"))              # 古い手で描いた中割りは使わない
    assert len(list((p / "reject/hands_replaced").glob("count_3_*/ib/ib_home_count_3_1.png"))) == 1
    assert (p / "parts/count_2_m1.png").exists()                            # 名前が似た別の姿勢は動かさない


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


def test_run_jobs_does_not_call_the_tool_for_jobs_whose_reference_is_missing(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
    import poses
    called = []
    monkeypatch.setattr(poses.subprocess, "run", lambda cmd, **k: called.append(cmd) or subprocess.CompletedProcess(cmd, 1, "", ""))
    monkeypatch.setattr(poses.time, "sleep", lambda s: None)
    have = tmp_path / "have.png"; have.write_bytes(b"x")
    jobs = [(str(tmp_path / "a.png"), "p", [str(tmp_path / "pose_count_3.png")]),      # まだはめていない手の姿勢を参照
            (str(tmp_path / "b.png"), "p", [str(tmp_path / "c.png")]),                  # この回で描く絵を参照（待つ）
            (str(tmp_path / "c.png"), "p", [str(have)])]
    ok = poses.run_jobs(jobs, 1, False)
    assert not ok
    assert not any(str(tmp_path / "a.png") in c for c in called)                       # 参照が無い仕事は呼ばない
    assert any(str(tmp_path / "c.png") in c for c in called)                           # ほかは今までどおり描きに行く


def test_run_jobs_skips_the_whole_chain_after_a_missing_reference(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
    import poses
    called = []
    monkeypatch.setattr(poses.subprocess, "run", lambda cmd, **k: called.append(cmd) or subprocess.CompletedProcess(cmd, 1, "", ""))
    monkeypatch.setattr(poses.time, "sleep", lambda s: None)
    start = str(tmp_path / "pose_count_3.png")                                                  # まだはめていない
    ib = [str(tmp_path / f"ib_{k}.png") for k in range(1, 4)]
    jobs = [(ib[0], "p", [start]), (ib[1], "p", [ib[0]]), (ib[2], "p", [ib[1]])]                 # chain: 前の1枚を参照に順に
    assert not poses.run_jobs(jobs, 1, False)
    assert called == []


def test_self_referential_base_is_rejected_before_any_change(tmp_path):
    p = proj(tmp_path); drawn_hand(p)
    cfg = json.loads((p / "config.json").read_text(encoding="utf-8")); cfg["hands"]["count_3"]["base"] = "count_3"
    (p / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    old = cv2.imread(str(p / "poses/pose_point.png")); cv2.imwrite(str(p / "poses/pose_count_3.png"), old)
    before = (p / "poses/pose_count_3.png").read_bytes()
    r = run(p, "place", "--force")
    assert r.returncode != 0 and "自分自身" in r.stderr + r.stdout
    assert (p / "poses/pose_count_3.png").read_bytes() == before and not (p / "reject").exists()
