"""マスコットパック（opt-in）: 1体のキャラの姿勢・部品・中割りを、動画ごとの作業フォルダから1つにまとめて使い回す。
  vm pack <パック> --from <作業フォルダ> [--from <作業フォルダ> ...] [--force]
      作業フォルダの姿勢・部品・中割り・手の部品を1つのパックにまとめる。同じ姿勢が複数にあれば、後に書いた --from が勝つ。
      中割りは、両端の姿勢の絵がパックの絵と同じ作業フォルダからだけ持ってくる（端の絵が違う中割りは切り替えで跳ぶため）。
      持ってこられなかった組は pairs に残すので、`vm poses <パック> inbetweens` で描き足す。
      台本に属するもの（voice・events・視線の予定・name）は持ってこない。補間の控え（ib_interp/）は書き出しのときに作り直す。
      パックは作業フォルダと同じ形（config.json・mascot.png・poses/・parts/・parts_<姿勢>/・ib/・hands/）で、出どころを pack.json に書く。
      既にあるパックは --force で置き換える（古いパックは <パック>.old-<時刻> に残す）。
  vm pack <パック> --new <新しい作業フォルダ> [--name 名前]
      パックを丸ごと複製して、新しい動画の作業フォルダを作る（台本・声・動きは空）。パックは書き換えない。"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import time

from lib import die

SCRIPT_KEYS = {"name", "voice", "events", "events_kw", "events_script", "events_demo", "gaze_script", "gaze_demo"}
SPECIAL = {"poses", "pairs", "ib_steps", "hands", "mirrored", "gaze", "interp", "face", "anchor"}


def md5(path):
    if not os.path.exists(path): return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def load(src):
    cf = os.path.join(src, "config.json")
    if not os.path.exists(cf): die(f"作業フォルダに config.json が無い: {src}")
    return json.load(open(cf, encoding="utf-8"))


def pose_files(src, n):
    """姿勢 n に属するファイル（作業フォルダからの相対パス）。部品の切り抜きのフォルダは丸ごと。"""
    out = [f"poses/pose_{n}.png"] if os.path.exists(os.path.join(src, f"poses/pose_{n}.png")) else []
    for k in ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "e1", "e2", "g_l", "g_r", "g_u", "g_c"):
        if os.path.exists(os.path.join(src, f"parts/{n}_{k}.png")): out.append(f"parts/{n}_{k}.png")
    for f in (f"hands/{n}.png", f"hands/{n}.placed.json", f"hands/_ref_{n}.png"):
        if os.path.exists(os.path.join(src, f)): out.append(f)
    if os.path.isdir(os.path.join(src, f"parts_{n}")): out.append(f"parts_{n}/")
    return out


def ib_full(src, a, b, div):
    """組 a>b の中割りが、分割数 div の枚数そろっているときだけ、その名前（作業フォルダからの相対パス）を返す。欠けていれば []。"""
    names = [f"ib/ib_{a}_{b}_{k}.png" if div == 6 else f"ib/ib_{a}_{b}_{k}_{div}.png" for k in range(1, div)]
    return names if all(os.path.exists(os.path.join(src, n)) for n in names) else []


def ib_files(src, a, b):
    """組 a>b の中割り（ib_<a>_<b>_<k>.png と分割数つきの ib_<a>_<b>_<k>_<div>.png）。名前の続きが数字のものだけ。"""
    pre = os.path.join(src, "ib", f"ib_{a}_{b}_")
    out = []
    for p in sorted(glob.glob(glob.escape(pre) + "*.png")):
        rest = p[len(pre):-4].split("_")
        if all(x.isdigit() for x in rest) and 1 <= len(rest) <= 2: out.append(os.path.relpath(p, src))
    return out


def copy(src, rel, dst):
    s = os.path.join(src, rel); d = os.path.join(dst, rel)
    if rel.endswith("/"):
        shutil.copytree(s, d.rstrip("/"), dirs_exist_ok=False)
    else:
        os.makedirs(os.path.dirname(d), exist_ok=True); shutil.copy2(s, d)


def settle_mtimes(root, pairs):
    """持ってきたファイルの日時を揃える。vm poses は chain の中割りが古いか（前の枚より古いか）を日時で決めるので、
    別の作業フォルダから来た姿勢の絵が新しいと、持ってきた中割りを描き直してしまう。姿勢の絵を同じ日時にし、
    中割りは k の順に1秒ずつ新しくする。"""
    t0 = time.time() - 3600
    for p in glob.glob(os.path.join(root, "poses", "pose_*.png")): os.utime(p, (t0, t0))
    for a, b in pairs:
        for rel in ib_files(root, a, b):
            k = int(os.path.basename(rel)[len(f"ib_{a}_{b}_"):-4].split("_")[0]); os.utime(os.path.join(root, rel), (t0 + k, t0 + k))


def merge_top(cfg, c):
    """台本に属さない上位の設定を重ねる（後が勝つ）。interp の durs と face は項目ごとに重ねる。"""
    for k, v in c.items():
        if k in SCRIPT_KEYS or k in SPECIAL or k.startswith("events_") or k.startswith("gaze_"): continue
        cfg[k] = v
    if isinstance(c.get("interp"), dict):
        it = dict(cfg.get("interp") or {}); durs = dict(it.get("durs") or {})
        for k, v in (c["interp"].get("durs") or {}).items():   # 向きだけ違う組は同じ組なので、逆向きの古い秒は消す
            x, _, y = k.partition(">"); durs.pop(f"{y}>{x}", None); durs[k] = v
        it.update(c["interp"]); it["durs"] = durs; cfg["interp"] = it
    elif "interp" in c: cfg["interp"] = c["interp"]
    if isinstance(c.get("face"), dict): cfg["face"] = {**(cfg.get("face") or {}), **c["face"]}
    if isinstance(c.get("anchor"), dict):          # 手で決めた立ち位置（manual の points・scales）は姿勢ごとの表なので、表ごと重ねる
        old = cfg.get("anchor") if isinstance(cfg.get("anchor"), dict) else {}; new = {**old, **c["anchor"]}
        for k in ("points", "scales"):
            if isinstance(old.get(k), dict) or isinstance(c["anchor"].get(k), dict): new[k] = {**(old.get(k) or {}), **(c["anchor"].get(k) or {})}
        cfg["anchor"] = new
    if isinstance(c.get("gaze"), dict): cfg["gaze"] = {k: v for k, v in c["gaze"].items() if k != "events"}   # 視線の予定は台本に属する
    elif "gaze" in c: cfg["gaze"] = c["gaze"]      # true / false はそのまま（後が勝つ）


def build(pack, sources, force=False):
    sources = [os.path.abspath(s) for s in sources]
    for s in sources:
        if not os.path.isdir(s): die(f"作業フォルダが無い: {s}")
    cfgs = [load(s) for s in sources]
    ms = {md5(os.path.join(s, "mascot.png")) for s in sources}
    if None in ms: die("mascot.png（元の絵）が無い作業フォルダがある")
    if len(ms) > 1: die("mascot.png（元の絵）が作業フォルダごとに違う。1つのパックには同じキャラだけをまとめる")
    pack = os.path.abspath(pack)
    for s in sources:
        if inside(pack, s) or inside(s, pack): die(f"パックは作業フォルダの外に作る: {pack}")
    if os.path.exists(pack) and not force: die(f"パックが既にある: {pack}（作り直すなら --force）")
    tmp = pack + f".tmp-{os.getpid()}"
    if os.path.exists(tmp): shutil.rmtree(tmp)
    os.makedirs(tmp)
    try:
        cfg = {}; owner = {}
        for s, c in zip(sources, cfgs):
            merge_top(cfg, c)
            for n in c.get("poses", {}):              # 絵の無い姿勢では、前の作業フォルダの絵を置き換えない
                if os.path.exists(os.path.join(s, f"poses/pose_{n}.png")) or n not in owner: owner[n] = s
        nopic = sorted(n for n, s in owner.items() if not os.path.exists(os.path.join(s, f"poses/pose_{n}.png")))
        if nopic: die(f"どの作業フォルダにも絵が無い姿勢: {nopic}（描いてからまとめるか、config.poses から外す）")
        an = cfg.get("anchor")
        if isinstance(an, dict):                       # 置き換えた姿勢に、前の作業フォルダの手で決めた立ち位置を残さない
            for n, s in owner.items():
                own = cfgs[sources.index(s)].get("anchor"); own = own if isinstance(own, dict) else {}
                for k in ("points", "scales"):            # 姿勢の持ち主の値に戻す（後の作業フォルダの値が、前の絵に付かないように）
                    if not isinstance(an.get(k), dict): continue
                    if n in (own.get(k) or {}): an[k][n] = own[k][n]
                    elif n in an[k]: del an[k][n]
        home = cfg.get("home", "home")
        if isinstance(cfg.get("face"), dict) and home in owner:   # 顔の範囲は home の絵の座標なので、home の絵の持ち主の値にする
            hf = cfgs[sources.index(owner[home])].get("face"); hf = hf if isinstance(hf, dict) else {}
            for k in ("mouth_roi", "eye_roi", "jaw_roi"):
                if k in hf: cfg["face"][k] = hf[k]
                else: cfg["face"].pop(k, None)
        cfg["poses"] = {}; hands = {}; mirrored = {}
        for n, s in owner.items():
            c = cfgs[sources.index(s)]
            cfg["poses"][n] = c["poses"][n]
            if n in (c.get("hands") or {}): hands[n] = c["hands"][n]
            if n in (c.get("mirrored") or {}): mirrored[n] = c["mirrored"][n]
            for rel in pose_files(s, n): copy(s, rel, tmp)
            for r in ((c.get("hands") or {}).get(n) or {}).get("refs", []):   # 手の部品の形の手本も持ってくる（無ければ止める）
                if not os.path.exists(os.path.join(s, r)): die(f"手の部品 {n} の手本が無い: {os.path.join(s, r)}")
                if not os.path.exists(os.path.join(tmp, r)): copy(s, r, tmp)
            if c["poses"][n].get("face", True) is not False and not os.path.exists(os.path.join(tmp, f"parts_{n}", "parts.json")):
                same = md5(os.path.join(s, f"poses/pose_{n}.png"))     # 部品を切っていなければ、同じ絵を持つ前の作業フォルダの部品を使う
                alt = next((x for x in reversed(sources) if x != s and md5(os.path.join(x, f"poses/pose_{n}.png")) == same
                            and os.path.exists(os.path.join(x, f"parts_{n}", "parts.json"))), None)
                if not alt: die(f"顔の見える姿勢 {n} の部品が無い（{s} で vm parts {n} を先に）")
                shutil.rmtree(os.path.join(tmp, f"parts_{n}"), ignore_errors=True); copy(alt, f"parts_{n}/", tmp)
        stale_hands = []
        for n, h in hands.items():                     # 手の部品は、描いたときの土台の絵とパックの土台の絵が同じときだけ、作り直しに使える
            b = h.get("base")
            if b in owner and md5(os.path.join(owner[n], f"poses/pose_{b}.png")) != md5(os.path.join(owner[b], f"poses/pose_{b}.png")):
                stale_hands.append(n)
        if stale_hands: print(f"  手の部品の土台の絵が、描いたときと違う: {stale_hands}（姿勢の絵はそのまま使える。vm hands place で作り直すなら、先に draw し直す）")
        if hands: cfg["hands"] = hands
        if mirrored:
            note = next((c["mirrored"]["note"] for c in reversed(cfgs) if "note" in (c.get("mirrored") or {})), None)
            cfg["mirrored"] = {**mirrored, **({"note": note} if note else {})}
        for n, h in hands.items():
            if h.get("base") not in cfg["poses"]: die(f"手の部品 {n} の土台 {h.get('base')} がパックに無い")
        shutil.copy2(os.path.join(sources[-1], "mascot.png"), os.path.join(tmp, "mascot.png"))
        pose_md5 = {n: md5(os.path.join(tmp, f"poses/pose_{n}.png")) for n in cfg["poses"]}
        div = int(cfg.get("inbetween_div", 6))
        pairs, ib_steps, pair_src, missing = [], {}, {}, []
        steps_of = lambda s: cfgs[sources.index(s)].get("ib_steps") or {}
        has = lambda s, a, b: [a, b] in [list(p) for p in cfgs[sources.index(s)].get("pairs", [])]
        seen = set()
        for c in cfgs:
            for a, b in c.get("pairs", []):
                if frozenset((a, b)) in seen: continue           # 向きだけ違う組は同じ組（書き出しは逆向きにも使う）
                seen.add(frozenset((a, b)))
                if a not in cfg["poses"] or b not in cfg["poses"]: continue
                got = None
                for s in reversed(sources):                       # 後の作業フォルダから、端の絵がパックと同じ中割りを探す（どちらの向きでも）
                    for x, y in ((a, b), (b, a)):
                        if not has(s, x, y): continue
                        fs = ib_full(s, x, y, div)
                        if fs and md5(os.path.join(s, f"poses/pose_{x}.png")) == pose_md5[x] and md5(os.path.join(s, f"poses/pose_{y}.png")) == pose_md5[y]:
                            got = (s, x, y); [copy(s, rel, tmp) for rel in fs]; break
                    if got: break
                if got: s, a, b = got
                else:                                             # 描き足す組は、最後に文を書いた作業フォルダの向きにそろえる
                    lst = next(((x, y) for s in reversed(sources) for x, y in ((a, b), (b, a)) if f"{x}>{y}" in steps_of(s)), None)
                    if lst: a, b = lst
                key = f"{a}>{b}"
                pairs.append([a, b])
                src = [got[0]] if got else list(reversed(sources))
                st = next((s for s in src if key in steps_of(s)), None)
                if st: ib_steps[key] = steps_of(st)[key]          # 中割りを持ってきた所の文。描き足す組は最後に書いた文
                pair_src[key] = got[0] if got else None
                if not got: missing.append(key)
        cfg["pairs"] = pairs
        an = cfg.get("anchor")
        if isinstance(an, dict) and an.get("mode") == "manual":   # manual では、どの姿勢にも手で決めた立ち位置が要る
            lack = sorted(n for n, pc in cfg["poses"].items() if n not in (an.get("points") or {}) and "anchor" not in pc)
            if lack: die(f"anchor.mode が manual なのに、立ち位置の無い姿勢がある: {lack}（作業フォルダの anchor をそろえてからまとめる）")
        settle_mtimes(tmp, pairs)
        if ib_steps: cfg["ib_steps"] = ib_steps
        for d in ("poses", "parts", "ib", "out", "voice"): os.makedirs(os.path.join(tmp, d), exist_ok=True)
        cfg["name"] = os.path.basename(pack)
        json.dump(cfg, open(os.path.join(tmp, "config.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        man = {"built": time.strftime("%Y-%m-%d %H:%M:%S"), "sources": sources,
               "poses": {n: s for n, s in owner.items()}, "pairs": pair_src, "missing_inbetweens": missing, "hands_base_changed": stale_hands}
        json.dump(man, open(os.path.join(tmp, "pack.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if os.path.exists(pack):                  # 古いパックは消さずに、重ならない名前で残す（同じ秒に2回作っても）
            old = unique(pack + ".old-" + time.strftime("%Y%m%d_%H%M%S")); os.rename(pack, old); print("古いパック:", old)
        os.rename(tmp, pack)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True); raise
    by = {}
    for n, s in owner.items(): by.setdefault(s, []).append(n)
    print("パック:", pack)
    for s in sources: print(f"  {s}: 姿勢 {len(by.get(s, []))} {sorted(by.get(s, []))}")
    print(f"  中割りの組 {len(pairs)}（持ってきた {len(pairs) - len(missing)}）")
    if missing: print(f"  中割りが要る組（端の絵が変わった・描いていない）: {missing}\n  → vm poses {pack} inbetweens で描き足す")
    return man


def unique(path):
    if not os.path.exists(path): return path
    n = 2
    while os.path.exists(f"{path}_{n}"): n += 1
    return f"{path}_{n}"


def inside(child, parent):
    child, parent = os.path.realpath(child), os.path.realpath(parent)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def new(pack, dst, name=None):
    pack = os.path.abspath(pack); dst = os.path.abspath(dst)
    if inside(dst, pack) or inside(pack, dst): die(f"作業フォルダはパックの外に作る: {dst}")
    if not os.path.exists(os.path.join(pack, "pack.json")): die(f"パックではない（pack.json が無い）: {pack}")
    if os.path.exists(dst): die(f"作業フォルダが既にある: {dst}")
    tmp = dst + f".tmp-{os.getpid()}"
    try:
        shutil.copytree(pack, tmp, ignore=shutil.ignore_patterns("pack.json", "ib_interp", "out", "voice", "reject"))
        for d in ("out", "voice"): os.makedirs(os.path.join(tmp, d), exist_ok=True)
        cf = os.path.join(tmp, "config.json"); c = json.load(open(cf, encoding="utf-8"))
        c["name"] = name or os.path.basename(dst); c["from_pack"] = pack
        json.dump(c, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.rename(tmp, dst)
    except BaseException:                          # 途中で落ちたら、半端な複製を残さない
        shutil.rmtree(tmp, ignore_errors=True); raise
    print("作業フォルダ:", dst, f"（{pack} から。台本・声・動きは空）")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack"); ap.add_argument("--from", dest="sources", action="append", default=[])
    ap.add_argument("--new"); ap.add_argument("--name"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if bool(a.sources) == bool(a.new): die("--from（まとめる）か --new（使う）のどちらか一方を指定する")
    if a.sources: build(a.pack, a.sources, a.force)
    else: new(a.pack, a.new, a.name)


if __name__ == "__main__":
    main()
