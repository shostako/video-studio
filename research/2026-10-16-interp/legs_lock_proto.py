"""下半身の差し替えの試作（使い捨て）。正面の姿勢と中割りの腰から下を、基準の姿勢の下半身に置き換える。

切れ目（cut）は背の高さの割合で、足元から測る。切れ目の上 feather の帯で溶かす。
手（肌の色）は切れ目の下でも元の絵を残す（腿の上に置いた手・体の横に下ろした手）。ただし足首の肌は基準のまま。
使い方: python legs_lock_proto.py <mascot> <出力png> <基準の姿勢> <cut> <feather> pose_or_ib_path...
"""
import os, sys
import cv2, numpy as np

sys.path.insert(0, os.path.expanduser("~/ClaudeCode/video-studio/skills/video-mascot/scripts"))
from lib import fg_mask  # noqa: E402


def floor_y(img):
    rows = np.where(fg_mask(img).sum(1) > 3)[0]; return int(rows.max()) + 1, int(rows.min())


def leg_profile(img, y0, y1):
    return fg_mask(img)[y0:y1].sum(0).astype(np.float32)


def skin_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV); h, s, v = cv2.split(hsv)
    return ((h < 25) & (s > 30) & (s < 170) & (v > 120)).astype(np.uint8)


def lock_legs(img, canon, cut=0.38, feather=0.03, hand_zone=0.45):
    """img の腰から下を canon の下半身に置き換えた絵を返す（同じ大きさの BGR）。
    canon は切れ目の帯の脚の左右位置が img と重なるよう横にずらし、足元の y を img に合わせる。"""
    H, W = img.shape[:2]
    fy, top = floor_y(img); cfy, ctop = floor_y(canon); h = fy - top
    cy = int(round(fy - cut * h)); fb = max(2, int(round(feather * h)))
    dy = fy - cfy
    a = leg_profile(img, cy - fb, cy); b = leg_profile(np.roll(canon, dy, axis=0), cy - fb, cy)
    best, dx = -1, 0
    for s in range(-40, 41):                          # 切れ目の帯の脚の重なりが一番大きい横のずれ
        sc = float((a * np.roll(b, s)).sum())
        if sc > best: best, dx = sc, s
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    c = cv2.warpAffine(canon, M, (W, H), borderMode=cv2.BORDER_CONSTANT, borderValue=(253, 253, 253))
    yy = np.arange(H); wr = np.clip((yy - (cy - fb)) / fb, 0, 1).astype(np.float32)   # 行ごとの基準の重み（切れ目の上 fb で 0→1）
    imgW = img.copy(); cW = c.copy(); mi, mc = fg_mask(img), fg_mask(c); cx = int(round(W / 2))
    def edges(m, y):
        xs = np.where(m[y])[0]
        if not len(xs): return None
        near = xs[np.abs(xs - cx) < 0.18 * W]
        if not len(near): return None
        runs = np.split(xs, np.where(np.diff(xs) > 3)[0] + 1)
        sel = [r for r in runs if r.min() <= near.max() and r.max() >= near.min() and abs((r.min() + r.max()) / 2 - cx) < 0.15 * W]
        return (min(r.min() for r in sel), max(r.max() for r in sel)) if sel else None
    X = np.arange(W, dtype=np.float32)
    for y in range(cy - fb, cy):                      # 帯の中は、両方の絵の輪郭を途中の輪郭へ横に伸び縮みさせてから混ぜる（二重の輪郭を出さない）
        t = wr[y]; ef, ec = edges(mi, y), edges(mc, y)
        if ef is None or ec is None or ef[1] - ef[0] < 10 or ec[1] - ec[0] < 10: continue
        L = (1 - t) * ef[0] + t * ec[0]; R = (1 - t) * ef[1] + t * ec[1]
        for src, dst, e in ((img, imgW, ef), (c, cW, ec)):
            mx = (e[0] + (X - L) * (e[1] - e[0]) / (R - L)).astype(np.float32)
            dst[y] = cv2.remap(src[y:y + 1], mx[None, :], np.full((1, W), 0, np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]
    w = np.repeat(wr[:, None], W, axis=1)
    hz = int(round(cy + hand_zone * (fy - cy)))      # 手を残すのは切れ目から足元までの上 hand_zone まで（足首の肌は基準）
    sk = skin_mask(img); sk[hz:] = 0; sk[:cy - fb] = 0
    sk = cv2.dilate(sk, np.ones((9, 9), np.uint8)); skf = np.clip(cv2.GaussianBlur(sk.astype(np.float32), (0, 0), 3), 0, 1)
    out = imgW.astype(np.float32) * (1 - w[..., None]) + cW.astype(np.float32) * w[..., None]
    keep = np.zeros((H, W), np.uint8)                 # 腰と脚の外にある元の絵の前景（体の横に下ろした腕・手）は元のまま
    for y in range(cy - fb, hz):
        e = edges(mi, y)
        if e is None: continue
        row = mi[y].copy(); row[max(0, e[0] - 2):e[1] + 3] = 0; keep[y] = row
    keep = np.clip(cv2.GaussianBlur(cv2.dilate(keep, np.ones((7, 7), np.uint8)).astype(np.float32), (0, 0), 2), 0, 1)
    skf = np.maximum(skf, keep)
    out = out * (1 - skf[..., None]) + img.astype(np.float32) * skf[..., None]
    return out.astype(np.uint8), dict(cut=cy, feather=fb, dx=dx, dy=dy)


def main():
    m, out, ref, cut, fe = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
    canon = cv2.imread(os.path.join(m, "poses", f"pose_{ref}.png")); tiles = []
    for p in sys.argv[6:]:
        path = p if os.path.exists(p) else os.path.join(m, "poses", f"pose_{p}.png")
        img = cv2.imread(path); r, info = lock_legs(img, canon, cut, fe)
        print(os.path.basename(path), info, flush=True)
        a, b = img[850:1560, 230:720].copy(), r[850:1560, 230:720].copy()
        cv2.line(b, (0, info["cut"] - 850), (b.shape[1], info["cut"] - 850), (0, 0, 255), 1)
        cv2.putText(a, os.path.basename(path)[:18], (5, 25), 0, 0.7, (0, 0, 255), 2)
        tiles.append(np.vstack([a, b]))
    cv2.imwrite(out, np.hstack(tiles))


if __name__ == "__main__":
    main()
