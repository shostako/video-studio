"""姿勢の絵の揃い（大きさ・足元・立ち位置・背の高さ）を home と比べて表にする。向きの違う姿勢を描いたあとの確かめ用（docs/mascot-views-spec.md）。
  vm views <作業フォルダ> [姿勢 ...]
列: 絵の大きさ、軸足（向かって左の靴の底。anchor.mode が feet なら色に依らない足元の真ん中）、両足の真ん中、靴の底の高さのずれ、立ち位置の横のずれ、背の高さの比（home=1）、
    立ち位置を home に揃える anchor の候補（config の poses.<名前>.anchor にそのまま書ける）。
config の floor.clean が true なら、台座を消してから測る（vm render と同じ）。絵は読むだけで、何も書き換えない。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, defloor, boot_anchor, feet_center, centered_anchor, body_height, feet_anchor, fg_height, die


def measure(P, pose, y0=None):
    img = P.read_pose(pose); H = img.shape[0]; fl = P.cfg.get("floor", {"clean": True})
    if fl.get("clean", False): img, _ = defloor(img, int(fl.get("y0", round(H * 0.705))) if y0 is None else y0)
    if P.cfg.get("anchor", {}).get("mode", "boot") == "feet":                  # 色に依らない足元: 軸足がそのまま両足の真ん中
        b = c = feet_anchor(img); return {"size": (img.shape[1], img.shape[0]), "boot": b, "feet": c, "height": fg_height(img, b) if b else None}
    b = boot_anchor(img); c = feet_center(img)
    return {"size": (img.shape[1], img.shape[0]), "boot": b, "feet": c, "height": body_height(img, b) if b else None}


def table(P, poses):
    h = measure(P, P.home); rows = []
    for p in poses:
        m = h if p == P.home else measure(P, p); r = {"pose": p, "size": "x".join(map(str, m["size"])), "same_size": m["size"] == h["size"]}
        if m["boot"] and m["feet"] and h["boot"] and h["feet"]:
            r.update(boot=[round(float(v), 1) for v in m["boot"]], feet=[round(float(v), 1) for v in m["feet"]],
                     dy=round(float(m["boot"][1] - h["boot"][1]), 1), dx=round(float(m["feet"][0] - h["feet"][0]), 1),
                     height=round(float(m["height"] / h["height"]), 3), anchor=list(centered_anchor(m["boot"], m["feet"], h["boot"], h["feet"])))
        rows.append(r)
    return rows


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a: die("使い方: vm views <作業フォルダ> [姿勢 ...] [--json]")
    P = Proj(a[0]); rows = table(P, a[1:] or P.poses)
    if "--json" in sys.argv: print(json.dumps(rows, ensure_ascii=False, indent=1)); sys.exit(0)
    print("姿勢        大きさ      足元のずれ  立ち位置のずれ  背の比  anchor の候補")
    for r in rows:
        if "anchor" not in r: print(f"{r['pose']:<10}  {r['size']:<10}  （靴が見つからない。vm grid で読んで anchor を書く）"); continue
        warn = ("" if r["same_size"] else "  ※大きさが home と違う") + ("  ※背が±3%を超える" if abs(r["height"] - 1) > 0.03 else "")
        print(f"{r['pose']:<10}  {r['size']:<10}  {r['dy']:+7.1f}     {r['dx']:+8.1f}      {r['height']:.3f}  {r['anchor']}{warn}")
    print("足元のずれ・背の比は vm render が軸足の靴と背の高さで自動で揃える。立ち位置のずれが気になる姿勢は anchor の候補を config に書く")
