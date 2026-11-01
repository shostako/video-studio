"""vm packs: パックを公開用の zip に書き出し、リポの控え（data/packs.json）の版を取ってきて置く。"""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "video-mascot" / "scripts"


def run(*args, env=None):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / "packs.py"), *map(str, args)], capture_output=True, text=True, timeout=120, env=env)


def make_pack(root, name="rin"):
    p = root / name; (p / "poses").mkdir(parents=True); (p / "ib_wan" / "home__point" / "n3").mkdir(parents=True); (p / "out").mkdir(); (p / "voice").mkdir()
    (p / "poses" / "pose_home.png").write_bytes(b"png")
    for j in (1, 2, 3): (p / "ib_wan" / "home__point" / "n3" / f"f{j}.webp").write_bytes(b"webp")
    (p / "ib_wan" / ".readonly").write_text(""); (p / "out" / "junk.webm").write_bytes(b"x"); (p / "reject").mkdir(); (p / "reject" / "bad.png").write_bytes(b"x")
    home = os.path.expanduser("~")
    json.dump({"built": "x", "sources": [f"{home}/.local/share/video-scene/work/b-cad"], "poses": {"home": f"{home}/w/b-cad"},
               "pairs": {}, "workspaces": [f"{home}/w/v1"]}, open(p / "pack.json", "w"))
    json.dump({"name": name, "poses": {"home": {}}, "from_pack": f"{home}/.local/share/video-scene/packs/old"}, open(p / "config.json", "w"))
    return p


@pytest.fixture()
def env(tmp_path, monkeypatch):
    e = dict(os.environ, VIDEO_SCENE_HOME=str(tmp_path / "vs"), VM_PACK_REGISTRY=str(tmp_path / "reg.json"))
    return e


def write_manifest(path, entries):
    json.dump({"packs": entries}, open(path, "w")); return path


def test_export_strips_local_paths_and_writes_release(tmp_path):
    p = make_pack(tmp_path / "src"); out = tmp_path / "rin-pack.zip"
    r = run("export", p, out, "--version", "2026-11-01")
    assert r.returncode == 0, r.stderr
    entry = json.loads(r.stdout.strip().splitlines()[-1])
    assert entry["name"] == "rin" and entry["version"] == "2026-11-01" and len(entry["sha256"]) == 64 and entry["size"] == out.stat().st_size
    z = zipfile.ZipFile(out); names = z.namelist()
    assert "rin/ib_wan/.readonly" in names and "rin/ib_wan/home__point/n3/f3.webp" in names and "CC0" in z.read("rin/LICENSE.txt").decode()
    assert not any(n.startswith("rin/reject") or n == "rin/out/junk.webm" for n in names) and "rin/out/" in names
    man = json.loads(z.read("rin/pack.json")); cfg = json.loads(z.read("rin/config.json"))
    assert man["release"] == "2026-11-01" and man["sources"] == ["b-cad"] and man["poses"]["home"] == "b-cad" and "workspaces" not in man
    assert "from_pack" not in cfg
    home = os.path.expanduser("~")
    assert all(home not in z.read(n).decode("utf-8", "ignore") for n in names if n.endswith(".json"))


def test_fetch_installs_checks_and_upgrades_with_repin(tmp_path, env):
    p = make_pack(tmp_path / "src"); z1 = tmp_path / "v1.zip"
    e1 = json.loads(run("export", p, z1, "--version", "v1").stdout.strip().splitlines()[-1]); e1["url"] = str(z1)
    mf = write_manifest(tmp_path / "packs.json", [e1])
    r = run("--manifest", mf, env=env); assert r.returncode == 1 and "手元 無し" in r.stdout          # 無い
    r = run("fetch", "--manifest", mf, env=env); assert r.returncode == 0, r.stderr
    dst = tmp_path / "vs" / "packs" / "rin"
    assert (dst / "ib_wan" / ".readonly").exists() and json.loads((dst / "pack.json").read_text())["release"] == "v1"
    assert run("--manifest", mf, env=env).returncode == 0                                          # そろった
    assert "そろっている" in run("fetch", "--manifest", mf, env=env).stdout                         # 2 回目は取らない
    ws = tmp_path / "video"; ws.mkdir(); os.symlink(dst / "ib_wan", ws / "ib_wan")                  # このパックから作った作業フォルダ
    json.dump({str(dst): [str(ws)]}, open(tmp_path / "reg.json", "w"))
    z2 = tmp_path / "v2.zip"
    e2 = json.loads(run("export", p, z2, "--version", "v2").stdout.strip().splitlines()[-1]); e2["url"] = str(z2)
    mf2 = write_manifest(tmp_path / "packs2.json", [e2])
    r = run("fetch", "--manifest", mf2, env=env); assert r.returncode == 0, r.stderr
    assert json.loads((dst / "pack.json").read_text())["release"] == "v2"
    old = next(x for x in (tmp_path / "vs" / "packs").iterdir() if x.name.startswith("rin.old-"))
    assert os.readlink(ws / "ib_wan") == str(old / "ib_wan")                                      # 前の作業フォルダは前の版を使い続ける


