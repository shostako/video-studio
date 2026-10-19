"""vm mirror（opt-in）: 右の姿勢を左右反転して左の姿勢を作る。合成のマスコット（tests/fixtures/synth_mascot.py）の髪に
左右を見分ける印を付け、反転した絵で頭が home のまま（印が元の側に残る）・腕と手は反転・髪の上に来た手は手のまま、
中割りの組も反転すること、部品を home から写すこと、作り直しに --force が要ることを確かめる。"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
MIRROR = ROOT / "skills/video-mascot/scripts/mirror.py"
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import synth_mascot  # noqa: E402

MARK = (180, 120)                    # 髪の向かって左の印（左右を見分ける）
HAND = (320, 150)                    # 挙げた手（髪の右の縁に重なる）


def mark(path):
    im = Image.open(path).convert("RGB"); d = ImageDraw.Draw(im)
    d.ellipse([MARK[0] - 6, MARK[1] - 6, MARK[0] + 6, MARK[1] + 6], fill=(255, 0, 0)); im.save(path)


def proj(tmp_path):
    p = Path(synth_mascot.make(str(tmp_path / "proj")))
    im = Image.open(p / "poses/pose_home.png").convert("RGB"); d = ImageDraw.Draw(im)
    d.line([(288, 312), HAND], fill=synth_mascot.BLUE, width=26)
    d.ellipse([HAND[0] - 14, HAND[1] - 14, HAND[0] + 14, HAND[1] + 14], fill=synth_mascot.SKIN); im.save(p / "poses/pose_raise.png")
    for n in ("home", "point", "raise"): mark(p / f"poses/pose_{n}.png")
    for k in range(1, 6): mark(p / f"ib/ib_home_point_{k}.png")
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    c["poses"]["raise"] = {"desc": "the hand on the image-right side raised beside her head"}
    c["ib_steps"] = {"home>point": [f"step {k}: the arm on the image-right side moves" for k in range(1, 6)]}
    c["interp"] = {"durs": {"home>point": 0.9, "point>raise": 0.3, "raise>point": 0.4}}
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    import shutil; shutil.copytree(p / "parts_home", p / "parts_raise")
    return p


def run(*args):
    return subprocess.run([sys.executable, "-B", str(MIRROR), *map(str, args)], capture_output=True, text=True, timeout=120)


def col(img, xy): return tuple(int(v) for v in img[xy[1], xy[0]][::-1])   # RGB


def test_head_stays_home_and_limbs_flip(tmp_path):
    p = proj(tmp_path)
    r = run(p, "raise:raise_l", "point:point_l", "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    out = cv2.imread(str(p / "poses/pose_raise_l.png")); W = out.shape[1]
    assert col(out, MARK) == (255, 0, 0)                               # 頭は home の絵（印は元の側）
    assert col(out, (W - 1 - MARK[0], MARK[1])) != (255, 0, 0)
    hx = W - 1 - HAND[0]
    assert np.abs(np.array(col(out, (hx, HAND[1]))) - synth_mascot.SKIN).max() < 30   # 髪の上に来た手は手のまま
    src = cv2.imread(str(p / "poses/pose_raise.png"))
    assert np.abs(out[600:, :].astype(int) - src[600:, ::-1].astype(int)).max() == 0   # 脚は反転した絵のまま
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    assert c["poses"]["raise_l"]["mirror_of"] == "raise" and "image-left" in c["poses"]["raise_l"]["desc"]
    assert (p / "mirror_check/raise_l.png").exists()


def test_inbetweens_and_parts_are_mirrored(tmp_path):
    p = proj(tmp_path)
    r = run(p, "point:point_l")
    assert r.returncode == 0, r.stdout + r.stderr
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    assert ["home", "point_l"] in c["pairs"]
    assert c["ib_steps"]["home>point_l"][0] == "step 1: the arm on the image-left side moves"
    assert c["interp"]["durs"]["home>point_l"] == 0.9
    for k in range(1, 6):
        ib = cv2.imread(str(p / f"ib/ib_home_point_l_{k}.png"))
        assert ib is not None and col(ib, MARK) == (255, 0, 0)
    b = json.loads((p / "parts_point_l/borrowed.json").read_text())
    assert b["from"] == "home" and b["mirror"] is True
    hp = json.loads((p / "parts_home/parts.json").read_text()); pp = json.loads((p / "parts_point_l/parts.json").read_text())
    assert pp["m1"] == hp["m1"]                                         # 頭は home の絵なので、部品はずらさない


def test_rerun_needs_force_and_moves_old(tmp_path):
    p = proj(tmp_path)
    assert run(p, "point:point_l").returncode == 0
    r = run(p, "point:point_l")
    assert r.returncode != 0 and "--force" in (r.stdout + r.stderr)
    assert run(p, "point:point_l", "--force").returncode == 0
    old = list((p / "reject/mirror_replaced").glob("*/pose_point_l.png"))
    assert old and list((p / "reject/mirror_replaced").glob("*/ib_home_point_l_1.png"))


def test_rejects_home_and_bad_names(tmp_path):
    p = proj(tmp_path)
    assert run(p, "home:home_l").returncode != 0
    assert run(p, "point:home").returncode != 0
    assert run(p, "nothing:x").returncode != 0
    assert run(p, "point").returncode != 0


def test_direct_switch_seconds_are_mirrored(tmp_path):
    p = proj(tmp_path)
    assert run(p, "point:point_l", "raise:raise_l").returncode == 0
    d = json.loads((p / "config.json").read_text(encoding="utf-8"))["interp"]["durs"]
    assert d["point_l>raise_l"] == 0.3 and d["raise_l>point_l"] == 0.4
    p2 = proj(tmp_path / "x")
    assert run(p2, "point:point_l").returncode == 0                    # 片方だけ反転するなら、相手の無い秒は写さない
    d = json.loads((p2 / "config.json").read_text(encoding="utf-8"))["interp"]["durs"]
    assert not any("point_l>raise" in k or "raise>point_l" in k for k in d)


def test_anchors_are_mirrored(tmp_path):
    p = proj(tmp_path)
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    c["poses"]["point"]["anchor"] = [200, 730]
    c["anchor"] = {"mode": "manual", "points": {"home": [235, 735], "raise": [230, 735]}, "scales": {"raise": 1.01}}
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    assert run(p, "point:point_l", "raise:raise_l").returncode == 0
    c = json.loads((p / "config.json").read_text(encoding="utf-8")); W = 470
    assert c["poses"]["point_l"]["anchor"] == [W - 1 - 200, 730]
    assert c["anchor"]["points"]["raise_l"] == [W - 1 - 230, 735] and c["anchor"]["scales"]["raise_l"] == 1.01


def test_checks_happen_before_anything_is_written(tmp_path):
    p = proj(tmp_path)
    r = run(p, "raise:pose_l", "point:pose_l")
    assert r.returncode != 0 and not (p / "poses/pose_pose_l.png").exists()
    import shutil; shutil.rmtree(p / "parts_home")
    r = run(p, "point:point_l")
    assert r.returncode != 0 and "vm parts" in (r.stdout + r.stderr) and not (p / "poses/pose_point_l.png").exists()


def test_interp_allowlist_and_missing_source_image(tmp_path):
    p = proj(tmp_path)
    c = json.loads((p / "config.json").read_text(encoding="utf-8")); c["interp"]["pairs"] = ["home>point", "point>raise"]
    c["poses"]["undrawn"] = {"desc": "not drawn"}
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    r = run(p, "point:point_l", "undrawn:undrawn_l")
    assert r.returncode != 0 and not (p / "poses/pose_point_l.png").exists()    # 絵の無い元があれば、何も書かずに止まる
    assert run(p, "point:point_l", "raise:raise_l").returncode == 0
    ps = json.loads((p / "config.json").read_text(encoding="utf-8"))["interp"]["pairs"]
    assert "home>point_l" in ps and "point_l>raise_l" in ps


def test_edge_words_and_reverse_pair_and_forced_cleanup(tmp_path):
    p = proj(tmp_path)
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    c["poses"]["point"]["desc"] = "her left arm points at the image-right side, toward the RIGHT edge"
    c["pairs"].append(["point_l", "home"])                              # 反転先の組が逆向きで書いてある
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    assert run(p, "point:point_l").returncode == 0
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    assert c["poses"]["point_l"]["desc"] == "her right arm points at the image-left side, toward the LEFT edge"
    # 前から書いてあった反転先の組は消して、元の組の向きで作り直す（組の向きと絵の名前が食い違わない）
    assert ["home", "point_l"] in c["pairs"] and ["point_l", "home"] not in c["pairs"]
    assert (p / "ib/ib_home_point_l_1.png").exists() and not (p / "ib/ib_point_l_home_1.png").exists()
    # 元の組を消してから --force で作り直すと、反転した組も消える
    c["pairs"] = [q for q in c["pairs"] if q != ["home", "point"]]; del c["ib_steps"]["home>point"]
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    assert run(p, "point:point_l", "--force").returncode == 0
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    assert not any("point_l" in q for q in c["pairs"]) and not any("point_l" in k for k in c.get("ib_steps", {}))


def test_incomplete_source_pairs_and_non_frontal_sources(tmp_path):
    p = proj(tmp_path)
    (p / "ib/ib_home_point_3.png").unlink()
    r = run(p, "point:point_l")
    assert r.returncode == 0 and "そろっていない" in r.stdout
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    assert ["home", "point_l"] not in c["pairs"] and not list((p / "ib").glob("ib_home_point_l_*"))
    c["poses"]["back"] = {"desc": "back", "face": False}; c["poses"]["turn"] = {"desc": "turn", "yaw": 40}
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    import shutil
    for n in ("back", "turn"): shutil.copy(p / "poses/pose_home.png", p / f"poses/pose_{n}.png")
    assert run(p, "back:back_l").returncode != 0 and run(p, "turn:turn_l").returncode != 0


def test_force_rebuild_of_connected_pair_and_stale_anchor(tmp_path):
    p = proj(tmp_path)
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    c["pairs"].append(["point", "raise"]); c["anchor"] = {"mode": "manual", "points": {"home": [235, 735], "point": [230, 735], "raise": [230, 735]}}
    for k in range(1, 6):
        import shutil; shutil.copy(p / f"ib/ib_home_point_{k}.png", p / f"ib/ib_point_raise_{k}.png")
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    assert run(p, "point:point_l", "raise:raise_l").returncode == 0
    assert (p / "ib/ib_point_l_raise_l_1.png").exists()
    c = json.loads((p / "config.json").read_text(encoding="utf-8")); del c["anchor"]["points"]["raise"]; c["poses"]["raise"]["anchor"] = [230, 735]
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    r = run(p, "point:point_l", "raise:raise_l", "--force")             # 2つをつなぐ組の絵を2回移そうとして落ちない
    assert r.returncode == 0, r.stdout + r.stderr
    c = json.loads((p / "config.json").read_text(encoding="utf-8"))
    assert "raise_l" not in c["anchor"]["points"] and c["poses"]["raise_l"]["anchor"] == [470 - 1 - 230, 735]


def test_unreadable_home_part_and_unique_archive(tmp_path):
    p = proj(tmp_path)
    for _ in range(3): assert run(p, "point:point_l", "--force").returncode == 0
    assert len(list((p / "reject/mirror_replaced").iterdir())) == 2      # 1回目は移すものが無い。2回目と3回目は別の控え
    (p / "parts_home/m1.png").write_bytes(b"broken")
    r = run(p, "point:point_l", "--force")
    assert r.returncode != 0 and "m1" in (r.stdout + r.stderr) and (p / "poses/pose_point_l.png").exists()   # 何も移さずに止まる


def test_bad_sizes_and_corrupt_frames_are_caught_before_writing(tmp_path):
    p = proj(tmp_path)
    (p / "ib/ib_home_point_2.png").write_bytes(b"broken")
    r = run(p, "point:point_l")
    assert r.returncode == 0 and "そろっていない" in r.stdout and not list((p / "ib").glob("ib_home_point_l_*"))
    im = cv2.imread(str(p / "poses/pose_raise.png")); cv2.imwrite(str(p / "poses/pose_raise.png"), im[:-10])
    r = run(p, "raise:raise_l")
    assert r.returncode != 0 and not (p / "poses/pose_raise_l.png").exists()


def test_pose_with_moved_head_is_rejected_and_face_meta_dropped(tmp_path):
    p = proj(tmp_path)
    c = json.loads((p / "config.json").read_text(encoding="utf-8")); c["poses"]["point"]["face"] = {"mouth_roi": [1, 2, 3, 4]}; c["poses"]["point"]["scale"] = 1.0
    c["poses"]["bowish"] = {"desc": "head lower"}
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    im = cv2.imread(str(p / "poses/pose_home.png")); low = np.full_like(im, 253); low[80:] = im[:-80]   # 頭ごと 80px 下がった絵
    cv2.imwrite(str(p / "poses/pose_bowish.png"), low)
    r = run(p, "bowish:bowish_l")
    assert r.returncode != 0 and "頭" in (r.stdout + r.stderr)
    assert run(p, "point:point_l").returncode == 0
    pc = json.loads((p / "config.json").read_text(encoding="utf-8"))["poses"]["point_l"]
    assert "face" not in pc and "scale" not in pc
