"""flipbook.py — /img で作った差分を元の絵に揃え、状態ごとの絵（PNG）を書き出す。

使い方:
  vs flipbook spec.json --outdir states/

spec.json:
  {
    "base": "start.png",                                  # 元の絵（すべての差分の基準）
    "layers": [                                           # 部分だけ差し替える差分（重ねて組み合わせられる）
      {"name": "hand", "box": [0, 430, 1536, 640],        #   差し替える範囲（元の絵の座標、x0,y0,x1,y1）
       "variants": {"N": "hand_near_up.png", "F": "hand_far_up.png"}},
      {"name": "head", "box": [0, 0, 1536, 430], "variants": {"K": "blink.png", "S": "smirk.png"}}
    ],
    "full": {"shock": "shock.png", "panic": "panic.png"},  # 絵ごと差し替える差分
    "states": "auto"                                      # auto = 部分差分の全組み合わせ＋full 全部
  }
  - 状態の名前: 部分差分は "<層>-<記号>" を _ でつなぐ（例 hand-N_head-S）。元のままの層は B
    （例 hand-B_head-B が元の絵）。full はその名前のまま（例 shock）
  - 差分は SIFT で元の絵に位置合わせしてから使う（/img の編集は指定外がほぼ1px以内で一致する）
  - 部分差分は「元の絵との差がある所」だけを box 内で切り抜き、境目をぼかして重ねる
"""
import argparse, itertools, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import die


def main():
    import cv2, numpy as np
    ap = argparse.ArgumentParser(); ap.add_argument("spec"); ap.add_argument("--outdir", required=True)
    ap.add_argument("--diff-threshold", type=float, default=25); ap.add_argument("--grow", type=int, default=25); ap.add_argument("--feather", type=float, default=8)
    a = ap.parse_args()
    root = os.path.dirname(os.path.abspath(a.spec)); P = lambda p: p if os.path.isabs(p) else os.path.join(root, p)
    spec = json.load(open(a.spec, encoding="utf-8")); os.makedirs(a.outdir, exist_ok=True)
    base = cv2.imread(P(spec["base"]))
    if base is None: die(f"元の絵を読めない: {spec['base']}", 2)
    sift = cv2.SIFT_create(8000); bf = cv2.BFMatcher()
    kb, db = sift.detectAndCompute(cv2.cvtColor(base, cv2.COLOR_BGR2GRAY), None)
    report = {}

    def align(path):
        im = cv2.imread(P(path))
        if im is None: die(f"差分を読めない: {path}", 2)
        kv, dv = sift.detectAndCompute(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), None)
        m = [x for x, y in bf.knnMatch(dv, db, k=2) if x.distance < 0.75 * y.distance]
        if len(m) < 30: die(f"位置合わせの手がかりが少なすぎる（{len(m)}点）: {path}。構図ごと描き直された可能性", 2)
        M, inl = cv2.estimateAffinePartial2D(np.float32([kv[x.queryIdx].pt for x in m]), np.float32([kb[x.trainIdx].pt for x in m]),
                                             method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=5000)
        s = float(np.hypot(M[0, 0], M[1, 0]))
        report[path] = {"scale": round(s, 4), "tx": round(float(M[0, 2]), 1), "ty": round(float(M[1, 2]), 1), "inliers": int(inl.sum())}
        return cv2.warpAffine(im, M, (base.shape[1], base.shape[0]), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)

    B = base.astype(np.float32)
    layers = []
    for L in spec.get("layers", []):
        x0, y0, x1, y1 = L["box"]; vs = {}
        for key, path in L["variants"].items():
            V = align(path)
            d = np.abs(V - B).max(axis=2); m = (cv2.GaussianBlur(d, (9, 9), 0) > a.diff_threshold).astype(np.uint8)
            box = np.zeros_like(m); box[y0:y1, x0:x1] = 1; m &= box
            m = cv2.dilate(m, np.ones((a.grow, a.grow), np.uint8))
            vs[key] = (V, cv2.GaussianBlur(m.astype(np.float32), (0, 0), a.feather)[..., None])
        layers.append((L["name"], vs))
    names = []
    combos = itertools.product(*[["B"] + list(vs) for _, vs in layers]) if layers else [()]
    for combo in combos:
        f = B.copy()
        for (lname, vs), key in zip(layers, combo):
            if key != "B": V, al = vs[key]; f = f * (1 - al) + V * al
        n = "_".join(f"{lname}-{key}" for (lname, _), key in zip(layers, combo)) or "base"
        cv2.imwrite(os.path.join(a.outdir, n + ".png"), np.clip(f, 0, 255).astype(np.uint8)); names.append(n)
    for n, path in spec.get("full", {}).items():
        cv2.imwrite(os.path.join(a.outdir, n + ".png"), np.clip(align(path), 0, 255).astype(np.uint8)); names.append(n)
    manifest = {"size": [base.shape[1], base.shape[0]], "states": names, "align": report}
    json.dump(manifest, open(os.path.join(a.outdir, "manifest.json"), "w"), ensure_ascii=False, indent=1)
    for p, r in report.items():
        flag = "" if abs(r["scale"] - 1) < 0.01 and abs(r["tx"]) < 3 and abs(r["ty"]) < 3 else "  ← ずれが大きい。差分を作り直すか確かめる"
        print(f"align {os.path.basename(p)}: scale {r['scale']} shift ({r['tx']},{r['ty']}) inliers {r['inliers']}{flag}")
    print(f"{len(names)} states -> {a.outdir}")


if __name__ == "__main__":
    main()
