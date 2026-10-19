"""右の姿勢の絵を左右反転して、左の姿勢を作る（opt-in）。腕・手・指・体は反転した絵、頭（髪の輪郭ごと）は home の絵のまま。
顔は左右対称に描かれていないので、丸ごと反転すると分け目や毛先が逆になって別の顔に見える。頭だけ home に戻せば、顔の部品も home のものがそのまま合う。
  vm mirror <作業フォルダ> <右の姿勢>:<左の姿勢> [...] [--force] [--check]
    poses/pose_<左>.png を作り、config.poses に足す（mirror_of に元の名前）。元の姿勢と組になる中割りも反転して作る:
    組の相手が home か、同じ指定で反転する姿勢なら ib/ib_<..>_<k>.png を作り、pairs・ib_steps（image-right と image-left を入れ替える）・interp.durs を足す。
    顔の部品は home の部品をずらさずに写す（parts_<左>/、顔の前の手には貼らない）。parts_<左>/borrowed.json に印を書く。
    既に左の姿勢の絵があれば止まる。--force で古い絵・中割り・部品を reject/mirror_replaced/<時刻>/ へ移してから作る。
    --check で、元・反転・頭の範囲を並べた確かめの絵を mirror_check/<左>.png に書く。
  反転の手順:
    1. 反転した絵を土台にする
    2. home の頭（髪と顔の色の一番大きな塊。あごより上、穴は埋める）を home の絵で戻す
    3. 頭の範囲に来る手（前腕からつながった肌）は、反転した絵の手を上に戻す
    4. 反転した絵の髪が home の頭からはみ出す所は home の絵で埋める（腕の近くは除く）
  髪と肌の色は home の絵から測る（頭のてっぺんと、目と口の間）。あごの高さと首の幅は config.face の範囲から決める。
  合わないときは config.mirror で上書きする: {"chin": あごの y, "neck_x": [左, 右], "hair_tol": 60, "skin_tol": 55}"""
import argparse
import json
import os
import re
import shutil
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, die, occlude  # noqa: E402

MIRROR_KEYS = {"chin", "neck_x", "hair_tol", "skin_tol"}


