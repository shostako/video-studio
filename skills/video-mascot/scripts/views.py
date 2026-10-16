"""姿勢の絵の揃い（大きさ・足元・立ち位置・背の高さ）を home と比べて表にする。向きの違う姿勢を描いたあとの確かめ用（docs/mascot-views-spec.md）。
  vm views <作業フォルダ> [姿勢 ...]
列: 絵の大きさ、足元の高さのずれ、立ち位置（両足の真ん中）の横のずれ、背の高さの比（home=1）。どれも服の色に依らずに測る。
anchor.mode が boot（黒い靴）なら、靴で拾った軸足が足元の線に乗っているかを見て、外れた姿勢を知らせる（feet にするよう勧める）。
poses.<名前>.anchor を書いた姿勢は、vm render と同じくそれを軸足として扱う（外れとは言わない）。
乗っていれば、立ち位置を home に揃える anchor の候補（config の poses.<名前>.anchor にそのまま書ける）も出す。
config の floor.clean が true なら、台座を消してから測る（vm render と同じ）。絵は読むだけで、何も書き換えない。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, defloor, boot_anchor, centered_anchor, feet_anchor, fg_height, die


def measure(P, pose, y0=None):
    """足元・背は服の色に依らずに測る（背景の白と違う所の一番下・一番上）。anchor.mode が boot なら、靴で拾った軸足も測って、
    足元の線に乗っているか（boot_ok）を見る。紺のズボンの裾など、靴でない暗い所を拾うと外れる（新PCの実物で起きた）。"""
    img = P.read_pose(pose); H = img.shape[0]; fl = P.cfg.get("floor", {"clean": True})
    if fl.get("clean", False): img, _ = defloor(img, int(fl.get("y0", round(H * 0.705))) if y0 is None else y0)
    f = feet_anchor(img); r = {"size": (img.shape[1], img.shape[0]), "feet": f, "height": fg_height(img, f) if f else None, "boot": None, "boot_ok": None}
    if P.cfg.get("anchor", {}).get("mode", "boot") == "boot":
        own = P.cfg["poses"].get(pose, {}).get("anchor")
        if own is not None: r["boot"] = tuple(map(float, own)); r["boot_ok"] = True       # anchor を書いた姿勢は vm render もそれを使う（靴は測らない）
        else: b = boot_anchor(img); r["boot"] = b; r["boot_ok"] = bool(b and f and abs(b[1] - f[1]) <= 0.01 * H)
    return r


def table(P, poses):
    h = measure(P, P.home); rows = []; mode = P.cfg.get("anchor", {}).get("mode", "boot")
    for p in poses:
        m = h if p == P.home else measure(P, p); r = {"pose": p, "size": "x".join(map(str, m["size"])), "same_size": m["size"] == h["size"], "mode": mode}
        if m["feet"] and h["feet"]:
            r.update(feet=[round(float(v), 1) for v in m["feet"]], dy=round(float(m["feet"][1] - h["feet"][1]), 1),
                     dx=round(float(m["feet"][0] - h["feet"][0]), 1), height=round(float(m["height"] / h["height"]), 3))
            if mode == "boot":
                r["boot"] = [round(float(v), 1) for v in m["boot"]] if m["boot"] else None; r["boot_ok"] = m["boot_ok"]
                if m["boot_ok"] and h["boot_ok"]: r["anchor"] = list(centered_anchor(m["boot"], m["feet"], h["boot"], h["feet"]))
        rows.append(r)
    return rows


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a: die("使い方: vm views <作業フォルダ> [姿勢 ...] [--json]")
    P = Proj(a[0]); rows = table(P, a[1:] or P.poses)
    if "--json" in sys.argv: print(json.dumps(rows, ensure_ascii=False, indent=1)); sys.exit(0)
    mode = P.cfg.get("anchor", {}).get("mode", "boot")
    print(f"足元の揃え方: {mode}")
    print("姿勢        大きさ      足元のずれ  立ち位置のずれ  背の比  " + ("anchor の候補" if mode == "boot" else ""))
    off = []
    for r in rows:
        if "feet" not in r: print(f"{r['pose']:<10}  {r['size']:<10}  （足元が見つからない。vm grid で読んで anchor を書く）"); continue
        warn = ("" if r["same_size"] else "  ※大きさが home と違う") + ("  ※背が±3%を超える" if abs(r["height"] - 1) > 0.03 else "")
        if mode == "boot" and not r["boot_ok"]: warn += "  ※靴で拾った軸足が足元に無い（服の裾など）"; off.append(r["pose"])
        print(f"{r['pose']:<10}  {r['size']:<10}  {r['dy']:+7.1f}     {r['dx']:+8.1f}      {r['height']:.3f}  {r.get('anchor', '') if mode == 'boot' else ''}{warn}")
    print("足元・背は服の色に依らずに測った値（背景の白と違う所の一番下・一番上）")
    if off: print(f"靴の軸足が外れた姿勢: {', '.join(off)} → config の anchor を {{\"mode\": \"feet\"}} にする（色に依らない足元で揃う。anchor の候補は要らない）")
    elif mode == "boot": print("立ち位置のずれが気になる姿勢は anchor の候補を poses.<姿勢>.anchor に書く。feet なら両足の真ん中で揃うので要らない")
