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
