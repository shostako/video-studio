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


def _run(tmp_path, *extra, scenes=None, wipe_on=True):
    shots, voice, wipe = tmp_path / "shots", tmp_path / "work", tmp_path / "wipe"
    for p in (shots, voice, wipe): p.mkdir(exist_ok=True)
    _shots(shots); end = _voice(voice); _wipe(wipe)
    env = dict(os.environ, SCREEN_EXPLAINER_FONT=FONT)
    cmd = [sys.executable, str(SK / "scripts" / "compose.py"), "--shots", str(shots), "--voice", str(voice),
           "--scenes", str(scenes or SK / "assets" / "example_scenes.py"), "--out", str(tmp_path / "out.mp4")] + (["--wipe", str(wipe)] if wipe_on else []) + list(extra)
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


def _film(shots, n=5):
    for i in range(n):
        Image.new("RGB", (1920, 1020), (10 + 40 * i, 200, 30)).save(shots / f"rot_{i:03d}.png")
    (shots / "film.json").write_text(json.dumps({"rot": [[600 + 50 * i, 500] for i in range(n)]}))


@needs_font
def test_compose_plays_film_frames_in_order(tmp_path):
    shots = tmp_path / "shots"; shots.mkdir(); _film(shots)
    sc = tmp_path / "film.py"
    sc.write_text('add(imgs=[(0, "s01")], cam=[(0, FULL)], cur=[(0, (10, 10))], film=[(0, 1, "rot")])\n'
                  'add(imgs=[(0, "s01")], cam=[(0, FULL)], cur=[(0, (10, 10))])\n'
                  'add(imgs=[(0, "s02")], cam=[(0, FULL)], cur=[(0, (10, 10))])\n', encoding="utf-8")
    r, _ = _run(tmp_path, "--preview", "0.1,1.0,1.9", scenes=sc)        # 行 1 は 0〜2.0 秒、連番 5 枚
    assert r.returncode == 0, r.stderr
    reds = [Image.open(p).getpixel((1500, 700))[0] for p in sorted(tmp_path.glob("out_t*.png"))]
    assert reds[0] < reds[1] < reds[2]                                # 重ねずに、順に進む


@needs_font
def test_compose_wipe_home_corner(tmp_path):
    r, _ = _run(tmp_path, "--preview", "0.5", "--wipe-home", "BL")    # 行 1 の強調とカーソルは画面の上半分だけ
    assert r.returncode == 0, r.stderr
    a = np.asarray(Image.open(next(tmp_path.glob("out_t*.png"))).convert("RGB"), np.int16)
    ring = lambda y0, y1, x0, x1: int(((a[y0:y1, x0:x1, 0] > 230) & (a[y0:y1, x0:x1, 1] < 120) & (a[y0:y1, x0:x1, 2] < 40)).sum())
    assert ring(660, 1020, 0, 380) > 500 and ring(660, 1020, 1540, 1920) < 50


@needs_font
def test_compose_film_end_switch_does_not_rewind(tmp_path):
    shots = tmp_path / "shots"; shots.mkdir(); _film(shots)
    sc = tmp_path / "film.py"                                          # 連番の終わり（.5）で動きの後の撮影 s02 に切り替える
    sc.write_text('add(imgs=[(0, "s01"), (.5, "s02")], cam=[(0, FULL)], cur=[(0, (10, 10))], film=[(0, .5, "rot")])\n'
                  'add(imgs=[(0, "s02")], cam=[(0, FULL)], cur=[(0, (10, 10))])\n'
                  'add(imgs=[(0, "s02")], cam=[(0, FULL)], cur=[(0, (10, 10))])\n', encoding="utf-8")
    r, _ = _run(tmp_path, "--preview", "1.05", scenes=sc)              # 切り替えの 0.05 秒後（重ねると s01 が混ざる）
    assert r.returncode == 0, r.stderr
    got = Image.open(next(tmp_path.glob("out_t*.png"))).getpixel((410, 545))
    assert got == (200, 230, 200)                                     # s02 にだけある欄の色そのまま（s01 は地の色）


@needs_font
def test_compose_wipe_avoids_film_cursor(tmp_path):
    shots = tmp_path / "shots"; shots.mkdir()
    for i in range(4): Image.new("RGB", (1920, 1020), (90, 90, 90)).save(shots / f"drag_{i:03d}.png")
    (shots / "film.json").write_text(json.dumps({"drag": [[1700 + 20 * i, 850] for i in range(4)]}))   # 右下で動かす
    sc = tmp_path / "film.py"
    sc.write_text('add(imgs=[(0, "s01")], cam=[(0, FULL)], cur=[(0, (500, 300)), (.5, (500, 300))], film=[(.1, .9, "drag")])\n'
                  'add(imgs=[(0, "s01")], cam=[(0, FULL)], cur=[(0, (500, 300))])\n'
                  'add(imgs=[(0, "s02")], cam=[(0, FULL)], cur=[(0, (500, 300))])\n', encoding="utf-8")
    r, _ = _run(tmp_path, "--preview", "0.1", scenes=sc)
    assert r.returncode == 0, r.stderr
    a = np.asarray(Image.open(next(tmp_path.glob("out_t*.png"))).convert("RGB"), np.int16)
    ring = lambda y0, y1, x0, x1: int(((a[y0:y1, x0:x1, 0] > 230) & (a[y0:y1, x0:x1, 1] < 120) & (a[y0:y1, x0:x1, 2] < 40)).sum())
    assert ring(660, 1020, 1540, 1920) < 50 and ring(0, 360, 1540, 1920) > 500     # 右下を避けて右上へ


