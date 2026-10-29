"""screen-explainer: 合成した撮影・声・顔で、ワイプの顔づくりと compose.py の組み立てが通るかを見る。"""
import json, math, os, shutil, struct, subprocess, sys, wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SK = ROOT / "skills" / "screen-explainer"
sys.path.insert(0, str(SK / "scripts"))
import wipe_faces  # noqa: E402

FONTS = [os.environ.get("SCREEN_EXPLAINER_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONT = next((p for p in FONTS if p and os.path.exists(p)), None)
needs_font = pytest.mark.skipif(FONT is None, reason="太字のフォントが無い")


def _pose(h=900, w=700):
    im = np.full((h, w, 3), 200, np.float32)
    im[100:800, 150:550] = (90, 120, 160)                # 頭と体の代わり
    return im


def test_wipe_faces_changes_only_mouth_region():
    pose = _pose(); roi = [250, 500, 450, 600]
    parts = []
    for v in (40, 80, 120):
        p = pose.copy(); p[480:620, 230:470] = v; parts.append(p)   # 口の範囲より少し広く変えておく
    fs = wipe_faces.faces(pose, parts, roi, (350, 520), 0.8)
    assert len(fs) == 4 and all(f.shape == (440, 440, 3) for f in fs)
    assert np.array_equal(fs[0], wipe_faces.wipe_crop(pose, (350, 520), 0.8).astype(np.uint8))
    # 頭（口の楕円から遠い所）は 4 枚とも同じ、口のまん中は違う
    far = (slice(20, 120), slice(20, 420))
    for f in fs[1:]:
        assert np.array_equal(f[far], fs[0][far])
    cy, cx = int(220 + (550 - 520) * 0.8), int(220 + (350 - 350) * 0.8) + 0
    vals = [int(f[cy, cx, 0]) for f in fs]
    assert vals[0] != vals[1] != vals[2] != vals[3]


def test_wipe_faces_rejects_size_mismatch():
    with pytest.raises(ValueError):
        wipe_faces.faces(_pose(), [_pose(800, 700)] * 3, [250, 500, 450, 600], (350, 520), 0.8)


def test_wipe_crop_pads_outside_image():
    out = wipe_faces.wipe_crop(_pose(300, 300), (10, 10), 0.8)
    assert out.shape == (440, 440, 3)


def _shots(d):
    rects = {}
    for name, extra in (("s01", None), ("s02", "42")):
        im = Image.new("RGB", (1920, 1020), (245, 245, 245)); dr = ImageDraw.Draw(im)
        dr.rectangle([200, 120, 900, 180], fill=(60, 90, 160)); dr.rectangle([300, 400, 520, 450], outline=(0, 0, 0), width=2)
        if extra: dr.rectangle([300, 520, 520, 570], fill=(200, 230, 200))
        im.save(d / f"{name}.png")
        rects[name] = {"title": [200, 120, 900, 180], "input": [300, 400, 520, 450], "result": [300, 520, 520, 570]}
    (d / "rects.json").write_text(json.dumps(rects), encoding="utf-8")


def _voice(d, durs=(2.0, 2.5, 1.5), gap=0.5, sr=16000):
    (d / "voice").mkdir(parents=True)
    lines, t, info = [], 0.0, []
    for i, du in enumerate(durs):
        lines.append({"text": f"行{i + 1}の台詞だ。二つ目の文だ。"}); info.append({"n": i + 1, "start": round(t, 3), "dur": du}); t += du + gap
    end = t - gap + 0.6
    (d / "config.json").write_text(json.dumps({"name": "t", "fps": 30, "poses": {"none": {}}, "voice": {"lines": lines}}, ensure_ascii=False), encoding="utf-8")
    (d / "voice" / "timing.json").write_text(json.dumps({"lines": info, "end": end}))
    n = int(end * sr); buf = bytearray()
    for k in range(n):
        tt = k / sr; on = any(x["start"] <= tt < x["start"] + x["dur"] for x in info)
        amp = (0.3 + 0.3 * math.sin(2 * math.pi * 3 * tt)) if on else 0.0         # 声の大きさが揺れる代わり
        buf += struct.pack("<h", int(32767 * amp * math.sin(2 * math.pi * 220 * tt)))
    with wave.open(str(d / "voice" / "master.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(bytes(buf))
    return end


def _wipe(d):
    pose = _pose(); parts = []
    for v in (40, 80, 120):
        p = pose.copy(); p[480:620, 230:470] = v; parts.append(p)
    import cv2
    for i, f in enumerate(wipe_faces.faces(pose, parts, [250, 500, 450, 600], (350, 520), 0.8)):
        cv2.imwrite(str(d / f"mouth{i}.png"), f)


def _run(tmp_path, *extra, scenes=None):
    shots, voice, wipe = tmp_path / "shots", tmp_path / "work", tmp_path / "wipe"
    for p in (shots, voice, wipe): p.mkdir(exist_ok=True)
    _shots(shots); end = _voice(voice); _wipe(wipe)
    env = dict(os.environ, SCREEN_EXPLAINER_FONT=FONT)
    cmd = [sys.executable, str(SK / "scripts" / "compose.py"), "--shots", str(shots), "--voice", str(voice),
           "--scenes", str(scenes or SK / "assets" / "example_scenes.py"), "--out", str(tmp_path / "out.mp4"), "--wipe", str(wipe), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, env=env), end


@needs_font
def test_compose_preview_from_example_scenes(tmp_path):
    r, _ = _run(tmp_path, "--preview", "0.5,3.2,5.8")
    assert r.returncode == 0, r.stderr
    outs = sorted(tmp_path.glob("out_t*.png"))
    assert len(outs) == 3
    for p in outs:
        assert Image.open(p).size == (1920, 1080)
    a, b = (np.asarray(Image.open(p).convert("RGB"), np.int16) for p in outs[:2])
    assert np.abs(a - b).mean() > 1          # 寄りと強調で、場面ごとに絵が変わる


@needs_font
def test_compose_rejects_scene_count_mismatch(tmp_path):
    sc = tmp_path / "two.py"
    sc.write_text('add(imgs=[(0, "s01")], cam=[(0, FULL)], cur=[(0, (10, 10))])\n' * 2, encoding="utf-8")
    r, _ = _run(tmp_path, "--preview", "0.5", scenes=sc)
    assert r.returncode != 0 and "場面の数" in r.stderr


@needs_font
@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg が無い")
def test_compose_writes_mp4_atomically(tmp_path):
    r, _ = _run(tmp_path, "--from", "0", "--to", "1")
    assert r.returncode == 0, r.stderr
    out = tmp_path / "out.mp4"
    assert out.exists() and not (tmp_path / "out.mp4.part").exists()
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                             capture_output=True, text=True).stdout)
    assert 0.8 < d < 1.3
