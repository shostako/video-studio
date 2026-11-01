"""vm layout（画面を縮めた主動画の余白にマスコットを置き、左上に章の見出しを出す）の純関数と、合成の動画での書き出し。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import layout as L

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "video-mascot" / "scripts"


# ---------- 章の見出し（純関数）----------
def test_chapter_plan_orders_by_time_and_numbers():
    spec = {"chapters": [{"line": 3, "title": "視点"}, {"line": 1, "title": "使い方"}, {"at": 5.0, "title": "開く"}],
            "credits": [{"from": 2, "to": 4, "text": ["サンプル: a.iges"]}, {"from": 4, "text": "サンプル: b.iges"}]}
    plan, credits = L.chapter_plan(spec, {1: 0.3, 2: 4.0, 3: 10.0})
    assert plan == [(0.0, "01", "使い方"), (5.0, "02", "開く"), (9.4, "03", "視点")]   # line は 0.6 秒前、0 秒より前にしない
    assert credits == [(2.0, 4.0, ["サンプル: a.iges"]), (4.0, 1e9, ["サンプル: b.iges"])]
    plan2, _ = L.chapter_plan({"chapters": [{"line": 2, "title": "x"}], "lead": 0}, {2: 4.0})
    assert plan2 == [(4.0, "01", "x")]


@pytest.mark.parametrize("spec", [
    {"chapters": [{"line": 9, "title": "無い台詞"}]},
    {"chapters": [{"title": "時刻が無い"}]},
    {"chapters": [{"line": 1}]},
    {"credits": [{"from": 0, "text": []}]},
])
def test_chapter_plan_rejects_bad_spec(spec):
    with pytest.raises(SystemExit):
        L.chapter_plan(spec, {1: 0.0})


def test_chapter_at_and_credit_alpha():
    plan = [(0.0, "01", "a"), (5.0, "02", "b"), (9.0, "03", "c")]
    assert [L.chapter_at(t, plan) for t in (0, 4.99, 5.0, 8.9, 100)] == [0, 0, 1, 1, 2]
    assert L.chapter_at(-1, [(2.0, "01", "a")]) == 0 and L.chapter_at(3, []) is None
    assert L.credit_alpha(1.9, 2, 4) == 0 and L.credit_alpha(2.15, 2, 4) == pytest.approx(0.5) and L.credit_alpha(3, 2, 4) == 1
    assert L.credit_alpha(4.0, 2, 4) == 0


def test_fit_text_shrinks_then_truncates():
    w = lambda t, sz: len(t) * sz                                    # 1 字 = 大きさ px の等幅として
    assert L.fit_text("あいう", w, 100, 16, 34) == (32, "あいう")    # 34*3=102 → 32 で収まる
    sz, t = L.fit_text("あ" * 30, w, 200, 16, 34)
    assert sz == 16 and t.endswith("…") and w(t, sz) <= 200 and len(t) == 12   # 16px でも広いので末尾を切る
    assert L.fit_text("短い", w, 400, 16, 34) == (34, "短い")


def test_text_rgba_never_exceeds_margin():
    if not any(p and os.path.exists(p) for p in L.FONTS): pytest.skip("日本語の太字のフォントが無い")
    im = L.text_rgba("とても長いサンプルの出どころの表示で余白に収まらない文字列の例です" * 2, 20, L.SUB, 416)
    assert im.shape[1] <= 416


def test_heading_bottom():
    assert L.heading_bottom([]) == L.RULE_Y + 3
    assert L.heading_bottom([(0, 1, ["a", "b", "c"])]) == L.CREDIT_Y + 3 * L.CREDIT_STEP


# ---------- 合成の動画で書き出す ----------
W, H, FPS = 1920, 1080, 60


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def font_or_skip():
    if not any(p and os.path.exists(p) for p in L.FONTS): pytest.skip("日本語の太字のフォントが無い")


def make_inputs(root, env, secs=1.0):
    """主動画（灰色の 1920x1080）、透明のマスコット（941x1672 を高さ 1280 に縮めた形の中に黒い人型の箱）、声、timing.json。"""
    root.mkdir(parents=True, exist_ok=True); (root / "voice").mkdir(); (root / "out").mkdir()
    n = int(secs * FPS)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0xf4f4f4:s={W}x{H}:r={FPS}:d={secs}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(root / "main.mp4")], env=env, check=True)
    mw, mh = 720, 1280
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{mw}x{mh}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "30", "-auto-alt-ref", "0",
                          str(root / "out" / "mascot.webm")], stdin=subprocess.PIPE, env=env)
    fr = np.zeros((mh, mw, 4), np.uint8); fr[200:1160, 260:460] = (20, 20, 20, 255)   # 人物（上端 200・足元 1159）
    for _ in range(n): p.stdin.write(fr.tobytes())
    p.stdin.close(); assert p.wait() == 0
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}", "-ar", "24000",
                    str(root / "voice" / "master.wav")], env=env, check=True)
    json.dump({"lines": [{"n": 1, "start": 0.0, "dur": 0.4}, {"n": 2, "start": 0.7, "dur": 0.3}], "end": secs}, open(root / "voice" / "timing.json", "w"))


def frame_at(path, t, env):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, env=env).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def run_layout(root, env, *extra):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "layout.py"), str(root / "main.mp4"), str(root), *extra],
                          capture_output=True, text=True, env=env, timeout=300)


def test_layout_places_mascot_and_draws_chapters(tmp_path, env):
    font_or_skip()
    root = tmp_path / "proj"; make_inputs(root, env)
    json.dump({"chapters": [{"line": 1, "title": "はじめに"}, {"line": 2, "title": "つぎ"}],
               "credits": [{"from": 0.5, "text": ["サンプル: 合成"]}]}, open(root / "chapters.json", "w"), ensure_ascii=False)
    out = tmp_path / "out.mp4"
    r = run_layout(root, env, "--out", str(out), "--chapters", str(root / "chapters.json"))
    assert r.returncode == 0, r.stderr
    crop = next(l.split()[1] for l in r.stdout.splitlines() if l.startswith("CROP "))
    x, y, cw, ch = map(int, crop.split(","))
    assert 0 <= x and x + cw <= 496 and y > L.heading_bottom([(0, 1, ["a"])])     # マスコットは余白の中で、見出しの下
    f0, f1 = frame_at(out, 0.05, env), frame_at(out, 0.9, env)
    rule = f0[L.RULE_Y, L.HEAD_X + 10]
    assert rule[0] > 180 and rule[2] < 100                                        # 橙の下線
    assert (f0[L.TITLE_Y:L.TITLE_Y + 40, L.HEAD_X:L.HEAD_X + 200] < 120).any()   # 見出しの字（濃い色）
    assert not (f0[L.CREDIT_Y:L.CREDIT_Y + 24, L.HEAD_X:L.HEAD_X + 200] < 200).any()   # 0.5 秒より前は出どころを出さない
    assert (f1[L.CREDIT_Y:L.CREDIT_Y + 24, L.HEAD_X:L.HEAD_X + 200] < 200).any()
    assert (f0[L.NUM_Y:L.NUM_Y + 20, L.HEAD_X:L.HEAD_X + 40] != f1[L.NUM_Y:L.NUM_Y + 20, L.HEAD_X:L.HEAD_X + 40]).any()   # 01 → 02
    body = f0[y + 10:y + ch - 10, x:x + cw]
    assert (body < 60).all(axis=2).any()                                          # 人物（黒）が置かれている
    assert f0[600, 1200].min() > 220                                              # 余白の外（主動画）はそのまま


def test_layout_without_chapters_and_place_only(tmp_path, env):
    root = tmp_path / "proj"; make_inputs(root, env, secs=0.5)
    r = run_layout(root, env, "--place-only")
    assert r.returncode == 0 and "CROP " in r.stdout and "見出し" not in r.stdout
    out = tmp_path / "plain.mp4"
    r = run_layout(root, env, "--out", str(out))
    assert r.returncode == 0, r.stderr
    f = frame_at(out, 0.1, env)
    assert f[L.RULE_Y, L.HEAD_X + 10].min() > 220                                  # 見出しは出さない


# ---------- chapters.py（compose.py と共通）----------
import chapters as CH  # noqa: E402


def test_fit_heading_one_line_two_lines_truncate():
    w = lambda t, sz: len(t) * sz
    assert CH.fit_heading("はじめに", w, 416) == (34, ["はじめに"])
    assert CH.fit_heading("あ" * 15, w, 416) == (26, ["あ" * 15])                       # 34 では入らず 26 で 1 行
    sz, rows = CH.fit_heading("とても長い見出しの例を書いてみるとどうなるか", w, 416)
    assert sz == 30 and len(rows) == 2 and all(w(r, sz) <= 416 for r in rows) and "".join(rows) == "とても長い見出しの例を書いてみるとどうなるか"
    sz, rows = CH.fit_heading("設備の電気代・基本料金の見方", w, 330)
    assert sz == 30 and rows == ["設備の電気代・", "基本料金の見方"]                       # 区切りの字の後ろで折る
    sz, rows = CH.fit_heading("あ" * 60, w, 416)
    assert sz == 22 and rows[1].endswith("…") and all(w(r, sz) <= 416 for r in rows)


def test_heading_block_and_flash_alpha():
    assert CH.heading_block(34, 1) == ([76], 128)
    ys, ry = CH.heading_block(30, 2); assert ys == [76, 118] and ry == 166
    assert [CH.flash_alpha(t, 10) for t in (9.9, 10.15, 12, 13.8, 14.3)] == [0.0, pytest.approx(0.5), 1.0, pytest.approx(0.5), 0.0]


def test_layout_reads_margin_from_layout_json(tmp_path, env):
    font_or_skip()
    root = tmp_path / "proj"; make_inputs(root, env, secs=0.5)
    (root / "main.layout.json").write_text(json.dumps({"layout": "margin", "margin": 384, "chapters": True}))
    json.dump({"chapters": [{"at": 0, "title": "x"}]}, open(root / "ch.json", "w"))
    r = run_layout(root, env, "--place-only", "--chapters", str(root / "ch.json"))
    assert r.returncode == 0, r.stderr
    x, y, cw, ch = map(int, next(l.split()[1] for l in r.stdout.splitlines() if l.startswith("CROP ")).split(","))
    assert x + cw <= 384 + 20 and abs((x + cw / 2) - 192) < 40                            # 余白 384 の真ん中に立つ
    assert "二重に出る" in r.stdout



def test_layout_shrinks_mascot_to_fit_narrow_margin(tmp_path, env):
    """余白が狭い（--scale 0.88 で 208px）と、全身も胸から上も余白に収まるまで縮める（Codex の指摘）。"""
    root = tmp_path / "proj"; make_inputs(root, env, secs=0.5)
    for extra in ([], ["--frame", "bust"]):
        r = run_layout(root, env, "--place-only", "--margin", "208", *extra)
        assert r.returncode == 0, r.stderr
        x, y, cw, ch = map(int, next(l.split()[1] for l in r.stdout.splitlines() if l.startswith("CROP ")).split(","))
        if extra: assert x >= 0 and x + cw <= 208 and "縮めた" in r.stdout
    r = run_layout(root, env, "--place-only", "--margin", "60")
    assert r.returncode != 0 and "狭すぎて" in r.stderr


# ---------- ワイプの型（--style wipe）----------
def test_face_box_centers_on_head_and_stays_inside():
    fg = np.zeros((1280, 720), bool); fg[200:1160, 260:460] = True; fg[200:440, 300:420] = True
    x, y, side = L.face_box(fg)
    assert side == int(0.44 * 959) // 2 * 2 and abs((x + side / 2) - 360) <= 2 and y == round(200 - 0.01 * 959)
    fg2 = np.zeros((600, 300), bool); fg2[0:590, 0:40] = True                      # 端に寄った人物でも枠は画面の内側
    x2, y2, s2 = L.face_box(fg2)
    assert x2 >= 0 and y2 >= 0 and x2 + s2 <= 300 and y2 + s2 <= 600


def test_wipe_layers_shapes():
    under, over, mask = L.wipe_layers(200)
    assert under.shape == over.shape == (252, 252, 4) and mask.shape == (200, 200, 1)
    assert mask[100, 100, 0] > 0.99 and mask[0, 0, 0] < 0.01                       # 丸の中は 1、角は 0
    assert over[26 - 4 + 3, 126, 0] > 200 and over[26 - 4 + 3, 126, 2] < 100       # 上の縁は橙


def test_layout_wipe_puts_round_face_bottom_left(tmp_path, env):
    root = tmp_path / "proj"; make_inputs(root, env, secs=0.5)
    out = tmp_path / "wipe.mp4"
    r = run_layout(root, env, "--out", str(out), "--style", "wipe")
    assert r.returncode == 0, r.stderr
    crop = next(l.split()[1] for l in r.stdout.splitlines() if l.startswith("CROP "))
    assert crop == "48,632,400,400"                                                # 余白 496 の真ん中、下から 48、直径 400
    f = frame_at(out, 0.2, env)
    assert f[832, 248].max() < 80                                                  # 丸の真ん中に人物（黒）
    assert f[632 + 2, 248][0] > 180 and f[632 + 2, 248][2] < 110                   # 上の縁は橙
    assert f[632 + 30, 48 + 30].min() > 200                                        # 丸の外の角は余白の地のまま（四角く出ない）
    r = run_layout(root, env, "--place-only", "--style", "wipe", "--margin", "150")
    assert r.returncode != 0 and "ワイプを置けない" in r.stderr



def test_layout_wipe_uses_precropped_mascot(tmp_path, env):
    """vm render --crop で顔の周りだけを書き出した動画（隣に .crop.json）は、測り直さずにそのまま丸にする。"""
    root = tmp_path / "proj"; make_inputs(root, env, secs=0.5)
    sq = root / "out" / "face.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", str(root / "out" / "mascot.webm"), "-vf", "crop=200:200:260:200",
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(sq)], env=env, check=True)
    json.dump({"box": [260, 200, 200], "size": [720, 1280]}, open(root / "out" / "face.crop.json", "w"))
    out = tmp_path / "wipe.mp4"
    r = run_layout(root, env, "--out", str(out), "--style", "wipe", "--mascot", str(sq))
    assert r.returncode == 0, r.stderr
    assert "切り抜き済み" in r.stdout and "切り抜き 0,0 辺 200" in r.stdout
    f = frame_at(out, 0.2, env)
    assert f[832, 248].max() < 80 and f[640, 248].max() < 80                       # 丸いっぱいに人物（黒い箱の上の方）
    os.utime(root / "out" / "face.crop.json", (1, 1))                               # 動画より古い控えは使わない
    r = run_layout(root, env, "--place-only", "--style", "wipe", "--mascot", str(sq))
    assert r.returncode == 0 and "切り抜き済み" not in r.stdout


def test_layout_rejects_wipe_size_larger_than_margin(tmp_path, env):
    """--wipe-size が余白に入らなければ書き出す前に止める（Codex の指摘。負の x で NumPy が落ちていた）。"""
    root = tmp_path / "proj"; make_inputs(root, env, secs=0.5)
    r = run_layout(root, env, "--out", str(tmp_path / "o.mp4"), "--style", "wipe", "--margin", "384", "--wipe-size", "400")
    assert r.returncode != 0 and "入らない" in r.stderr and not (tmp_path / "o.mp4").exists()
    r = run_layout(root, env, "--place-only", "--style", "wipe", "--margin", "384", "--wipe-size", "320")
    assert r.returncode == 0 and "CROP 32,712,320,320" in r.stdout
