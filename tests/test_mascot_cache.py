"""作り置き（Wan・RIFE の列）の判定を、ファイルの中身の印（md5）で比べる。パックを別の PC に運ぶと更新時刻が変わるが、
元の絵が同じなら作り直さない。前の形（更新時刻）の stamp は、合っていれば中身の印に書き換える。"""
import json
import os
import shutil
import time

import cv2
import numpy as np
import pytest

import interp
import lib


def write(p, v):
    cv2.imwrite(str(p), np.full((20, 20, 3), v, np.uint8)); return str(p)


def test_file_sig_ignores_mtime():
    import tempfile
    d = tempfile.mkdtemp(); a = write(os.path.join(d, "a.png"), 10)
    s1 = lib.file_sig([a]); os.utime(a, (1, 1)); s2 = lib.file_sig([a])
    assert s1 == s2 and s1[0][0] == "a.png" and len(s1[0][2]) == 32
    write(a, 11); assert lib.file_sig([a]) != s1
    shutil.rmtree(d)


def test_stamp_ok_new_old_and_mismatch(tmp_path):
    a = write(tmp_path / "a.png", 10); sp = tmp_path / "stamp.json"
    make = lambda sig: {"src": sig([a]), "mult": 2}
    assert not lib.stamp_ok(str(sp), make)                                    # stamp が無い
    json.dump(make(lib.file_sig_mtime), open(sp, "w"))                        # 前の形（更新時刻）
    assert lib.stamp_ok(str(sp), make)
    assert json.load(open(sp)) == json.loads(json.dumps(make(lib.file_sig)))   # 中身の印に書き換わった
    os.utime(a, (time.time() + 100, time.time() + 100))                      # 別の PC に運んだのと同じ（更新時刻だけ変わる）
    assert lib.stamp_ok(str(sp), make)
    write(a, 99)                                                              # 中身が変われば作り直す
    assert not lib.stamp_ok(str(sp), make)
    sp.write_text("{壊れた")
    assert not lib.stamp_ok(str(sp), make)


def test_interp_cache_survives_copy_with_new_mtime(tmp_path):
    """RIFE の列を作っておき、フォルダを更新時刻が変わる形で写しても、RIFE を呼ばずに使える（exe が無いので呼べば止まる）。"""
    root = tmp_path / "p"; (root / "poses").mkdir(parents=True)
    json.dump({"name": "t", "fps": 30, "poses": {"home": {}, "open": {}}}, open(root / "config.json", "w"))
    write(root / "poses" / "pose_home.png", 30); write(root / "poses" / "pose_open.png", 200)
    P = lib.Proj(str(root)); cfg = dict(lib.INTERP_DEFAULTS); cfg["mult"] = 2; cfg["exe"] = str(tmp_path / "no-rife.exe")
    srcs = [P.pose_path("home"), P.pose_path("open")]; tot = cfg["mult"] * P.ib_div
    out = P.p("ib_interp", f"home_open_direct_x{tot}_{cfg['model']}"); os.makedirs(out)
    for j in range(1, tot): write(os.path.join(out, f"f{j}.png"), 30 + j)
    json.dump(interp._stamp(srcs, cfg, lib.file_sig_mtime), open(os.path.join(out, "stamp.json"), "w"))   # 前の形の stamp
    assert len(interp.dense_paths(P, "home", "open", P.ib_div, cfg, direct=True)) == tot - 1          # 書き換えて使う
    dst = tmp_path / "copy"; shutil.copytree(root, dst, copy_function=shutil.copy)                     # 更新時刻は写した時刻
    later = time.time() + 1000
    for dp, _, fs in os.walk(dst):
        for f in fs: os.utime(os.path.join(dp, f), (later, later))
    P2 = lib.Proj(str(dst))
    assert len(interp.dense_paths(P2, "home", "open", P2.ib_div, cfg, direct=True)) == tot - 1
    write(dst / "poses" / "pose_open.png", 201)                                                         # 元の絵が変われば RIFE（無いので止まる）
    with pytest.raises(SystemExit):
        interp.dense_paths(P2, "home", "open", P2.ib_div, cfg, direct=True)


