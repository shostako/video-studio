"""Wan の切り替えの列で、顔（口の周り）がどれだけ動くかを測る。home の絵から各コマへ ECC で合わせる。"""
import sys, glob, json, cv2, numpy as np
P = sys.argv[1]
home = cv2.imread(f"{P}/poses/pose_home.png")
pj = json.load(open(f"{P}/parts_home/parts.json"))
def roi_of():
    xs, ys = [], []
    for k, (x, y) in pj.items():
        im = cv2.imread(f"{P}/parts_home/{k}.png", -1); xs += [x, x + im.shape[1]]; ys += [y, y + im.shape[0]]
    return max(0, min(xs) - 80), max(0, min(ys) - 100), max(xs) + 80, max(ys) + 60
ROI = roi_of()
def affine(dst):
    x0, y0, x1, y1 = ROI
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(home, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = np.zeros(g0.shape, np.uint8); m[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), m, 5)
    except cv2.error: pass
    return cv2.invertAffineTransform(M), cc
for d in sys.argv[2:]:
    fs = sorted(glob.glob(f"{P}/ib_wan/{d}/n47/f*.webp"), key=lambda s: int(s.split("/f")[-1][:-5]))
    tx, ty, ccs = [], [], []
    for f in fs[::4]:
        A, cc = affine(cv2.imread(f)); tx.append(A[0, 2]); ty.append(A[1, 2]); ccs.append(cc)
    print(f"{d:22s} n={len(fs)} dx {min(tx):6.1f}..{max(tx):6.1f}  dy {min(ty):6.1f}..{max(ty):6.1f}  cc min {min(ccs):.3f}")