def params(P, home):
    """あごの高さ・首の幅・髪と肌の色を、config.face と home の絵から決める。config.mirror の値が優先。"""
    m = P.cfg.get("mirror") or {}
    unknown = set(m) - MIRROR_KEYS
    if unknown: die(f"mirror に知らない項目: {sorted(unknown)}")
    f = P.cfg.get("face") or {}
    if "mouth_roi" not in f or "eye_roi" not in f: die("config.face に mouth_roi と eye_roi が要る（vm face で測る）")
    mx0, my0, mx1, my1 = f["mouth_roi"]; ex0, ey0, ex1, ey1 = f["eye_roi"]
    chin = m.get("chin", f["jaw_roi"][3] if "jaw_roi" in f else my1 + (my1 - ey1) // 2)
    cx = (mx0 + mx1) / 2; hw = 0.75 * (mx1 - mx0)
    neck_x = m.get("neck_x", [int(cx - hw), int(cx + hw)])
    H, W = home.shape[:2]
    bg = np.median(np.concatenate([home[:8, :8].reshape(-1, 3), home[:8, -8:].reshape(-1, 3)]), 0)
    fg = np.abs(home.astype(int) - bg).max(2) > 18
    cols = np.where(fg[:, int(cx) - 20:int(cx) + 20].any(1))[0]
    if not len(cols): die("home の絵で頭が見つからない（背景と同じ色）")
    top = cols[0]; band = home[top + 4:top + 4 + max(6, (ey0 - top) // 6), int(cx) - 15:int(cx) + 15].reshape(-1, 3)
    hair = np.median(band, 0)
    sk = home[ey1 + 2:max(ey1 + 4, my0 - 2), int(cx) - 8:int(cx) + 8].reshape(-1, 3)
    skin = np.median(sk, 0)
    return {"chin": int(chin), "eye_bottom": int(ey1), "face_pt": (int(cx), int((ey1 + my0) / 2)), "neck_x": [int(neck_x[0]), int(neck_x[1])], "hair": hair, "skin": skin, "bg": bg,
            "hair_tol": m.get("hair_tol", 60), "skin_tol": m.get("skin_tol", 55)}


def near(im, col, tol):
    return (np.linalg.norm(im.astype(np.float32) - col.astype(np.float32), axis=2) < tol).astype(np.uint8)


def head_mask(home, prm):
    """髪と顔の色の一番大きな塊（あごより上）。目・口・額の明るい所などの穴は埋める。"""
    m = (near(home, prm["hair"], prm["hair_tol"]) | near(home, prm["skin"], prm["skin_tol"])).astype(np.uint8)
    m[prm["chin"]:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2: die("home の絵で頭の塊が見つからない（config.mirror の hair_tol・skin_tol を見直す）")
    hm = (lab == 1 + np.argmax(st[1:, 4])).astype(np.uint8)
    cs, _ = cv2.findContours(hm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(hm, cs, -1, 1, thickness=cv2.FILLED)
    # 髪と上着の色が近いと、あごの横から肩・襟まで頭に入る。目より下で頭の幅が一番細い行（あご・首）から下は、首の幅の中だけにする
    nx0, nx1 = prm["neck_x"]; y0 = prm["eye_bottom"]
    w = [(r.max() - r.min()) if len(r := np.nonzero(hm[y])[0]) else 10 ** 9 for y in range(y0, prm["chin"])]
    if w:
        ys = y0 + int(np.argmin(w)); hm[ys:, :nx0] = 0; hm[ys:, nx1:] = 0
    return hm


def arm_skin(pf, prm, hm):
    """反転した絵の肌のうち、手と腕の塊。顔（目と口の間の点を含む塊）・首・頭の範囲にすっかり収まる塊（耳など）は入れない。
    頭の外へはみ出している肌（頭の横に挙げた手、髪にかかる指）だけを手と見なす。"""
    m = near(pf, prm["skin"], prm["skin_tol"]); m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m); out = np.zeros_like(m)
    fx, fy = prm["face_pt"]; face = lab[fy, fx]; nx0, nx1 = prm["neck_x"]; min_area = max(60, int(pf.shape[0] * pf.shape[1] * 1e-4))
    for k in range(1, n):
        if k == face or st[k, 4] < min_area: continue
        x, y, w, h = st[k, :4]
        if x >= nx0 and x + w <= nx1 and y >= fy: continue             # 首（首の幅の中で、顔の真ん中より下）
        comp = lab == k
        if (comp & (hm == 0)).sum() >= 0.1 * st[k, 4]: out[comp] = 1
    return out


def feather(m, s=1.5): return np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), s) * 1.3, 0, 1)[..., None]


def make(home, pose, prm, hm=None):
    """反転した絵に home の頭を戻す。戻り値は（絵、頭の範囲、髪の上に戻した手）。"""
    pf = pose[:, ::-1].copy(); c = prm["chin"]; nx0, nx1 = prm["neck_x"]
    hm = head_mask(home, prm) if hm is None else hm.copy(); hm[c:, nx0:nx1] = 0
    arm = arm_skin(pf, prm, hm)
    hk = cv2.dilate(arm & cv2.dilate(hm, np.ones((21, 21), np.uint8)), np.ones((3, 3), np.uint8))
    out = pf.astype(np.float32)
    a = feather(cv2.dilate(hm, np.ones((5, 5), np.uint8))); out = home * a + out * (1 - a)
    hair_pf = near(pf, prm["hair"], prm["hair_tol"])
    stray = hair_pf & (1 - cv2.dilate(hm, np.ones((5, 5), np.uint8))) & cv2.dilate(hm, np.ones((41, 41), np.uint8))
    stray[c:] = 0; stray &= (1 - cv2.dilate(arm, np.ones((25, 25), np.uint8)))
    stray = cv2.dilate(stray, np.ones((5, 5), np.uint8))
    a = feather(stray); out = home * a + out * (1 - a)
    a = feather(hk, 1.0); out = pf * a + out * (1 - a)
    return np.clip(out, 0, 255).astype(np.uint8), hm, hk


def swap_side(s):
    return re.sub(r"image-(right|left)", lambda m: "image-" + ("left" if m.group(1) == "right" else "right"), s)


def ib_list(P, a, b):
    out = []
    for f in sorted(os.listdir(P.p("ib"))) if os.path.isdir(P.p("ib")) else []:
        pre = f"ib_{a}_{b}_"
        if f.startswith(pre) and f.endswith(".png"):
            rest = f[len(pre):-4].split("_")
            if all(x.isdigit() for x in rest) and 1 <= len(rest) <= 2: out.append(f)
    return out


def copy_home_parts(P, dst_name, img, home_img):
    """home の部品をずらさずに写す（頭は home の絵そのもの）。顔の前の手には貼らない。"""
    sm = P.p(f"parts_{P.home}", "parts.json")
    if not os.path.exists(sm): die(f"home の部品が無い: parts_{P.home}（先に vm parts {P.home}）")
    od = P.p(f"parts_{dst_name}"); os.makedirs(od, exist_ok=True); meta = {}; H, W = img.shape[:2]
    for k, (px, py) in json.load(open(sm)).items():
        im = cv2.imread(P.p(f"parts_{P.home}", f"{k}.png"), cv2.IMREAD_UNCHANGED)
        full = np.zeros((H, W, 4), np.uint8); full[py:py + im.shape[0], px:px + im.shape[1]] = im
        full = occlude(full, img, home_img)
        yy, xx = np.where(full[:, :, 3] > 0)
        if not len(xx): continue
        cv2.imwrite(os.path.join(od, f"{k}.png"), full[yy.min():yy.max() + 1, xx.min():xx.max() + 1]); meta[k] = [int(xx.min()), int(yy.min())]
    json.dump(meta, open(os.path.join(od, "parts.json"), "w"), indent=1)
    json.dump({"from": P.home, "cc": 1.0, "mirror": True}, open(os.path.join(od, "borrowed.json"), "w"))


def run(P, maps, force=False, check=False):
    home = P.read_pose(P.home); prm = params(P, home); hm = head_mask(home, prm)
    dst_of = dict(maps)
    for s, d in maps:
        if s not in P.cfg["poses"]: die(f"元の姿勢が config に無い: {s}")
        if d == P.home or d in dst_of: die(f"作る名前が使えない: {d}")
        if s == P.home: die("home は反転しない（頭を戻す土台）")
    cfg = P.cfg; rej = None
    for s, d in maps:
        olds = ([P.pose_path(d)] if os.path.exists(P.pose_path(d)) else []) + \
               [P.p("ib", f) for x, y in [(p[0], p[1]) for p in P.pairs] if d in (x, y) for f in ib_list(P, x, y)] + \
               ([P.p(f"parts_{d}")] if os.path.isdir(P.p(f"parts_{d}")) else [])
        if olds and not force: die(f"{d} は既にある（作り直すなら --force。古い絵は reject/mirror_replaced/ へ移す）")
        if olds:
            rej = rej or P.p("reject", "mirror_replaced", time.strftime("%Y%m%d_%H%M%S")); os.makedirs(rej, exist_ok=True)
            for o in olds: shutil.move(o, os.path.join(rej, os.path.basename(o.rstrip("/"))))
    side = lambda x: x if x == P.home else dst_of.get(x)
    done_pairs = []
    for s, d in maps:
        img, hmask, hk = make(home, P.read_pose(s), prm, hm)
        cv2.imwrite(P.pose_path(d), img)
        pc = dict(cfg["poses"][s]); pc["desc"] = swap_side(pc.get("desc", "")); pc["mirror_of"] = s; pc["refs"] = [P.home]
        cfg["poses"][d] = pc
        copy_home_parts(P, d, img, home)
        if check:
            os.makedirs(P.p("mirror_check"), exist_ok=True)
            vis = img.copy(); vis[hmask > 0] = (0.6 * vis[hmask > 0] + 0.4 * np.array([255, 160, 0])).astype(np.uint8)
            vis[hk > 0] = (0, 0, 255)
            cv2.imwrite(P.p("mirror_check", f"{d}.png"), np.hstack([P.read_pose(s), img, vis]))
        print(f"{s} → {d}: 絵を作った（頭は {P.home} の絵、髪の上に戻した手 {int(hk.sum())} 画素）")
    pairs = [tuple(p) for p in cfg.get("pairs", [])]; steps = cfg.get("ib_steps") or {}
    for a, b in list(pairs):
        if a not in dst_of and b not in dst_of: continue
        ma, mb = side(a), side(b)
        if ma is None or mb is None or (ma, mb) == (a, b): continue
        fs = ib_list(P, a, b)
        for f in fs:
            rest = f[len(f"ib_{a}_{b}_"):]
            out, _, _ = make(home, cv2.imread(P.p("ib", f)), prm, hm); cv2.imwrite(P.p("ib", f"ib_{ma}_{mb}_{rest}"), out)
        if (ma, mb) not in pairs and (mb, ma) not in pairs: pairs.append((ma, mb))
        if f"{a}>{b}" in steps: steps[f"{ma}>{mb}"] = [swap_side(x) for x in steps[f"{a}>{b}"]]
        it = cfg.get("interp")
        if isinstance(it, dict) and f"{a}>{b}" in (it.get("durs") or {}): it["durs"][f"{ma}>{mb}"] = it["durs"][f"{a}>{b}"]
        done_pairs.append(f"{ma}>{mb}（{len(fs)} 枚）")
    cfg["pairs"] = [list(p) for p in pairs]
    if steps: cfg["ib_steps"] = steps
    cf = P.p("config.json"); shutil.copy2(cf, cf + ".bak")
    json.dump(cfg, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if done_pairs: print("反転した中割り:", ", ".join(done_pairs))
    if check: print("確かめる絵:", P.p("mirror_check"), "（橙が home から戻した頭、赤が髪の上に戻した手）")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("proj"); ap.add_argument("maps", nargs="+", help="右の姿勢:左の姿勢")
    ap.add_argument("--force", action="store_true"); ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    maps = []
    for m in a.maps:
        if m.count(":") != 1 or not all(m.split(":")): die(f"右の姿勢:左の姿勢 の形で書く: {m}")
        maps.append(tuple(m.split(":")))
    run(Proj(a.proj), maps, a.force, a.check)


if __name__ == "__main__":
    main()
