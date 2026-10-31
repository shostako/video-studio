"""マスコットの動画（白背景）を、画面を縮めた解説動画（1920x1080、左に 496px の余白）の余白に重ねる。
乗算で重ねるので、白い所は下の余白の色になる。声はマスコットの動画のもの。
使い方: python compose_layout.py <mascot.mp4|webm> <full|bust> <L|S> <out.mp4> [--bg main2.mp4] [--bg-from 10] [--audio 声.wav] [--full] [--place-only]
  --audio: 声を別の wav から付ける（透明の webm には声が無い）。--full: 主動画の最後まで書く（マスコットが先に終われば最後のコマのまま）。
  CROP x,y,幅,高さ を出す（完成の動画でマスコットのいる範囲。vm check --crop 用）。--place-only は位置を出すだけ
"""
import os, subprocess, sys

import numpy as np

BG = os.path.expanduser("~/.local/share/video-scene/work/cad-viewer-howto/out/main2.mp4")
W, H, FPS = 1920, 1080, 60
MARGIN_CX = 248                       # 余白（幅 496）の中心
# 立ち姿の座標（941x1672）での体の中心 x・頭の上・足元。A と B でほぼ同じなので共通にする
FIG_CX, FIG_TOP, FIG_FEET = 463, 195, 1521


def opt(name, default=None, typ=str):
    return typ(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def probe(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.split(",")
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout)
    return int(r[0]), int(r[1]), d


def main():
    mp, frame, size, outp = sys.argv[1:5]
    bg, bg_from = opt("--bg", BG), opt("--bg-from", 10.0, float)
    mw, mh, dur = probe(mp)
    if frame == "full":                # mw x mh は 941x1672 を高さ 1280 に縮めた物
        k = mh / 1672
        fig_h = {"L": 880, "S": 560}[size]
        top, feet, cx = FIG_TOP * k, FIG_FEET * k, FIG_CX * k
        if mp.endswith(".webm"):       # 透過の素材: 最初のコマのアルファから人物の上端・下端・中心を測る（キャラで背が揃う）
            raw = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", mp, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout
            al = np.frombuffer(raw, np.uint8).reshape(mh, mw, 4)[:, :, 3] > 128
            ys, xs = np.where(al)
            if len(ys): top, feet = float(ys.min()), float(ys.max()); cx = float(np.median(xs[ys > ys.min() + 0.6 * (ys.max() - ys.min())]))
        s = fig_h / (feet - top)
        sw, sh = round(mw * s), round(mh * s)
        x = round(MARGIN_CX - cx * s); y = round(1050 - feet * s)
    else:                              # 胸から上: 横幅で大きさを決め、切り口を下端にそろえる
        width = {"L": 496, "S": 340}[size]
        s = width / mw; sw, sh = round(mw * s), round(mh * s)
        x = round(MARGIN_CX - sw / 2); y = H - sh
    print(f"{frame} {size}: {mw}x{mh} → {sw}x{sh} at ({x},{y})", flush=True)
    x0, y0 = max(0, x), max(0, y); cw, ch_ = min(x + sw, W) - x0, min(y + sh, H) - y0
    print(f"CROP {x0},{y0},{cw},{ch_}", flush=True)
    if "--place-only" in sys.argv: return
    audio = opt("--audio"); full_len = "--full" in sys.argv

    rd_bg = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(bg_from)] + ([] if full_len else ["-t", f"{dur:.3f}"]) + ["-i", bg, "-f", "rawvideo", "-pix_fmt", "rgb24", "-r", str(FPS), "-"], stdout=subprocess.PIPE)
    ALPHA = mp.endswith(".webm")      # 背景が透明な webm（VP9 のアルファ）はアルファで重ねる。白背景の mp4 は乗算
    ch = 4 if ALPHA else 3
    rd_m = subprocess.Popen(["ffmpeg", "-v", "error"] + (["-c:v", "libvpx-vp9"] if ALPHA else []) + ["-i", mp, "-vf", f"scale={sw}:{sh}:flags=lanczos",
                            "-f", "rawvideo", "-pix_fmt", "rgba" if ALPHA else "rgb24", "-r", str(FPS), "-"], stdout=subprocess.PIPE)
    wr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                           "-i", audio or mp, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"] + ([] if full_len else ["-shortest"]) + [outp], stdin=subprocess.PIPE)
    # 重ねる範囲（画面の外にはみ出した分は切る）
    X0, Y0, X1, Y1 = max(0, x), max(0, y), min(W, x + sw), min(H, y + sh)
    n = 0; white = None; last_m = None
    while True:
        b = rd_bg.stdout.read(W * H * 3); m = rd_m.stdout.read(sw * sh * ch)
        if len(b) < W * H * 3: break
        if len(m) < sw * sh * ch:
            if not full_len or last_m is None: break
            m = last_m
        last_m = m
        img = np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()
        if ALPHA:
            rgba = np.frombuffer(m, np.uint8).reshape(sh, sw, 4)[Y0 - y:Y1 - y, X0 - x:X1 - x].astype(np.float32)
            a = rgba[:, :, 3:] / 255.0; reg = img[Y0:Y1, X0:X1].astype(np.float32)
            img[Y0:Y1, X0:X1] = (rgba[:, :, :3] * a + reg * (1 - a)).astype(np.uint8)
            wr.stdin.write(img.tobytes()); n += 1
            continue
        full = np.frombuffer(m, np.uint8).reshape(sh, sw, 3)
        if white is None:                # 圧縮で白が 251〜253 に落ちるので、四隅で測って 255 に戻す（戻さないと四角く暗く浮く）
            white = np.median(np.concatenate([full[:8, :8], full[:8, -8:], full[-8:, :8], full[-8:, -8:]]).reshape(-1, 3), 0).astype(np.float32)
        mm = np.clip(full[Y0 - y:Y1 - y, X0 - x:X1 - x].astype(np.float32) * (255.0 / white), 0, 255)
        reg = img[Y0:Y1, X0:X1].astype(np.float32)
        img[Y0:Y1, X0:X1] = (reg * mm / 255.0).astype(np.uint8)
        wr.stdin.write(img.tobytes()); n += 1
    wr.stdin.close(); wr.wait(); rd_bg.kill(); rd_m.kill()
    print(f"{n} コマ → {outp}", flush=True)


if __name__ == "__main__":
    main()
