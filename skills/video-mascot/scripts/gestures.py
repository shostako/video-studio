"""身振りの辞書（data/gestures.yaml）を読み、作業フォルダの config に身振りの姿勢を足す。キャラに依らない（書き方は references/gestures.md）。
  vm gestures                                  辞書の一覧（名前・意味・確かめたか・どこから動くか）
  vm gestures --check [辞書.yaml]              辞書の形を検査する（崩れていれば理由を出して終了コード 1）
  vm gestures <作業フォルダ> --add 名前 ... [--print] [--force]
                                               config.json の poses・pairs・ib_steps に足す。書く前の config.json は config.json.bak に残す
足すのは、姿勢の描かせる文（mascot.pronoun で代名詞を差し替える）・参照・大きさの決まり（scale・expect_height）と、
動き出す姿勢（既定 home）からの組と中割りの段階。既にある姿勢は --force が無ければ書き換えない。絵は描かない（次に vm poses）。"""
import argparse, json, os, shutil, sys
from pathlib import Path
import yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import init

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "gestures.yaml"
KEYS = {"name", "preset", "meaning", "lines", "checked", "from", "inbetween", "refs", "desc", "steps", "scale", "expect_height"}
PRESETS = ("gestures", "extras_a", "extras_b")
OWN = ("refs", "desc", "steps", "scale", "expect_height")   # preset の身振りでは書かない（雛形から取る）


class GestureError(ValueError): pass


def preset_entry(group, name):
    """vm init の雛形から、その身振りの姿勢（代名詞は {p} のまま）と、home からの中割りの段階。"""
    if group == "gestures": poses, _ = init.gesture_presets(); steps = init.gesture_steps()
    else: poses, _ = init.extra_presets(group[-1]); steps = init.extra_steps(group[-1])
    if name not in poses: raise GestureError(f"{name}: preset {group} の雛形に無い")
    return poses[name], steps.get(f"home>{name}")


def load(path=DEFAULT_PATH):
    """辞書を読んで検査し、名前→身振りの辞書（読んだ順）を返す。preset の身振りは雛形の desc・refs・steps などを埋める。"""
    with open(path, encoding="utf-8") as f: doc = yaml.safe_load(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("gestures"), list): raise GestureError("一番上に gestures: の並びが要る")
    out = {}
    for i, g in enumerate(doc["gestures"]):
        where = f"{i + 1}番目"
        if not isinstance(g, dict): raise GestureError(f"{where}: 表になっていない")
        bad = set(g) - KEYS
        if bad: raise GestureError(f"{where}: 知らないキー {sorted(bad)}")
        n = g.get("name")
        if not isinstance(n, str) or not n or not n.replace("_", "").isalnum() or not n.isascii(): raise GestureError(f"{where}: name は英数字と _ にする")
        where = n
        if n in out: raise GestureError(f"{n}: 同じ名前が2回ある")
        if n == "home": raise GestureError("home は辞書に入れない（基本の立ち姿は vm init が書く）")
        if not isinstance(g.get("meaning"), str) or not g["meaning"].strip(): raise GestureError(f"{n}: meaning（意味）が要る")
        if not isinstance(g.get("checked"), bool): raise GestureError(f"{n}: checked は true か false")
        lines = g.get("lines", [])
        if not isinstance(lines, list) or not all(isinstance(s, str) for s in lines): raise GestureError(f"{n}: lines は文字列の並び")
        e = {"name": n, "meaning": g["meaning"], "lines": lines, "checked": g["checked"], "from": g.get("from", "home")}
        if not isinstance(e["from"], str): raise GestureError(f"{n}: from は姿勢の名前")
        e["inbetween"] = g.get("inbetween", True)
        if not isinstance(e["inbetween"], bool): raise GestureError(f"{n}: inbetween は true か false")
        if not e["inbetween"] and g.get("steps") is not None: raise GestureError(f"{n}: inbetween: false の身振りに steps は書かない")
        if "preset" in g:
            if g["preset"] not in PRESETS: raise GestureError(f"{n}: preset は {', '.join(PRESETS)} のどれか")
            own = [k for k in OWN if k in g]
            if own: raise GestureError(f"{n}: preset の身振りに {own} は書かない（雛形から取る）")
            if e["from"] != "home": raise GestureError(f"{n}: preset の身振りは home から動く")
            pose, steps = preset_entry(g["preset"], n)
            e.update(preset=g["preset"], desc=pose["desc"], refs=pose.get("refs", ["home"]), steps=steps)
            for k in ("scale", "expect_height"):
                if k in pose: e[k] = pose[k]
        else:
            if not isinstance(g.get("desc"), str) or not g["desc"].strip(): raise GestureError(f"{n}: desc（描かせる英語の文）が要る")
            refs = g.get("refs", ["home"])
            if not isinstance(refs, list) or not refs or not all(isinstance(r, str) for r in refs): raise GestureError(f"{n}: refs は姿勢の名前の並び")
            st = g.get("steps")
            if st is not None and (not isinstance(st, list) or not st or not all(isinstance(s, str) and s.strip() for s in st)):
                raise GestureError(f"{n}: steps は中割りの各枚の様子の並び（書かなければ chain のまま、段階は言わせない）")
            e.update(desc=" ".join(g["desc"].split()), refs=refs, steps=st)
            if "scale" in g:
                if not isinstance(g["scale"], (int, float)) or g["scale"] <= 0: raise GestureError(f"{n}: scale は正の数")
                e["scale"] = float(g["scale"])
            if "expect_height" in g:
                eh = g["expect_height"]
                if not (isinstance(eh, list) and len(eh) == 2 and all(isinstance(v, (int, float)) for v in eh) and 0 < eh[0] < eh[1]):
                    raise GestureError(f"{n}: expect_height は [下限, 上限]（home を 1 とした背の比）")
                e["expect_height"] = [float(v) for v in eh]
        txt = e["desc"] + " ".join(e["steps"] or [])
        left = txt.replace("{p}", "").replace("{P}", "")
        if "{" in left or "}" in left: raise GestureError(f"{n}: 置き換えられない {{…}} がある（使えるのは {{p}} と {{P}}）")
        out[n] = e
    for n, e in out.items():     # 動き出す姿勢・参照は、辞書の身振りか home
        for r in [e["from"], *e["refs"]]:
            if r != "home" and r not in out: raise GestureError(f"{n}: {r} は辞書に無い姿勢")
    return out


