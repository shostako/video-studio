"""向き・視線（config.transition / events の via / config.gaze / poses.<名前>.yaw ほか）の純関数と、合成のマスコットでの書き出し。"""
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
import synth_mascot  # noqa: E402

RENDER = ROOT / "skills/video-mascot/scripts/render.py"


# ---------- transition_config / switch_kind ----------
def test_transition_config_defaults_and_errors():
    assert lib.transition_config(None) is None and lib.transition_config(False) is None
    assert lib.transition_config(True) == lib.TRANSITION_DEFAULTS
    assert lib.transition_config({"mode": "turn", "dur": 0.4}) == {"mode": "turn", "dur": 0.4, "squash": 0.06}
    for bad in ({"mode": "spin"}, {"dur": 0}, {"squash": 0.6}, {"speed": 1}, "fade"):
        with pytest.raises(ValueError): lib.transition_config(bad)


def test_switch_kind_priority():
    fade = lib.transition_config({"mode": "fade", "dur": 0.3})
    assert lib.switch_kind(True, None, fade, 0.33) is None                 # 中割りがある組は中割り
    assert lib.switch_kind(False, None, fade, 0.33) == ("fade", 0.3, 0.0)  # 無い組は transition
    assert lib.switch_kind(False, None, None, 0.33) is None                # どちらも無ければ今までどおり
    assert lib.switch_kind(True, "fade", None, 0.33) == ("fade", 0.25, 0.0)  # via が最優先（transition が無ければ既定の長さ）
    assert lib.switch_kind(True, "cut", fade, 0.33) == ("cut", 0.0, 0.0)
    assert lib.switch_kind(False, "turn", fade, 0.33) == ("turn", 0.3, 0.06)
    assert lib.switch_kind(False, None, {"mode": "cut", "dur": 0.3, "squash": 0.0}, 0.33) == ("cut", 0.0, 0.0)
    assert lib.switch_kind(True, None, {"mode": "cut", "dur": 0.3, "squash": 0.0}, 0.33) is None   # 中割りがある組は中割り


# ---------- plan_at の mix ----------
def _ib(a, b): return [("ib", a, b, k) for k in range(1, 6)] if (a, b) == ("home", "point") else None


def test_plan_at_without_trans_is_unchanged():
    ev = [(1.0, "home", "point"), (2.0, "point", "turn_l")]
    for t in np.arange(0, 3, 0.05):
        assert lib.plan_at(t, ev, "home", _ib, 15, 5) == lib.plan_at(t, [e + (None,) for e in ev], "home", _ib, 15, 5)


def test_plan_at_mix_fade_turn_and_cut():
    trans = lib.transition_config({"mode": "fade", "dur": 0.4})
    def tr(a, b, via): return lib.switch_kind(_ib(a, b) is not None, via, trans, 0.33)
    ev = [(1.0, "home", "point", None), (2.0, "point", "turn_l", None), (3.0, "turn_l", "home", "turn"), (4.0, "home", "point", "cut")]
    assert lib.plan_at(1.1, ev, "home", _ib, 15, 5, None, tr)[0] == "ib"           # 中割りがある組はそのまま
    m = lib.plan_at(2.2, ev, "home", _ib, 15, 5, None, tr)
    assert m[:3] == ("mix", "point", "turn_l") and 0.4 < m[3] < 0.6 and m[4] == 0.0
    assert lib.plan_at(2.0, ev, "home", _ib, 15, 5, None, tr)[3] == 0.0
    assert lib.plan_at(2.45, ev, "home", _ib, 15, 5, None, tr) == ("pose", "turn_l")
    us = [lib.plan_at(2 + i * 0.02, ev, "home", _ib, 15, 5, None, tr)[3] for i in range(20)]
    assert us == sorted(us)                                                       # 溶かす割合は単調に増える
    t_ = lib.plan_at(3.2, ev, "home", _ib, 15, 5, None, tr)
    assert t_[0] == "mix" and abs(t_[4] - 0.06) < 1e-9                            # turn は真ん中で一番縮む
    assert lib.plan_at(4.0, ev, "home", _ib, 15, 5, None, tr) == ("pose", "point")  # cut は中割りがあっても一瞬


