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


def test_face_suspicious_flags():
    import face
    assert face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [130, 150, 170, 180]}) == []
    assert "口が目より上" in face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [130, 60, 170, 90]})
    assert face.suspicious({"eye_roi": [100, 100, 200, 130], "mouth_roi": [0, 150, 400, 700]})       # 口が体じゅうに広がった
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
    assert init.build("x", "d")["inbetween_prompt"] == "percent"                   # 新しいキャラは割合の言い方で始める
