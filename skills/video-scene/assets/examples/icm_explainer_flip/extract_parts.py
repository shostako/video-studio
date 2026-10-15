"""差分の絵から「元と違う所」だけを切り抜いて部品にする。
  python extract_parts.py BASE.png OUTDIR [--roi=x0,y0,x1,y1] VAR1.png [VAR2.png ...]
--auto を付けると、渡した差分の過半数が変わる所（最大の塊）を範囲として自動で決める（口・目を別々に呼ぶ）。
--roi を付けると、その範囲の中の違いだけを取る（髪など範囲の外の違いは無視）。
各差分は元の絵に重ね直して（ECC）、色の差が大きい塊のうち顔のあたりのものを取り、縁をぼかした RGBA の部品にする。
出力: OUTDIR/<差分名>.png（部品）と OUTDIR/parts.json（{名前: [x, y]}、元の絵の上の左上の位置）"""
import json, math, os, sys
import cv2, numpy as np
base_p, od = sys.argv[1], sys.argv[2]; os.makedirs(od, exist_ok=True)
base = cv2.imread(base_p); H, W = base.shape[:2]
meta = json.load(open(os.path.join(od, "parts.json"))) if os.path.exists(os.path.join(od, "parts.json")) else {}
def align(var, roi=None):
    """変形版を元の絵に重ねる。roi があれば、その外側の周り（顔の輪郭・髪）だけを手がかりに合わせる（口・目そのものには合わせない）。"""
    var = cv2.resize(var, (W, H)) if var.shape[:2] != (H, W) else var
    g0 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(var, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = None
    if roi:
        mask = np.zeros((H, W), np.uint8); x0, y0, x1, y1 = roi; pd = 140
        mask[max(0, y0 - pd):y1 + pd, max(0, x0 - pd):x1 + pd] = 1; mask[y0:y1, x0:x1] = 0
    M = np.eye(2, 3, dtype=np.float32)
    try:
        _, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 400, 1e-6), mask, 5)
    except cv2.error:
        print("  位置合わせ失敗（そのまま使う）")
    return cv2.warpAffine(var, M, (W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
ROI = None; vars_ = []; AUTO = False
for a_ in sys.argv[3:]:
    if a_.startswith("--roi="): ROI = [int(v) for v in a_[6:].split(",")]
    elif a_ == "--auto": AUTO = True
    else: vars_.append(a_)
def diffmask(var):
    d = np.linalg.norm(var.astype(np.float32) - base.astype(np.float32), axis=2)
    m = (cv2.GaussianBlur(d, (0, 0), 2) > 22).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
if AUTO:
    ms = [diffmask(align(cv2.imread(v))) for v in vars_]
    cons = (sum(ms) >= max(2, int(math.ceil(len(ms) * 0.6)))).astype(np.uint8)
    cons = cv2.morphologyEx(cons, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n_, lab_, st_, cen_ = cv2.connectedComponentsWithStats(cons)
    cand_ = [i for i in range(1, n_) if cen_[i][1] < H * 0.6]
    if not cand_: print("自動の範囲が見つからない"); sys.exit(1)
    big = max(cand_, key=lambda i: st_[i, cv2.CC_STAT_AREA]); x_, y_, w_, h_ = st_[big, :4]
    ROI = [max(0, x_ - 10), max(0, y_ - 10), min(W, x_ + w_ + 10), min(H, y_ + h_ + 10)]
    print("自動の範囲", ROI)
for vp in vars_:
    name = os.path.splitext(os.path.basename(vp))[0]
    var = align(cv2.imread(vp), ROI)
    d = np.linalg.norm(var.astype(np.float32) - base.astype(np.float32), axis=2)
    m = (cv2.GaussianBlur(d, (0, 0), 2) > 22).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if ROI:
        r = np.zeros_like(m); r[ROI[1]:ROI[3], ROI[0]:ROI[2]] = 1; m = m * r
        if m.sum() == 0: print(name, "範囲内に差が無い"); continue
        mm = m; keep = [1]
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    # 顔のあたり（上半分）で一番大きい塊を中心に、近くの塊もまとめる
    if not ROI:
        cand = [i for i in range(1, n) if cen[i][1] < H * 0.55 and st[i, cv2.CC_STAT_AREA] > 80]
        if not cand: print(name, "差が見つからない"); continue
        main = max(cand, key=lambda i: st[i, cv2.CC_STAT_AREA]); cx, cy = cen[main]
        keep = [i for i in cand if abs(cen[i][0] - cx) < W * 0.12 and abs(cen[i][1] - cy) < H * 0.06]
        mm = np.isin(lab, keep).astype(np.uint8)
    ys, xs = np.where(mm > 0); pad = 14
    x0, x1 = max(0, xs.min() - pad), min(W, xs.max() + pad); y0, y1 = max(0, ys.min() - pad), min(H, ys.max() + pad)
    mm = cv2.dilate(mm, np.ones((11, 11), np.uint8))
    a = cv2.GaussianBlur(mm.astype(np.float32), (0, 0), 4)[y0:y1, x0:x1]
    a = np.clip(a * 1.6, 0, 1)
    patch = np.dstack([var[y0:y1, x0:x1], (a * 255).astype(np.uint8)])
    cv2.imwrite(os.path.join(od, f"{name}.png"), patch); meta[name] = [int(x0), int(y0)]
    print(name, "部品", (x1 - x0, y1 - y0), "位置", (x0, y0), "塊", len(keep))
json.dump(meta, open(os.path.join(od, "parts.json"), "w"), indent=1)
