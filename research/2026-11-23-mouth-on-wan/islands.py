"""口の部品の「離れ小島」（口から離れた髪・首の縁の切れ端）が、Wan のコマの上でどれだけ浮くか。
各コマで部品を顔の合わせで写し、小島の中で「部品の色 − コマの色」の ΔE を出す。口の本体（最大の島）と並べる。"""
import sys, os, glob, json, cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../skills/video-mascot/scripts'))
from lib import occlude, occlude_diff
OCC = '--occlude' in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]; P = args[0]; XS = args[1:]
home = cv2.imread(f"{P}/poses/pose_home.png"); pj = json.load(open(f"{P}/parts_home/parts.json"))
parts = {k: cv2.imread(f"{P}/parts_home/{k}.png", -1) for k in pj if k.startswith("m")}
m1 = parts["m1"]; mx, my = pj["m1"][0] + m1.shape[1] // 2, pj["m1"][1] + m1.shape[0] // 2
roi = (mx - 150, my - 200, mx + 150, my + 120)
def ecc(dst):
    x0, y0, x1, y1 = roi; g0 = cv2.cvtColor(dst, 6).astype(np.float32); g1 = cv2.cvtColor(home, 6).astype(np.float32)
    m = np.zeros(g0.shape, np.uint8); m[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32)
    _, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (3, 300, 1e-6), m, 5); return cv2.invertAffineTransform(M)
lab = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
for X in XS:
    res = {k: ([], []) for k in parts}
    fs = sorted(glob.glob(f"{P}/ib_wan/home__{X}/n47/f*.webp"), key=lambda s: int(s.split("/f")[-1][:-5]))[:24]   # home 側の半分（home の部品を使う所）
    for f in fs[::2]:
        fr = cv2.imread(f); A = ecc(fr); H, W = fr.shape[:2]
        if OCC: ref = cv2.warpAffine(home, A, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE); pre = occlude_diff(fr, ref)
        for k, im in parts.items():
            T = A.copy(); T[:, 2] += A[:, 0] * pj[k][0] + A[:, 1] * pj[k][1]
            full = cv2.warpAffine(im, T, (W, H), borderValue=(0, 0, 0, 0))
            if OCC: full = occlude(full, fr, ref, pre=pre, grow=7)
            a = full[:, :, 3] > 128
            n, lb, st, _ = cv2.connectedComponentsWithStats(a.astype(np.uint8), 8)
            if n < 2: continue
            big = 1 + int(np.argmax(st[1:, 4])); de = np.linalg.norm(lab(np.ascontiguousarray(full[:, :, :3])) - lab(fr), axis=2)
            # 本体は唇の形が違うので縁（外側 6px の帯）だけ、小島は全体
            main = lb == big; ring = main & ~cv2.erode(main.astype(np.uint8), np.ones((13, 13), np.uint8)).astype(bool)
            isl = (lb > 0) & (lb != big)
            res[k][0].append(de[ring].mean())
            if isl.any(): res[k][1].append(np.percentile(de[isl], 90))
    print(X, "  ".join(f"{k}: 縁 {np.mean(v[0]):.1f} 小島90% {np.max(v[1]) if v[1] else 0:.1f}" for k, v in sorted(res.items())))
