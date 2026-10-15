"""placement.py（vm overlay のプリセット・安全領域・登場退場）のテスト。入力はすべて合成。
後半は ffmpeg がある機体だけで、合成した主動画と色の四角のマスコットを vm overlay に通して、置かれた位置を画素で確かめる。"""
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import placement as pl

ROOT = Path(__file__).resolve().parent.parent
OVERLAY = ROOT / "skills/video-mascot/scripts/overlay.py"


# ---------- 大きさ ----------
def test_frame_size_matches_overlay_default_formula():
    # overlay.py の既定（--height 0.9）と同じ式であること
    for MH, OW, OH, h in [(1080, 1141, 1280, 0.9), (720, 1141, 1280, 0.55), (1081, 999, 1001, 0.37)]:
        H = int(round(MH * h / 2) * 2); W = int(round(OW * H / OH / 2) * 2)
        assert pl.frame_size(MH, OW, OH, h) == (W, H)
        assert W % 2 == 0 and H % 2 == 0


# ---------- プリセット ----------
MW, MH, OW, OH = 1920, 1080, 1141, 1280


def test_presets_left_right_center_sit_inside_safe_area():
    mx = round(MW * 0.05)
    W, H, X, Y, notes = pl.preset_geometry("left", MW, MH, OW, OH)
    assert (W, H) == pl.frame_size(MH, OW, OH, 0.9)
    assert X == mx and Y == MH - H and notes == []
    W, H, X, Y, _ = pl.preset_geometry("right", MW, MH, OW, OH)
    assert X + W == MW - mx
    W, H, X, Y, _ = pl.preset_geometry("center", MW, MH, OW, OH)
    assert abs((X + W / 2) - MW / 2) <= 1


def test_corner_presets_are_smaller():
    Wl, Hl, *_ = pl.preset_geometry("left", MW, MH, OW, OH)
    Wc, Hc, Xc, Yc, _ = pl.preset_geometry("corner-right", MW, MH, OW, OH)
    assert Hc < Hl and Wc < Wl
    assert Xc + Wc == MW - round(MW * 0.05) and Yc == MH - Hc


def test_preset_overrides_height_and_bottom():
    W, H, X, Y, _ = pl.preset_geometry("left", MW, MH, OW, OH, height=0.5, bottom=-40)
    assert (W, H) == pl.frame_size(MH, OW, OH, 0.5)
    assert Y == MH - H + 40


def test_preset_safe_zero_is_flush_to_edge():
    _, _, X, _, _ = pl.preset_geometry("left", MW, MH, OW, OH, safe=0.0)
    assert X == 0
    W, _, X, _, _ = pl.preset_geometry("right", MW, MH, OW, OH, safe=0.0)
    assert X + W == MW


def test_preset_too_wide_is_centered_with_note():
    # 縦長の主動画（スマホ向け 1080x1920）に横に広い枠
    W, H, X, Y, notes = pl.preset_geometry("left", 1080, 1920, 2000, 1280)
    assert W > 1080 * 0.9
    assert X == (1080 - W) // 2
    assert any("中央" in n for n in notes)


def test_preset_top_outside_safe_area_warns_but_keeps_size():
    W, H, X, Y, notes = pl.preset_geometry("left", MW, MH, OW, OH, height=1.0)
    assert H == MH and Y == 0
    assert any("上端" in n for n in notes)


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        pl.preset_geometry("top", MW, MH, OW, OH)


# ---------- イージング ----------
@pytest.mark.parametrize("name", pl.EASES)
def test_ease_endpoints_and_clip(name):
    assert pl.ease(name, 0) == pytest.approx(0, abs=1e-9)
    assert pl.ease(name, 1) == pytest.approx(1, abs=1e-9)
    assert pl.ease(name, -3) == pytest.approx(0, abs=1e-9)
    assert pl.ease(name, 7) == pytest.approx(1, abs=1e-9)


@pytest.mark.parametrize("name", ["linear", "out-cubic", "in-out-sine"])
def test_ease_monotone_without_overshoot(name):
    v = [pl.ease(name, i / 100) for i in range(101)]
    assert all(b >= a - 1e-12 for a, b in zip(v, v[1:]))
    assert max(v) <= 1 + 1e-12


def test_out_back_overshoots_then_settles():
    v = [pl.ease("out-back", i / 100) for i in range(101)]
    assert max(v) > 1.05          # 行き過ぎる（約 10%）
    assert v[-1] == pytest.approx(1)