def test_resolve_events_via_and_dur_of():
    words = [("そこで", 2.0, 2.4)]; stream = [("そ", 2.0), ("こ", 2.1), ("で", 2.2)]
    events = [{"line": 1, "kw": "そこで", "pose": "turn_l", "via": "fade"}, {"at": 5.0, "pose": "home"}]
    ev = lib.resolve_events(events, "home", {1: 1.0}, {1: 3.0}, 0.33, stream, words, dur_of=lambda a, b, v: 0.25, with_via=True)
    assert ev[0][1:] == ("home", "turn_l", "fade") and abs(ev[0][0] - (2.0 - 0.25 - 0.04)) < 1e-9
    assert ev[1] == (5.0, "turn_l", "home", None)
    plain = lib.resolve_events(events, "home", {1: 1.0}, {1: 3.0}, 0.33, stream, words)
    assert all(len(e) == 3 for e in plain) and abs(plain[0][0] - (2.0 - 0.33 - 0.04)) < 1e-9
    with pytest.raises(SystemExit):
        lib.resolve_events([{"at": 1, "pose": "x", "via": "spin"}], "home", {}, {}, 0.33, [], [])


# ---------- 視線 ----------
@pytest.mark.parametrize("look,yaw,want", [
    ("c", 0, None), ("l", 0, "g_l"), ("r", 0, "g_r"), ("u", 0, "g_u"),
    ("l", -30, None), ("r", -30, "g_c"), ("c", -30, "g_c"), ("u", -40, "g_u"),
    ("r", 40, None), ("l", 40, "g_c"),
    ("l", -90, None), ("u", -90, "g_u"), ("c", 180, None), (None, 0, None)])
def test_gaze_part(look, yaw, want):
    assert lib.gaze_part(look, yaw) == want


def test_gaze_part_missing_part_keeps_eyes_and_bad_look():
    assert lib.gaze_part("l", 0, {"m1", "e1"}) is None
    assert lib.gaze_part("l", 0, {"g_l"}) == "g_l"
    with pytest.raises(ValueError): lib.gaze_part("x", 0)


def test_gaze_keys():
    assert lib.gaze_keys(0) == ["g_l", "g_r", "g_u"]
    assert lib.gaze_keys(-40) == ["g_c", "g_u"] == lib.gaze_keys(30)
    assert lib.gaze_keys(90) == [] == lib.gaze_keys(180) == lib.gaze_keys(0, face=False)


def test_pose_view():
    assert lib.pose_view({}) == (0.0, 0.0)
    assert lib.pose_view({"yaw": -40}) == (-40.0, -40.0)
    assert lib.pose_view({"yaw": 0, "head_yaw": 30}) == (0.0, 30.0)


def test_gaze_config_and_resolve():
    assert lib.gaze_config(None) is None
    g = lib.gaze_config({"lead": 0.2, "events": [{"at": 1, "look": "l"}]})
    assert g["lead"] == 0.2 and g["hold"] == 1.0 and len(g["events"]) == 1
    for bad in ({"lead": -1}, {"hold": 0}, {"speed": 1}, 3):
        with pytest.raises(ValueError): lib.gaze_config(bad)
    words = [("ここ", 2.0, 2.3)]; stream = [("こ", 2.0), ("こ", 2.15)]
    sp = lib.resolve_gaze([{"line": 1, "kw": "ここ", "look": "l", "hold": 0.5}, {"at": 0.2, "look": "u", "until": 0.8},
                           {"line_end": 1, "look": "c"}], {1: 1.0}, {1: 2.0}, stream, words, hold=1.0)
    assert sp == [(0.2, 0.8, "u"), (2.0, 2.5, "l"), (3.0, 4.0, "c")]
    assert lib.resolve_gaze([{"at": 20, "offset": 0.5, "look": "l"}], {}, {}, [], []) == [(20.5, 21.5, "l")]   # at にも offset を足す
    for bad in ({"at": 1, "look": "x"}, {"look": "l"}, {"at": 1, "until": 0.5, "look": "l"}):
        with pytest.raises(SystemExit): lib.resolve_gaze([bad], {}, {}, [], [])


def test_gaze_track_lead_and_priority():
    yaw = {"home": 0, "turn_l": -40, "point": 0}.get
    sw = [(1.0, 0.3, "home", "turn_l"), (2.0, 0.3, "turn_l", "home"), (3.0, 0.3, "home", "point")]
    g = lib.gaze_track(120, 30, [(2.1, 2.2, "u")], sw, yaw, lead=0.2)
    assert g[23] is None and g[24] == "l" and g[38] == "l" and g[39] is None      # 0.8 秒から 1.3 秒まで先に左へ
    assert g[54] == "r" and g[63] == "u" and g[64] == "u"                         # 戻りは右へ。台本の指定が優先
    assert all(x is None for x in g[80:])                                         # 顔の向きが変わらない切り替えでは動かない
    assert lib.gaze_track(10, 30, []) == [None] * 10


