"""vm parts --borrow（opt-in）: 差分を描かずに、元の姿勢の口・目の部品を顔を重ね合わせて写す。
合成のマスコット（tests/fixtures/synth_mascot.py）の home を少し動かした姿勢へ写し、位置がそのずれだけ動くこと、
顔の合わない姿勢（後ろ向き）には書かないこと、写した姿勢を vm parts が切り直さず vm poses parts が描かないことを確かめる。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "skills/video-mascot/scripts/parts.py"
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import synth_mascot  # noqa: E402

DX, DY = 4, 6


def shifted(im, dx, dy):
    a = np.asarray(im); out = np.full_like(a, 253); out[dy:, dx:] = a[:a.shape[0] - dy, :a.shape[1] - dx]
    return Image.fromarray(out)


def proj(tmp_path):
    root = synth_mascot.make(str(tmp_path / "proj")); p = Path(root)
    cfg = json.loads((p / "config.json").read_text(encoding="utf-8"))
    cfg["poses"]["moved"] = {"desc": "same face, moved"}; cfg["poses"]["back"] = {"desc": "back view"}
    (p / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    shifted(synth_mascot.figure(0), DX, DY).save(p / "poses/pose_moved.png")
    synth_mascot.figure_back().save(p / "poses/pose_back.png")
    return p


def run(*args):
    return subprocess.run([sys.executable, "-B", str(PARTS), *map(str, args)], capture_output=True, text=True, timeout=120)


def test_borrow_moves_parts_with_the_face(tmp_path):
    p = proj(tmp_path)
    r = run(p, "--borrow", "home", "moved")
    assert r.returncode == 0, r.stdout + r.stderr
    src = json.load(open(p / "parts_home/parts.json")); dst = json.load(open(p / "parts_moved/parts.json"))
    assert set(dst) == set(src)
    for k in src:                                        # 写した部品は透明な余白を切り詰めるので、見える所の左上で比べる
        a = np.asarray(Image.open(p / f"parts_home/{k}.png").convert("RGBA"))[:, :, 3]; ys, xs = np.nonzero(a)
        x0, y0 = src[k][0] + xs.min(), src[k][1] + ys.min()
        assert abs(dst[k][0] - x0 - DX) <= 1 and abs(dst[k][1] - y0 - DY) <= 1, (k, (x0, y0), dst[k])
    rec = json.load(open(p / "parts_moved/borrowed.json"))
    assert rec["from"] == "home" and rec["cc"] >= 0.95


def test_borrow_refuses_a_face_that_does_not_match(tmp_path):
    p = proj(tmp_path)
    r = run(p, "--borrow", "home", "back")
    assert r.returncode == 3
    assert not (p / "parts_back/parts.json").exists()


def test_borrow_refuses_when_diffs_were_drawn(tmp_path):
    p = proj(tmp_path)
    synth_mascot.figure(0).save(p / "parts/moved_m1.png")
    r = run(p, "--borrow", "home", "moved")
    assert r.returncode == 3 and not (p / "parts_moved").exists()


def test_vm_parts_keeps_borrowed_and_vm_poses_skips_it(tmp_path):
    p = proj(tmp_path)
    assert run(p, "--borrow", "home", "moved").returncode == 0
    before = (p / "parts_moved/parts.json").read_text()
    r = run(p, "moved")
    assert r.returncode == 0 and "切り直さない" in r.stdout
    assert (p / "parts_moved/parts.json").read_text() == before
    sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
    from lib import Proj
    import poses
    jobs = [os.path.basename(j[0]) for j in poses.jobs_parts(Proj(str(p)))]
    assert not any(j.startswith("moved_") for j in jobs)
    assert any(j.startswith("back_") for j in jobs)        # 写していない姿勢は今までどおり描く


def test_failed_reborrow_clears_the_old_borrowed_parts(tmp_path):
    p = proj(tmp_path)
    assert run(p, "--borrow", "home", "moved").returncode == 0
    synth_mascot.figure_back().save(p / "poses/pose_moved.png")        # 描き直して顔が合わなくなった
    r = run(p, "--borrow", "home", "moved")
    assert r.returncode == 3
    assert not (p / "parts_moved/borrowed.json").exists() and not (p / "parts_moved/parts.json").exists()
    sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
    from lib import Proj
    import poses
    assert any(os.path.basename(j[0]).startswith("moved_") for j in poses.jobs_parts(Proj(str(p))))   # また描く対象に戻る


def test_drawn_diffs_win_over_borrowed_parts(tmp_path):
    p = proj(tmp_path)
    assert run(p, "--borrow", "home", "moved").returncode == 0
    shifted(synth_mascot.figure(0), DX, DY).save(p / "parts/moved_m1.png")   # 写したあとに差分を描いた
    r = run(p, "moved")
    assert r.returncode == 0 and "切り直す" in r.stdout
    assert not (p / "parts_moved/borrowed.json").exists()