def test_out_cubic_is_fast_then_slow():
    assert pl.ease("out-cubic", 0.25) > 0.25 and pl.ease("out-cubic", 0.5) == pytest.approx(0.875)


def _ffeval(expr, t):
    """ffmpeg の式を Python で評価する（使っている関数は clip・pow・cos・PI だけ）。"""
    ns = {"clip": lambda v, a, b: min(max(v, a), b), "pow": pow, "cos": math.cos, "PI": math.pi, "t": t, "__builtins__": {}}
    return eval(expr, ns)


@pytest.mark.parametrize("name", pl.EASES)
def test_ease_expr_matches_python(name):
    for i in range(-5, 26):
        u = i / 20
        assert _ffeval(pl.ease_expr(name, f"clip({u},0,1)"), 0) == pytest.approx(pl.ease(name, u), abs=1e-9)


def test_unknown_ease_raises():
    with pytest.raises(ValueError):
        pl.ease("bounce", 0.5)
    with pytest.raises(ValueError):
        pl.ease_expr("bounce", "t")


# ---------- 時間の割り振り ----------
def test_fit_durations():
    assert pl.fit_durations(10, 0.5, 0.5) == (0.5, 0.5)
    assert pl.fit_durations(0.6, 0.5, 0.7) == pytest.approx((0.25, 0.35))
    assert pl.fit_durations(0, 0.5, 0.5) == (0.0, 0.0)
    assert pl.fit_durations(5, -1, 0.5) == (0.0, 0.5)


# ---------- 滑り込み ----------
def test_slide_from_directions():
    assert pl.slide_from(0.0, 96, 108, 800, 972, MW, MH) == (-800, 108)
    assert pl.slide_from(1.0, 1000, 108, 800, 972, MW, MH) == (MW, 108)
    assert pl.slide_from(0.5, 560, 108, 800, 972, MW, MH) == (560, MH)