def needs(d, names):
    """足す身振りが要る、辞書の中の姿勢（from と refs を辿る。足す順に並べる）。"""
    order = []
    def visit(n, path=()):
        if n == "home" or n in order: return
        if n in path: raise GestureError(f"from / refs が輪になっている: {' > '.join(path + (n,))}")
        if n not in d: raise GestureError(f"辞書に無い身振り: {n}（vm gestures で一覧）")
        for r in [d[n]["from"], *d[n]["refs"]]: visit(r, path + (n,))
        order.append(n)
    for n in names: visit(n)
    return order


def add(cfg, d, names, force=False):
    """config に身振りを足した新しい config と、足した姿勢の名前の並び。from・refs の姿勢が config に無ければ、辞書から一緒に足す。"""
    cfg = json.loads(json.dumps(cfg)); home = cfg.get("home", "home")
    pron = cfg.get("mascot", {}).get("pronoun", "she")
    if pron not in init.POSS: raise GestureError(f"mascot.pronoun が知らない値: {pron}")
    poses = cfg.setdefault("poses", {}); pairs = cfg.setdefault("pairs", []); added = []
    for n in needs(d, names):
        if n in poses and not (force and n in names):
            if n in names: raise GestureError(f"{n} は config に既にある（書き換えるなら --force）")
            continue                                          # 参照に要るだけの姿勢は、既にあればそのまま使う
        e = d[n]; ren = lambda r: home if r == "home" else r
        pose = {"desc": e["desc"], "refs": [ren(r) for r in e["refs"]]}
        for k in ("scale", "expect_height"):
            if k in e: pose[k] = e[k]
        poses[n] = init.fill({n: pose}, pron)[n]
        if e["inbetween"]:                                    # 中割りを描く組（inbetween: false は組を足さない＝切り替えは一瞬か transition）
            a = ren(e["from"])
            if [a, n] not in pairs and [n, a] not in pairs: pairs.append([a, n])
            if e["steps"] is not None: cfg.setdefault("ib_steps", {})[f"{a}>{n}"] = init.fill_steps({"x": e["steps"]}, pron)["x"]
        added.append(n)
    return cfg, added


def table(d):
    rows = [f"{'名前':<14}{'確かめ':<6}{'from':<10}意味"]
    for n, e in d.items(): rows.append(f"{n:<14}{'済' if e['checked'] else '未':<6}{e['from']:<10}{e['meaning']}" + ("" if e["inbetween"] else "（中割りなし）"))
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="vm gestures", description=__doc__.splitlines()[0])
    ap.add_argument("dir", nargs="?", help="作業フォルダ（--add の時）か、--check の時の辞書のファイル")
    ap.add_argument("--add", nargs="+", metavar="名前", help="config に足す身振り")
    ap.add_argument("--check", action="store_true", help="辞書の形を検査する")
    ap.add_argument("--print", action="store_true", help="書き込まずに、足したあとの config.json を出す")
    ap.add_argument("--force", action="store_true", help="既にある姿勢も書き換える")
    ap.add_argument("--dict", default=str(DEFAULT_PATH), help="辞書のファイル（既定 data/gestures.yaml）")
    a = ap.parse_args()
    try:
        if a.check:
            d = load(a.dir or a.dict); print(f"ok: {len(d)} の身振り（確かめ済み {sum(e['checked'] for e in d.values())}）"); sys.exit(0)
        d = load(a.dict)
        if not a.add:
            if a.dir: sys.exit("使い方: vm gestures <作業フォルダ> --add 名前 ...（一覧は vm gestures）")
            print(table(d)); sys.exit(0)
        if not a.dir: sys.exit("使い方: vm gestures <作業フォルダ> --add 名前 ...")
        cp = os.path.join(os.path.abspath(a.dir), "config.json")
        if not os.path.exists(cp): sys.exit(f"config.json が無い: {cp}（先に vm init）")
        with open(cp, encoding="utf-8") as f: cfg = json.load(f)
        new, added = add(cfg, d, a.add, a.force)
    except (GestureError, yaml.YAMLError) as ex:
        print(f"ERROR: {ex}", file=sys.stderr); sys.exit(1)
    if a.print: print(json.dumps(new, ensure_ascii=False, indent=1)); sys.exit(0)
    shutil.copyfile(cp, cp + ".bak")
    with open(cp, "w", encoding="utf-8") as f: json.dump(new, f, ensure_ascii=False, indent=1)
    print(f"足した: {', '.join(added) or '（無し）'}（元は config.json.bak）")
    unchecked = [n for n in added if not d[n]["checked"]]
    if unchecked: print(f"まだ実物で確かめていない文: {', '.join(unchecked)}。描いたら1枚ずつ見る（左右・指の本数・足元）", file=sys.stderr)
    print("次: vm poses <作業フォルダ> poses --dry-run で描く予定を見てから、poses → inbetweens → parts の順に")