# ---------- パックの作り置き（WebP・raw なし・.readonly）----------
import sys  # noqa: E402
from pathlib import Path  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import synth_mascot as sm  # noqa: E402
import wanflf  # noqa: E402
from PIL import Image  # noqa: E402


def no_call(*a, **k):
    raise AssertionError("作り置きがあるのに Wan か RIFE を呼んだ")


def fake_gen(P, a, b, wan, raw_dir, log=None):
    A = cv2.resize(P.read_pose(a), (wan["width"], wan["height"])); B = cv2.resize(P.read_pose(b), (wan["width"], wan["height"]))
    os.makedirs(raw_dir, exist_ok=True)
    for i in range(wan["length"]): cv2.imwrite(os.path.join(raw_dir, f"w{i + 1:02d}.png"), cv2.addWeighted(A, 1 - i / (wan["length"] - 1), B, i / (wan["length"] - 1), 0))


def fake_rife(frames, mult, icfg, tag):
    out = []
    for a, b in zip(frames, frames[1:]): out += [cv2.addWeighted(a, 1 - j / mult, b, j / mult, 0) for j in range(mult)]
    return out + [frames[-1]]


def pack_like(P, a, b, n, icfg):
    """vm pack と同じ形にする: 列を WebP にし、raw/（元のコマ）を外し（raw_stamp.json は残す）、stamp の raw を空にして、置き場に .readonly。"""
    base = P.p("ib_wan", f"{a}__{b}"); out = os.path.join(base, f"n{n}")
    for j in range(1, n + 1):
        p = os.path.join(out, f"f{j}.png"); Image.open(p).save(os.path.join(out, f"f{j}.webp"), "WEBP", quality=95); os.remove(p)
    shutil.rmtree(os.path.join(base, "raw"))
    json.dump(wanflf._stamp_maker(P, a, b, icfg, [], [P.pose_path(a), P.pose_path(b)])(lib.file_sig), open(os.path.join(out, "stamp.json"), "w"))
    open(P.p("ib_wan", lib.READONLY), "w").close()


def test_frame_paths_png_webp_none(tmp_path):
    assert lib.frame_paths(str(tmp_path), 2) == ([str(tmp_path / "f1.png"), str(tmp_path / "f2.png")], False)
    for j in (1, 2): write(tmp_path / f"f{j}.png", 1)
    assert lib.frame_paths(str(tmp_path), 2)[1] and lib.frame_paths(str(tmp_path), 2)[0][0].endswith(".png")
    for j in (1, 2): os.rename(tmp_path / f"f{j}.png", tmp_path / f"f{j}.webp")
    ps, have = lib.frame_paths(str(tmp_path), 2); assert have and ps[1].endswith("f2.webp")
    assert lib.frame_paths(str(tmp_path), 3)[1] is False                        # 枚数が足りなければそろっていない


def test_packed_wan_cache_is_used_without_raw_and_never_rewritten(tmp_path):
    P = lib.Proj(sm.make(str(tmp_path / "proj"))); n = 11
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2}})
    wanflf.dense_paths(P, "home", "point", n, icfg, gen=fake_gen, rife=fake_rife)
    assert wanflf.need(P, "home", "point", n, icfg) is None
    pack_like(P, "home", "point", n, icfg)
    ps = wanflf.dense_paths(P, "home", "point", n, icfg, gen=no_call, rife=no_call)   # raw が無くても、WebP の列をそのまま使う
    assert len(ps) == n and all(p.endswith(".webp") for p in ps) and cv2.imread(ps[0]) is not None
    assert wanflf.need(P, "home", "point", n, icfg) is None
    write(P.pose_path("point"), 77)                                                    # 元の絵が変わった → Wan が要る
    assert wanflf.need(P, "home", "point", n, icfg) == "wan"
    with pytest.raises(SystemExit):                                                     # パックの作り置きは書き換えない
        wanflf.dense_paths(P, "home", "point", n, icfg, gen=no_call, rife=no_call)
    assert all(os.path.exists(p) for p in ps)