# ---------- 書き出し（合成のマスコット）----------
@pytest.fixture(scope="module")
def env(tmp_path_factory):
    pytest.importorskip("pykakasi")
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path_factory.mktemp("bin"); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


@pytest.fixture(scope="module")
def vproj(tmp_path_factory):
    return Path(synth_mascot.make_views(str(tmp_path_factory.mktemp("views") / "proj")))


def _render(proj, env, out, *args, ok=True):
    r = subprocess.run([sys.executable, "-B", str(RENDER), str(proj), "--out", str(out), *args], env=env, capture_output=True, text=True, timeout=300)
    if ok: assert r.returncode == 0, r.stderr
    return r


def _frames(path, env, rgba=False):
    dec = ["-c:v", "libvpx-vp9"] if rgba else []
    raw = subprocess.run(["ffmpeg", "-v", "error", *dec, "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba" if rgba else "rgb24", "-"],
                         env=env, capture_output=True, check=True).stdout
    ow = 2 * round(384 * (synth_mascot.W + 80) / synth_mascot.H / 2)
    return np.frombuffer(raw, np.uint8).reshape(-1, 384, ow, 4 if rgba else 3).astype(np.int16)


def test_render_views_white(vproj, env, tmp_path):
    out = tmp_path / "v.mp4"; _render(vproj, env, out, "--mode", "white")
    f = _frames(out, env); n = int(np.ceil(synth_mascot.END * 30))
    assert len(f) == n
    def d(a, b): return float(np.abs(f[a] - f[b]).mean())
    # 2.0 秒から turn で 0.3 秒: 途中のコマは前（home）とも後（turn_l）とも違う
    assert d(61, 58) > 0.3 and d(61, 70) > 0.3
    # 後ろ向き（2.7 秒から fade）のあと、3.1 秒の cut で一瞬で home に戻る
    assert d(92, 94) > 1.0 and d(94, 95) < d(92, 94)


def test_render_views_gaze_moves_eyes(vproj, env, tmp_path):
    cfg = json.loads((vproj / "config.json").read_text(encoding="utf-8"))
    on = tmp_path / "on.mp4"; _render(vproj, env, on, "--mode", "white")
    cfg2 = dict(cfg); cfg2.pop("gaze")
    p2 = tmp_path / "nogaze"; shutil.copytree(vproj, p2); (p2 / "config.json").write_text(json.dumps(cfg2, ensure_ascii=False), encoding="utf-8")
    off = tmp_path / "off.mp4"; _render(p2, env, off, "--mode", "white")
    a, b = _frames(on, env), _frames(off, env)
    eye = np.abs(a - b)[:, 88:116, 95:170].max(axis=(1, 2, 3))    # 目のまわり（h264 の揺れは数十まで）
    assert eye[6] > 100                        # 0.1〜0.5 秒は右を見る
    assert eye[56] > 100                       # 2.0 秒の左への切り替えの 0.15 秒前から目が先に動く
    assert eye[20] < 60                        # 視線の指定が無い所は同じ


def test_render_views_alpha(vproj, env, tmp_path):
    out = tmp_path / "v.webm"; _render(vproj, env, out, "--mode", "alpha", "--motion", "on")
    f = _frames(out, env, True); al = f[..., 3]
    assert (al[:, :4, :] < 8).all() and (al > 247).mean(axis=(1, 2)).min() > 0.05


def test_render_views_size_mismatch_is_an_error(vproj, env, tmp_path):
    p2 = tmp_path / "bad"; shutil.copytree(vproj, p2)
    from PIL import Image
    Image.open(p2 / "poses/pose_turn_l.png").resize((300, 500)).save(p2 / "poses/pose_turn_l.png")
    r = _render(p2, env, tmp_path / "x.mp4", "--mode", "white", ok=False)
    assert r.returncode != 0 and "turn_l" in r.stderr and "大きさ" in r.stderr


def test_parts_uses_own_face_and_skips_faceless(vproj):
    sys.argv = ["parts"]
    import parts
    P = lib.Proj(str(vproj))
    mr, er, cc = parts.map_rois(P, "turn_l")
    assert mr == synth_mascot.TURN_MOUTH_ROI and er == synth_mascot.TURN_EYE_ROI and cc == 1.0
    assert parts.extract(P, "back") == {}


