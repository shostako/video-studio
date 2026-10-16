"""中割りのコマ補間の見比べ（使い捨ての調査用）。

姿勢の組ごとに [A, 中割り1..n, B] を足元で揃え、次の3列を横に並べた動画を作る。
  1. 原画 15fps（今の vm render と同じ見え方。60fps の4コマずつ同じ絵）
  2. 溶かし 60fps（隣のコマを重ねて薄める。機械学習なし）
  3. RIFE 60fps（rife-ncnn-vulkan の Windows 版。新PCの GPU）
往復（A で止める→B へ→止める→A へ戻る）。等速と 1/4 速の2本。

使い方（video-scene の venv の python で）:
  python interp_compare.py <作業フォルダ/mascot> <出力フォルダ> home:point home:bow ...
"""
import os, shutil, subprocess, sys
import cv2, numpy as np

sys.path.insert(0, os.path.expanduser("~/ClaudeCode/video-studio/skills/video-mascot/scripts"))
from lib import feet_anchor, fg_height  # noqa: E402

RIFE = "/mnt/c/ComfyUI/tools/rife-ncnn-vulkan-20221029-windows/rife-ncnn-vulkan.exe"
WTMP = "/mnt/c/Users/shost/AppData/Local/Temp/rife_test"
OUT_H = 720; MULT = 4; HOLD = 0.6   # 出力の高さ、15fps→60fps、端で止める秒


def winpath(p): return subprocess.run(["wslpath", "-w", p], capture_output=True, text=True, check=True).stdout.strip()


def load_pair(mdir, a, b, nib):
    fw = os.path.join(mdir, "ib", f"ib_{a}_{b}_1.png"); rev = not os.path.exists(fw)
    pa, pb = (b, a) if rev else (a, b)
    ib = [os.path.join(mdir, "ib", f"ib_{pa}_{pb}_{k}.png") for k in range(1, nib + 1)]
    if rev: ib = ib[::-1]
    paths = [os.path.join(mdir, "poses", f"pose_{a}.png")] + ib + [os.path.join(mdir, "poses", f"pose_{b}.png")]
    return [cv2.imread(p) for p in paths]


def align(frames):
    """vm render の feet と同じ考え: 足元の点を揃え、背の高さを A に合わせる（中割りは両端の大きさの間で補う）。"""
    ref = frames[0]; H0, W0 = ref.shape[:2]
    anc = [feet_anchor(cv2.resize(f, (W0, H0))) for f in frames]
    ht = [fg_height(cv2.resize(f, (W0, H0)), a) for f, a in zip(frames, anc)]
    s_end = ht[0] / ht[-1]; n = len(frames) - 1; out = []
    for i, (f, a) in enumerate(zip(frames, anc)):
        f = cv2.resize(f, (W0, H0)); sc = 1.0 + (s_end - 1.0) * i / n
        M = np.float32([[sc, 0, anc[0][0] - sc * a[0]], [0, sc, anc[0][1] - sc * a[1]]])
        g = cv2.warpAffine(f, M, (W0, H0), flags=cv2.INTER_AREA, borderValue=(253, 253, 253))
        out.append(cv2.resize(g, (round(W0 * OUT_H / H0) // 2 * 2, OUT_H), interpolation=cv2.INTER_AREA))
    return out


def rife(frames, tag, model="rife-v4.6"):
    d = os.path.join(WTMP, tag); shutil.rmtree(d, ignore_errors=True); os.makedirs(d + "/in"); os.makedirs(d + "/out")
    for i, f in enumerate(frames): cv2.imwrite(f"{d}/in/{i:04d}.png", f)
    n_out = (len(frames) - 1) * MULT + 1
    subprocess.run([RIFE, "-i", winpath(d + "/in"), "-o", winpath(d + "/out"), "-m", model, "-n", str(n_out + MULT - 1)],
                   check=True, cwd=os.path.dirname(RIFE), capture_output=True)
    outs = sorted(os.listdir(d + "/out"))[:n_out]   # -n は列の末尾の外まで割り付けるので、最後の原画までで切る
    return [cv2.imread(f"{d}/out/{o}") for o in outs]


def crossfade(frames):
    out = []
    for i in range(len(frames) - 1):
        for k in range(MULT): out.append(cv2.addWeighted(frames[i], 1 - k / MULT, frames[i + 1], k / MULT, 0))
    return out + [frames[-1]]


def held(frames): return [f for f in frames[:-1] for _ in range(MULT)] + [frames[-1]]


def label(img, text):
    img = img.copy(); cv2.putText(img, text, (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 40, 40), 2, cv2.LINE_AA); return img


def roundtrip(seq, fps=60):
    h = [seq[0]] * int(HOLD * fps); t = [seq[-1]] * int(HOLD * fps)
    return h + seq + t + seq[::-1]


def write(path, frames, fps):
    H, W = frames[0].shape[:2]
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps),
                          "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for f in frames: p.stdin.write(f.tobytes())
    p.stdin.close(); p.wait()


def main():
    mdir, out = sys.argv[1], sys.argv[2]; pairs = [s.split(":") for s in sys.argv[3:]]; os.makedirs(out, exist_ok=True)
    allrows = []
    for a, b in pairs:
        src = align(load_pair(mdir, a, b, 5)); tag = f"{a}_{b}"
        cols = [roundtrip(held(src)), roundtrip(crossfade(src)), roundtrip(rife(src, tag))]
        names = ["original 15fps", "crossfade 60fps", "RIFE 60fps"]
        n = min(len(c) for c in cols)
        rows = [np.hstack([label(c[i], f"{tag}  {nm}") for c, nm in zip(cols, names)]) for i in range(n)]
        allrows += rows
        write(f"{out}/{tag}_1x.mp4", rows, 60)
        write(f"{out}/{tag}_quarter.mp4", rows, 15)
        print(tag, len(rows), "frames", flush=True)
    write(f"{out}/all_1x.mp4", allrows, 60)
    write(f"{out}/all_quarter.mp4", allrows, 15)


if __name__ == "__main__":
    main()
