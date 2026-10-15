"""line_fix.py — 動画の決まった範囲に残る「細い線」（口の消し残りなど）を、周りの色で埋めて消す。

使い方:
  vs line_fix 入力.mp4 出力.mp4 --roi x0,y0,x1,y1 --frames 14-20,25-37 [--delta 9] [--max-h 14] [--ratio 1.5]
                                 [--preview before_after.png]

  - 座標とコマ番号は「入力の動画そのもの」のもの（書き出し後の画面座標ではない）
  - 見つける線: 周りより delta 以上暗く、横に細長い（幅 >= ratio×高さ、高さ <= max-h）もの
    縦に5px以上厚い所（開いた口など）は除外する
  - 直すコマは、開いた口の横に線が重なっているコマだけにする。口そのものが線の形のコマ
    （しゃべって横に広がった口、閉じかけの口）は入れない
  - 必ず --preview で直す前と後を並べて Read で確かめる。口を削ったコマがあれば --frames から外す
"""
import argparse, os, subprocess, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import probe, die


def parse_frames(s):
    out = []
    for part in s.split(","):
        if "-" in part: a, b = map(int, part.split("-")); out += list(range(a, b + 1))
        elif part: out.append(int(part))
    return sorted(set(out))


def fix(img, roi, delta, max_h, ratio):
    import cv2, numpy as np
    X0, Y0, X1, Y1 = roi; r = img[Y0:Y1, X0:X1]
    g = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    dark = ((cv2.medianBlur(g, 11).astype(np.float32) - g.astype(np.float32)) > delta).astype(np.uint8)
    thick = cv2.dilate(cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5, 3), np.uint8)), np.ones((5, 5), np.uint8))
    line = dark & (1 - thick)
    n, lab, st, _ = cv2.connectedComponentsWithStats(line); keep = np.zeros_like(line)
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if w >= 4 and h <= max_h and w >= ratio * h and area >= 4: keep[lab == i] = 1
    mask = cv2.dilate(keep, np.ones((3, 3), np.uint8)) * 255
    out = img.copy(); out[Y0:Y1, X0:X1] = cv2.inpaint(r, mask, 3, cv2.INPAINT_TELEA)
    return out, int((mask > 0).sum())


def main():
    import cv2, numpy as np
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("out"); ap.add_argument("--roi", required=True)
    ap.add_argument("--frames", required=True); ap.add_argument("--delta", type=float, default=9); ap.add_argument("--max-h", type=int, default=14)
    ap.add_argument("--ratio", type=float, default=1.5); ap.add_argument("--preview"); ap.add_argument("--crf", type=int, default=12)
    a = ap.parse_args()
    roi = tuple(map(int, a.roi.split(","))); targets = parse_frames(a.frames); info = probe(a.src)
    work = tempfile.mkdtemp(prefix="linefix.")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-i", a.src, "-start_number", "0", os.path.join(work, "f%05d.png")], check=True)
        tiles = []; X0, Y0, X1, Y1 = roi; pad = 12
        for n in targets:
            p = os.path.join(work, f"f{n:05d}.png"); im = cv2.imread(p)
            if im is None: die(f"コマ {n} が無い", 2)
            o, px = fix(im, roi, a.delta, a.max_h, a.ratio); cv2.imwrite(p, o); print(f"frame {n}: {px}px")
            if a.preview:
                c = lambda z: cv2.resize(z[max(0, Y0 - pad):Y1 + pad, max(0, X0 - pad):X1 + pad], None, fx=2.5, fy=2.5, interpolation=cv2.INTER_LANCZOS4)
                t = np.hstack([c(im), np.full((c(im).shape[0], 4, 3), 255, np.uint8), c(o)])
                cv2.putText(t, str(n), (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2); tiles.append(t)
        if tiles:
            cols = 3
            while len(tiles) % cols: tiles.append(np.full_like(tiles[0], 255))
            cv2.imwrite(a.preview, np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]))
        part = a.out + ".part.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", f"{info['fps']:g}", "-start_number", "0", "-i", os.path.join(work, "f%05d.png")]
        if info["has_audio"]: cmd += ["-i", a.src, "-map", "0:v", "-map", "1:a", "-c:a", "copy"]
        cmd += ["-c:v", "libx264", "-crf", str(a.crf), "-preset", "slow", "-pix_fmt", "yuv420p", part]
        subprocess.run(cmd, check=True); os.replace(part, a.out); print(a.out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
