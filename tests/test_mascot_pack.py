"""vm pack（opt-in）: 作業フォルダ2つ（合成のマスコット）を1つのパックにまとめ、パックから新しい作業フォルダを作る。
後の --from が姿勢を取ること、中割りは端の絵がパックと同じ作業フォルダからだけ持ってくること（逆向きの組も同じ組）、
台本に属する設定を持ってこないこと、パックから作った作業フォルダで書き出しが通ることを確かめる。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/video-mascot/scripts"
sys.path.insert(0, str(ROOT / "tests/fixtures"))
import synth_mascot  # noqa: E402


def run(script, *args, env=None):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True, timeout=300, env=env)


def ffmpeg_env(tmp_path):
    """ffmpeg が無い機体（CI）では imageio-ffmpeg の ffmpeg を PATH の先頭に置く。"""
    e = dict(os.environ)
    if not shutil.which("ffmpeg"):
        import pytest
        imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
        b = tmp_path / "bin"; b.mkdir(); (b / "ffmpeg").symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
        e["PATH"] = f"{b}{os.pathsep}{e['PATH']}"
    return e


def wf(tmp_path, name):
    p = Path(synth_mascot.make(str(tmp_path / name)))
    shutil.copy(p / "poses/pose_home.png", p / "mascot.png")
    return p


def cfg(p):
    return json.loads((p / "config.json").read_text(encoding="utf-8"))


def put(p, c):
    (p / "config.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def two(tmp_path):
    """A: home・point（中割り home>point）と、A だけの姿勢 wave。B: home と描き直した point（絵が違う）と、B だけの姿勢 bow（中割り bow>home）。"""
    a = wf(tmp_path, "a"); b = wf(tmp_path, "b")
    ca = cfg(a); ca["poses"]["wave"] = {"desc": "wave"}; ca["ib_steps"] = {"home>point": ["a1", "a2", "a3", "a4", "a5"]}
    ca["interp"] = {"mult": 8, "durs": {"home>point": 0.9}}; ca["gaze"] = {"lead": 0.2, "events": [{"at": 1, "look": "l"}]}; put(a, ca)
    shutil.copy(a / "poses/pose_point.png", a / "poses/pose_wave.png")
    shutil.copytree(a / "parts_point", a / "parts_wave")
    cb = cfg(b); cb["poses"]["bow"] = {"desc": "bow"}; cb["pairs"] = [["home", "point"], ["bow", "home"]]; cb["ib_steps"] = {"home>point": ["b1"] * 5}
    cb["interp"] = {"dur": 0.7, "durs": {"bow>home": 1.1}}; cb["idle"] = False; put(b, cb)
    im = Image.open(b / "poses/pose_point.png"); im.putpixel((5, 5), (0, 0, 0)); im.save(b / "poses/pose_point.png")   # B の point は別の絵
    shutil.copy(b / "poses/pose_home.png", b / "poses/pose_bow.png")
    shutil.copytree(b / "parts_home", b / "parts_bow")
    for k in range(1, 6): shutil.copy(b / f"ib/ib_home_point_{k}.png", b / f"ib/ib_bow_home_{k}.png")
    return a, b


def test_later_source_wins_and_inbetweens_need_matching_ends(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    r = run("pack.py", pk, "--from", a, "--from", b)
    assert r.returncode == 0, r.stdout + r.stderr
    c = cfg(pk); man = json.loads((pk / "pack.json").read_text(encoding="utf-8"))
    assert set(c["poses"]) == {"home", "point", "wave", "bow"}
    assert man["poses"]["point"] == str(b) and man["poses"]["wave"] == str(a)
    assert (pk / "poses/pose_point.png").read_bytes() == (b / "poses/pose_point.png").read_bytes()
    assert (pk / "parts_point").is_dir() and (pk / "parts_home").is_dir()
    # B の home>point の中割りは B の point（パックの絵）につながるので B から持ってくる
    assert man["pairs"]["home>point"] == str(b) and c["ib_steps"]["home>point"] == ["b1"] * 5
    assert (pk / "ib/ib_bow_home_1.png").exists() and man["pairs"]["bow>home"] == str(b)
    assert man["missing_inbetweens"] == []
    # 台本に属するものは持ってこない。interp の durs は重ねる。視線の予定は落とす
    assert "voice" not in c and "events" not in c and c["name"] == "pack"
    assert c["interp"]["durs"] == {"home>point": 0.9, "bow>home": 1.1} and c["interp"]["mult"] == 8 and c["idle"] is False
    assert c["gaze"] == {"lead": 0.2}


def test_inbetween_with_changed_end_is_not_copied(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    for k in range(1, 6): (b / f"ib/ib_home_point_{k}.png").unlink()   # B には home>point の中割りが無い。A のは A の point（違う絵）につながる
    r = run("pack.py", pk, "--from", a, "--from", b)
    assert r.returncode == 0, r.stdout + r.stderr
    man = json.loads((pk / "pack.json").read_text(encoding="utf-8"))
    assert man["missing_inbetweens"] == ["home>point"] and not list((pk / "ib").glob("ib_home_point_*"))
    assert ["home", "point"] in cfg(pk)["pairs"]                      # 組は残す（vm poses inbetweens で描き足す）
    assert "vm poses" in r.stdout


def test_reverse_pair_is_the_same_pair(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    ca = cfg(a); ca["pairs"].append(["home", "bow"]); put(a, ca)       # A は逆向きの組（絵は無い）
    r = run("pack.py", pk, "--from", a, "--from", b)
    assert r.returncode == 0, r.stdout + r.stderr
    pairs = cfg(pk)["pairs"]
    assert ["bow", "home"] in pairs and ["home", "bow"] not in pairs


def test_refuses_different_character_and_existing_pack(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    im = Image.open(b / "mascot.png"); im.putpixel((1, 1), (1, 2, 3)); im.save(b / "mascot.png")
    r = run("pack.py", pk, "--from", a, "--from", b)
    assert r.returncode != 0 and not pk.exists()
    shutil.copy(a / "mascot.png", b / "mascot.png")
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    r = run("pack.py", pk, "--from", a)
    assert r.returncode != 0                                            # 既にあるパックは --force が要る
    r = run("pack.py", pk, "--from", a, "--force")
    assert r.returncode == 0 and set(cfg(pk)["poses"]) == {"home", "point", "wave"}
    assert list(tmp_path.glob("pack.old-*"))                             # 古いパックは残す


def test_new_workfolder_from_pack_renders(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    nw = tmp_path / "video3"
    r = run("pack.py", pk, "--new", nw)
    assert r.returncode == 0, r.stdout + r.stderr
    c = cfg(nw)
    assert c["name"] == "video3" and c["from_pack"] == str(pk) and not (nw / "pack.json").exists()
    assert run("pack.py", pk, "--new", nw).returncode != 0              # 既にある作業フォルダは上書きしない
    # 台本と声を足せば書き出せる（合成の声は元の作業フォルダから持ってくる）
    shutil.rmtree(nw / "voice"); shutil.copytree(a / "voice", nw / "voice")
    c.pop("interp")                                                   # CI に RIFE は無い
    c["voice"] = cfg(a)["voice"]; c["events"] = [{"at": 0.6, "pose": "bow"}, {"at": 2.0, "pose": "point"}]; put(nw, c)
    r = run("render.py", nw, "--mode", "white", "--out", nw / "out/t.mp4", env=ffmpeg_env(tmp_path))
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert (nw / "out/t.mp4").stat().st_size > 0


def test_inbetweens_are_not_redrawn_because_of_copied_dates(tmp_path):
    """別の作業フォルダの姿勢の絵が中割りより新しくても、パックでは中割りを古いと見なさない（vm poses の chain の判定）。"""
    import os, time
    a, b = two(tmp_path); pk = tmp_path / "pack"
    now = time.time()
    for k in range(1, 6): os.utime(b / f"ib/ib_bow_home_{k}.png", (now - 1000, now - 1000))
    os.utime(b / "poses/pose_home.png", (now, now))                    # 土台の絵が中割りより新しい
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    m = lambda p: os.path.getmtime(pk / p)
    assert m("poses/pose_bow.png") <= m("ib/ib_bow_home_1.png") < m("ib/ib_bow_home_2.png") < m("ib/ib_bow_home_5.png")
    assert m("poses/pose_home.png") <= m("ib/ib_bow_home_1.png")


def test_partial_inbetweens_count_as_missing(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    (b / "ib/ib_bow_home_3.png").unlink()                              # 途中で止まった中割り
    r = run("pack.py", pk, "--from", a, "--from", b)
    assert r.returncode == 0, r.stdout + r.stderr
    man = json.loads((pk / "pack.json").read_text(encoding="utf-8"))
    assert "bow>home" in man["missing_inbetweens"] and not list((pk / "ib").glob("ib_bow_home_*"))


def test_manual_anchor_maps_are_merged(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    ca = cfg(a); ca["anchor"] = {"mode": "manual", "points": {"home": [10, 20], "wave": [11, 21]}, "scales": {"wave": 1.01}}; put(a, ca)
    cb = cfg(b); cb["anchor"] = {"mode": "manual", "points": {"home": [12, 22], "bow": [13, 23], "point": [14, 24]}}; put(b, cb)
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    an = cfg(pk)["anchor"]
    assert an["points"] == {"home": [12, 22], "wave": [11, 21], "bow": [13, 23], "point": [14, 24]} and an["scales"] == {"wave": 1.01}


def test_nested_destinations_are_rejected(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    assert run("pack.py", a / "pack", "--from", a).returncode != 0      # 作業フォルダの中にパックは作らない
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    r = run("pack.py", pk, "--new", pk / "poses" / "video")
    assert r.returncode != 0 and not (pk / "poses" / "video").exists()


def test_two_forced_rebuilds_in_the_same_second_keep_both_backups(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    assert run("pack.py", pk, "--from", a).returncode == 0
    for _ in range(3):
        r = run("pack.py", pk, "--from", a, "--force"); assert r.returncode == 0, r.stdout + r.stderr
    assert len(list(tmp_path.glob("pack.old-*"))) == 3 and not list(tmp_path.glob("pack.tmp-*"))


def test_later_source_without_the_image_does_not_take_the_pose(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    cb = cfg(b); cb["poses"]["wave"] = {"desc": "wave, not drawn yet"}; put(b, cb)   # B は config にだけ書いて、絵が無い
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    man = json.loads((pk / "pack.json").read_text(encoding="utf-8"))
    assert man["poses"]["wave"] == str(a) and (pk / "poses/pose_wave.png").exists()
    cb["poses"]["ghost"] = {"desc": "nowhere"}; put(b, cb)
    r = run("pack.py", pk, "--from", a, "--from", b, "--force")
    assert r.returncode != 0 and "ghost" in (r.stdout + r.stderr)


def test_replaced_pose_drops_stale_manual_anchor(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    ca = cfg(a); ca["anchor"] = {"mode": "manual", "points": {"home": [1, 1], "point": [5, 5], "wave": [6, 6]}, "scales": {"point": 1.2}}; put(a, ca)
    cb = cfg(b); cb["anchor"] = {"mode": "manual", "points": {"home": [2, 2], "bow": [3, 3]}}; cb["poses"]["point"]["anchor"] = [9, 9]; put(b, cb)
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    an = cfg(pk)["anchor"]
    assert "point" not in an["points"] and "point" not in an.get("scales", {})     # B の point（姿勢の anchor を使う）に A の点を残さない
    assert an["points"]["wave"] == [6, 6]                                          # A だけの姿勢の点は残す


def test_manual_anchor_must_cover_every_pose(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    cb = cfg(b); cb["anchor"] = {"mode": "manual", "points": {"home": [1, 1], "point": [2, 2], "bow": [3, 3]}}; put(b, cb)
    r = run("pack.py", pk, "--from", a, "--from", b)                   # A の wave に立ち位置が無い
    assert r.returncode != 0 and "wave" in (r.stdout + r.stderr) and not pk.exists()


def test_missing_pair_follows_latest_hint_direction(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    ca = cfg(a); ca["pairs"].append(["home", "wave"]); ca["ib_steps"]["home>wave"] = ["old"] * 5; put(a, ca)
    cb = cfg(b); cb["pairs"].append(["wave", "home"]); cb["ib_steps"]["wave>home"] = ["new"] * 5; put(b, cb)
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    c = cfg(pk)
    assert ["wave", "home"] in c["pairs"] and c["ib_steps"]["wave>home"] == ["new"] * 5 and "home>wave" not in c["ib_steps"]


def test_parts_are_required_or_reused_and_hand_base_change_is_reported(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    shutil.rmtree(b / "parts_home")                                    # B の home は A と同じ絵で、部品を切っていない
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    assert (pk / "parts_home/parts.json").exists()                      # A の部品を使う
    shutil.rmtree(b / "parts_bow")                                     # B だけの bow に部品が無い
    r = run("pack.py", pk, "--from", a, "--from", b, "--force")
    assert r.returncode != 0 and "bow" in (r.stdout + r.stderr)
    shutil.copytree(b / "parts_home", b / "parts_bow") if (b / "parts_home").exists() else shutil.copytree(a / "parts_home", b / "parts_bow")
    ca = cfg(a); ca["hands"] = {"wave": {"base": "point", "box": [0, 0, 10, 10], "desc": "x"}}; put(a, ca)   # A の wave は A の point（B と違う絵）から作った
    r = run("pack.py", pk, "--from", a, "--from", b, "--force")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((pk / "pack.json").read_text(encoding="utf-8"))["hands_base_changed"] == ["wave"]


def test_anchor_value_follows_the_pose_owner(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    ca = cfg(a); ca["anchor"] = {"mode": "manual", "points": {"home": [1, 1], "point": [2, 2], "wave": [3, 3]}}; put(a, ca)
    cb = cfg(b); cb["anchor"] = {"mode": "manual", "points": {"home": [4, 4], "point": [5, 5], "bow": [6, 6], "wave": [99, 99]}}
    cb["poses"]["wave"] = {"desc": "not drawn in B"}; put(b, cb)      # B は wave の絵が無いのに点だけ持つ
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    assert cfg(pk)["anchor"]["points"]["wave"] == [3, 3]                # 絵の持ち主（A）の点


def test_reverse_durations_and_face_rois_follow_home_owner(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    ca = cfg(a); ca["interp"]["durs"]["point>home"] = 0.5; ca["face"]["jaw_roi"] = [1, 2, 3, 4]; put(a, ca)
    cb = cfg(b); cb["interp"]["durs"]["home>point"] = 0.8; cb["face"]["mouth_roi"] = [9, 9, 9, 9]; cb["poses"]["home"] = {"desc": "x"}; put(b, cb)
    (b / "poses/pose_home.png").unlink()                               # B は home の絵を持たない（A の home を使う）
    shutil.copytree(a / "parts_home", b / "parts_home", dirs_exist_ok=True)
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    c = cfg(pk)
    assert c["interp"]["durs"]["home>point"] == 0.8 and "point>home" not in c["interp"]["durs"]
    assert c["face"]["mouth_roi"] == cfg(a)["face"]["mouth_roi"] and c["face"]["jaw_roi"] == [1, 2, 3, 4]


def test_boolean_gaze_is_merged(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    cb = cfg(b); cb["gaze"] = False; put(b, cb)                         # A は辞書、B は false
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0 and cfg(pk)["gaze"] is False
    cb["gaze"] = True; put(b, cb)
    assert run("pack.py", pk, "--from", a, "--from", b, "--force").returncode == 0 and cfg(pk)["gaze"] is True


def test_hand_reference_images_are_copied(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    (a / "guides").mkdir(); shutil.copy(a / "poses/pose_home.png", a / "guides/three.png")
    ca = cfg(a); ca["hands"] = {"wave": {"base": "home", "box": [0, 0, 10, 10], "desc": "x", "refs": ["guides/three.png"]}}; put(a, ca)
    assert run("pack.py", pk, "--from", a, "--from", b).returncode == 0
    assert (pk / "guides/three.png").exists()
    (a / "guides/three.png").unlink()
    assert run("pack.py", pk, "--from", a, "--from", b, "--force").returncode != 0


def test_hand_reference_outside_the_workspace_is_rejected(tmp_path):
    a, b = two(tmp_path); pk = tmp_path / "pack"
    shutil.copy(a / "poses/pose_home.png", tmp_path / "outside.png")
    ca = cfg(a); ca["hands"] = {"wave": {"base": "home", "box": [0, 0, 10, 10], "desc": "x", "refs": ["../outside.png"]}}; put(a, ca)
    r = run("pack.py", pk, "--from", a, "--from", b)
    assert r.returncode != 0 and not pk.exists()


# ---------- 作り置きを入れたパック（--with-cache）----------
def _wan_wf(tmp_path, name="w"):
    """Wan で動かす作業フォルダ。home⇄point の切り替えを偽の生成でためておく（ComfyUI・RIFE は呼ばない）。"""
    import cv2
    sys.path.insert(0, str(SCRIPTS)); import lib, wanflf  # noqa: E401
    p = wf(tmp_path, name); c = cfg(p)
    c["interp"] = {"engine": "wan", "mult": 4, "wan": {"width": 240, "height": 384, "rife_mult": 1}}; c["legs_lock"] = {"fix_x": True}
    c["head"] = {"chain": ["home", "point"], "mult": 2, "events": [{"at": 0.4, "pose": "point"}]}; put(p, c)
    P = lib.Proj(str(p)); icfg = lib.interp_config(c["interp"]); n = P.ib_div * icfg["mult"] - 1

    def gen(P_, a, b, wan, raw_dir, log=None):
        A = cv2.resize(P_.read_pose(a), (wan["width"], wan["height"])); B = cv2.resize(P_.read_pose(b), (wan["width"], wan["height"]))
        os.makedirs(raw_dir, exist_ok=True)
        for i in range(wan["length"]): cv2.imwrite(os.path.join(raw_dir, f"w{i + 1:02d}.png"), cv2.addWeighted(A, 1 - i / (wan["length"] - 1), B, i / (wan["length"] - 1), 0))

    def rife(frames, mult, icfg_, tag):
        out = []
        for x, y in zip(frames, frames[1:]): out += [cv2.addWeighted(x, 1 - j / mult, y, j / mult, 0) for j in range(mult)]
        return out + [frames[-1]]
    for a_, b_ in (("home", "point"), ("point", "home")): wanflf.dense_paths(P, a_, b_, n, icfg, gen=gen, rife=rife)
    return p, n


def test_pack_with_cache_holds_webp_without_raw_and_new_links_it(tmp_path):
    p, n = _wan_wf(tmp_path); pk = tmp_path / "pack"
    r = run("pack.py", pk, "--from", p, "--with-cache")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Wan の切り替え 2 組" in r.stdout
    d = pk / "ib_wan" / "home__point"
    assert (d / "raw_stamp.json").exists() and not (d / "raw").exists() and (pk / "ib_wan" / ".readonly").exists()
    assert len(list((d / f"n{n}").glob("f*.webp"))) == n and not list((d / f"n{n}").glob("f*.png"))
    man = json.loads((pk / "pack.json").read_text()); assert sorted(man["cache"]["wan"]) == ["home__point", "point__home"]
    assert "events" not in cfg(pk)["head"] and cfg(pk)["head"]["chain"] == ["home", "point"]   # 頭の動きの予定は台本に属する
    nw = tmp_path / "video"
    assert run("pack.py", pk, "--new", nw).returncode == 0
    assert (nw / "ib_wan").is_symlink() and os.path.realpath(nw / "ib_wan") == os.path.realpath(pk / "ib_wan")
    shutil.rmtree(nw / "voice"); shutil.copytree(p / "voice", nw / "voice")
    c = cfg(nw); c["voice"] = cfg(p)["voice"]; c["events"] = [{"at": 0.6, "pose": "point"}, {"at": 2.0, "pose": "home"}]; put(nw, c)
    r = run("render.py", nw, "--mode", "white", "--out", nw / "out/t.mp4", "--check-only")
    assert r.returncode == 0 and "Wan で新しく作る組: 0" in r.stderr, r.stderr[-1500:]
    r = run("render.py", nw, "--mode", "white", "--out", nw / "out/t.mp4", "--strict", env=ffmpeg_env(tmp_path))   # ComfyUI は無いので、作ろうとすれば落ちる
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    own = tmp_path / "video_own"
    assert run("pack.py", pk, "--new", own, "--own-cache").returncode == 0
    assert not (own / "ib_wan").is_symlink() and not (own / "ib_wan" / ".readonly").exists()


def test_pack_with_cache_skips_stale_pairs(tmp_path):
    p, n = _wan_wf(tmp_path)
    im = Image.open(p / "poses/pose_point.png"); im.putpixel((3, 3), (1, 2, 3)); im.save(p / "poses/pose_point.png")   # 作った後に絵を描き直した
    r = run("pack.py", tmp_path / "pack", "--from", p, "--with-cache")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Wan の切り替え 0 組" in r.stdout and "入れなかった: home__point" in r.stdout


def test_pack_without_cache_flag_keeps_old_behavior(tmp_path):
    p, n = _wan_wf(tmp_path); pk = tmp_path / "pack"
    assert run("pack.py", pk, "--from", p).returncode == 0
    assert not (pk / "ib_wan").exists() and "cache" not in json.loads((pk / "pack.json").read_text())