def test_poses_gaze_jobs_are_opt_in(vproj, tmp_path):
    import poses
    P = lib.Proj(str(vproj))
    names = {os.path.basename(j[0]) for j in poses.jobs_parts(P)}
    assert "home_g_l.png" in names and "turn_l_g_c.png" in names and "turn_l_g_l.png" not in names
    assert not any(n.startswith("back_") for n in names)                          # 顔の無い姿勢は部品を描かない
    p2 = tmp_path / "nog"; shutil.copytree(vproj, p2)
    cfg = json.loads((p2 / "config.json").read_text(encoding="utf-8")); cfg.pop("gaze")
    (p2 / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    names2 = {os.path.basename(j[0]) for j in poses.jobs_parts(lib.Proj(str(p2)))}
    assert not any("_g_" in n for n in names2) and "home_m1.png" in names2


def test_render_gaze_lead_ends_at_instant_cut(vproj, env, tmp_path):
    """中割りもつなぎも無い切り替え（一瞬）では、目の先回りは切り替えの時刻で終わる（中割りの長さ分残らない）。"""
    def variant(name, gaze):
        p2 = tmp_path / name; shutil.copytree(vproj, p2)
        cfg = json.loads((p2 / "config.json").read_text(encoding="utf-8")); cfg.pop("transition")
        cfg["events"] = [{"at": 2.0, "pose": "turn_l"}, {"at": 2.5, "pose": "home"}]
        if gaze: cfg["gaze"] = {"lead": 0.15}
        else: cfg.pop("gaze")
        (p2 / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / f"{name}.mp4"; _render(p2, env, out, "--mode", "white"); return _frames(out, env)
    a, b = variant("g", True), variant("n", False)
    eye = np.abs(a - b)[:, 88:116, 95:170].max(axis=(1, 2, 3))
    assert eye[72] > 100                       # 2.35〜2.5 秒は右へ先回り（home に戻る前の turn_l で g_c）
    assert eye[80] < 60                        # 2.5 秒で一瞬で home に戻ったあとは、元の目


def test_render_ib_uses_pose_anchor_interpolation(vproj, env, tmp_path):
    """端の姿勢に anchor を書いたら、中割りは靴を測らず両端の anchor の間で補う（測った靴の位置へ跳ばない）。"""
    p2 = tmp_path / "anc"; shutil.copytree(vproj, p2)
    cfg = json.loads((p2 / "config.json").read_text(encoding="utf-8")); cfg.pop("transition"); cfg.pop("gaze")
    cfg["poses"]["point"]["anchor"] = [213.5, 735.0]                            # 測った靴より 20 右を軸足とする → 絵は 20 左へ
    cfg["events"] = [{"at": 0.6, "pose": "point"}]
    (p2 / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "a.mp4"; _render(p2, env, out, "--mode", "white"); f = _frames(out, env)
    def shoe_left(fr):                                                            # 足元の黒の一番左（出力の画素）
        g = fr[330:375].mean(axis=2); xs = np.where((g < 60).any(axis=0))[0]; return int(xs.min())
    xs = [shoe_left(f[k]) for k in range(16, 40)]
    assert max(abs(a - b) for a, b in zip(xs, xs[1:])) <= 4                      # コマの間で跳ばない（20 画素 × 0.5 = 10 の跳びが無い）
    assert xs[0] - xs[-1] >= 8                                                    # 終わりは 10 ほど左


def test_render_alpha_fade_blends_color_and_alpha(vproj, env, tmp_path):
    """透明の書き出しで溶かす時は、姿勢ごとに切り抜いてから混ぜる。片方の姿勢にしか無い所（伸ばした腕）は、
    途中で半透明の腕の色になり、白と混ざった不透明の灰色にならない。"""
    p2 = tmp_path / "fade"; shutil.copytree(vproj, p2)
    cfg = json.loads((p2 / "config.json").read_text(encoding="utf-8")); cfg.pop("gaze")
    cfg["transition"] = {"mode": "fade", "dur": 0.4}
    cfg["events"] = [{"at": 1.0, "pose": "point", "via": "fade"}]
    (p2 / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "f.webm"; _render(p2, env, out, "--mode", "alpha"); f = _frames(out, env, True)
    before, mid, after = f[27], f[36], f[48]                                     # 0.9 秒・1.2 秒（真ん中）・1.6 秒
    arm = (after[..., 3] > 250) & (before[..., 3] < 5)
    assert arm.sum() > 50
    a_mid = mid[..., 3][arm]
    assert 70 < np.median(a_mid) < 190                                           # 半透明
    d = np.abs(mid[..., :3][arm] - after[..., :3][arm]).mean()
    assert d < 40                                                                 # 色は腕の色のまま（白と混ざった灰色ではない）
