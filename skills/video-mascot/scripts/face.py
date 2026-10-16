"""口と目の範囲（face の mouth_roi / eye_roi）を、描いた口・目の差分から測る。vm grid で目で読む代わり（キャラに依らない）。
  vm face <作業フォルダ> [姿勢 ...] [--write]
姿勢の絵と parts/<姿勢>_m1..m7（口）・_e1 _e2（目）を重ねて、変わった所を囲む。差分が無い姿勢は飛ばす。
--write: home の範囲を config.face に、顔が正面でない姿勢（head_yaw が 15 度以上）の範囲を poses.<姿勢>.face に書く
（正面の姿勢は vm parts が home から自動で写すので書かない）。書く前の config.json は config.json.bak に残す。
測った範囲は vm parts --check の絵で確かめる（口の差分が髪や服まで変えていると、範囲が広がる）。"""
import json, os, shutil, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, MOUTHS, EYES, pose_view, die


def diff_boxes(base, var, thr=30, min_area=12):
    """var を base に平行移動で重ねてから、違う所の塊の箱 [(面積, x0, y0, x1, y1), ...]（大きい順）。"""
    H, W = base.shape[:2]
    if var.shape[:2] != (H, W): var = cv2.resize(var, (W, H))
    g0 = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(var, cv2.COLOR_BGR2GRAY).astype(np.float32)
    M = np.eye(2, 3, dtype=np.float32)
    try: _, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_TRANSLATION, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5), None, 5)
    except cv2.error: pass
    var = cv2.warpAffine(var, M, (W, H), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    d = np.linalg.norm(var.astype(np.float32) - base.astype(np.float32), axis=2)
    m = (cv2.GaussianBlur(d, (0, 0), 1.5) > thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)); m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = [(int(st[i, 4]), int(st[i, 0]), int(st[i, 1]), int(st[i, 0] + st[i, 2]), int(st[i, 1] + st[i, 3])) for i in range(1, n) if st[i, 4] >= min_area]
    return sorted(out, reverse=True)


def pick(boxes, n_keep):
    """一番大きい塊と、その 25% 以上の大きさの塊を n_keep 個まで（目は両目で2つ）。"""
    if not boxes: return None
    big = [b for b in boxes if b[0] >= 0.25 * boxes[0][0]][:n_keep]
    return [min(b[1] for b in big), min(b[2] for b in big), max(b[3] for b in big), max(b[4] for b in big)]


def merge(found, margin=0.15, minpad=6):
    """差分ごとの箱から、真ん中が大きく外れたもの（髪・服の変化を拾った箱）を除いて、合わせた箱に少し余白を足す。"""
    if not found: return None
    cx = np.median([(b[0] + b[2]) / 2 for b in found]); cy = np.median([(b[1] + b[3]) / 2 for b in found])
    w = np.median([b[2] - b[0] for b in found]); h = np.median([b[3] - b[1] for b in found])
    ok = [b for b in found if abs((b[0] + b[2]) / 2 - cx) <= max(w, 8) and abs((b[1] + b[3]) / 2 - cy) <= max(h, 8)] or found
    x0, y0, x1, y1 = min(b[0] for b in ok), min(b[1] for b in ok), max(b[2] for b in ok), max(b[3] for b in ok)
    px = max(minpad, int(round((x1 - x0) * margin))); py = max(minpad, int(round((y1 - y0) * margin)))
    return [x0 - px, y0 - py, x1 + px, y1 + py], len(ok), len(found)


def measure(P, pose):
    base = P.read_pose(pose); H, W = base.shape[:2]; res = {}
    for key, names, keep in (("mouth_roi", MOUTHS, 1), ("eye_roi", EYES, 2)):
        found = []
        for k in names:
            vp = P.p("parts", f"{pose}_{k}.png"); var = cv2.imread(vp) if os.path.exists(vp) else None
            if var is None: continue
            b = pick(diff_boxes(base, var), keep)
            if b: found.append(b)
        m = merge(found)
        if m: r, used, total = m; res[key] = [max(0, r[0]), max(0, r[1]), min(W, r[2]), min(H, r[3])]; res[key + "_n"] = f"{used}/{total}"
    return res


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not a: die("使い方: vm face <作業フォルダ> [姿勢 ...] [--write]")
    P = Proj(a[0]); poses = a[1:] or [p for p in P.poses if P.cfg["poses"][p].get("face", True) is not False]
    cfg = P.cfg; wrote = []
    for p in poses:
        r = measure(P, p)
        if "mouth_roi" not in r or "eye_roi" not in r:
            print(f"{p:<10}  差分が足りない（parts/{p}_m*.png と _e*.png を先に vm poses parts で）"); continue
        warn = "  ※目が口より下にある（差分を見直す）" if r["eye_roi"][3] > r["mouth_roi"][3] else ""
        print(f"{p:<10}  mouth_roi {r['mouth_roi']}（{r['mouth_roi_n']}）  eye_roi {r['eye_roi']}（{r['eye_roi_n']}）{warn}")
        face = {"mouth_roi": r["mouth_roi"], "eye_roi": r["eye_roi"]}
        if p == P.home: cfg["face"] = face; wrote.append(p)
        elif abs(pose_view(cfg["poses"][p])[1]) >= 15: cfg["poses"][p]["face"] = face; wrote.append(p)
    if "--write" in sys.argv and wrote:
        cp = P.p("config.json"); shutil.copyfile(cp, cp + ".bak")
        with open(cp, "w", encoding="utf-8") as f: json.dump(cfg, f, ensure_ascii=False, indent=1)
        print("書いた:", ", ".join(wrote), "（元は config.json.bak）")
    elif wrote: print("config に書くなら --write（home は face、正面でない姿勢は poses.<姿勢>.face）")
