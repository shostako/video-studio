"""Wan の切り替えのコマの上で話し続けたら口が浮くか・遅れるかの試し（2026-11-23）。

home→X→home の 2 本の Wan の列（各 47 コマ）を 30fps でそのまま流し（約 3.1 秒）、凜の声の頭に合わせて
home／X の口の部品を貼る。貼り方を 3 つ並べて比べる:
  A 今のまま   : 部品を顔の合わせ（ECC のアフィン）で写して貼るだけ（render.py の中割りと同じ）
  B 平均の色   : 部品の縁の帯で「コマ − 元の姿勢の絵」の平均（Lab）を取り、部品全体に足す（効かないので出力からは外した）
  C 場所ごとの色: 同じ差を、唇の形の違う所を除いて大きくぼかし、部品の場所ごとに足す
  D 小島を捨てる: 部品のいちばん大きい島（口の本体）だけを貼る。色は合わせない
縁の浮き（部品の縁のすぐ内側の色と、その下のコマの色の差、ΔE）をコマごとに出す。

使い方: python mouth_on_wan.py <パック> <声の作業フォルダ> <出力フォルダ> X [X ...]
"""
import sys, os, json, glob, subprocess, cv2, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../skills/video-mascot/scripts"))
from lib import frame_levels, choose_mouth, smooth_mouth, vowel_frames, words_hira, word_hira, fill_vowel_gaps  # noqa: E402

P, VW, OUT = sys.argv[1], sys.argv[2], sys.argv[3]; XS = sys.argv[4:]
os.makedirs(OUT, exist_ok=True)
FPS = 30


def load_parts(pose):
    d = f"{P}/parts_{pose}"; pj = json.load(open(f"{d}/parts.json"))
    return {k: (cv2.imread(f"{d}/{k}.png", -1), x, y) for k, (x, y) in pj.items() if k.startswith("m")}


def main_island(im):
    """口の部品のうち、いちばん大きい島（口の本体）だけを残す。髪・首の縁の切れ端は透明にする。"""
    a = im[:, :, 3]; n, lb, st, _ = cv2.connectedComponentsWithStats((a > 0).astype(np.uint8), 8)
    if n <= 2: return im
    big = 1 + int(np.argmax(st[1:, 4])); keep = cv2.dilate((lb == big).astype(np.uint8), np.ones((3, 3), np.uint8))
    out = im.copy(); out[:, :, 3] = a * keep; return out


def roi_of(parts, W, H):
    xs = [x for _, x, _ in parts.values()] + [x + im.shape[1] for im, x, _ in parts.values()]
    ys = [y for _, _, y in parts.values()] + [y + im.shape[0] for im, _, y in parts.values()]
    return max(0, min(xs) - 80), max(0, min(ys) - 100), min(W, max(xs) + 80), min(H, max(ys) + 60)


def face_affine(src, dst, roi):            # render.py の face_affine と同じ
    x0, y0, x1, y1 = roi
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = np.zeros(g0.shape, np.uint8); m[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), m, 5)
    except cv2.error: pass
    return cv2.invertAffineTransform(M), cc


def lab(img): return cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)


