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
