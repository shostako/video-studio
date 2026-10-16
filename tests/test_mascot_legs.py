"""下半身の差し替え（config.legs_lock、opt-in）。純関数 legs_config / lock_legs と、合成のマスコットでの書き出し。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import lib  # noqa: E402
import synth_mascot as sm  # noqa: E402

RENDER = ROOT / "skills/video-mascot/scripts/render.py"
POSES = {"home": {}, "point": {}, "head_l": {"yaw": 0, "head_yaw": -30}, "turn_l": {"yaw": -40}}


def wide(k=0, spread=14):
    """合成の人型の脚を左右に spread px ずつ開いた絵（BGR）。腰（胴の下端）より上は figure(k) と同じ。"""
    im = sm.figure(k); d = ImageDraw.Draw(im); bg = (253, 253, 253)
    d.rectangle([150, 526, 330, 740], fill=bg)                                                    # 胴の下から下を消して描き直す
    d.rectangle([190 - spread, 526, 228 - spread, 700], fill=sm.NAVY); d.rectangle([242 + spread, 526, 280 + spread, 700], fill=sm.NAVY)
    d.ellipse([150 - spread, 692, 236 - spread, 734], fill=sm.SHOE); d.ellipse([244 + spread, 692, 330 + spread, 734], fill=sm.SHOE)
    d.line([(182, 312), (150, 480)], fill=sm.BLUE, width=26); d.ellipse([138, 468, 164, 494], fill=sm.SKIN)   # 向かって左の腕は元のまま
    return np.ascontiguousarray(np.array(im)[:, :, ::-1])


def bgr(im): return np.ascontiguousarray(np.array(im)[:, :, ::-1])


# ---------- legs_config ----------
def test_legs_config_defaults_and_errors():
    assert lib.legs_config(None, POSES, "home") is None and lib.legs_config(False, POSES, "home") is None
    c = lib.legs_config(True, POSES, "home")
    assert c["from"] == "home" and c["poses"] == ["point", "head_l"]          # 正面（yaw が無いか 0）だけ、元の姿勢は除く
    assert lib.legs_config({"from": "point"}, POSES, "home")["poses"] == ["home", "head_l"]
    assert lib.legs_config({"poses": ["home", "turn_l"]}, POSES, "home")["poses"] == ["turn_l"]   # 書けば斜めも入る
    for bad in ({"from": "nope"}, {"cut": 0.9}, {"feather": 0}, {"feather": 0.5, "cut": 0.38}, {"hand_zone": 2},
                {"poses": ["nope"]}, {"legs": 1}, "home"):
        with pytest.raises(ValueError): lib.legs_config(bad, POSES, "home")


# ---------- lock_legs ----------
def test_lock_legs_same_image_is_unchanged():
    a = bgr(sm.figure(0)); out, info = lib.lock_legs(a, a)
    assert info["dx"] == 0 and info["dy"] == 0
    assert np.abs(out.astype(int) - a).max() <= 1


def test_lock_legs_takes_the_lower_body_from_canon():
    img, canon = wide(), bgr(sm.figure(0))
    out, info = lib.lock_legs(img, canon)
    cut, fb = info["cut"], info["feather"]
    assert cut - fb > 525 - 60 and cut < 700                                   # 切れ目は胴の下端あたりから脚の上の方
    assert np.array_equal(out[:cut - fb], img[:cut - fb])                       # 帯より上は元の絵のまま
    lo = slice(cut + 20, 735)
    assert np.abs(out[lo].astype(int) - canon[lo]).max() <= 1                  # 帯より下は基準の脚と靴
    assert lib.feet_anchor(out)[0] == pytest.approx(lib.feet_anchor(canon)[0], abs=1)


def test_lock_legs_band_has_no_double_edge():
    """帯の中で元の絵と基準の絵の腰の幅が違っても、腰の端は透けない（色を重ねるだけだと、端に薄い帯が出る）。"""
    img = bgr(sm.figure(0)); canon = img.copy()
    canon[400:526, 295:312] = sm.BLUE[::-1]                                     # 基準は腰が向かって右に 17px 広い（左は腕に付かないよう触らない）
    out, info = lib.lock_legs(img, canon)
    g = out[:, :, 0].astype(int)                                                 # 青の成分: 胴 160・背景 253
    for y in range(info["cut"] - info["feather"] + 2, info["cut"] - 2):
        faint = ((g[y, 290:320] > 175) & (g[y, 290:320] < 240)).sum()
        assert faint <= 2, (y, g[y, 290:320].tolist())
    naive = (img * 0.5 + canon * 0.5)[:, :, 0]                                   # 比べ: 色を半々に重ねると端に 17px の薄い帯
    assert ((naive[480, 290:320] > 175) & (naive[480, 290:320] < 240)).sum() > 10


def test_lock_legs_keeps_hands_of_the_original():
    """元の絵の手（肌の色）は、切れ目の下でも残す。基準の絵に手が無くても消えない。"""
    img = wide(); d_img = img.copy()
    d_img[540:570, 225:245] = sm.SKIN[::-1]                                     # 腿の前に置いた手
    canon = bgr(sm.figure(0))
    out, info = lib.lock_legs(d_img, canon)
    assert info["cut"] < 540
    assert np.abs(out[545:565, 228:242].astype(int) - np.array(sm.SKIN[::-1])).max() <= 2


def test_lock_legs_ignores_a_faint_floor_shadow():
    """床に描かれた薄い影（人物と離れた塊）を足元と取り違えない。"""
    img = wide(); img[745:760, 60:420] = (215, 215, 215)                       # 足元より下の薄い影
    canon = bgr(sm.figure(0))
    out, info = lib.lock_legs(img, canon)
    assert info["dy"] == 0
    assert np.abs(out[600:735].astype(int) - canon[600:735]).max() <= 1


def test_lock_legs_does_not_copy_hands_of_canon():
    """基準の絵の腰の前の手（肌の色）は、帯の中でも写さない。"""
    canon = bgr(sm.figure(0)); canon[476:492, 215:255] = sm.SKIN[::-1]          # 基準は切れ目のすぐ上で手を組んでいる
    img = wide()
    out, info = lib.lock_legs(img, canon)
    assert info["cut"] - info["feather"] < 476
    sk = lib._skin_mask(out[476:492, 215:255]).mean()
    assert sk < 0.05, sk


def test_lock_legs_canon_scale_and_transform():
    """canon_scale で基準の脚の大きさを変え、M は基準の足元を出来上がりの足元へ写す。"""
    img, canon = wide(), bgr(sm.figure(0))
    out, info = lib.lock_legs(img, canon, canon_scale=0.9)
    M = info["M"]; a = lib.feet_anchor(canon); b = lib.feet_anchor(out)
    assert M[0, 0] == pytest.approx(0.9) and M[1, 1] == pytest.approx(0.9)
    assert (M[0, 0] * a[0] + M[0, 2]) == pytest.approx(b[0], abs=2)
    assert (M[1, 1] * a[1] + M[1, 2]) == pytest.approx(b[1], abs=2)
    w = lambda im: np.ptp(np.where(lib.fg_mask(im)[650])[0])
    assert w(out) == pytest.approx(0.9 * w(canon), abs=3)                       # 足首の幅が 0.9 倍


def test_lock_legs_rejects_a_different_canvas():
    img, canon = wide(), bgr(sm.figure(0))
    with pytest.raises(ValueError): lib.lock_legs(img[:-8], canon)


def test_lock_legs_band_stays_inside_the_image():
    """帯が絵の上端より上に出る値でも、負の添字で絵の下の行を書き換えない。"""
    img, canon = wide(), bgr(sm.figure(0))
    out, info = lib.lock_legs(img, canon, cut=0.7, feather=0.69)
    assert info["cut"] - info["feather"] == 0
    assert np.array_equal(out[0], img[0])
    assert np.abs(out[740:].astype(int) - canon[740:]).max() <= 1               # 足元より下（背景）は基準のまま。上の行の値が回り込まない


# ---------- 書き出し ----------
def read_frames(path, env):
    import cv2
    cap = cv2.VideoCapture(str(path)); out = []
    while True:
        ok, f = cap.read()
        if not ok: break
        out.append(f[:, :, ::-1])
    assert out
    return out


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def test_render_with_legs_lock(tmp_path, env):
    pytest.importorskip("pykakasi")
    import cv2
    root = Path(sm.make(str(tmp_path / "proj")))
    cv2.imwrite(str(root / "poses" / "pose_point.png"), wide(1))                # point だけ脚を開いた絵にする
    for k in range(1, 6): cv2.imwrite(str(root / "ib" / f"ib_home_point_{k}.png"), wide(k / 6, spread=k * 2))
    cfg = json.loads((root / "config.json").read_text()); cfg["legs_lock"] = {"from": "home"}
    (root / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    out = tmp_path / "o.mp4"
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(root), "--out", str(out), "--mode", "white"],
                       env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "下半身の差し替え: home → ['point']" in r.stderr
    frames_ = read_frames(out, env)
    cfg["poses"]["point"]["scale"] = 0.9; cfg["poses"]["point"]["anchor"] = [235.0, 700.0]   # 大きさを変え、足元を手で書いても
    (root / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(root), "--out", str(out), "--mode", "white"],
                       env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    for f_ in (frames_, read_frames(out, env)):                                  # どのコマでも、足首の左右の端は動かない
        edges = []
        for fr in f_:
            m = lib.fg_mask(fr[:, :, ::-1].copy()); y = int(fr.shape[0] * 0.86); xs = np.where(m[y])[0]; edges.append((xs.min(), xs.max()))
        e = np.array(edges); assert np.ptp(e[:, 0]) <= 4 and np.ptp(e[:, 1]) <= 4, (np.ptp(e[:, 0]), np.ptp(e[:, 1]))   # 呼吸の伸び縮みと縮小の丸めで 2〜3px。直す前は 8〜30px
    import cv2 as cv2_
    small = cv2_.resize(cv2_.imread(str(root / "poses" / "pose_point.png")), (sm.W - 10, sm.H - 16))
    cv2_.imwrite(str(root / "poses" / "pose_point.png"), small)                 # 基準と大きさの違う絵は止める
    del cfg["poses"]["point"]["scale"]; del cfg["poses"]["point"]["anchor"]
    (root / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(root), "--out", str(out), "--mode", "white"],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "絵の大きさが home と違う姿勢: ['point']" in r.stderr
    cfg["legs_lock"] = {"cut": 2}
    (root / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(root), "--out", str(out), "--mode", "white"],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "legs_lock.cut" in r.stderr
