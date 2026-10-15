"""frames.py — 確かめ用のコマ一覧（コンタクトシート）を作る。Read で見る前提で、小さく並べる。

使い方:
  vs frames 動画 --out sheet.png [--every 0.5 | --step N] [--range 開始:終了(秒)] [--crop x,y,w,h]
            [--width 320] [--cols 6]
  よく使う形:
    全体を0.5秒ごと:        --every 0.5
    最後の1秒を1コマずつ:   --range=-1: --step 1   （負の数は終わりからの秒）
    口元を拡大:             --range 0.5:2 --step 2 --crop 385,345,110,80 --width 220
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import probe


def main():
    import cv2, numpy as np, subprocess
    ap = argparse.ArgumentParser(); ap.add_argument("video"); ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=float); ap.add_argument("--step", type=int); ap.add_argument("--range", default=":")
    ap.add_argument("--crop"); ap.add_argument("--width", type=int, default=320); ap.add_argument("--cols", type=int, default=6)
    a = ap.parse_args()
    info = probe(a.video); fps, dur = info["fps"], info["duration"]; total = int(round(dur * fps))
    s, e = (a.range.split(":") + [""])[:2]
    t0 = float(s) if s else 0.0; t1 = float(e) if e else dur
    if t0 < 0: t0 = dur + t0
    if t1 < 0: t1 = dur + t1
    f0, f1 = int(t0 * fps), min(total - 1, int(round(t1 * fps)))
    step = a.step or max(1, int(round((a.every or 0.5) * fps)))
    idx = list(range(f0, f1 + 1, step))
    vf = f"select='{'+'.join(f'eq(n\\,{i})' for i in idx)}'"
    if a.crop: x, y, w, h = map(int, a.crop.split(",")); vf += f",crop={w}:{h}:{x}:{y}"
    else: w, h = info["width"], info["height"]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.video, "-vf", vf, "-vsync", "vfr", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    th = int(a.width * h / w); tiles = []
    for i, f in zip(idx, frames):
        t = cv2.resize(f, (a.width, th), interpolation=cv2.INTER_AREA if a.width < w else cv2.INTER_LANCZOS4)
        cv2.putText(t, f"{i / fps:.2f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA); tiles.append(t)
    while len(tiles) % a.cols: tiles.append(np.full_like(tiles[0], 255))
    sheet = np.vstack([np.hstack(tiles[i:i + a.cols]) for i in range(0, len(tiles), a.cols)])
    cv2.imwrite(a.out, sheet); print(f"{a.out} ({len(idx)} コマ, {sheet.shape[1]}x{sheet.shape[0]})")


if __name__ == "__main__":
    main()
