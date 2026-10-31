"""解説の画面を縮めた主動画（1920x1080、左に余白）の余白にマスコットを置き、左上に章の見出しを出して1本にする。
  vm layout <主動画.mp4> <作業フォルダ> --out 出力.mp4 [--mascot 動画] [--frame full|bust] [--size S|L] [--bg-from 秒]
            [--audio 声.wav] [--full] [--chapters 章.json] [--margin 496] [--place-only]
  --mascot   重ねるマスコット（既定 <作業フォルダ>/out/mascot.webm）。.webm は透明で、.mp4 は白背景を乗算で重ねる
  --frame    full（全身。既定）か bust（胸から上）。--size は大きさ（全身は S=高さ 560px・L=880px、胸から上は S=幅 340・L=496）
  --bg-from  主動画のどこから使うか（秒、既定 0）
  --audio    付ける声（既定 <作業フォルダ>/voice/master_clean.wav、無ければ master.wav）
  --full     主動画の最後まで書く（マスコットが先に終われば最後のコマのまま）。付けなければ短い方で終わる
  --chapters 章の見出しとサンプルの出どころ（下の形の JSON）。付けなければ見出しは出さない
  --margin   主動画の左の余白の幅（既定 496。screen-explainer の画面の左端）
  --place-only  位置を出すだけで書き出さない
最後に CROP x,y,幅,高さ（完成の動画でマスコットのいる範囲）を出す。vm check <出力> --switches ... --crop に渡す。

章の JSON:
  {"chapters": [{"line": 1, "title": "cad-viewer の使い方"}, {"at": 24.0, "title": "視点を動かす"}, ...],
   "credits":  [{"from": 18, "to": 56, "text": ["サンプル: bearing.iges", "Open CASCADE 付属のデータ"]}, ...],
   "lead": 0.6}
  line は台詞の番号（voice/timing.json の n）で、その台詞の lead 秒前（既定 0.6）に見出しが替わる。at は秒で直に書く。
  見出しは左上に番号（01, 02, ...）・見出し・下線で出す。credits は見出しの下に小さく出す（サンプルの出典・許諾の表示に使う）。
"""
import json, os, subprocess, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import die
from check import probe as vprobe

