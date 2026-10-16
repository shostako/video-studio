"""中割りのコマ補間の見比べ v2（使い捨ての調査用）。

v1（interp_compare.py）からの変更:
  - 大きさ: config の poses.<名前>.scale があればそれに固定（vm render と同じ。伸び・お辞儀が縮まない）
  - 揺れ止め: 中割りの各枚を、脚（絵の下 40%）が A に重なるよう ECC で揃えてから補間する
  - 緩急: RIFE で原画の間を 16 倍に細かく作っておき、ease-in-out の位置に一番近いコマを拾う
  - 長さ: 切り替えを 0.33 秒（今の 5枚÷15fps）から伸ばせる
並べる列: 原画 15fps ／ RIFE v1（等速 0.33 秒）／ RIFE v2（揺れ止め＋緩急＋長さ）
使い方: python interp_v2.py <作業フォルダ/mascot> <出力フォルダ> <切り替えの秒> home:point ...
"""
import json, os, sys
import cv2, numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import interp_compare as v1  # noqa: E402
from interp_compare import feet_anchor, fg_height, load_pair, rife, held, label, write, OUT_H  # noqa: E402

FPS = 60; HOLD = 0.6; DENSE = 16


def align_scaled(frames, sc_a, sc_b):
    """v1 の align と同じだが、両端の大きさを config の scale で決める（None は背で揃える）。"""
    ref = frames[0]; H0, W0 = ref.shape[:2]
    fr = [cv2.resize(f, (W0, H0)) for f in frames]
    anc = [feet_anchor(f) for f in fr]; ht = [fg_height(f, a) for f, a in zip(fr, anc)]
    s0 = 1.0 if sc_a is None else 1.0          # A が基準
    s1 = ht[0] / ht[-1] if sc_b is None else sc_b / (sc_a if sc_a else 1.0)
    n = len(fr) - 1; out = []
    for i, (f, a) in enumerate(zip(fr, anc)):
        sc = s0 + (s1 - s0) * i / n
        M = np.float32([[sc, 0, anc[0][0] - sc * a[0]], [0, sc, anc[0][1] - sc * a[1]]])
        g = cv2.warpAffine(f, M, (W0, H0), flags=cv2.INTER_AREA, borderValue=(253, 253, 253))
        out.append(cv2.resize(g, (round(W0 * OUT_H / H0) // 2 * 2, OUT_H), interpolation=cv2.INTER_AREA))
    return out


def stabilize(frames, top=0.6):
    """脚（絵の下 1-top）が1枚目に重なるよう、各枚を平行移動＋回転で揃える。"""
    g0 = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY).astype(np.float32)
    H, W = g0.shape; mask = np.zeros((H, W), np.uint8); mask[int(H * top):] = 1
    out = [frames[0]]; shifts = []
    for f in frames[1:]:
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32); M = np.eye(2, 3, dtype=np.float32)
        try: _, M = cv2.findTransformECC(g0, g, M, cv2.MOTION_EUCLIDEAN, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6), mask, 5)
        except cv2.error: pass
        shifts.append((round(float(M[0, 2]), 1), round(float(M[1, 2]), 1)))
        out.append(cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=(253, 253, 253)))
    return out, shifts


def ease_io(u):  # 3次の ease-in-out
    return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def eased(dense, dur):
    n = max(2, round(dur * FPS)); last = len(dense) - 1
    return [dense[round(ease_io(j / (n - 1)) * last)] for j in range(n)]


def timeline(seq, total):
    """A で HOLD 止める→切り替え→B で止める→戻る。列ごとの長さを total に揃える（B の止めで調整）。"""
    h = [seq[0]] * int(HOLD * FPS); mid = total - 2 * len(seq)
    return h + seq + [seq[-1]] * mid + seq[::-1] + h


def main():
    mdir, out, dur = sys.argv[1], sys.argv[2], float(sys.argv[3]); pairs = [s.split(":") for s in sys.argv[4:]]
    os.makedirs(out, exist_ok=True); poses = json.load(open(os.path.join(mdir, "config.json")))["poses"]; allrows = []
    for a, b in pairs:
        tag = f"{a}_{b}"; raw = load_pair(mdir, a, b, 5)
        src = align_scaled(raw, poses[a].get("scale"), poses[b].get("scale"))
        stab, shifts = stabilize(src); print(tag, "揺れ止めの移動(px):", shifts, flush=True)
        v1.MULT = 4; c0 = held(src)                                   # 原画 15fps（0.33 秒）
        v1.MULT = 4; c1 = rife(src, tag + "_v1")         # RIFE 等速（0.33 秒）
        v1.MULT = DENSE; c2 = eased(rife(stab, tag + "_v2"), dur)
        total = int(HOLD * FPS) * 2 + 2 * max(len(c0), len(c1), len(c2)) + int(HOLD * FPS)
        cols = [timeline(c, total) for c in (c0, c1, c2)]
        names = ["original 15fps", "RIFE v1 0.33s", f"RIFE v2 ease {dur}s"]
        n = min(len(c) for c in cols)
        rows = [np.hstack([label(c[i], f"{tag}  {nm}") for c, nm in zip(cols, names)]) for i in range(n)]
        allrows += rows
        write(f"{out}/{tag}_1x.mp4", rows, FPS); write(f"{out}/{tag}_half.mp4", rows, FPS // 2)
    write(f"{out}/all_1x.mp4", allrows, FPS); write(f"{out}/all_half.mp4", allrows, FPS // 2)


if __name__ == "__main__":
    main()
