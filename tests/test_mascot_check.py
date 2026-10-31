"""切り替えの検査: vm render の最後の表と .check.json（--strict・--check-only）、書き出した動画を画素で測る vm check。
純関数・合成のマスコットでの vm render・合成した動画での vm check。RIFE・ComfyUI・GPU はここでは使わない。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import lib  # noqa: E402
import synth_mascot as sm  # noqa: E402
from test_mascot_head import fill_direct  # noqa: E402

RENDER = ROOT / "skills/video-mascot/scripts/render.py"
CHECK = ROOT / "skills/video-mascot/scripts/check.py"
SW1 = {"at": 1.0, "dur": 0.3, "from": "home", "to": "point", "kind": "ib", "engine": "drawn"}


# ---------- frame_tag ----------
def test_frame_tag():
    assert lib.frame_tag(("pose", "home")) == ("pose", "home")
    assert lib.frame_tag(("ib", ("/w/p/ib_wan/home__point/n47/f3.png", "home", "point", 1), "home")) == ("ib", "home", "point", "wan")
    assert lib.frame_tag(("ib", ("/w/p/ib_interp/home_point_x6/f3.png", "home", "point", 1), "home")) == ("ib", "home", "point", "interp")
    assert lib.frame_tag(("ib", ("/w/p/ib/home_point_3.png", "home", "point", 3), "home")) == ("ib", "home", "point", "drawn")
    assert lib.frame_tag(("mix", "home", "turn_l", 0.5, 0.0)) == ("mix", "home", "turn_l")
    assert lib.frame_tag(("ib", ("/x.png", "home", "home", 0), "home", "head"), head=True) == ("head",)


# ---------- switch_check ----------
def tags(home=10, mid=3, after="point", mid_tag=("ib", "home", "point", "drawn"), n=30):
    return [("pose", "home")] * home + [mid_tag] * mid + [("pose", after)] * (n - home - mid)


@pytest.mark.parametrize("tg, sw, want", [
    (tags(), SW1, "ok"),
    (tags(mid_tag=("head",)), SW1, "head"),                                              # 頭の動きに隠れた
    (tags(mid_tag=("pose", "home")), SW1, "missing"),                                    # 列が一度も出ていない
    (tags(mid_tag=("ib", "home", "point", "interp")), {**SW1, "engine": "wan"}, "not_wan"),
    (tags(after="home"), SW1, "not_reached"),                                            # 終わった後に次の姿勢でない
    (tags(mid=4), SW1, "ok"),                                                            # 終わりのコマが丸めで列の最後の 1 枚（1 コマの差は許す）
    (tags(mid=0), {**SW1, "kind": "instant", "dur": 0.0}, "ok"),                         # 一瞬の切り替え
    (tags(mid=0, after="home"), {**SW1, "kind": "instant", "dur": 0.0}, "not_reached"),
    (tags(mid_tag=("mix", "point", "home")), {**SW1, "kind": "mix"}, "ok"),              # 溶かしは前後どちら向きでもその組
    (tags(n=15) + [("head",)] * 15, SW1, "ok"),                                           # 着いた（1.3・1.4 秒）すぐ後に頭の動き（1.5 秒〜）
    (tags(n=13) + [("head",)] * 17, SW1, "head"),                                         # 着く前に頭の動き
])
def test_switch_check_status(tg, sw, want):
    r = lib.switch_check(tg, 0, 10, [sw])[0]
    assert r["status"] == want, r
    assert r["from"] == sw["from"] and "frames" in r


def test_switch_check_skips_outside_range_and_does_not_modify_input():
    sws = [dict(SW1)]
    assert lib.switch_check(tags(), 20, 10, sws)[0]["status"] == "skip"          # 書き出した範囲（2.0 秒から）の外
    assert lib.switch_check([("pose", "home")] * 5, 0, 10, sws)[0]["status"] == "skip"   # 範囲（0.5 秒まで）の外
    assert "status" not in sws[0]


def test_switch_check_next_switch_starts_before_the_end():
    """次の切り替えが前の終わりより先に始まるなら、前の「次の姿勢に着いたか」は見ない。"""
    sws = [{**SW1, "dur": 0.6}, {"at": 1.3, "dur": 0.3, "from": "point", "to": "home", "kind": "ib", "engine": "drawn"}]
    tg = [("pose", "home")] * 10 + [("ib", "home", "point", "drawn")] * 3 + [("ib", "home", "point", "drawn")] * 3 + [("pose", "home")] * 14
    assert [r["status"] for r in lib.switch_check(tg, 0, 10, sws)] == ["ok", "ok"]


def test_switch_report():
    ok = lib.switch_check(tags(), 0, 10, [SW1])
    assert lib.switch_report(ok) == ["切り替えの検査: 1 件（drawn 1） — 全部動いた"]
    bad = lib.switch_report(lib.switch_check(tags(mid_tag=("head",)), 0, 10, [SW1]))
    assert "問題 1 件" in bad[0] and "✗ 1.00 秒 home→point" in bad[1] and "頭の動きに隠れて" in bad[1]


# ---------- 測るための純関数 ----------
def test_head_spans():
    keys = [(1.0, "home"), (1.5, "look_r"), (2.0, "home"), (9.0, "home"), (9.5, "look_r"), (10.0, "home")]
    assert lib.head_spans(keys, "home") == [(1.0, 2.0), (9.0, 10.0)]
    assert lib.head_spans(keys) == [(1.0, 10.0)]
    assert lib.head_spans([(1.0, "home")], "home") == []


def test_motion_verdict():
    assert lib.motion_verdict(0.003, 0.0005) == "moved"
    assert lib.motion_verdict(0.0007, 0.0005) == "weak"
    assert lib.motion_verdict(0.0001, 0.0005) == "still"
    assert lib.motion_verdict(0.5, None) == "unknown"


def test_switch_spans():
    sws = [SW1, {"at": 1.4, "dur": 0.3, "from": "point", "to": "home", "kind": "ib"}, {"at": 3.0, "dur": 0.3, "from": "home", "to": "home", "kind": "ib"},
           {"at": 9.0, "dur": 0.3, "from": "home", "to": "point", "kind": "ib"}]
    sp = lib.switch_spans(sws, 0.05, 0.0, 5.0)
    assert sp[0] == pytest.approx((0.95, 1.35))                                     # 直後は次の開始（1.4 秒）の手前まで
    assert sp[1] == pytest.approx((1.35, 1.75)) and sp[2] is None and sp[3] is None  # 同じ姿勢・範囲の外
    b2b = [SW1, {"at": 1.3, "dur": 0.3, "from": "point", "to": "home", "kind": "ib"}]   # 続けて並ぶ切り替え
    sp = lib.switch_spans(b2b, 2 / 30, 0.0, 5.0)
    assert sp[0] == pytest.approx((1.0 - 2 / 30, 1.3)) and sp[1] == pytest.approx((1.3, 1.6 + 2 / 30))   # 前の終わり・次の始まりで止める
    ovl = [SW1, {"at": 1.2, "dur": 0.3, "from": "point", "to": "home", "kind": "ib"}]   # 前の終わりより先に次が始まる
    assert lib.switch_spans(ovl, 2 / 30, 0.0, 5.0) == ["unclean", "unclean"]
    sp = lib.switch_spans([SW1], 2 / 30, 0.0, 5.0, busy=[(0.5, 0.97), (1.35, 2.0)])   # 頭の動きの外に収める
    assert sp[0] == pytest.approx((0.97, 1.35))
    assert lib.switch_spans([SW1], 2 / 30, 0.0, 5.0, busy=[(1.1, 1.5)]) == ["unclean"]   # 頭の動きが切り替えに重なる


def test_rest_pairs_avoid_switches_and_head():
    sws = [SW1, {"at": 3.0, "dur": 0.3, "from": "point", "to": "home", "kind": "ib"}]
    pr = lib.rest_pairs(sws, [(5.0, 6.0)], 0.4, 0.0, 8.0)
    busy = [(1.0, 1.3), (3.0, 3.3), (5.0, 6.0)]
    assert pr and all(not (p < b1 + 0.15 and q > b0 - 0.15) for p, q in pr for b0, b1 in busy)
    assert all(q - p == pytest.approx(0.4) for p, q in pr)
    assert len(lib.rest_pairs(sws, [], 0.1, 0.0, 1000.0, limit=50)) == 50
    far = [SW1, {"at": 10.0, "dur": 0.3, "from": "point", "to": "home", "kind": "ib"}]   # 範囲（4 秒まで）の後の切り替え
    pr = lib.rest_pairs(far, [], 0.4, 0.0, 4.0)
    assert pr and all(0.0 <= p and q < 4.0 for p, q in pr)


# ---------- vm render の表と .check.json ----------
@pytest.fixture(scope="module")
def env(tmp_path_factory):
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def render(root, out, env, *extra):
    return subprocess.run([sys.executable, "-B", str(RENDER), root, "--mode", "white", "--out", str(out), *extra], env=env, capture_output=True, text=True, timeout=300)


def test_render_writes_check_json(tmp_path, env):
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj")); out = tmp_path / "m.mp4"
    r = render(root, out, env, "--strict")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "切り替えの検査: 3 件（drawn 3） — 全部動いた" in r.stderr
    j = json.load(open(tmp_path / "m.check.json"))
    assert j["problems"] == 0 and [s["status"] for s in j["switches"]] == ["ok"] * 3 and j["video"] == str(out.resolve())


def hidden_by_head(root):
    """体の切り替え（1.0 秒 home→point）が、頭の動き（0.6〜1.6 秒は point の向きのまま）の中にある config。"""
    cfgp = os.path.join(root, "config.json"); cfg = json.load(open(cfgp))
    cfg["events"] = [{"at": 1.0, "pose": "point"}, {"at": 2.4, "pose": "home"}]; cfg["idle"] = False
    cfg["head"] = {"chain": ["home", "point"], "mult": 2, "events": [{"at": 0.4, "pose": "home"}, {"at": 0.6, "pose": "point"}, {"at": 1.6, "pose": "point"}, {"at": 1.8, "pose": "home"}]}
    json.dump(cfg, open(cfgp, "w"))


def test_render_reports_switch_hidden_by_head_and_strict_fails(tmp_path, env):
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj")); hidden_by_head(root); fill_direct(lib.Proj(root), "home", "point", 2)
    out = tmp_path / "h.mp4"
    r = render(root, out, env)
    assert r.returncode == 0, r.stderr[-2000:]                                        # --strict が無ければ今までどおり 0
    assert "問題 1 件" in r.stderr and "1.00 秒 home→point" in r.stderr and "頭の動きに隠れて" in r.stderr
    r2 = render(root, out, env, "--strict")
    assert r2.returncode == 3 and out.exists()                                       # 動画は書き出したまま残る
    j = json.load(open(tmp_path / "h.check.json"))
    assert [s["status"] for s in j["switches"]] == ["head", "ok"] and j["head_spans"] == [[0.4, 1.8]]


def test_render_check_only_makes_no_video_and_calls_no_rife(tmp_path, env):
    """下見は絵を作らない: 頭の列の RIFE を先にためていなくても（CI に RIFE は無い）通り、動画は書かない。"""
    pytest.importorskip("pykakasi")
    root = sm.make(str(tmp_path / "proj")); hidden_by_head(root)
    out = tmp_path / "d.mp4"
    r = render(root, out, env, "--check-only", "--strict")
    assert r.returncode == 3, r.stderr[-2000:]
    assert "頭の動きに隠れて" in r.stderr and "Wan で新しく作る組: 0" in r.stderr
    assert not out.exists() and not (tmp_path / "d.check.json").exists()
    assert json.load(open(tmp_path / "d.precheck.json"))["video"] is None


# ---------- vm check（書き出した動画を画素で測る）----------
FPS = 30


def synth_video(path, env, size=(240, 320), offset=(0, 0), canvas=None, lead=0.0, start=0.0, head_from=None):
    """白地に「腕」（1.0〜1.3 秒に横へ動く）と「顔」（口は毎コマでたらめに変わる、目は 0.2 秒と 3.2 秒で開き 2.6 秒で閉じる）。
    2.5 秒の切り替えでは顔（目）しか変わらない＝身振りが消えた切り替え。lead 秒の無地を頭に足せる。
    start 秒より前は書かない（vm render --from start で書き出した動画と同じく、動画の 0 秒が start 秒）。"""
    rng = np.random.default_rng(7); W, H = canvas or size; ox, oy = offset
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                          "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE, env=env)
    for f in range(int(round((4.0 + lead - start) * FPS))):
        t = f / FPS - lead + start; im = np.full((H, W), 250, np.uint8)
        if t >= 0:
            v = im[oy:oy + size[1], ox:ox + size[0]]
            u = min(1.0, max(0.0, (t - 1.0) / 0.3)); x = int(40 + 100 * u)
            v[200:260, x:x + 40] = 40                                                   # 腕
            v[60:70, 100:140] = int(rng.integers(0, 4)) * 60                          # 口
            if (0.2 <= t < 2.6) or t >= 3.2: v[30:40, 100:110] = 20; v[30:40, 130:140] = 20   # 目
            if head_from is not None and head_from <= t < head_from + 0.3: v[5:25, 150:200] = 0   # 頭の動き（顔の外の髪が動く）
        p.stdin.write(im.tobytes())
    p.stdin.close(); assert p.wait() == 0


def switches_json(path, start=0.0, sws=None):
    sws = sws or [{**SW1, "status": "ok"}, {"at": 2.5, "dur": 0.3, "from": "point", "to": "home", "kind": "ib", "engine": "drawn", "status": "ok"}]
    json.dump({"fps": FPS, "from": start, "to": 4.0, "problems": 0, "head_spans": [], "switches": sws}, open(path, "w"))


def check(video, env, *extra):
    return subprocess.run([sys.executable, "-B", str(CHECK), str(video), *extra], env=env, capture_output=True, text=True, timeout=120)


def test_check_finds_switch_that_did_not_move(tmp_path, env):
    v = tmp_path / "m.mp4"; synth_video(v, env); switches_json(tmp_path / "m.check.json")
    r = check(v, env)
    assert r.returncode == 0, r.stderr[-2000:]
    j = json.load(open(tmp_path / "m.motion.json"))
    assert [s["verdict"] for s in j["switches"]] == ["moved", "still"], j     # 2.5 秒は目しか変わっていない
    assert j["switches"][1]["change_face"] > 0 and j["switches"][1]["change"] == 0
    assert "動いていない" in r.stdout
    assert check(v, env, "--strict").returncode == 3


def test_check_on_composited_video_with_crop_and_shift(tmp_path, env):
    """主動画に重ねた完成の動画: マスコットの範囲を --crop で切り出し、頭に足した 0.5 秒を --shift で戻す。"""
    v = tmp_path / "full.mp4"; synth_video(v, env, offset=(300, 100), canvas=(640, 480), lead=0.5)
    j = tmp_path / "sw.json"; switches_json(j)
    r = check(v, env, "--switches", str(j), "--crop", "300,100,240,320", "--shift", "0.5")
    assert r.returncode == 0, r.stderr[-2000:]
    assert [s["verdict"] for s in json.load(open(tmp_path / "full.motion.json"))["switches"]] == ["moved", "still"]


def test_check_video_rendered_with_from(tmp_path, env):
    """vm render --from 0.5 の動画（動画の 0 秒が 0.5 秒）。一覧の時刻から 0.5 秒を引いて読む（引かないと全部範囲外で、--strict が何も測らずに通った）。"""
    v = tmp_path / "m.mp4"; synth_video(v, env, start=0.5); switches_json(tmp_path / "m.check.json", start=0.5)
    r = check(v, env)
    assert r.returncode == 0, r.stderr[-2000:]
    assert [s["verdict"] for s in json.load(open(tmp_path / "m.motion.json"))["switches"]] == ["moved", "still"]


def test_check_without_rest_pairs_is_unknown_and_strict_fails(tmp_path, env):
    """切り替えが詰まっていて話しているだけの区間が取れない: 顔を外せないので「測れない」。画面全体で「動いた」と言わない。"""
    v = tmp_path / "m.mp4"; synth_video(v, env)
    sws = [{"at": 0.2 + 0.5 * i, "dur": 0.3, "from": "home" if i % 2 == 0 else "point", "to": "point" if i % 2 == 0 else "home",
            "kind": "ib", "engine": "drawn", "status": "ok"} for i in range(8)]
    switches_json(tmp_path / "m.check.json", sws=sws)
    r = check(v, env)
    assert r.returncode == 0, r.stderr[-2000:]
    j = json.load(open(tmp_path / "m.motion.json"))
    assert j["face_mask"] is None and {s["verdict"] for s in j["switches"]} <= {"unknown", "skip"} and "測れない" in r.stdout
    assert check(v, env, "--strict").returncode == 3


def test_check_back_to_back_missing_gesture_is_still(tmp_path, env):
    """1.0〜1.3 秒の腕の動きのすぐ後に、1.3〜1.6 秒の切り替え（実際には腕は止まったまま＝消えた身振り）。
    2 つ目の直前のコマを 1 つ目の途中から取ると、1 つ目の動きの残りで「動いた」に見えた。"""
    v = tmp_path / "m.mp4"; synth_video(v, env)
    sws = [{**SW1, "status": "ok"}, {"at": 1.3, "dur": 0.3, "from": "point", "to": "home", "kind": "ib", "engine": "drawn", "status": "ok"},
           {"at": 2.5, "dur": 0.3, "from": "home", "to": "point", "kind": "ib", "engine": "drawn", "status": "ok"}]
    switches_json(tmp_path / "m.check.json", sws=sws)
    r = check(v, env)
    assert r.returncode == 0, r.stderr[-2000:]
    assert [s["verdict"] for s in json.load(open(tmp_path / "m.motion.json"))["switches"]] == ["moved", "still", "still"]


def test_check_head_motion_right_after_missing_gesture_is_still(tmp_path, env):
    """2.5〜2.8 秒の消えた身振りのすぐ後（2.82 秒〜）に頭の動き。直後のコマを頭の動きの中から取ると、頭の動きで「動いた」に見えた。"""
    v = tmp_path / "m.mp4"; synth_video(v, env, head_from=2.85)
    switches_json(tmp_path / "m.check.json")
    j = json.load(open(tmp_path / "m.check.json")); j["head_spans"] = [[2.82, 3.15]]; json.dump(j, open(tmp_path / "m.check.json", "w"))
    r = check(v, env)
    assert r.returncode == 0, r.stderr[-2000:]
    assert [s["verdict"] for s in json.load(open(tmp_path / "m.motion.json"))["switches"]] == ["moved", "still"]


def test_check_strict_fails_when_nothing_was_measured(tmp_path, env):
    """切り替えがあるのに 1 件も測れない（--shift の取り違えなど）は --strict で失敗。"""
    v = tmp_path / "m.mp4"; synth_video(v, env); switches_json(tmp_path / "m.check.json")
    r = check(v, env, "--shift", "10", "--strict")
    assert r.returncode == 3 and "1 件も測れなかった" in r.stdout


def test_check_reports_render_problems_and_needs_switches(tmp_path, env):
    v = tmp_path / "m.mp4"; synth_video(v, env)
    assert check(v, env).returncode == 2                                           # 切り替えの一覧が無い
    switches_json(tmp_path / "m.check.json"); j = json.load(open(tmp_path / "m.check.json")); j["problems"] = 2
    json.dump(j, open(tmp_path / "m.check.json", "w"))
    r = check(v, env, "--strict")
    assert r.returncode == 3 and "問題が 2 件" in r.stdout