def test_need_rife_when_only_post_is_stale(tmp_path):
    P = lib.Proj(sm.make(str(tmp_path / "proj"))); n = 11
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2}})
    wanflf.dense_paths(P, "home", "point", n, icfg, gen=fake_gen, rife=fake_rife)
    icfg2 = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2, "edge": 0.3}})   # 後処理だけに効く値
    assert wanflf.need(P, "home", "point", n, icfg2) == "rife"


def test_packed_interp_cache_webp_and_readonly(tmp_path):
    root = tmp_path / "p"; (root / "poses").mkdir(parents=True)
    json.dump({"name": "t", "fps": 30, "poses": {"home": {}, "open": {}}}, open(root / "config.json", "w"))
    write(root / "poses" / "pose_home.png", 30); write(root / "poses" / "pose_open.png", 200)
    P = lib.Proj(str(root)); cfg = dict(lib.INTERP_DEFAULTS); cfg["mult"] = 2; cfg["exe"] = str(tmp_path / "no-rife.exe")
    srcs = [P.pose_path("home"), P.pose_path("open")]; tot = cfg["mult"] * P.ib_div
    out = P.p("ib_interp", f"home_open_direct_x{tot}_{cfg['model']}"); os.makedirs(out)
    for j in range(1, tot): Image.fromarray(np.full((20, 20, 3), 30 + j, np.uint8)).save(os.path.join(out, f"f{j}.webp"), "WEBP", quality=95)
    json.dump(interp._stamp(srcs, cfg), open(os.path.join(out, "stamp.json"), "w")); open(P.p("ib_interp", lib.READONLY), "w").close()
    assert interp.ready(P, "home", "open", P.ib_div, cfg, direct=True)
    ps = interp.dense_paths(P, "home", "open", P.ib_div, cfg, direct=True)
    assert len(ps) == tot - 1 and ps[0].endswith(".webp")
    write(P.pose_path("open"), 201)
    assert not interp.ready(P, "home", "open", P.ib_div, cfg, direct=True)
    with pytest.raises(SystemExit):
        interp.dense_paths(P, "home", "open", P.ib_div, cfg, direct=True)


def test_packed_wan_cache_notices_prompt_change(tmp_path):
    """パックは元のコマを持たないが、raw_stamp.json（描かせる文・生成の値）は持つので、生成の設定が変われば作り直しに行く。"""
    P = lib.Proj(sm.make(str(tmp_path / "proj"))); n = 11
    icfg = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2}})
    wanflf.dense_paths(P, "home", "point", n, icfg, gen=fake_gen, rife=fake_rife); pack_like(P, "home", "point", n, icfg)
    icfg2 = lib.interp_config({"engine": "wan", "wan": {"width": 240, "height": 384, "rife_mult": 2, "seed": 7}})
    assert wanflf.need(P, "home", "point", n, icfg2) == "wan"
    with pytest.raises(SystemExit):
        wanflf.dense_paths(P, "home", "point", n, icfg2, gen=no_call, rife=no_call)


def test_stamp_ok_never_writes_under_readonly(tmp_path):
    """パックの作り置き（.readonly）に前の形の stamp があっても、合っていれば使い、書き換えない（Codex の指摘）。"""
    root = tmp_path / "ib_interp"; d = root / "k"; d.mkdir(parents=True); (root / lib.READONLY).write_text("")
    a = write(tmp_path / "a.png", 10); sp = d / "stamp.json"
    make = lambda sig: {"src": sig([a]), "mult": 2}
    json.dump(make(lib.file_sig_mtime), open(sp, "w")); before = sp.read_text()
    assert lib.stamp_ok(str(sp), make) and sp.read_text() == before
    os.chmod(sp, 0o444); os.chmod(d, 0o555)
    try: assert lib.stamp_ok(str(sp), make)
    finally: os.chmod(d, 0o755); os.chmod(sp, 0o644)
    deep = root / "x" / "n47"; deep.mkdir(parents=True); assert lib.under_readonly(str(deep / "stamp.json"))
    assert not lib.under_readonly(str(tmp_path / "other" / "stamp.json"))
