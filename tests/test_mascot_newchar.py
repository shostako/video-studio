"""新しいキャラの立ち上げ（vm init・vm face・anchor.mode feet・mascot.pronoun）を、合成のマスコットで確かめる。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/video-mascot/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import cv2  # noqa: E402
import lib  # noqa: E402
import synth_mascot as sm  # noqa: E402


def _run(script, *args, env=None):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=300, env=env)


def _bgr(im): return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def _brown_shoes(im):
    """靴を茶色・ズボンを明るい灰色にした絵（黒い靴の軸足 boot が使えないキャラ）。"""
    a = np.array(im)
    for src, dst in ((sm.SHOE, (150, 95, 60)), (sm.NAVY, (150, 150, 160))): a[(a == np.array(src)).all(axis=2)] = dst
    return Image.fromarray(a)


# ---------- 足元（色に依らない）----------
def test_feet_anchor_is_color_independent():
    black = _bgr(sm.figure(0)); brown = _bgr(_brown_shoes(sm.figure(0)))
    assert lib.boot_anchor(brown) is None                                         # 黒い靴の前提では見つからない
    fa, fb = lib.feet_anchor(black), lib.feet_anchor(brown)
    assert fa == fb and abs(fa[1] - 735) <= 1 and abs(fa[0] - 240) <= 2          # 両足の真ん中、靴の底
    assert abs(lib.fg_height(brown, fb) - lib.body_height(black, lib.boot_anchor(black))) <= 2
    sh = np.full_like(brown, 253); sh[:, 30:] = brown[:, :-30]
    assert abs(lib.feet_anchor(sh)[0] - fb[0] - 30) <= 1                          # 絵がずれたら同じだけずれる


# ---------- vm init ----------
def test_init_build_presets_and_pronoun():
    import init
    she = init.build("x", "a test mascot", "she", "a")
    assert list(she["poses"]) == ["home", "head_l", "turn_l", "present_l", "head_r", "turn_r", "present_r"]
    assert she["pairs"] == [["turn_l", "present_l"], ["turn_r", "present_r"]] and she["gaze"] == {} and she["transition"]["mode"] == "fade"
    d = she["poses"]["turn_l"]["desc"]
    assert "her nose and her toes point toward the LEFT edge of the image" in d and "do not copy the eye direction" in d
    assert not any(k in json.dumps(she["poses"]) for k in ("{p}", "{P}", "{s}", "{S}"))   # 置き換え漏れが無い
    he = init.build("x", "a test mascot", "he", "abc", gestures=True)
    txt = json.dumps(he["poses"])
    assert " her " not in txt and "his nose" in txt and "His arm" in txt
    assert he["poses"]["back"]["face"] is False and "side_r" in he["poses"] and "point_l" in he["poses"]
    assert ["home", "open"] in he["pairs"]
    none = init.build("x", "d", tiers="none")
    assert list(none["poses"]) == ["home"] and "gaze" not in none and "transition" not in none
    assert none["floor"] == {"clean": False} and none["mascot"] == {"description": "d", "pronoun": "she"}


def test_init_command_picks_anchor_and_refuses_overwrite(tmp_path):
    img = tmp_path / "m.png"; _brown_shoes(sm.figure(0)).save(img)
    w = tmp_path / "w"; r = _run("init.py", w, img, "--desc", "a test mascot", "--pronoun", "it")
    assert r.returncode == 0, r.stderr
    cfg = json.loads((w / "config.json").read_text(encoding="utf-8"))
    assert cfg["anchor"]["mode"] == "feet" and cfg["mascot"]["pronoun"] == "it" and "its nose" in cfg["poses"]["head_l"]["desc"]
    assert (w / "mascot.png").read_bytes() == img.read_bytes() == (w / "poses/pose_home.png").read_bytes()
    assert _run("init.py", w, img, "--desc", "again").returncode != 0              # 上書きしない
    sm.figure(0).save(img); assert _run("init.py", w, img, "--desc", "again", "--force").returncode == 0
    assert json.loads((w / "config.json").read_text(encoding="utf-8"))["anchor"]["mode"] == "boot"
    p = _run("init.py", tmp_path / "none", "--print", "--views", "ab")
    assert p.returncode == 0 and "side_l" in json.loads(p.stdout)["poses"] and not (tmp_path / "none" / "config.json").exists()


# ---------- mascot.pronoun が描かせる文に入る ----------
def test_poses_prompts_use_pronoun(tmp_path):
    import poses
    proj = Path(sm.make(str(tmp_path / "p"))); cfg = json.loads((proj / "config.json").read_text(encoding="utf-8"))
    cfg["mascot"] = {"description": "x"}; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert all("Her face" in j[1] for j in poses.jobs_ib(lib.Proj(str(proj))))   # 既定は今までどおり
    cfg["mascot"]["pronoun"] = "he"; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    jobs = poses.jobs_ib(lib.Proj(str(proj)))
    assert jobs and all("His face" in j[1] and "Her" not in j[1] for j in jobs)


# ---------- vm face ----------
def _variant(base, part, roi, shift=(0, 0), noise=0):
    im = base.copy(); im.paste(part, tuple(roi[:2]), part)
    a = np.array(im).astype(np.int16)
    if noise: a += np.random.default_rng(0).integers(-noise, noise + 1, a.shape)
    a = np.roll(a, shift, axis=(0, 1)); return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def test_face_measures_rois_from_drawn_variants(tmp_path):
    proj = Path(sm.make_views(str(tmp_path / "p")))
    base = Image.open(proj / "poses/pose_home.png").convert("RGB")
    for k, part in (("m2", sm.mouth_part(30, 16)), ("m3", sm.mouth_part(34, 24)), ("m5", sm.mouth_part(22, 8, True))):
        _variant(base, part, sm.MOUTH_ROI, (1, -2), 3).save(proj / f"parts/home_{k}.png")
    for k, h in (("e1", 6), ("e2", 1)): _variant(base, sm.eye_part(h), sm.EYE_ROI, (0, 2), 3).save(proj / f"parts/home_{k}.png")
    tb = Image.open(proj / "poses/pose_turn_l.png").convert("RGB")
    _variant(tb, sm.mouth_part(34, 24), sm.TURN_MOUTH_ROI).save(proj / "parts/turn_l_m3.png")
    _variant(tb, sm.eye_part(1), sm.TURN_EYE_ROI).save(proj / "parts/turn_l_e2.png")
    import face
    r = face.measure(lib.Proj(str(proj)), "home")
    mx0, my0, mx1, my1 = r["mouth_roi"]; ex0, ey0, ex1, ey1 = r["eye_roi"]
    assert 200 <= mx0 <= 225 and 240 <= mx1 <= 270 and 226 <= my0 <= 248 and 258 <= my1 <= 275   # 口（開いた所）を囲む
    assert 180 <= ex0 <= 196 and 274 <= ex1 <= 292 and ey1 < my0                                # 両目を囲み、口より上
    w = _run("face.py", proj, "home", "turn_l", "point", "--write")
    assert w.returncode == 0, w.stderr
    cfg = json.loads((proj / "config.json").read_text(encoding="utf-8"))
    assert cfg["face"]["mouth_roi"] == r["mouth_roi"] and "face" in cfg["poses"]["turn_l"]   # 正面でない姿勢は poses.<姿勢>.face
    assert cfg["poses"]["turn_l"]["face"]["mouth_roi"][0] < r["mouth_roi"][0] - 20             # 斜めの口は左へ寄る
    assert "face" not in cfg["poses"]["point"] and "測れない" in w.stdout
    assert (proj / "config.json.bak").exists()


# ---------- anchor.mode feet で書き出せる ----------
@pytest.fixture(scope="module")
def env(tmp_path_factory):
    pytest.importorskip("pykakasi")
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def test_render_with_feet_anchor_and_brown_shoes(env, tmp_path):
    proj = Path(sm.make(str(tmp_path / "p")))
    for f in list((proj / "poses").glob("*.png")) + list((proj / "ib").glob("*.png")): _brown_shoes(Image.open(f).convert("RGB")).save(f)
    cfg = json.loads((proj / "config.json").read_text(encoding="utf-8")); cfg["floor"] = {"clean": False}
    (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    out = tmp_path / "o.mp4"
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "render.py"), str(proj), "--out", str(out), "--mode", "white", "--to", "1.0"], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode != 0 and "feet" in r.stderr                               # 黒い靴が無いと boot は止まり、feet を勧める
    cfg["anchor"] = {"mode": "feet"}; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "render.py"), str(proj), "--out", str(out), "--mode", "white", "--to", "1.0"], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert out.stat().st_size > 1000


def test_init_presets_match_views_spec_doc():
    """docs/mascot-views-spec.md の段階 A の config の例と、vm init が書く雛形（she）が同じ（片方だけ直してずれないように）。"""
    import re
    import init
    blk = re.search(r"```json\n(.*?)```", (ROOT / "docs/mascot-views-spec.md").read_text(encoding="utf-8"), re.S).group(1)
    doc = json.loads("{" + re.sub(r'\s*"home": \{"desc": "[^"]*"\},', "", blk) + "}")
    built = init.build("x", "d", "she", "a")
    assert {k: built["poses"][k] for k in doc["poses"]} == doc["poses"] and built["pairs"] == doc["pairs"]


def test_init_prefers_feet_when_dark_area_is_not_shoes(tmp_path):
    """靴は茶色で、黒いスカート（裾が足元より上）がある絵は、黒い塊を靴と取り違えず feet にする。"""
    from PIL import ImageDraw
    im = _brown_shoes(sm.figure(0)); ImageDraw.Draw(im).rectangle([170, 500, 300, 640], fill=(10, 10, 10))
    assert lib.boot_anchor(_bgr(im)) is not None                                   # 黒い塊としては見つかる
    img = tmp_path / "m.png"; im.save(img)
    r = _run("init.py", tmp_path / "w", img, "--desc", "d")
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "w/config.json").read_text(encoding="utf-8"))["anchor"]["mode"] == "feet"


def test_init_force_refuses_folder_with_drawn_assets(tmp_path):
    img = tmp_path / "m.png"; sm.figure(0).save(img); w = tmp_path / "w"
    assert _run("init.py", w, img, "--desc", "d").returncode == 0
    sm.figure(1).save(w / "poses/pose_turn_l.png")                                 # 前のキャラで描いた絵
    r = _run("init.py", w, img, "--desc", "new", "--force")
    assert r.returncode != 0 and "pose_turn_l" in r.stderr
    assert json.loads((w / "config.json").read_text(encoding="utf-8"))["mascot"]["description"] == "d"   # 何も書き換えない


def test_face_ignores_hair_and_hand_changes_in_variants(tmp_path):
    """差分の絵が髪や手まで少し描き変えても（新PCの実物で起きた）、口と目の範囲は顔の中に収まる。"""
    from PIL import ImageDraw
    proj = Path(sm.make(str(tmp_path / "p"))); base = Image.open(proj / "poses/pose_home.png").convert("RGB")
    def noisy(im):
        d = ImageDraw.Draw(im); d.ellipse([150, 100, 230, 140], fill=(110, 80, 70))       # 髪の一部の色が変わる
        d.ellipse([130, 460, 175, 505], fill=(240, 190, 170))                              # 手の形が変わる
        d.rectangle([200, 380, 270, 420], fill=(60, 100, 190)); return im                  # 服のしわ
    for k, part in (("m2", sm.mouth_part(30, 16)), ("m3", sm.mouth_part(34, 24))):
        noisy(_variant(base, part, sm.MOUTH_ROI)).save(proj / f"parts/home_{k}.png")
    for k, h in (("e1", 6), ("e2", 1)): noisy(_variant(base, sm.eye_part(h), sm.EYE_ROI)).save(proj / f"parts/home_{k}.png")
    import face
    r = face.measure(lib.Proj(str(proj)), "home")
    assert not face.suspicious(r)
    ex0, ey0, ex1, ey1 = r["eye_roi"]; mx0, my0, mx1, my1 = r["mouth_roi"]
    assert 170 <= ex0 <= 196 and 274 <= ex1 <= 300 and 175 <= ey0 and ey1 <= 232      # 両目だけ（髪の 100〜140 を含まない）
    assert 195 <= mx0 and mx1 <= 275 and 226 <= my0 and my1 <= 285                    # 口だけ（手・服を含まない）


def test_face_eyes_not_taken_from_symmetric_hair_or_brows(tmp_path):
    """目の差分が、目より大きい左右対称の塊（前髪の房・眉）まで描き変えても、目の範囲は目に付く（Codex の指摘）。"""
    from PIL import ImageDraw
    proj = Path(sm.make(str(tmp_path / "p"))); base = Image.open(proj / "poses/pose_home.png").convert("RGB")
    for k, part in (("m2", sm.mouth_part(30, 16)), ("m3", sm.mouth_part(34, 24))): _variant(base, part, sm.MOUTH_ROI).save(proj / f"parts/home_{k}.png")
    for k, h in (("e1", 6), ("e2", 1)):
        im = _variant(base, sm.eye_part(h), sm.EYE_ROI); d = ImageDraw.Draw(im)
        d.rectangle([160, 150, 220, 172], fill=(70, 50, 40)); d.rectangle([250, 150, 310, 172], fill=(70, 50, 40))   # 眉・前髪（目より大きい）
        im.save(proj / f"parts/home_{k}.png")
    import face
    r = face.measure(lib.Proj(str(proj)), "home")
    ex0, ey0, ex1, ey1 = r["eye_roi"]
    assert ey0 >= 175 and ey1 <= 232 and 170 <= ex0 <= 196 and 274 <= ex1 <= 300
    assert face.pick_eyes([(2000, 10, 10, 60, 30)]) == [10, 10, 60, 30]                 # 組が無ければ一番大きい塊


def test_face_eyes_not_taken_from_shoulders_or_hands(tmp_path):
    """目の差分が、肩や手の左右の組まで（目より大きく、目より下で）描き変えても、目は頭の辺りの上の方から取る。
    新PCの実物で、目の範囲が胴に広がり、口の範囲が胴（y 700〜1090）に出た。"""
    from PIL import ImageDraw
    proj = Path(sm.make(str(tmp_path / "p"))); base = Image.open(proj / "poses/pose_home.png").convert("RGB")
    for k, part in (("m2", sm.mouth_part(30, 16)), ("m3", sm.mouth_part(34, 24))): _variant(base, part, sm.MOUTH_ROI).save(proj / f"parts/home_{k}.png")
    for k, h in (("e1", 6), ("e2", 1)):
        im = _variant(base, sm.eye_part(h), sm.EYE_ROI); d = ImageDraw.Draw(im)
        d.rectangle([150, 335, 200, 370], fill=(200, 60, 60)); d.rectangle([270, 335, 320, 370], fill=(200, 60, 60))   # 肩・手の組（目より下）
        im.save(proj / f"parts/home_{k}.png")
    import face
    r = face.measure(lib.Proj(str(proj)), "home")
    ex0, ey0, ex1, ey1 = r["eye_roi"]
    assert ey0 >= 175 and ey1 <= 232 and 170 <= ex0 <= 196 and 274 <= ex1 <= 300 and not face.suspicious(r)


def test_face_votes_across_variants(tmp_path):
    """各差分が別々の所（髪・手）も描き変えていても、何枚にも共通する口と目の所だけを拾う。"""
    from PIL import ImageDraw
    proj = Path(sm.make(str(tmp_path / "p"))); base = Image.open(proj / "poses/pose_home.png").convert("RGB")
    junk = [[150, 230, 172, 250], [300, 236, 322, 262], [205, 300, 265, 310], [140, 470, 170, 500], [290, 420, 330, 450], [160, 110, 190, 130], [260, 280, 300, 290]]
    for i, (k, part) in enumerate((("m1", sm.mouth_part(26, 6)), ("m2", sm.mouth_part(30, 16)), ("m3", sm.mouth_part(34, 24)), ("m6", sm.mouth_part(36, 8)))):
        im = _variant(base, part, sm.MOUTH_ROI); ImageDraw.Draw(im).rectangle(junk[i], fill=(90, 160, 90)); im.save(proj / f"parts/home_{k}.png")
    for i, (k, h) in enumerate((("e1", 6), ("e2", 1))):
        im = _variant(base, sm.eye_part(h), sm.EYE_ROI); ImageDraw.Draw(im).rectangle(junk[5 - i], fill=(90, 160, 90)); im.save(proj / f"parts/home_{k}.png")
    import face
    r = face.measure(lib.Proj(str(proj)), "home")
    mx0, my0, mx1, my1 = r["mouth_roi"]
    assert 195 <= mx0 and mx1 <= 275 and 226 <= my0 and my1 <= 280 and not face.suspicious(r)


def test_face_suspicious_flags():
    import face
    assert face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [130, 150, 170, 180]}) == []
    assert "口が目より上" in face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [130, 60, 170, 90]})
    assert face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [0, 150, 400, 700]})       # 口が体じゅうに広がった
    assert "口が目から離れすぎ" in face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [130, 300, 170, 330]})
    assert "口が両目の間に無い" in face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [210, 150, 250, 180]})
    wide = {"eye_roi": [40, 300, 560, 380], "mouth_roi": [200, 700, 400, 1090], "head": [30, 50, 570, 600], "eye_zone_y": 400}
    assert {"目の範囲が頭の幅に近い（顔より広い）", "口が頭の辺りの外"} <= set(face.suspicious(wide))   # 新PCの実物の外れ方
    assert "目が頭の辺りより下" in face.suspicious({**wide, "eye_zone_y": 250})
    assert "目が片方しか取れていない" in face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [130, 150, 170, 180], "eye_single": True})
    near, far = (600, 100, 100, 130, 125), (200, 160, 102, 175, 122)                 # 斜めの顔: 奥の目は手前の 1/3
    assert face.eye_pair([near, far]) == ([100, 100, 175, 125], 2)
    assert face.eye_pair([near])[1] == 1


def _shoes_only_brown(im):
    a = np.array(im); a[(a == np.array(sm.SHOE)).all(axis=2)] = (150, 95, 60); return Image.fromarray(a)   # 紺のズボンは暗いまま


def test_views_flags_boot_on_trouser_hem(tmp_path, env):
    """靴が黒くなく紺のズボンが暗いと、boot はズボンの裾を軸足に拾う（新PCの実物で起きた）。vm views は外れを知らせて feet を勧め、
    背の比は色に依らずに測る。render は知らせるだけで、書き出しは変えない。"""
    proj = Path(sm.make(str(tmp_path / "p")))
    for f in list((proj / "poses").glob("*.png")) + list((proj / "ib").glob("*.png")): _shoes_only_brown(Image.open(f).convert("RGB")).save(f)
    cfg = json.loads((proj / "config.json").read_text(encoding="utf-8")); cfg["floor"] = {"clean": False}
    (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    import views
    rows = {r["pose"]: r for r in views.table(lib.Proj(str(proj)), ["home", "point"])}
    assert rows["home"]["boot_ok"] is False and "anchor" not in rows["home"] and abs(rows["point"]["height"] - 1) < 0.01
    out = _run("views.py", proj)
    assert out.returncode == 0 and "feet" in out.stdout and "靴で拾った軸足が足元に無い" in out.stdout
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "render.py"), str(proj), "--out", str(tmp_path / "o.mp4"), "--mode", "white", "--to", "0.5"],
                       env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "軸足が足元に無い姿勢" in r.stderr
    f = views.measure(lib.Proj(str(proj)), "point")["feet"]                        # anchor を書いた姿勢は、render と同じく外れと言わない
    cfg["poses"]["point"]["anchor"] = [round(float(v), 1) for v in f]; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    rows = {r["pose"]: r for r in views.table(lib.Proj(str(proj)), ["home", "point"])}
    assert rows["point"]["boot_ok"] is True and rows["home"]["boot_ok"] is False
    assert "point" not in _run("views.py", proj).stdout.split("靴の軸足が外れた姿勢:")[1].splitlines()[0]


def test_inbetween_percent_prompt_is_opt_in(tmp_path):
    import poses, init
    proj = Path(sm.make(str(tmp_path / "p"))); cfg = json.loads((proj / "config.json").read_text(encoding="utf-8"))
    cfg["mascot"] = {"description": "x"}; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    plain = poses.jobs_ib(lib.Proj(str(proj)))
    assert all("%" not in j[1] and "one sixth" in plain[0][1] for j in plain)      # 既定は今までの言い方
    cfg["inbetween_prompt"] = "percent"; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    pc = poses.jobs_ib(lib.Proj(str(proj)))
    assert "17% of the way" in pc[0][1] and "only 17% extended" in pc[0][1] and "closer to the first" in pc[0][1]
    assert "halfway" in pc[2][1] and "closer to the second" in pc[4][1] and [j[2] for j in pc] == [j[2] for j in plain]
    assert init.build("x", "d")["inbetween_prompt"] == "chain"                     # 新しいキャラは前の1枚から少しずつ描く


def test_inbetween_chain_draws_from_previous_frame_in_order(tmp_path, monkeypatch):
    """chain: 1枚目は始めの姿勢だけ、k 枚目は k-1 枚目だけを参照に描き、vm poses は前の枚が描けてから次を描く（参照に終わりの絵を渡さない）。"""
    import poses
    proj = Path(sm.make(str(tmp_path / "p"))); cfg = json.loads((proj / "config.json").read_text(encoding="utf-8"))
    cfg["mascot"] = {"description": "x"}; cfg["inbetween_prompt"] = "chain"; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    for f in (proj / "ib").glob("*.png"): f.unlink()
    jobs = poses.jobs_ib(lib.Proj(str(proj)))
    assert [j[2] for j in jobs] == [[str(proj / "poses/pose_home.png")]] + [[str(proj / f"ib/ib_home_point_{k}.png")] for k in range(1, 5)]
    assert "17% of the way" in jobs[0][1] and "exactly 33% of the way" in jobs[1][1] and "only about 17% of the total distance" in jobs[4][1]
    assert all("pose_point" not in r for j in jobs for r in j[2])
    log = tmp_path / "log.txt"; fake = tmp_path / "img.sh"
    fake.write_text('#!/bin/bash\nwhile [ $# -gt 0 ]; do case "$1" in -r) r="$2"; shift 2;; -o) o="$2"; shift 2;; *) shift;; esac; done\n'
                    '[ -f "$r" ] || exit 1; cp "$r" "$o"; echo "$(basename "$o")" >> ' + str(log) + '\n')
    fake.chmod(0o755); monkeypatch.setattr(poses, "IMG", str(fake))
    assert poses.run_jobs(jobs, 4, False)
    assert log.read_text().split() == [f"ib_home_point_{k}.png" for k in range(1, 6)]
    import time
    time.sleep(0.05); (proj / "ib/ib_home_point_2.png").unlink()               # 2枚目だけ消して描き直すと、3〜5枚目は古い2枚目から描いたもの
    assert poses.chain_stale(lib.Proj(str(proj))) == [str(proj / f"ib/ib_home_point_{k}.png") for k in (3, 4, 5)]
    log.write_text("")
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "poses.py"), str(proj), "inbetweens"], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HOME": str(tmp_path / "home")})
    assert "ib/old/" in r.stdout and (proj / "ib/old/ib_home_point_3.png").exists()
    log2 = tmp_path / "log2.txt"; log.write_text("")
    for f in (proj / "ib").glob("ib_home_point_[345].png"): f.unlink(missing_ok=True)
    fake.write_text(fake.read_text().replace('[ -f "$r" ] || exit 1; cp', '[ -f "$r" ] || exit 1; case "$o" in *_2.png) exit 1;; esac; cp'))
    (proj / "ib/ib_home_point_2.png").unlink(missing_ok=True)
    jobs = poses.jobs_ib(lib.Proj(str(proj)))
    assert not poses.run_jobs(jobs, 4, False)                                     # 2枚目が描けなければ、3枚目からは呼ばない
    assert log.read_text().split() == []


def _spec_blocks():
    import re
    blks = re.findall(r"```json\n(.*?)```", (ROOT / "docs/mascot-poses-spec.md").read_text(encoding="utf-8"), re.S)
    return [json.loads("{" + b + "}") for b in blks]


def test_extra_presets_match_poses_spec_doc():
    """docs/mascot-poses-spec.md の段階 A・B の config の例と、vm init --extras が書く雛形（she）が同じ（片方だけ直してずれないように）。"""
    import init
    a, b = _spec_blocks()
    for tier, doc in (("a", a), ("b", b)):
        x, xp = init.extra_presets(tier)
        assert init.fill(x, "she") == doc["poses"] and xp == doc["pairs"]


def test_init_extras_are_opt_in():
    import init
    plain = init.build("x", "d", "he", "a"); ex = init.build("x", "d", "he", "a", extras="ab")
    assert not set(plain["poses"]) & {"think", "bow", "raise_r", "stretch", "crouch", "knee_bend"}
    assert set(ex["poses"]) - set(plain["poses"]) == {"think", "bow", "raise_r", "stretch", "crouch", "knee_bend"}
    assert ex["poses"]["bow"]["scale"] == 1.0 and "scale" not in ex["poses"]["think"] and "his" in ex["poses"]["bow"]["desc"]
    assert ["home", "crouch"] in ex["pairs"] and all("{" not in c["desc"] for c in ex["poses"].values())
    assert set(init.build("x", "d", extras="a")["poses"]) - set(plain["poses"]) == {"think", "bow", "raise_r", "stretch"}


def test_scale_fixes_size_of_height_changing_pose(tmp_path, env):
    """伸び（背が高くなる）を背の高さで揃えると縮む。poses.<名前>.scale を書くと、その倍率に固定する（書かない姿勢は今まで通り）。"""
    import re
    from PIL import ImageDraw
    proj = Path(sm.make(str(tmp_path / "p"))); pp = proj / "poses/pose_point.png"
    im = Image.open(pp).convert("RGB"); d = ImageDraw.Draw(im); d.rectangle([225, 30, 245, 100], fill=(40, 40, 60)); im.save(pp)   # 頭の上に挙げた腕（暗い袖）
    def scales():
        r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "render.py"), str(proj), "--out", str(tmp_path / "o.mp4"), "--mode", "white", "--to", "0.3"],
                           env=env, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr
        return eval(re.search(r"大きさ: (\{.*?\})", r.stderr).group(1))
    assert scales()["point"] < 0.95                                                 # 既定: 背で揃えて縮む
    cfg = json.loads((proj / "config.json").read_text(encoding="utf-8")); cfg["poses"]["point"]["scale"] = 1.0
    (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert scales() == {"home": 1.0, "point": 1.0}
    cfg["anchor"] = {"mode": "none"}; cfg["poses"]["point"]["scale"] = 0.9; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert scales() == {"home": 1.0, "point": 0.9}                                  # 揃えない（none）でも scale は効く
    cfg["anchor"] = {"mode": "boot"}; cfg["poses"]["point"]["scale"] = 1.0; (proj / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    out = _run("views.py", proj)
    assert "scale 固定" in out.stdout and "背が±3%を超える" not in out.stdout
