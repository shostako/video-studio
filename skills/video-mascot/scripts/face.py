"""口と目の範囲（face の mouth_roi / eye_roi）を、描いた口・目の差分から測る。vm grid で目で読む代わり（キャラに依らない）。
  vm face <作業フォルダ> [姿勢 ...] [--write]
姿勢の絵と parts/<姿勢>_m1..m7（口）・_e1 _e2（目）を重ねて、変わった所を囲む。差分が無い姿勢は飛ばす。
--write: home の範囲を config.face に、顔が正面でない姿勢（head_yaw が 15 度以上）の範囲を poses.<姿勢>.face に書く
（正面の姿勢は vm parts が home から自動で写すので書かない）。書く前の config.json は config.json.bak に残す。
目は「頭の辺り（前景の上から背の 45%。--head で指定もできる）の中で、高さの揃った2つの塊」、口は「目の下で、目の幅の中に真ん中がある塊」
を探すので、差分が髪・手・服まで描き変えていても、そこは拾わない。おかしそうな範囲（口が目より上、口が目の幅より大きい等）は書かずに知らせる。
測った範囲は vm parts --check の絵で確かめる。"""
import json, os, shutil, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, MOUTHS, EYES, pose_view, fg_mask, die


def diff_boxes(base, var, thr=30, min_area=12, region=None):
    """var を base に平行移動で重ねてから、違う所の塊の箱 [(面積, x0, y0, x1, y1), ...]（大きい順）。region=[x0,y0,x1,y1] の外は見ない。"""
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
    if region is not None:
        r = np.zeros_like(m); x0, y0, x1, y1 = [int(round(v)) for v in region]; r[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 1; m = m * r
    n, _, st, _ = cv2.connectedComponentsWithStats(m)
    out = [(int(st[i, 4]), int(st[i, 0]), int(st[i, 1]), int(st[i, 0] + st[i, 2]), int(st[i, 1] + st[i, 3])) for i in range(1, n) if st[i, 4] >= min_area]
    return sorted(out, reverse=True)


def head_box(img, frac=0.45):
    """頭の辺りの目安: 前景の一番上から、背の高さの frac までの行と、その行の前景の左右の端。"""
    m = fg_mask(img); rows = np.where(m.any(axis=1))[0]
    if not len(rows): return [0, 0, img.shape[1], img.shape[0]]
    top, bot = int(rows.min()), int(rows.max()); y1 = top + int((bot - top) * frac)
    xs = np.where(m[top:y1].any(axis=0))[0]
    return [int(xs.min()), top, int(xs.max()) + 1, y1]


def pick_eyes(boxes):
    """両目: 高さが揃っていて、大きさが近い（2倍以内）2つの塊のうち、合わせて一番大きい組。組が無ければ一番大きい塊。
    髪・服の変化は1つだけの塊になりやすく、目の組より選ばれにくい。"""
    if not boxes: return None
    best = None
    for i, a in enumerate(boxes[:12]):
        for b in boxes[i + 1:12]:
            h = max(a[4] - a[2], b[4] - b[2], 4)
            if b[0] * 2 >= a[0] and abs((a[2] + a[4]) / 2 - (b[2] + b[4]) / 2) <= h * 0.6 and (best is None or a[0] + b[0] > best[0][0] + best[1][0]):
                best = (a, b)
    pair = best or (boxes[0],)
    return [min(b[1] for b in pair), min(b[2] for b in pair), max(b[3] for b in pair), max(b[4] for b in pair)]


def pick_mouth(boxes, eye):
    """目の下の、目の左右の幅の中に真ん中がある塊のうち一番大きいもの（手・服の変化は外れる）。"""
    ex0, ey0, ex1, ey1 = eye
    ok = [b for b in boxes if ex0 <= (b[1] + b[3]) / 2 <= ex1 and (b[2] + b[4]) / 2 > ey1]
    if not ok: return None
    b = ok[0]; return [b[1], b[2], b[3], b[4]]


def merge(found, margin=0.15, minpad=6):
    """差分ごとの箱から、真ん中が大きく外れたもの（髪・服の変化を拾った箱）を除いて、合わせた箱に少し余白を足す。"""
    if not found: return None
    cx = np.median([(b[0] + b[2]) / 2 for b in found]); cy = np.median([(b[1] + b[3]) / 2 for b in found])
    w = np.median([b[2] - b[0] for b in found]); h = np.median([b[3] - b[1] for b in found])
    ok = [b for b in found if abs((b[0] + b[2]) / 2 - cx) <= max(w, 8) and abs((b[1] + b[3]) / 2 - cy) <= max(h, 8)] or found
    x0, y0, x1, y1 = min(b[0] for b in ok), min(b[1] for b in ok), max(b[2] for b in ok), max(b[3] for b in ok)
    px = max(minpad, int(round((x1 - x0) * margin))); py = max(minpad, int(round((y1 - y0) * margin)))
    return [x0 - px, y0 - py, x1 + px, y1 + py], len(ok), len(found)


def _variants(P, pose, names):
    for k in names:
        vp = P.p("parts", f"{pose}_{k}.png"); var = cv2.imread(vp) if os.path.exists(vp) else None
        if var is not None: yield var


def measure(P, pose, head=None):
    """目を先に（頭の辺りの中で、高さの揃った2つの塊）、口はその下で目の幅の中から探す。差分が髪・手・服まで変えていても、そこは拾わない。"""
    base = P.read_pose(pose); H, W = base.shape[:2]; res = {}; hb = head or head_box(base)
    eyes = [e for e in (pick_eyes(diff_boxes(base, v, region=hb)) for v in _variants(P, pose, EYES)) if e]
    m = merge(eyes)
    if not m: return res
    (ex0, ey0, ex1, ey1), used, total = m; res["eye_roi"] = [max(0, ex0), max(0, ey0), min(W, ex1), min(H, ey1)]; res["eye_roi_n"] = f"{used}/{total}"
    ew = ex1 - ex0; reg = [ex0 - 0.25 * ew, (ey0 + ey1) / 2, ex1 + 0.25 * ew, ey1 + 1.2 * ew]   # 口を探す所: 目の下、目の幅の 1.2 倍まで
    mouths = [b for b in (pick_mouth(diff_boxes(base, v, region=reg), res["eye_roi"]) for v in _variants(P, pose, MOUTHS)) if b]
    m = merge(mouths)
    if m: r, used, total = m; res["mouth_roi"] = [max(0, r[0]), max(0, r[1]), min(W, r[2]), min(H, r[3])]; res["mouth_roi_n"] = f"{used}/{total}"
    return res


def suspicious(r):
    """測った範囲がおかしそうな理由（無ければ空）。人か Claude が方眼（vm grid）で読み直す目安。"""
    e, mo = r["eye_roi"], r["mouth_roi"]; ew = e[2] - e[0]; why = []
    if mo[1] < (e[1] + e[3]) / 2: why.append("口が目より上")
    if (mo[2] - mo[0]) > 1.2 * ew or (mo[3] - mo[1]) > 0.8 * ew: why.append("口の範囲が目の幅に比べて大きすぎる")
    if (e[3] - e[1]) > 0.8 * ew: why.append("目の範囲が縦に長すぎる")
    return why


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    head = None
    if "--head" in sys.argv:
        k = sys.argv.index("--head"); head = [int(v) for v in sys.argv[k + 1:k + 5]]; a = [x for x in a if x not in sys.argv[k + 1:k + 5]]
    if not a: die("使い方: vm face <作業フォルダ> [姿勢 ...] [--head x0 y0 x1 y1] [--write]")
    P = Proj(a[0]); poses = a[1:] or [p for p in P.poses if P.cfg["poses"][p].get("face", True) is not False]
    cfg = P.cfg; wrote = []; bad = []
    for p in poses:
        r = measure(P, p, head)
        if "mouth_roi" not in r or "eye_roi" not in r:
            print(f"{p:<10}  測れない（parts/{p}_m*.png と _e*.png が無いか、頭の辺りに差が無い。vm grid で読んで書く）"); bad.append(p); continue
        why = suspicious(r)
        print(f"{p:<10}  mouth_roi {r['mouth_roi']}（{r['mouth_roi_n']}）  eye_roi {r['eye_roi']}（{r['eye_roi_n']}）" + (f"  ※{'、'.join(why)}。書かない（vm grid で読む）" if why else ""))
        if why: bad.append(p); continue
        face = {"mouth_roi": r["mouth_roi"], "eye_roi": r["eye_roi"]}
        if p == P.home: cfg["face"] = face; wrote.append(p)
        elif abs(pose_view(cfg["poses"][p])[1]) >= 15: cfg["poses"][p]["face"] = face; wrote.append(p)
    if "--write" in sys.argv and wrote:
        cp = P.p("config.json"); shutil.copyfile(cp, cp + ".bak")
        with open(cp, "w", encoding="utf-8") as f: json.dump(cfg, f, ensure_ascii=False, indent=1)
        print("書いた:", ", ".join(wrote), "（元は config.json.bak）")
    elif wrote: print("config に書くなら --write（home は face、正面でない姿勢は poses.<姿勢>.face）")
    if bad: print("測れなかった・怪しい姿勢:", ", ".join(bad), "→ vm grid poses/pose_<姿勢>.png で読んで書く（references/pose-design.md）")