W, H, FPS = 1920, 1080, 60
FIG_CX, FIG_TOP, FIG_FEET = 463, 195, 1521     # 立ち姿（941x1672）での体の中心 x・頭の上・足元。白背景の mp4 で測れないときの目安
INK, ACC, SUB = (28, 33, 44), (232, 120, 30), (110, 114, 122)
FONTS = (os.environ.get("VIDEO_MASCOT_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc")
HEAD_X, NUM_Y, TITLE_Y, RULE_Y, CREDIT_Y, CREDIT_STEP = 40, 44, 76, 128, 148, 30


def opt(name, default=None, typ=str):
    return typ(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


# ---------- 章の見出し（純関数）----------
def chapter_plan(spec, line_starts):
    """章の JSON（dict）と台詞の開始秒 {n: 秒} から、[(替わる秒, 番号の文字, 見出し), ...]（時刻の順）と credits を返す。
    line の章は台詞の lead 秒前に替わる（0 秒より前にはしない）。知らない台詞の番号や、line も at も無い章は止める。"""
    lead = float(spec.get("lead", 0.6)); out = []
    for k, c in enumerate(spec.get("chapters", [])):
        if "title" not in c: die(f"章 {k + 1} に title が無い")
        if "at" in c: t = float(c["at"])
        elif "line" in c:
            if c["line"] not in line_starts: die(f"章 {k + 1} の line {c['line']} が timing.json に無い")
            t = max(0.0, line_starts[c["line"]] - lead)
        else: die(f"章 {k + 1} に line も at も無い")
        out.append([t, c["title"]])
    out.sort(key=lambda x: x[0])
    plan = [(t, f"{k + 1:02d}", title) for k, (t, title) in enumerate(out)]
    credits = []
    for c in spec.get("credits", []):
        if not c.get("text"): die("credits に text が無い")
        credits.append((float(c.get("from", 0)), float(c.get("to", 1e9)), list(c["text"]) if isinstance(c["text"], list) else [c["text"]]))
    return plan, credits


def chapter_at(t, plan):
    """時刻 t に出す章の番号（plan の添字）。最初の章より前は最初の章。章が無ければ None。"""
    if not plan: return None
    k = 0
    for i, (t0, _, _) in enumerate(plan):
        if t0 <= t: k = i
    return k


def credit_alpha(t, c0, c1, fade=0.3):
    """サンプルの出どころの濃さ（0〜1）。c0 から fade 秒で出し、c1 で消す。"""
    if t < c0 or t >= c1: return 0.0
    return min(1.0, (t - c0) / fade) if fade > 0 else 1.0


# ---------- 描く ----------
def font_path():
    p = next((p for p in FONTS if p and os.path.exists(p)), None)
    if not p: die("日本語の太字のフォントが無い。VIDEO_MASCOT_FONT にフォントのパスを入れるか、fonts-noto-cjk を入れる")
    return p


def fit_text(text, width_of, maxw, min_size, size):
    """余白に収まる (字の大きさ, 文字)。maxw を超えるうちは字を 2px ずつ小さくし、min_size でも超えるなら末尾を「…」にして削る。
    width_of(文字, 大きさ) は描いたときの幅。"""
    while size > min_size and width_of(text, size) > maxw: size -= 2
    if width_of(text, size) <= maxw: return size, text
    t = text
    while t and width_of(t + "…", size) > maxw: t = t[:-1]
    return size, t + "…"


def text_rgba(text, size, color, maxw=None):
    """文字を透明の RGBA（numpy, 高さ x 幅 x 4）に。maxw より広ければ字を小さくし、16px でも広ければ末尾を「…」で切って収める。"""
    from PIL import Image, ImageDraw, ImageFont
    fp = font_path(); fonts = {}
    def width_of(t, sz):
        f = fonts.setdefault(sz, ImageFont.truetype(fp, sz)); b = f.getbbox(t); return b[2] - b[0]
    if maxw is not None: size, text = fit_text(text, width_of, maxw, 16, size)
    f = fonts.setdefault(size, ImageFont.truetype(fp, size)); b = f.getbbox(text)
    im = Image.new("RGBA", (max(1, b[2] - b[0]), max(1, b[3] - b[1])), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((-b[0], -b[1]), text, font=f, fill=color + (255,))
    return np.asarray(im).copy()


def blend(img, rgba, x, y, alpha=1.0):
    """img（RGB, uint8）の (x, y) に rgba を重ねる（はみ出しは切る）。"""
    h, w = rgba.shape[:2]; x0, y0 = max(0, x), max(0, y); x1, y1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 <= x0 or y1 <= y0: return
    s = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32); a = s[:, :, 3:] / 255.0 * alpha
    reg = img[y0:y1, x0:x1].astype(np.float32); img[y0:y1, x0:x1] = (s[:, :, :3] * a + reg * (1 - a)).astype(np.uint8)


def heading_layers(plan, credits, margin):
    """章ごとの (番号, 見出し, 下線の長さ) と、credits ごとの行の絵。見出しは余白（margin − 左右 40）に収める。"""
    maxw = margin - 2 * HEAD_X
    heads = [(text_rgba(num, 22, ACC), text_rgba(title, 34, INK, maxw)) for _, num, title in plan]
    heads = [(n, t, min(maxw, max(120, t.shape[1]))) for n, t in heads]
    creds = [[text_rgba(x, 20, SUB, maxw) for x in c[2]] for c in credits]
    return heads, creds


def heading_bottom(credits):
    """見出しの区画の下端（px）。マスコットの頭と重ならないかを見るのに使う。"""
    return max([RULE_Y + 3] + [CREDIT_Y + CREDIT_STEP * len(c[2]) for c in credits])


def draw_heading(img, t, plan, heads, credits, creds):
    k = chapter_at(t, plan)
    if k is not None:
        num, title, rule = heads[k]
        blend(img, num, HEAD_X, NUM_Y); blend(img, title, HEAD_X, TITLE_Y)
        img[RULE_Y - 1:RULE_Y + 2, HEAD_X:HEAD_X + rule] = ACC
    for (c0, c1, _), rows in zip(credits, creds):
        a = credit_alpha(t, c0, c1)
        if a > 0:
            for j, r in enumerate(rows): blend(img, r, HEAD_X, CREDIT_Y + CREDIT_STEP * j, a)


# ---------- 置き場所 ----------
def probe(p):
    """(幅, 高さ, 秒)。ffprobe の無い環境（CI）でも動く check.probe を使う。"""
    w, h, _, _, _, d = vprobe(p)
    return w, h, d


def place(mp, frame, size, margin):
    """マスコットの縮めた大きさと置く位置: (sw, sh, x, y, 人物の上端の y)。"""
    mw, mh, _ = probe(mp); cx_m = margin / 2
    if frame == "full":
        k = mh / 1672; top, feet, cx = FIG_TOP * k, FIG_FEET * k, FIG_CX * k
        if mp.endswith(".webm"):      # 透明の素材: 最初のコマのアルファから人物の上端・下端・中心を測る（キャラで背が揃う）
            raw = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", mp, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout
            if len(raw) == mw * mh * 4:
                al = np.frombuffer(raw, np.uint8).reshape(mh, mw, 4)[:, :, 3] > 128; ys, xs = np.where(al)
                if len(ys): top, feet = float(ys.min()), float(ys.max()); cx = float(np.median(xs[ys > ys.min() + 0.6 * (ys.max() - ys.min())]))
        s = {"L": 880, "S": 560}[size] / (feet - top)
        sw, sh = round(mw * s), round(mh * s); x = round(cx_m - cx * s); y = round(1050 - feet * s)
        return sw, sh, x, y, round(y + top * s)
    s = {"L": margin, "S": 340}[size] / mw; sw, sh = round(mw * s), round(mh * s)
    return sw, sh, round(cx_m - sw / 2), H - sh, H - sh


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    vals = {sys.argv[i + 1] for i, x in enumerate(sys.argv[:-1]) if x.startswith("--") and x not in ("--full", "--place-only")}
    a = [x for x in a if x not in vals]
    if len(a) < 2: die(__doc__.split("\n\n")[0])
    bg, proj = a[0], a[1]
    outp = opt("--out")
    if not outp and "--place-only" not in sys.argv: die("--out が要る")
    mp = opt("--mascot", os.path.join(proj, "out", "mascot.webm"))
    frame, size, margin = opt("--frame", "full"), opt("--size", "S"), opt("--margin", 496, int)
    if frame not in ("full", "bust") or size not in ("S", "L"): die("--frame は full|bust、--size は S|L")
    for p in (bg, mp):
        if not os.path.exists(p): die(f"無い: {p}")
    sw, sh, x, y, fig_top = place(mp, frame, size, margin)
    print(f"{frame} {size}: → {sw}x{sh} at ({x},{y})", flush=True)
    x0, y0 = max(0, x), max(0, y); cw, ch_ = min(x + sw, W) - x0, min(y + sh, H) - y0
    print(f"CROP {x0},{y0},{cw},{ch_}", flush=True)
    plan, credits = [], []
    if opt("--chapters"):
        tp = os.path.join(proj, "voice", "timing.json")
        starts = {x_["n"]: x_["start"] for x_ in json.load(open(tp))["lines"]} if os.path.exists(tp) else {}
        plan, credits = chapter_plan(json.load(open(opt("--chapters"))), starts)
        bot = heading_bottom(credits)
        print(f"見出し: {len(plan)} 章（{'・'.join(t for _, _, t in plan)}）、出どころ {len(credits)} 件。区画の下端 {bot}px、マスコットの頭 {fig_top}px", flush=True)
        if bot + 10 > fig_top: print(f"注意: 見出しの区画（下端 {bot}px）がマスコットの頭（{fig_top}px）に近い・重なる", flush=True)
    if "--place-only" in sys.argv: return
    audio = opt("--audio") or next((p for p in (os.path.join(proj, "voice", "master_clean.wav"), os.path.join(proj, "voice", "master.wav")) if os.path.exists(p)), None)
    if not audio: die("声が無い（--audio で渡す）")
    full_len = "--full" in sys.argv; _, _, dur = probe(mp); bg_from = opt("--bg-from", 0.0, float)
    heads, creds = heading_layers(plan, credits, margin) if plan or credits else ([], [])

    rd_bg = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(bg_from)] + ([] if full_len else ["-t", f"{dur:.3f}"]) + ["-i", bg, "-vf", f"scale={W}:{H}",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-r", str(FPS), "-"], stdout=subprocess.PIPE)
    ALPHA = mp.endswith(".webm"); ch = 4 if ALPHA else 3
    rd_m = subprocess.Popen(["ffmpeg", "-v", "error"] + (["-c:v", "libvpx-vp9"] if ALPHA else []) + ["-i", mp, "-vf", f"scale={sw}:{sh}:flags=lanczos",
                            "-f", "rawvideo", "-pix_fmt", "rgba" if ALPHA else "rgb24", "-r", str(FPS), "-"], stdout=subprocess.PIPE)
    tmp = outp + ".part.mp4"
    wr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                           "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
                          + ([] if full_len else ["-shortest"]) + [tmp], stdin=subprocess.PIPE)
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
        if plan or credits: draw_heading(img, n / FPS, plan, heads, credits, creds)
        if ALPHA:
            rgba = np.frombuffer(m, np.uint8).reshape(sh, sw, 4)[Y0 - y:Y1 - y, X0 - x:X1 - x].astype(np.float32)
            al = rgba[:, :, 3:] / 255.0; reg = img[Y0:Y1, X0:X1].astype(np.float32)
            img[Y0:Y1, X0:X1] = (rgba[:, :, :3] * al + reg * (1 - al)).astype(np.uint8)
        else:
            full = np.frombuffer(m, np.uint8).reshape(sh, sw, 3)
            if white is None:            # 圧縮で白が 251〜253 に落ちるので、四隅で測って 255 に戻す（戻さないと四角く暗く浮く）
                white = np.median(np.concatenate([full[:8, :8], full[:8, -8:], full[-8:, :8], full[-8:, -8:]]).reshape(-1, 3), 0).astype(np.float32)
            mm = np.clip(full[Y0 - y:Y1 - y, X0 - x:X1 - x].astype(np.float32) * (255.0 / white), 0, 255)
            img[Y0:Y1, X0:X1] = (img[Y0:Y1, X0:X1].astype(np.float32) * mm / 255.0).astype(np.uint8)
        wr.stdin.write(img.tobytes()); n += 1
    wr.stdin.close(); rc = wr.wait(); rd_bg.kill(); rd_m.kill()
    if rc != 0 or n == 0: die(f"書き出しに失敗（{n} コマ）")
    os.replace(tmp, outp)
    print(f"{n} コマ → {outp}", flush=True)


if __name__ == "__main__":
    main()
