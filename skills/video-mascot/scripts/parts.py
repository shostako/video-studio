"""描いた口・目の差分から「元と違う所」だけを切り抜いて部品にする。
  vm parts <作業フォルダ> [姿勢 ...]            未指定なら全姿勢。parts_<姿勢>/ に m1..m7, e1, e2 と parts.json を作る
  vm parts <作業フォルダ> --check [姿勢 ...]    貼った結果を並べた確認の絵を parts_check/<姿勢>.png に書く
  vm parts <作業フォルダ> --borrow <元の姿勢> 姿勢 ...
                                              差分を描かずに、元の姿勢の部品を顔を重ね合わせて写す（同じ顔の正面の身振り向け。opt-in）。
                                              顔の合いが --min-cc（既定 0.95）に届かない姿勢には書かない。写した姿勢は parts_<姿勢>/borrowed.json を持ち、
                                              vm parts はその姿勢を切り直さず、vm poses parts はその姿勢の差分を描かない（描くなら borrowed.json を消す）
口と目の範囲は config.json の face.mouth_roi / face.eye_roi（基本の姿勢 home の絵で測った座標）。
他の姿勢へは、顔の周りを重ね合わせた変換でその範囲を写す（髪の差分を拾わないため）。"""
import json, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, MOUTHS, EYES, GAZES, die, occlude


def face_box(P):
    f = P.cfg["face"]; xs = [f["mouth_roi"][0], f["mouth_roi"][2], f["eye_roi"][0], f["eye_roi"][2]]; ys = [f["mouth_roi"][1], f["mouth_roi"][3], f["eye_roi"][1], f["eye_roi"][3]]
    return min(xs), min(ys), max(xs), max(ys)


def map_rois(P, pose, pad=8, mouth_key="mouth_roi"):
    """home で測った口・目の範囲を、顔を重ね合わせて pose に写す。
    poses.<姿勢>.face に範囲が書いてあれば（斜め・横の顔）、写さずにそれを使う（顔の合いは 1.0 とする）。"""
    own = P.cfg["poses"].get(pose, {}).get("face")
    if isinstance(own, dict):
        if mouth_key not in own and mouth_key in P.cfg.get("face", {}):   # 向きの違う姿勢は顔の範囲を手で書くので、jaw_roi も姿勢ごとに書く
            print(f"  {pose}: poses.{pose}.face に {mouth_key} が無い。口の範囲（mouth_roi）で切るので、あごの線の変化は切り落とされる。"
                  f"向きの違う姿勢は poses.{pose}.face.{mouth_key} を書く", file=sys.stderr)
        return [max(0, v) for v in own.get(mouth_key, own["mouth_roi"])], [max(0, v) for v in own["eye_roi"]], 1.0
    f = P.cfg["face"]; home = P.read_pose(P.home); mk = f.get(mouth_key, f["mouth_roi"])
    if pose == P.home: return [max(0, v) for v in mk], [max(0, v) for v in f["eye_roi"]], 1.0
    dst = P.read_pose(pose); x0, y0, x1, y1 = face_box(P); H, W = dst.shape[:2]
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(home, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = np.zeros(g0.shape, np.uint8); mask[max(0, y0 - 170):y1 + 170, max(0, x0 - 170):x1 + 170] = 1; M = np.eye(2, 3, dtype=np.float32)
    cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 400, 1e-6), mask, 5)
    A = cv2.invertAffineTransform(M)
    def box(b):
        pts = np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], np.float32); q = pts @ A[:, :2].T + A[:, 2]
        return [int(max(0, q[:, 0].min() - pad)), int(max(0, q[:, 1].min() - pad)), int(min(W, q[:, 0].max() + pad)), int(min(H, q[:, 1].max() + pad))]
    return box(mk), box(f["eye_roi"]), float(cc)