def test_fetch_rejects_bad_hash_and_unsafe_zip(tmp_path, env):
    p = make_pack(tmp_path / "src"); z1 = tmp_path / "v1.zip"
    e1 = json.loads(run("export", p, z1, "--version", "v1").stdout.strip().splitlines()[-1]); e1["url"] = str(z1)
    bad = dict(e1, sha256="0" * 64)
    r = run("fetch", "--manifest", write_manifest(tmp_path / "m1.json", [bad]), env=env)
    assert r.returncode != 0 and "ハッシュ" in r.stderr and not (tmp_path / "vs" / "packs" / "rin").exists()
    ev = tmp_path / "evil.zip"
    with zipfile.ZipFile(ev, "w") as z: z.writestr("../escape.txt", "x"); z.writestr("rin/pack.json", json.dumps({"release": "v1"}))
    r = run("fetch", "--manifest", write_manifest(tmp_path / "m2.json", [dict(e1, url=str(ev), sha256="")]), env=env)
    assert r.returncode != 0 and "置き場の外" in r.stderr and not (tmp_path / "vs" / "escape.txt").exists()
    r = run("fetch", "nope", "--manifest", write_manifest(tmp_path / "m3.json", [e1]), env=env)
    assert r.returncode != 0 and "控えに無い" in r.stderr



def test_fetch_keeps_inbetween_chain_newer_than_poses(tmp_path, env):
    """展開のあとも、中割りの続きが姿勢の絵より新しく、k の順に新しい（vm poses inbetweens が描き直さない）（Codex の指摘）。"""
    p = make_pack(tmp_path / "src"); (p / "ib").mkdir()
    (p / "poses" / "pose_point.png").write_bytes(b"png")
    for k in range(1, 6): (p / "ib" / f"ib_home_point_{k}.png").write_bytes(b"ib")
    c = json.loads((p / "config.json").read_text()); c["pairs"] = [["home", "point"]]; (p / "config.json").write_text(json.dumps(c))
    z1 = tmp_path / "v1.zip"
    e1 = json.loads(run("export", p, z1, "--version", "v1").stdout.strip().splitlines()[-1]); e1["url"] = str(z1)
    assert run("fetch", "--manifest", write_manifest(tmp_path / "m.json", [e1]), env=env).returncode == 0
    dst = tmp_path / "vs" / "packs" / "rin"
    mt = lambda f: os.path.getmtime(dst / f)
    ks = [mt(f"ib/ib_home_point_{k}.png") for k in range(1, 6)]
    assert max(mt("poses/pose_home.png"), mt("poses/pose_point.png")) < ks[0] and ks == sorted(ks)


def test_status_can_look_at_named_packs_only(tmp_path):
    """VM_PACKS=ran で入れた PC の setup.sh --check が、使わない凜で NG にならない。"""
    m = tmp_path / "packs.json"
    m.write_text(json.dumps({"packs": [
        {"name": "a", "version": "1", "url": "u", "size": 1, "sha256": "x"},
        {"name": "b", "version": "1", "url": "u", "size": 1, "sha256": "x"}]}), encoding="utf-8")
    env = dict(os.environ, VIDEO_SCENE_HOME=str(tmp_path / "home"))
    run = lambda *a: subprocess.run([sys.executable, "-B", str(SCRIPTS / "packs.py"), "status", *a, "--manifest", str(m)], capture_output=True, text=True, env=env)
    both = run(); only = run("a"); bad = run("zzz")
    assert both.returncode == 1 and " a:" in both.stdout and " b:" in both.stdout
    assert only.returncode == 1 and " a:" in only.stdout and " b:" not in only.stdout
    assert bad.returncode == 2 and "zzz" in bad.stderr