def bgr(lab_): return cv2.cvtColor(np.clip(lab_, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def compose(frame, pose_img, part, A, mode):
    """部品を A で frame に写して貼る。返り値: 貼った絵、縁の ΔE、部品の中心。"""
    im, px, py = part; H, W = frame.shape[:2]
    T = A.copy(); T[:, 2] += A[:, 0] * px + A[:, 1] * py
    full = cv2.warpAffine(im, T, (W, H), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    a = full[:, :, 3].astype(np.float32) / 255; yy, xx = np.where(a > 0)
    x0, x1, y0, y1 = xx.min() - 30, xx.max() + 31, yy.min() - 30, yy.max() + 31
    sl = (slice(y0, y1), slice(x0, x1))
    fl, pl = lab(frame[sl]), lab(np.ascontiguousarray(full[sl][:, :, :3])); al = a[sl]
    if mode == "D": im = main_island(im)
    if mode in ("B", "C"):
        ref = cv2.warpAffine(pose_img, A, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        d = fl - lab(ref[sl])                                   # コマと元の姿勢の絵の差（明るさ・色のずれ＋唇の形の違い）
        # 唇の形の違う所（差の大きい所）と部品の外は重みを落とす。縁の帯（部品の外側寄り）を主に見る
        mag = np.linalg.norm(d, axis=2)
        w = (al > 0.02).astype(np.float32) * (mag < 12).astype(np.float32)
        if mode == "B":
            ring = w * ((al > 0.02) & (al < 0.9)).astype(np.float32)
            ww = ring if ring.sum() > 50 else w
            off = (d * ww[..., None]).sum((0, 1)) / max(ww.sum(), 1e-6)
            pl = pl + off
        else:
            s = 9.0
            num = cv2.GaussianBlur(d * w[..., None], (0, 0), s); den = cv2.GaussianBlur(w, (0, 0), s)[..., None]
            glob_off = (d * w[..., None]).sum((0, 1)) / max(w.sum(), 1e-6)
            field = np.where(den > 0.05, num / np.maximum(den, 1e-6), glob_off)
            pl = pl + field
    pb = bgr(pl).astype(np.float32)
    out = frame.copy(); o = out[sl].astype(np.float32)
    o = o * (1 - al[..., None]) + pb * al[..., None]; out[sl] = o.astype(np.uint8)
    # 縁の浮き: 部品の縁のすぐ内側（アルファ 0.5〜0.95）で、貼った色とその下のコマの色の差
    band = (al > 0.5) & (al < 0.95)
    de = float(np.linalg.norm(pl[band] - fl[band], axis=1).mean()) if band.any() else 0.0
    m_ = cv2.moments((al > 0.5).astype(np.uint8))
    cen = (x0 + m_["m10"] / max(m_["m00"], 1), y0 + m_["m01"] / max(m_["m00"], 1))
    return out, de, cen


def wan_frames(a, b):
    fs = sorted(glob.glob(f"{P}/ib_wan/{a}__{b}/n47/f*.webp"), key=lambda s: int(s.split("/f")[-1][:-5]))
    return [cv2.imread(f) for f in fs]


# ---------- 声と口（render.py の音量式と同じ流れ） ----------
import pykakasi  # noqa: E402
KK = pykakasi.kakasi()
wav = f"{VW}/voice/master.wav"
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768; SR = 16000
words = json.load(open(f"{VW}/voice/master.words.json"))
NMAX = int(20 * FPS)
WIN = SR * 2 // 30
rms = frame_levels(x, SR, FPS, NMAX, WIN)
lvl = np.clip(rms / (np.percentile(rms[rms > 0], 95) + 1e-6), 0, 1.5)
lvl_s = np.array([np.median(lvl[max(0, f - 1):f + 2]) for f in range(NMAX)])
WH = [(h, s, e) for h, (w, s, e) in zip(words_hira([w for w, _, _ in words], KK.convert), words)]
vowel_at, _ = vowel_frames([(word_hira(h, w[0]), s, e) for (h, s, e), w in zip(WH, words)], FPS, NMAX)
vowel_at = fill_vowel_gaps(vowel_at, lvl_s >= 0.15, FPS)
MOUTH = smooth_mouth([choose_mouth(lvl_s[f], vowel_at[f]) for f in range(NMAX)], 1)
FB = {"m7": "m1", "m3": "m2", "m6": "m1"}

HOME = cv2.imread(f"{P}/poses/pose_home.png"); PARTS = {"home": load_parts("home")}
report = {}
for X in XS:
    PARTS[X] = load_parts(X); PIMG = {"home": HOME, X: cv2.imread(f"{P}/poses/pose_{X}.png")}
    seq = [(f, "home", X, i, 47) for i, f in enumerate(wan_frames("home", X))] + [(f, X, "home", i, 47) for i, f in enumerate(wan_frames(X, "home"))]
    N = len(seq); stats = {m: [] for m in "ACD"}; ccs = []; des_t = []
    H, W = HOME.shape[:2]
    # 顔の正方形は home の口の部品の場所で固定（動きを追わない枠で切ると、口が顔に遅れたかが見える）
    im1, px1, py1 = PARTS["home"]["m1"]; S = 220
    cx0, cy0 = px1 + im1.shape[1] // 2 - S // 2 + 40, py1 + im1.shape[0] // 2 - S // 2 + 20
    crop = lambda im: cv2.resize(im[cy0:cy0 + S, cx0:cx0 + S], (S * 2, S * 2), interpolation=cv2.INTER_CUBIC)
    body = lambda im: cv2.resize(im, (int(W * S * 2 / H) // 2 * 2, S * 2), interpolation=cv2.INTER_AREA)
    tmp = f"{OUT}/{X}_frames"; os.makedirs(tmp, exist_ok=True)
    for t, (fr, a, b, i, n) in enumerate(seq):
        src = a if i < n / 2 else b                      # 近い端の姿勢の部品を使う
        parts = PARTS[src]; roi = roi_of(parts, W, H)
        A, cc = face_affine(PIMG[src], fr, roi); ccs.append(cc)
        k = MOUTH[t]
        while k and k not in parts: k = FB.get(k)
        outs = {}
        for m in "ACD":
            if k is None or cc < 0.80: outs[m] = fr; continue
            outs[m], de, _ = compose(fr, PIMG[src], parts[k], A, m); stats[m].append(de)
            if m == "A": des_t.append((de, t))
        row = [body(outs["D"]), crop(outs["A"]), crop(outs["C"]), crop(outs["D"])]
        img = np.hstack(row)
        for j, s_ in enumerate(["A now", "C color", "D no-island"]):
            cv2.putText(img, s_, (row[0].shape[1] + j * S * 2 + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 200), 2)
        cv2.imwrite(f"{tmp}/{t:04d}.png", img)
        seq[t] = None                                    # 使い終わったコマを手放す
    dur = N / FPS
    mp4 = f"{OUT}/mouth_on_wan_{X}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", f"{tmp}/%04d.png", "-ss", "0", "-t", f"{dur:.3f}", "-i", wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", "-shortest", mp4], check=True)
    talk = sum(1 for t in range(N) if MOUTH[t])
    report[X] = {"frames": N, "sec": round(dur, 2), "talking_frames": talk, "cc_min": round(min(ccs), 3),
                 **{f"edge_dE_{m}": [round(float(np.mean(stats[m])), 2), round(float(np.max(stats[m])), 2)] for m in "ACD" if stats[m]}}
    tw = max(des_t)[1] if des_t else 0                   # 縁の浮きが一番大きいコマの見比べ
    cv2.imwrite(f"{OUT}/worst_{X}.png", cv2.imread(f"{tmp}/{tw:04d}.png"))
    report[X]["worst_frame"] = tw
    print(X, json.dumps(report[X], ensure_ascii=False), flush=True)
json.dump(report, open(f"{OUT}/report.json", "w"), ensure_ascii=False, indent=1)
