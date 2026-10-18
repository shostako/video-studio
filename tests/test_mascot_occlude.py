"""口・目の部品を写すとき、顔の前にある手の上には貼らない（lib.occlude）。顔の中で閉じた違い（目の描き方の差）は手と見なさない。
あわせて、口の描かせる文の opt-in（config.mouth_prompt: "jaw"）が、書かなければ今までどおりであること。"""
import numpy as np

from lib import Proj, occlude
import poses


def part_full(H, W, box):
    full = np.zeros((H, W, 4), np.uint8); x0, y0, x1, y1 = box; full[y0:y1, x0:x1] = (10, 20, 200, 255); return full


def test_hand_entering_from_outside_is_not_covered():
    H, W = 200, 200; ref = np.full((H, W, 3), 200, np.uint8); target = ref.copy()
    target[120:200, 90:110] = (40, 60, 200)                  # 下から伸びてくる手（部品の箱の外まで続く）
    out = occlude(part_full(H, W, (60, 100, 140, 150)), target, ref)
    assert out[130, 100, 3] == 0                              # 手の上には貼らない
    assert out[110, 70, 3] == 255                             # 手から離れた所は貼る


def test_difference_closed_inside_the_face_is_kept():
    H, W = 200, 200; ref = np.full((H, W, 3), 200, np.uint8); target = ref.copy()
    target[60:70, 80:100] = (20, 20, 20)                      # 目の描き方の違い（部品の箱の中で閉じている）
    out = occlude(part_full(H, W, (60, 40, 140, 90)), target, ref)
    assert out[65, 90, 3] == 255


def test_mouth_prompt_default_is_unchanged_and_jaw_is_opt_in(tmp_path):
    import json, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures")); import synth_mascot
    p = Path(synth_mascot.make(str(tmp_path / "proj"))); cfg = json.loads((p / "config.json").read_text(encoding="utf-8")); cfg["mascot"] = {"description": "x"}
    (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    before = {j[0]: j[1] for j in poses.jobs_parts(Proj(str(p)))}
    assert all("jaw" not in t for t in before.values())
    assert before[str(p / "parts/home_m3.png")] == f"{poses.KEEP} {poses.M['m3']}"      # 今までの文と同じ
    cfg["mouth_prompt"] = "jaw"; (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    after = {j[0]: j[1] for j in poses.jobs_parts(Proj(str(p)))}
    assert "lower jaw drops" in after[str(p / "parts/home_m3.png")] and "neck, collar" in after[str(p / "parts/home_m3.png")]
    assert after[str(p / "parts/home_e1.png")] == before[str(p / "parts/home_e1.png")]   # 目は変えない


def test_jaw_roi_is_used_for_cutting_but_mouth_roi_stays_for_the_rig(tmp_path):
    import json, sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures")); import synth_mascot
    import parts
    p = Path(synth_mascot.make(str(tmp_path / "proj"))); cfg = json.loads((p / "config.json").read_text(encoding="utf-8"))
    cfg["face"]["jaw_roi"] = [180, 230, 290, 300]; (p / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    P = Proj(str(p))
    assert parts.map_rois(P, "home")[0] == synth_mascot.MOUTH_ROI                   # 首の位置などに使う範囲は変わらない
    assert parts.map_rois(P, "home", mouth_key="jaw_roi")[0] == [180, 230, 290, 300]