def test_anchor_of():
    assert pl.anchor_of(0, 800, MW) == 0.0
    assert pl.anchor_of(MW - 800, 800, MW) == 1.0
    assert pl.anchor_of((MW - 800) // 2, 800, MW) == 0.5


def test_slide_expr_without_motion_is_plain_number():
    assert pl.slide_expr(96, -800, 0, 0.5, 9.5, 0.5, "out-cubic", False, False) == "96"
    assert pl.slide_expr(96, -800, 0, 0.0, 9.5, 0.0, "out-cubic", True, True) == "96"


@pytest.mark.parametrize("name", pl.EASES)
@pytest.mark.parametrize("sin,sout", [(True, False), (False, True), (True, True)])
def test_slide_expr_matches_slide_value(name, sin, sout):
    args = (96, -800, 1.0, 0.5, 9.5, 0.5, name, sin, sout)
    e = pl.slide_expr(*args)
    for i in range(0, 121):
        t = i / 10
        assert _ffeval(e, t) == pytest.approx(pl.slide_value(args[0], args[1], t, *args[2:]), abs=1e-6)


def test_slide_value_path():
    # 1.0 秒から 0.5 秒で -800 → 96 に入り、9.5 秒から 0.5 秒で -800 へ出る
    v = lambda t: pl.slide_value(96, -800, t, 1.0, 0.5, 9.5, 0.5, "out-cubic", True, True)
    assert v(0.0) == -800 and v(1.0) == -800
    assert -800 < v(1.25) < 96
    assert v(1.5) == 96 and v(5) == 96 and v(9.5) == pytest.approx(96)
    assert -800 < v(9.75) < 96
    assert v(10.0) == pytest.approx(-800)
    # 退場は登場を逆に再生した形
    assert v(9.5 + 0.1) == pytest.approx(v(1.5 - 0.1))


# ---------- fade ----------
def test_fade_filters():
    assert pl.fade_filters("alpha", 0.5, 10, 0.5, False, False) == []
    assert pl.fade_filters("alpha", 0.5, 10, 0.5, True, True) == [
        "fade=t=in:st=0:d=0.5000:alpha=1", "fade=t=out:st=9.5000:d=0.5000:alpha=1"]
    assert pl.fade_filters("multiply", 0.5, 10, 0.4, False, True) == ["fade=t=out:st=9.6000:d=0.4000:color=0xfdfdfd"]


# ---------- vm overlay を通す（ffmpeg が要る） ----------
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg が無い")


def _ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    """合成の素材: 主動画 320x180（黒、音あり、3秒）、マスコット 100x160（赤い四角、alpha は透明の余白つき）、声（サイン波）。"""
    d = tmp_path_factory.mktemp("ov")
    work = d / "work"; (work / "out").mkdir(parents=True); (work / "voice").mkdir()
    (work / "config.json").write_text(json.dumps({"poses": {"home": {}}}), encoding="utf-8")
    _ff("-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=3", "-f", "lavfi", "-i", "sine=f=220:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "main.mp4"))
    # 枠いっぱいの赤（alpha では枠の位置そのものが見える）
    _ff("-f", "lavfi", "-i", "color=c=red:s=100x160:r=10:d=2.5", "-vf", "format=yuva420p",
        "-c:v", "libvpx-vp9", "-auto-alt-ref", "0", str(work / "out/mascot.webm"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=100x160:r=10:d=2.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(work / "out/mascot_white.mp4"))
    _ff("-f", "lavfi", "-i", "sine=f=440:d=2", "-ar", "48000", str(work / "voice/master.wav"))
    return d, work


def _overlay(d, work, *opts, out="o.mp4"):
    o = d / out
    r = subprocess.run([sys.executable, str(OVERLAY), str(d / "main.mp4"), str(work), "--out", str(o), *opts], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return o, r.stderr


def _frame(path, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(180, 320, 3)


def _red_box(img):
    m = (img[..., 0] > 150) & (img[..., 1] < 90)
    if not m.any(): return None
    ys, xs = np.nonzero(m)
    return xs.min(), ys.min(), xs.max(), ys.max()


@needs_ffmpeg
def test_overlay_preset_places_frame(synth):
    d, work = synth
    o, err = _overlay(d, work, "--preset", "right", "--duck", "1")
    W, H, X, Y, _ = pl.preset_geometry("right", 320, 180, 100, 160)
    assert f"位置 ({X}, {Y})" in err
    x0, y0, x1, y1 = _red_box(_frame(o, 1.0))
    assert abs(x0 - X) <= 2 and abs(x1 - (X + W - 1)) <= 2 and abs(y0 - Y) <= 2 and y1 >= 177


@needs_ffmpeg
def test_overlay_slide_in_and_fade_out(synth):
    d, work = synth
    o, _ = _overlay(d, work, "--preset", "left", "--enter", "slide", "--exit", "fade", "--move-dur", "0.8", "--duck", "1", out="s.mp4")
    W, H, X, Y, _ = pl.preset_geometry("left", 320, 180, 100, 160)
    mid = _red_box(_frame(o, 0.4))           # 滑り込みの途中: 左の外から入ってくる
    assert mid is not None and mid[0] == 0 and mid[2] < X + W - 4
    x0, *_ = _red_box(_frame(o, 1.2))        # 入り終わった
    assert abs(x0 - X) <= 2
    late = _frame(o, 2.35)[Y + 20:Y + 60, X + 10:X + W - 10, 0].mean()   # 退場の途中: 薄くなっている
    full = _frame(o, 1.2)[Y + 20:Y + 60, X + 10:X + W - 10, 0].mean()
    assert late < full * 0.6


@needs_ffmpeg
def test_overlay_multiply_slide(synth):
    d, work = synth
    W, H, X, Y, _ = pl.preset_geometry("center", 320, 180, 100, 160)
    # 乗算は黒い主動画では何も見えないので、白い主動画で確かめる
    _ff("-f", "lavfi", "-i", "color=c=white:s=320x180:r=10:d=3", "-f", "lavfi", "-i", "sine=f=220:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(d / "white.mp4"))
    o = d / "mw.mp4"
    r = subprocess.run([sys.executable, str(OVERLAY), str(d / "white.mp4"), str(work), "--out", str(o), "--preset", "center", "--mode", "multiply",
                        "--enter", "slide", "--move-dur", "0.8", "--duck", "1"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    mid = _red_box(_frame(o, 0.4))           # 下から上がってくる途中
    assert mid is not None and mid[1] > Y + 4 and abs(mid[0] - X) <= 2
    done = _red_box(_frame(o, 1.2))
    assert abs(done[1] - Y) <= 2


@needs_ffmpeg
def test_overlay_rejects_side_with_preset(synth):
    d, work = synth
    r = subprocess.run([sys.executable, str(OVERLAY), str(d / "main.mp4"), str(work), "--out", str(d / "x.mp4"), "--preset", "left", "--side", "right"],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "--side" in r.stderr
