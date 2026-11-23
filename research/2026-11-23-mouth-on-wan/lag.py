"""貼った口が顔に遅れないか: 各コマで、顔の合わせ（ECC）で写した口の置き場所と、鼻先（home の絵から切った型を
コマの中で探した位置）の差を出す。差の揺れ（最大−最小）が小さければ、口は顔と一緒に動いている。"""
import sys, glob, json, cv2, numpy as np
sys.path.insert(0, ".")
P = sys.argv[1]; XS = sys.argv[2:]
home = cv2.imread(f"{P}/poses/pose_home.png")
pj = json.load(open(f"{P}/parts_home/parts.json")); m1 = cv2.imread(f"{P}/parts_home/m1.png", -1)
mx, my = pj["m1"][0] + m1.shape[1] / 2, pj["m1"][1] + m1.shape[0] / 2
# 鼻先: 口の中心の少し上
nx, ny = int(mx), int(my - 55); T = 18
tpl = cv2.cvtColor(home[ny - T:ny + T, nx - T:nx + T], cv2.COLOR_BGR2GRAY)
roi = (int(mx) - 150, int(my) - 200, int(mx) + 150, int(my) + 120)
def ecc(dst):
    x0, y0, x1, y1 = roi
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(home, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = np.zeros(g0.shape, np.uint8); m[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32)
    try: _, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), m, 5)
    except cv2.error: pass
    return cv2.invertAffineTransform(M)
def lips(fr, c):
    """コマの中の唇（赤みの強い所）の重心。c の周り 70x50 で、a* の上位 15 % の画素。"""
    x0, y0 = int(c[0]) - 35, int(c[1]) - 25
    a = cv2.cvtColor(fr[y0:y0 + 50, x0:x0 + 70], cv2.COLOR_BGR2LAB)[:, :, 1].astype(np.float32)
    m = a >= np.percentile(a, 85); yy, xx = np.where(m)
    return (x0 + xx.mean(), y0 + yy.mean()), float(a[m].mean())
base = lips(home, (mx, my))[0]; print("home の唇の重心と口の部品の中心の差", round(base[0] - mx, 1), round(base[1] - my, 1))
for X in XS:
    rows = []
    for d in (f"home__{X}", f"{X}__home"):
        fs = sorted(glob.glob(f"{P}/ib_wan/{d}/n47/f*.webp"), key=lambda s: int(s.split("/f")[-1][:-5]))
        for f in fs:
            fr = cv2.imread(f); A = ecc(fr)
            pm = A @ np.array([mx, my, 1]); pn_pred = A @ np.array([nx, ny, 1])
            pn, sc = lips(fr, pm)
            rows.append((pm[0] - pn[0], pm[1] - pn[1], sc, pm[0], pm[1]))
    a = np.array(rows)
    print(f"{X:8s} 口の移動 x {np.ptp(a[:,3]):5.1f} y {np.ptp(a[:,4]):5.1f} px | 口−唇 x {np.ptp(a[:,0]):4.1f} y {np.ptp(a[:,1]):4.1f} px（揺れ幅）| コマ間の跳び最大 {np.abs(np.diff(a[:,:2],axis=0)).max():.1f} px | 唇の a* min {a[:,2].min():.0f}")
