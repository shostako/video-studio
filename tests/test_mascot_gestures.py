"""身振りの辞書（data/gestures.yaml）と vm gestures。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills/video-mascot/scripts"
sys.path.insert(0, str(SCRIPTS))
import gestures as G  # noqa: E402
import init  # noqa: E402


def _dict(tmp_path, text):
    p = tmp_path / "g.yaml"; p.write_text(text, encoding="utf-8"); return p


def test_dictionary_loads_and_presets_match_vm_init():
    d = G.load()
    assert len(d) >= 15 and all(e["meaning"] for e in d.values())
    full = init.build("x", "a test", "she", "none", gestures=True, extras="ab")
    for n, e in d.items():
        if not e.get("preset"): continue
        cfg, _ = G.add(init.build("x", "a test", "she", "none"), d, [n])
        assert cfg["poses"][n] == full["poses"][n]                       # vm init --gestures / --extras と同じ文・大きさの決まり
        assert ["home", n] in cfg["pairs"]
        assert cfg.get("ib_steps", {}).get(f"home>{n}") == full.get("ib_steps", {}).get(f"home>{n}")


def test_dictionary_has_no_character_specific_words():
    txt = json.dumps([[e["desc"], e["steps"]] for e in G.load().values()]).lower()
    for w in ("monday", "suit", "navy", "black shoes", " her ", " his "):   # キャラ固有の服・色・代名詞を焼き込まない
        assert w not in txt


def test_add_fills_pronoun_pairs_steps_and_dependencies():
    d = G.load(); base = init.build("x", "a test", "he", "a")
    cfg, added = G.add(base, d, ["count_3", "pinch"])
    assert added == ["raise_r", "count_3", "pinch"]                      # count_3 の参照 raise_r も一緒に足す
    assert cfg["poses"]["count_3"]["refs"] == ["raise_r"] and "his index" in cfg["poses"]["count_3"]["desc"]
    assert ["home", "raise_r"] in cfg["pairs"] and ["home", "pinch"] in cfg["pairs"]
    assert not any("count_3" in p for p in cfg["pairs"])                  # inbetween: false は組を足さない
    assert len(cfg["ib_steps"]["home>pinch"]) == 5 and "{p}" not in json.dumps(cfg)
    assert base["pairs"] == [["turn_l", "present_l"], ["turn_r", "present_r"]]   # 元の config は書き換えない


def test_add_keeps_existing_poses_unless_forced():
    d = G.load(); base = init.build("x", "a test", "she", "none", gestures=True)
    base["poses"]["open"]["desc"] = "my own text"
    with pytest.raises(G.GestureError): G.add(base, d, ["open"])
    cfg, added = G.add(base, d, ["open"], force=True)
    assert added == ["open"] and cfg["poses"]["open"]["desc"] != "my own text"
    base["poses"]["raise_r"] = {"desc": "already drawn", "refs": ["home"]}
    cfg, added = G.add(base, d, ["count_2"])
    assert added == ["count_2"] and cfg["poses"]["raise_r"]["desc"] == "already drawn"   # 参照に要るだけの既にある姿勢はそのまま


def test_add_uses_config_home_name():
    d = G.load(); base = init.build("x", "a test", "she", "none"); base["home"] = "stand"
    base["poses"] = {"stand": base["poses"].pop("home")}
    cfg, _ = G.add(base, d, ["span"])
    assert cfg["poses"]["span"]["refs"] == ["stand"] and ["stand", "span"] in cfg["pairs"] and "stand>span" in cfg["ib_steps"]


@pytest.mark.parametrize("body, msg", [
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, color: red}\n", "知らないキー"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d}\n  - {name: a, meaning: y, checked: true, desc: d}\n", "2回"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: 'her {s} arm'}\n", "置き換えられない"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, refs: [b]}\n", "辞書に無い"),
    ("gestures:\n  - {name: a, meaning: x, checked: yes please, desc: d}\n", "checked"),
    ("gestures:\n  - {name: open, preset: gestures, meaning: x, checked: true, desc: d}\n", "雛形から取る"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, inbetween: false, steps: [s]}\n", "steps は書かない"),
    ("gestures:\n  - {name: home, meaning: x, checked: true, desc: d}\n", "home"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, scale: true}\n", "scale"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: 'raise her hand'}\n", "代名詞"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: 'my hand is raised'}\n", "代名詞"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, steps: ['His arm is up']}\n", "代名詞"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, scale: .nan}\n", "scale"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, scale: .inf}\n", "scale"),
    ("gestures:\n  - {name: a, meaning: x, checked: true, desc: d, expect_height: [0.9, .inf]}\n", "expect_height"),
    ("gestures:\n  - name: a\n    meaning: x\n    checked: true\n    desc: d\n    desc: e\n", "同じキーが2回"),
])
def test_check_rejects_broken_dictionaries(tmp_path, body, msg):
    with pytest.raises(G.GestureError, match=msg): G.load(_dict(tmp_path, body))


def test_cycle_is_rejected(tmp_path):
    p = _dict(tmp_path, "gestures:\n  - {name: a, meaning: x, checked: true, desc: d, refs: [b]}\n"
                        "  - {name: b, meaning: y, checked: true, desc: d, from: a}\n")
    with pytest.raises(G.GestureError, match="輪"): G.load(p)                     # --check の段階で止める
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gestures.py"), "--check", str(p)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "輪" in r.stderr


def test_cli_add_writes_backup_and_check(tmp_path):
    cp = tmp_path / "config.json"; cfg = init.build("w", "a test", "she", "none")
    cp.write_text(json.dumps(cfg), encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, "-B", str(SCRIPTS / "gestures.py"), *map(str, a)], capture_output=True, text=True, timeout=60)
    r = run(tmp_path, "--add", "arms_crossed", "--print"); assert r.returncode == 0 and "arms_crossed" in r.stdout
    assert json.loads(cp.read_text(encoding="utf-8")) == cfg                         # --print は書かない
    r = run(tmp_path, "--add", "arms_crossed"); assert r.returncode == 0, r.stderr
    assert "arms_crossed" in json.loads(cp.read_text(encoding="utf-8"))["poses"]
    assert json.loads((tmp_path / "config.json.bak").read_text(encoding="utf-8")) == cfg
    assert run(tmp_path, "--add", "nope").returncode == 1
    r = run("--check"); assert r.returncode == 0 and r.stdout.startswith("ok:")
    assert "palm_stop" in run().stdout


def test_force_with_reverse_pair_keeps_its_direction():
    d = G.load(); base = init.build("x", "a test", "she", "none")
    base["poses"]["pinch"] = {"desc": "old", "refs": ["home"]}; base["pairs"].append(["pinch", "home"])
    cfg, _ = G.add(base, d, ["pinch"], force=True)
    assert cfg["pairs"].count(["pinch", "home"]) == 1 and ["home", "pinch"] not in cfg["pairs"]
    assert "home>pinch" not in cfg["ib_steps"]
    fwd, _ = G.add(init.build("x", "a test", "she", "none"), d, ["pinch"])
    assert cfg["ib_steps"]["pinch>home"] == fwd["ib_steps"]["home>pinch"][::-1]       # 組の向きで引かれ、段階は逆の順


def test_force_refuses_home_and_drawn_poses():
    d = G.load(); base = init.build("x", "a test", "she", "none", gestures=True)
    with pytest.raises(G.GestureError, match="drawn|描けている"): G.add(base, d, ["open"], force=True, drawn={"open"})
    base["home"] = "span"; base["poses"]["span"] = base["poses"].pop("home")
    with pytest.raises(G.GestureError, match="基本の姿勢"): G.add(base, d, ["span"], force=True)
    base = init.build("x", "a test", "she", "none"); base["home"] = "raise_r"; base["poses"] = {"raise_r": base["poses"].pop("home")}
    with pytest.raises(G.GestureError, match="基本の姿勢"): G.add(base, d, ["count_3"])            # 参照の raise_r が home と同じ名前


def test_cli_force_refuses_drawn_pose(tmp_path):
    cfg = init.build("w", "a test", "she", "none", gestures=True); (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "poses").mkdir(); (tmp_path / "poses" / "pose_open.png").write_bytes(b"x")
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gestures.py"), str(tmp_path), "--add", "open", "--force"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "描けている" in r.stderr


def test_cli_refuses_orphan_pose_image(tmp_path):
    cfg = init.build("w", "a test", "she", "none"); (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "poses").mkdir(); (tmp_path / "poses" / "pose_span.png").write_bytes(b"x")       # config に無い絵だけが残っている
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gestures.py"), str(tmp_path), "--add", "span"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "pose_span.png" in r.stderr
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8")) == cfg


@pytest.mark.parametrize("left", ["parts/span_m1.png", "parts_span/m1.png", "ib/ib_home_span_3.png", "ib/ib_span_home_2_12.png", "ib/ib_home_span_2_12.png"])
def test_cli_refuses_leftover_derived_assets(tmp_path, left):
    cfg = init.build("w", "a test", "she", "none"); (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    f = tmp_path / left; f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"x")          # 姿勢の絵は消えたが、差分・中割りが残っている
    r = subprocess.run([sys.executable, "-B", str(SCRIPTS / "gestures.py"), str(tmp_path), "--add", "span"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "描けている" in r.stderr


def test_has_assets_does_not_match_other_poses(tmp_path):
    (tmp_path / "ib").mkdir(); (tmp_path / "ib" / "ib_home_span_wide_3.png").write_bytes(b"x")
    (tmp_path / "parts").mkdir(); (tmp_path / "parts" / "span_wide_m1.png").write_bytes(b"x")
    assert not G.has_assets(tmp_path, "span") and G.has_assets(tmp_path, "span_wide")
