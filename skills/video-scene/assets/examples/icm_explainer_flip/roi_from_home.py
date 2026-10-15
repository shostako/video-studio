"""基本の構え（home）で測った口・目の範囲を、顔を重ね合わせて他の姿勢へ写し、範囲（広めに）を出す。
  python roi_from_home.py <pose>   → 1行目 口の範囲 x0,y0,x1,y1  2行目 目の範囲"""
import sys, cv2, numpy as np
p = sys.argv[1]; home = cv2.imread("../hedra/poses/pose_home.png"); dst = cv2.imread(f"../hedra/poses/pose_{p}.png")
MOUTH = (450, 575, 600, 680); EYES = (370, 500, 640, 600)    # home 上で手で測った範囲（口の差分の外側・目の差分を含む）
g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(home, cv2.COLOR_BGR2GRAY).astype(np.float32)
mask = np.zeros(g0.shape, np.uint8); mask[330:760, 280:760] = 1; M = np.eye(2, 3, dtype=np.float32)
cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 400, 1e-6), mask, 5)
A = cv2.invertAffineTransform(M)
def mapbox(b, pad):
    pts = np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], np.float32); q = pts @ A[:, :2].T + A[:, 2]
    return [int(max(0, q[:, 0].min() - pad)), int(max(0, q[:, 1].min() - pad)), int(q[:, 0].max() + pad), int(q[:, 1].max() + pad)]
print(",".join(map(str, mapbox(MOUTH, 8)))); print(",".join(map(str, mapbox(EYES, 8)))); print(f"cc={cc:.3f}", file=sys.stderr)