# ---------- 余白ありの割り付け（--layout margin）と章の見出し（--chapters）----------
def _chapters(tmp_path, spec=None):
    p = tmp_path / "ch.json"
    p.write_text(json.dumps(spec or {"chapters": [{"line": 1, "title": "はじめに"}, {"line": 2, "title": "つぎ"}],
                                     "credits": [{"from": 0.0, "text": ["サンプル: 合成"]}]}, ensure_ascii=False), encoding="utf-8")
    return p


def _png(tmp_path, t):
    return np.asarray(Image.open(tmp_path / f"out_t{t:06.2f}.png").convert("RGB"), np.int16)


@needs_font
def test_compose_margin_layout_places_panel_right(tmp_path):
    r, _ = _run(tmp_path, "--layout", "margin", "--preview", "0.5", wipe_on=False)
    assert r.returncode == 0, r.stderr
    a = _png(tmp_path, 0.5)
    pw = int(1920 * 0.73 / 2) * 2; px = 1920 - 24 - pw
    assert px == 496
    assert (np.abs(a[600, 100] - (247, 246, 244)) <= 2).all()       # 余白は明るい無地（マスコットを置く所）
    assert (np.abs(a[300, px + pw // 2] - (245, 245, 245)) <= 6).all()   # 画面（撮影の背景）は右に寄っている
    assert (a[800:900, px:px + pw] < 120).any()                    # 字幕は画面のすぐ下に濃い字で（上 34＋画面 744＋30）


@needs_font
def test_compose_margin_rejects_wipe_and_bad_scale(tmp_path):
    r, _ = _run(tmp_path, "--layout", "margin", "--preview", "0.5")
    assert r.returncode != 0 and "--wipe" in r.stderr
    (tmp_path / "b").mkdir(); r, _ = _run(tmp_path / "b", "--layout", "margin", "--scale", "0.95", "--preview", "0.5", wipe_on=False)
    assert r.returncode != 0 and "--scale" in r.stderr


@needs_font
def test_compose_margin_chapters_stay_in_margin(tmp_path):
    ch = _chapters(tmp_path)
    r, _ = _run(tmp_path, "--layout", "margin", "--chapters", str(ch), "--preview", "0.5,3.2", wipe_on=False)
    assert r.returncode == 0, r.stderr
    a, b = _png(tmp_path, 0.5), _png(tmp_path, 3.2)
    rule = a[128, 50]; assert rule[0] > 180 and rule[2] < 100      # 橙の下線（1 行の見出しは 128）
    assert (a[44:66, 40:80] != b[44:66, 40:80]).any()              # 番号が 01 → 02 に替わる
    assert (a[148:170, 40:200] < 200).any() and (b[148:170, 40:200] < 200).any()   # 出どころは出し続ける


@needs_font
def test_compose_full_chapters_flash_then_fade(tmp_path):
    ch = _chapters(tmp_path, {"chapters": [{"at": 0.0, "title": "はじめに"}]})
    r, end = _run(tmp_path, "--chapters", str(ch), "--preview", "1.0,5.5", wipe_on=False)
    assert r.returncode == 0, r.stderr
    a, b = _png(tmp_path, 1.0), _png(tmp_path, 5.5)
    assert a[60:100, 40:100].mean() < 120                          # 1 秒: 左上に濃い札
    assert b[60:100, 40:100].mean() > 200                          # 5.5 秒（0.3+3+1 秒の後）: 消えて撮影の明るい地に戻る


@needs_font
@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg が無い")
def test_compose_writes_layout_json(tmp_path):
    r, _ = _run(tmp_path, "--layout", "margin", "--scale", "0.8", "--from", "0", "--to", "0.5", wipe_on=False)
    assert r.returncode == 0, r.stderr
    lay = json.loads((tmp_path / "out.layout.json").read_text())
    assert lay["layout"] == "margin" and lay["margin"] == 1920 - 24 - 1536 and lay["panel"][2] == 1536 and lay["chapters"] is False


@needs_font
def test_compose_margin_captions_do_not_overlap_or_overflow(tmp_path):
    """台詞の間が短くても字幕は 1 つだけ（Codex の指摘）。入らない長い行は文ごとに分け、1 文でも入らなければ止める。"""
    shots, voice = tmp_path / "shots", tmp_path / "work"
    for p in (shots, voice): p.mkdir()
    _shots(shots); _voice(voice, gap=0.1)
    cfg = json.loads((voice / "config.json").read_text(encoding="utf-8"))
    cfg["voice"]["lines"][1]["text"] = "長い台詞の一つ目の文で、画面を大きくしたときに字幕が下の空きに入るかを見る。" * 3 + "二つ目の文だ。"
    (voice / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, SCREEN_EXPLAINER_FONT=FONT)
    base = [sys.executable, str(SK / "scripts" / "compose.py"), "--shots", str(shots), "--voice", str(voice),
            "--scenes", str(SK / "assets" / "example_scenes.py"), "--out", str(tmp_path / "out.mp4"), "--layout", "margin"]
    t = 2.05                                                        # 行 1 の終わり（2.0）と行 2 の頭（2.1）の間
    r = subprocess.run(base + ["--scale", "0.85", "--preview", f"{t}"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    a = _png(tmp_path, t)
    pw = int(1920 * 0.85 / 2) * 2; ph = int(round(pw * 1020 / 1920 / 2)) * 2; top = 34 + ph + 30
    assert a[top + 80:, :].min() >= 0 and (a[top:1080, 1920 - 24 - pw:1896] < 120).any()   # 字幕が出ている
    cfg["voice"]["lines"][2]["text"] = "区切りの無いとても長い一つの文" * 120 + "。"   # どの字体でも入らない長さ
    (voice / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(base + ["--scale", "0.88", "--preview", "3.0"], capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "行 3 の字幕" in r.stderr and "入らない" in r.stderr