def align(base, var, roi):
    """変形版を元の絵に重ねる。roi の外側の周り（顔の輪郭・髪）だけを手がかりに合わせる（口・目そのものには合わせない）。"""
    H, W = base.shape[:2]; var = cv2.resize(var, (W, H)) if var.shape[:2] != (H, W) else var
    g0 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(var, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = np.zeros((H, W), np.uint8); x0, y0, x1, y1 = roi; pd = 140
    mask[max(0, y0 - pd):y1 + pd, max(0, x0 - pd):x1 + pd] = 1; mask[y0:y1, x0:x1] = 0
    M = np.eye(2, 3, dtype=np.float32)
    try: _, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 400, 1e-6), mask, 5)
    except cv2.error: print("  位置合わせ失敗（そのまま使う）")
    return cv2.warpAffine(var, M, (W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def cut(base, var_path, roi):
    """差分の絵から、roi の中で元と違う所を縁をぼかした RGBA の部品にする。戻り値 (RGBA, x, y) か None。"""
    H, W = base.shape[:2]; var = align(base, cv2.imread(var_path), roi)
    d = np.linalg.norm(var.astype(np.float32) - base.astype(np.float32), axis=2)
    m = (cv2.GaussianBlur(d, (0, 0), 2) > 22).astype(np.uint8); m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    r = np.zeros_like(m); r[roi[1]:roi[3], roi[0]:roi[2]] = 1; mm = m * r
    if mm.sum() == 0: return None
    ys, xs = np.where(mm > 0); pad = 14
    x0, x1 = max(0, xs.min() - pad), min(W, xs.max() + pad); y0, y1 = max(0, ys.min() - pad), min(H, ys.max() + pad)
    mm = cv2.dilate(mm, np.ones((11, 11), np.uint8))
    a = np.clip(cv2.GaussianBlur(mm.astype(np.float32), (0, 0), 4)[y0:y1, x0:x1] * 1.6, 0, 1)
    return np.dstack([var[y0:y1, x0:x1], (a * 255).astype(np.uint8)]), int(x0), int(y0)


BORROWED = "borrowed.json"


def borrowed(P, pose):
    """--borrow で写した姿勢なら、その記録（{"from": 元の姿勢, "cc": 顔の合い}）。写していなければ None。"""
    f = P.p(f"parts_{pose}", BORROWED)
    return json.load(open(f)) if os.path.exists(f) else None


def drop_borrowed(P, pose):
    """前に --borrow で写した部品と印（parts_<姿勢>/ の絵・parts.json・borrowed.json）を消す。写していなければ何もしない。"""
    od = P.p(f"parts_{pose}")
    if not os.path.exists(os.path.join(od, BORROWED)): return False
    for f in os.listdir(od):
        if f.endswith(".png") or f in ("parts.json", BORROWED): os.remove(os.path.join(od, f))
    print(f"  {pose}: 前に写した部品を消した"); return True


def has_diffs(P, pose):
    return any(os.path.exists(P.p("parts", f"{pose}_{k}.png")) for k in MOUTHS + EYES + GAZES)


def borrow(P, src, pose, min_cc=0.95):
    """src の部品を、顔の周りを重ね合わせた変換で pose へ写す（差分を描かない）。書いたら True。"""
    if pose == src: print(f"{pose}: 元の姿勢と同じ。飛ばす"); return False
    if P.cfg["poses"].get(pose, {}).get("face", True) is False: print(f"{pose}: 顔なし（face: false）。部品は作らない"); return False
    if has_diffs(P, pose):
        print(f"{pose}: 描いた差分（parts/{pose}_*.png）があるので写さない。vm parts で切る"); drop_borrowed(P, pose); return False
    sm = P.p(f"parts_{src}", "parts.json")
    if not os.path.exists(sm): die(f"元の姿勢の部品が無い: parts_{src}（先に vm parts {src}）")
    parts = {k: (cv2.imread(P.p(f"parts_{src}", f"{k}.png"), cv2.IMREAD_UNCHANGED), px, py) for k, (px, py) in json.load(open(sm)).items()}
    if not parts: die(f"元の姿勢の部品が空: parts_{src}")
    base, dst = P.read_pose(src), P.read_pose(pose); H, W = dst.shape[:2]
    xs = [px for _, px, _ in parts.values()] + [px + im.shape[1] for im, px, _ in parts.values()]
    ys = [py for _, _, py in parts.values()] + [py + im.shape[0] for im, _, py in parts.values()]
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = np.zeros(g0.shape, np.uint8); mask[max(0, min(ys) - 100):max(ys) + 60, max(0, min(xs) - 80):max(xs) + 80] = 1   # 部品の周り（render の中割りと同じ範囲）
    M = np.eye(2, 3, dtype=np.float32); cc = -1.0
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), mask, 5)
    except cv2.error: pass
    if cc < min_cc:                             # 前に写した部品が残ると、描き直した絵に古い部品が乗ったままになるので消す
        print(f"{pose}: 顔の合い {cc:.3f} が {min_cc} に届かない。写さない（差分を描く）"); drop_borrowed(P, pose); return False
    A = cv2.invertAffineTransform(M); od = P.p(f"parts_{pose}"); os.makedirs(od, exist_ok=True); meta = {}
    ref = cv2.warpAffine(base, A, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)   # 元の姿勢の絵を写す先の顔に合わせたもの
    for k, (im, px, py) in parts.items():
        T = A.copy(); T[:, 2] += A[:, 0] * px + A[:, 1] * py
        full = cv2.warpAffine(im, T, (W, H), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
        full = occlude(full, dst, ref)          # 顔の前の手（元の絵と大きく違う所）には貼らない
        yy, xx = np.where(full[:, :, 3] > 0)
        if not len(xx): continue
        cv2.imwrite(os.path.join(od, f"{k}.png"), full[yy.min():yy.max() + 1, xx.min():xx.max() + 1]); meta[k] = [int(xx.min()), int(yy.min())]
    for f in os.listdir(od):                    # 前に切った部品の残りを消す（parts.json に無い絵は使われないが、紛らわしいので）
        if f.endswith(".png") and f[:-4] not in meta: os.remove(os.path.join(od, f))
    json.dump(meta, open(os.path.join(od, "parts.json"), "w"), indent=1)
    json.dump({"from": src, "cc": round(float(cc), 4)}, open(os.path.join(od, BORROWED), "w"))
    print(f"{pose}: {src} の部品を写した {sorted(meta)}  顔の合い {cc:.3f}  ずれ {np.round(A[:, 2], 1).tolist()}")
    return True


def extract(P, pose):
    if P.cfg["poses"].get(pose, {}).get("face", True) is False: print(f"{pose}: 顔なし（face: false）。部品は作らない"); return {}
    b = borrowed(P, pose)
    if b and has_diffs(P, pose):                # 写したあとに差分を描いたなら、描いた方で切る
        print(f"{pose}: {b['from']} から写した部品があるが、描いた差分があるので切り直す"); drop_borrowed(P, pose); b = None
    if b: print(f"{pose}: {b['from']} から写した部品。切り直さない（描いた差分で作るなら parts_{pose}/{BORROWED} を消す）"); return json.load(open(P.p(f"parts_{pose}", "parts.json")))
    mouth_roi, eye_roi, cc = map_rois(P, pose, mouth_key="jaw_roi")   # 口の部品は jaw_roi があればそこで切る（首の位置などは mouth_roi のまま）
    base = P.read_pose(pose); od = P.p(f"parts_{pose}"); os.makedirs(od, exist_ok=True); meta = {}
    for names, roi in ((MOUTHS, mouth_roi), (EYES + GAZES, eye_roi)):
        for k in names:
            vp = P.p("parts", f"{pose}_{k}.png")
            if not os.path.exists(vp): continue
            r = cut(base, vp, roi)
            if r is None: print(f"  {pose}_{k}: 範囲の中に差が無い"); continue
            cv2.imwrite(os.path.join(od, f"{k}.png"), r[0]); meta[k] = [r[1], r[2]]
    json.dump(meta, open(os.path.join(od, "parts.json"), "w"), indent=1)
    print(f"{pose}: 部品 {sorted(meta)}  口の範囲 {mouth_roi} 目の範囲 {eye_roi}  顔の合い {cc:.3f}")
    return meta


def check(P, pose):
    if P.cfg["poses"].get(pose, {}).get("face", True) is False: return
    base = P.read_pose(pose); meta = json.load(open(P.p(f"parts_{pose}", "parts.json"))); mouth_roi, eye_roi, _ = map_rois(P, pose)
    cx = (mouth_roi[0] + mouth_roi[2]) // 2; cy = (eye_roi[1] + mouth_roi[3]) // 2; hh, hw = 150, 190; tiles = []
    def crop(img):
        y0 = max(0, cy - hh); x0 = max(0, cx - hw); t = img[y0:y0 + 2 * hh, x0:x0 + 2 * hw].copy()
        return cv2.resize(t, (2 * hw, 2 * hh)) if t.shape[:2] != (2 * hh, 2 * hw) else t
    for k in MOUTHS + EYES + GAZES:
        if k not in meta: continue
        im = cv2.imread(P.p(f"parts_{pose}", f"{k}.png"), cv2.IMREAD_UNCHANGED); x, y = meta[k]; h, w = im.shape[:2]
        out = base.copy(); a = im[:, :, 3:4] / 255.0; out[y:y + h, x:x + w] = (out[y:y + h, x:x + w] * (1 - a) + im[:, :, :3] * a).astype(np.uint8)
        t = crop(out); cv2.putText(t, f"{pose} {k}", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2); tiles.append(t)
    b = crop(base); cv2.putText(b, f"{pose} base", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
    cols = 5; rows = []; items = [b] + tiles
    while len(items) % cols: items.append(np.full_like(b, 255))
    for i in range(0, len(items), cols): rows.append(np.hstack(items[i:i + cols]))
    os.makedirs(P.p("parts_check"), exist_ok=True); out = P.p("parts_check", f"{pose}.png"); cv2.imwrite(out, np.vstack(rows)); print("確認の絵:", out)


if __name__ == "__main__":
    argv = sys.argv[1:]; min_cc = 0.95
    if "--min-cc" in argv:
        i = argv.index("--min-cc")
        if i + 1 >= len(argv): die("--min-cc の後に数が無い")
        min_cc = float(argv[i + 1]); del argv[i:i + 2]
    src = None
    if "--borrow" in argv:
        i = argv.index("--borrow")
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"): die("--borrow の後に元の姿勢が無い")
        src = argv[i + 1]; del argv[i:i + 2]
    a = [x for x in argv if not x.startswith("--")]
    if not a: die("使い方: vm parts <作業フォルダ> [--check] [姿勢 ...] / vm parts <作業フォルダ> --borrow <元の姿勢> 姿勢 ...")
    P = Proj(a[0])
    if src is not None:
        if src not in P.cfg["poses"]: die(f"元の姿勢が config に無い: {src}")
        if not a[1:]: die("--borrow は写す先の姿勢を名指しする（全姿勢へは写さない）")
        bad = [p for p in a[1:] if p not in P.cfg["poses"]]
        if bad: die(f"config に無い姿勢: {bad}")
        n = sum(borrow(P, src, p, min_cc) for p in a[1:]); print(f"写した {n} / {len(a) - 1}")
        sys.exit(0 if n == len(a) - 1 else 3)
    poses = a[1:] or P.poses
    for p in poses:
        if "--check" in sys.argv: check(P, p)
        else: extract(P, p)
