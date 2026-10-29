"""ワイプ（右下の丸窓）に出す顔の絵 mouth0.png〜mouth3.png を作る。頭は 1 枚の絵に固定し、口（顎）の範囲だけを
口の部品の絵から楕円でぼかして貼る。口の形ごとに別の絵を丸ごと差し替えると、頭が少しずつずれてカクカク動いて見えるため。

usage:
  python3 wipe_faces.py --pose pose_home.png --parts home_m7.png home_m1.png home_m2.png --out <口の絵のフォルダ>
                        [--roi 350,560,610,690] [--center 480,560] [--scale 0.8]
  --pose   : 口を閉じた顔の絵（mouth0 になる）
  --parts  : 口を開けた絵を、小→中→大の順に 3 枚。--pose と同じ大きさ・同じ構図で、口のまわりだけが違う絵
             （video-mascot の口の部品 home_m1..m7 など。開き過ぎの形は入れない）
  --roi    : 貼る範囲 x0,y0,x1,y1（--pose の画素。頬から顎の下まで）。この範囲に内接する楕円をぼかした重みで貼る
  --center : ワイプの円の中心 (220,238) に来る --pose 上の点。--scale はその縮尺（440 角に縮める倍率）
compose.py の --wipe にこのフォルダを渡す。円 (220,238) 半径 200 の外は compose.py が切り落とす。
"""
import argparse, os, sys
import cv2, numpy as np

SIZE, CX, CY = 440, 220, 238

def blend_mask(shape, roi, feather=9):
    x0, y0, x1, y1 = roi
    m = np.zeros(shape[:2], np.float32)
    cv2.ellipse(m, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2 - 8, (y1 - y0) // 2 - 6), 0, 0, 360, 1, -1)
    return cv2.GaussianBlur(m, (0, 0), feather)[..., None]

def wipe_crop(im, center, scale):
    cx, cy = center
    x0, y0 = int(round(cx - CX / scale)), int(round(cy - CY / scale)); n = int(round(SIZE / scale))
    pad = max(0, -x0, -y0, x0 + n - im.shape[1], y0 + n - im.shape[0])
    if pad:                                             # 絵の外にはみ出す所は端の色で埋める
        im = cv2.copyMakeBorder(im, pad, pad, pad, pad, cv2.BORDER_REPLICATE); x0 += pad; y0 += pad
    return cv2.resize(im[y0:y0 + n, x0:x0 + n], (SIZE, SIZE), interpolation=cv2.INTER_AREA)

def faces(pose, parts, roi, center, scale):
    m = blend_mask(pose.shape, roi); out = [wipe_crop(pose, center, scale)]
    for p in parts:
        if p.shape != pose.shape: raise ValueError(f"口の部品の大きさ {p.shape[1]}x{p.shape[0]} が顔の絵 {pose.shape[1]}x{pose.shape[0]} と違う")
        out.append(wipe_crop(pose * (1 - m) + p * m, center, scale))
    return [np.clip(o, 0, 255).astype(np.uint8) for o in out]

def nums(s, n):
    v = [float(x) for x in s.split(",")]
    if len(v) != n: sys.exit(f"ERROR: {s} は {n} 個の数を , で区切って書く")
    return v

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", required=True); ap.add_argument("--parts", nargs=3, required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--roi", default="350,560,610,690"); ap.add_argument("--center", default="480,560"); ap.add_argument("--scale", type=float, default=0.8)
    A = ap.parse_args()
    rd = lambda p: (cv2.imread(p) if os.path.exists(p) else None)
    pose = rd(A.pose)
    if pose is None: sys.exit(f"ERROR: 顔の絵が読めない: {A.pose}")
    parts = []
    for p in A.parts:
        im = rd(p)
        if im is None: sys.exit(f"ERROR: 口の部品が読めない: {p}")
        parts.append(im.astype(np.float32))
    try:
        fs = faces(pose.astype(np.float32), parts, [int(x) for x in nums(A.roi, 4)], nums(A.center, 2), A.scale)
    except ValueError as e:
        sys.exit(f"ERROR: {e}")
    os.makedirs(A.out, exist_ok=True)
    for i, f in enumerate(fs):
        tmp = os.path.join(A.out, f".mouth{i}.tmp.png"); cv2.imwrite(tmp, f); os.replace(tmp, os.path.join(A.out, f"mouth{i}.png"))
    print("ok", A.out)
