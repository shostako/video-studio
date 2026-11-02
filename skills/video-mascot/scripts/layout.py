"""解説の画面を縮めた主動画（1920x1080、左に余白）の余白にマスコットを置き、左上に章の見出しを出して1本にする。
  vm layout <主動画.mp4> <作業フォルダ> --out 出力.mp4 [--style full|wipe] [--mascot 動画] [--frame full|bust] [--size S|L]
            [--wipe-size 400] [--wipe-box x,y,辺] [--bg-from 秒] [--audio 声.wav] [--full] [--chapters 章.json] [--margin 496] [--place-only]
  --style    full（既定。全身を余白の下に立たせる）か wipe（顔の周りを丸く切り抜いて余白の左下に置く）
  --wipe-size  ワイプの直径（既定は余白の幅 − 80 で、400 まで）
  --wipe-box   マスコットの動画のどこを切り抜くか（x,y,辺。画素）。既定は最初のコマの人物から顔の周りを測る。
             vm render --crop で顔の周りだけを書き出した動画（隣に <名前>.crop.json）は、そのまま丸にする
  --mascot   重ねるマスコット（既定 <作業フォルダ>/out/mascot.webm）。.webm は透明で、.mp4 は白背景を乗算で重ねる
  --frame    full（全身。既定）か bust（胸から上）。--size は大きさ（全身は S=高さ 560px・L=880px、胸から上は S=幅 340・L=496）
  --bg-from  主動画のどこから使うか（秒、既定 0）
  --audio    付ける声（既定 <作業フォルダ>/voice/master_clean.wav、無ければ master.wav）
  --full     主動画の最後まで書く（マスコットが先に終われば最後のコマのまま）。付けなければ短い方で終わる
  --chapters 章の見出しとサンプルの出どころ（下の形の JSON）。付けなければ見出しは出さない
  --margin   主動画の左の余白の幅（既定は主動画の隣の <名前>.layout.json の margin、無ければ 496）
  --place-only  位置を出すだけで書き出さない
  --fps      完成の動画のコマの速さ（既定 60）。vm explain の全身の型は 30
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
from lib import die, wipe_box
from check import probe as vprobe

W, H, FPS = 1920, 1080, 60   # FPS は --fps で変えられる
FIG_CX, FIG_TOP, FIG_FEET = 463, 195, 1521     # 立ち姿（941x1672）での体の中心 x・頭の上・足元。白背景の mp4 で測れないときの目安
INK, ACC, SUB = (28, 33, 44), (232, 120, 30), (110, 114, 122)
_WINFONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts") if os.name == "nt" else "/mnt/c/Windows/Fonts"
# Noto Sans CJK Bold が無いとき（Windows で直に動かすとき、WSL に fonts-noto-cjk を入れていないとき）は Windows の太字を使う
WIN_BOLD = tuple(os.path.join(_WINFONTS, f) for f in ("YuGothB.ttc", "BIZ-UDGothicB.ttc", "meiryob.ttc"))
FONTS = (os.environ.get("VIDEO_MASCOT_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc") + WIN_BOLD
HEAD_X, NUM_Y, TITLE_Y, RULE_Y, CREDIT_Y, CREDIT_STEP = 40, 44, 76, 128, 148, 30


def opt(name, default=None, typ=str):
    return typ(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


# 章の見出しの JSON は chapters.py（screen-explainer の compose.py と共通）
from chapters import chapter_plan, chapter_at, credit_alpha, fit_heading, heading_block  # noqa: E402,F401


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
    """章ごとの (番号, [(行の絵, y)], 下線の長さ, 下線の y) と、credits ごとの行の絵と、出どころの上端の y。
    見出しは余白（margin − 左右 40）に収め、長ければ 2 行に折る（chapters.fit_heading）。"""
    from PIL import ImageFont
    maxw = margin - 2 * HEAD_X; fp = font_path()
    def width_of(t, sz):
        b = ImageFont.truetype(fp, sz).getbbox(t); return b[2] - b[0]
    heads = []
    for _, num, title in plan:
        sz, rows = fit_heading(title, width_of, maxw); ys, ry = heading_block(sz, len(rows), TITLE_Y)
        ims = [(text_rgba(r, sz, INK, maxw), y) for r, y in zip(rows, ys)]
        heads.append((text_rgba(num, 22, ACC), ims, min(maxw, max([120] + [im.shape[1] for im, _ in ims])), ry))
    cred_y = max([RULE_Y] + [h[3] for h in heads]) + 20
    creds = [[text_rgba(x, 20, SUB, maxw) for x in c[2]] for c in credits]
    return heads, creds, cred_y


def heading_bottom(credits, heads_bottom=RULE_Y):
    """見出しの区画の下端（px）。マスコットの頭と重ならないかを見るのに使う。heads_bottom は見出しのいちばん下の下線の y。"""
    cy = max(RULE_Y, heads_bottom) + 20
    return max([heads_bottom + 3] + [cy + CREDIT_STEP * len(c[2]) for c in credits])


def draw_heading(img, t, plan, heads, credits, creds, cred_y=CREDIT_Y):
    k = chapter_at(t, plan)
    if k is not None:
        num, ims, rule, ry = heads[k]
        blend(img, num, HEAD_X, NUM_Y)
        for im, y in ims: blend(img, im, HEAD_X, y)
        img[ry - 1:ry + 2, HEAD_X:HEAD_X + rule] = ACC
    for (c0, c1, _), rows in zip(credits, creds):
        a = credit_alpha(t, c0, c1)
        if a > 0:
            for j, r in enumerate(rows): blend(img, r, HEAD_X, cred_y + CREDIT_STEP * j, a)


# ---------- 置き場所 ----------
def probe(p):
    """(幅, 高さ, 秒)。ffprobe の無い環境（CI）でも動く check.probe を使う。"""
    w, h, _, _, _, d = vprobe(p)
    return w, h, d


def place(mp, frame, size, margin):
    """マスコットの縮めた大きさと置く位置: (sw, sh, x, y, 人物の上端の y)。余白（左右 10px ずつ空ける）に収まらなければ、
    収まるまで小さくする（解説の画面にはみ出させない）。"""
    mw, mh, _ = probe(mp); cx_m = margin / 2; room = margin - 20
    if room < 60: die(f"余白が狭すぎてマスコットを置けない（{margin}px）")
    if frame == "full":
        k = mh / 1672; top, feet, cx = FIG_TOP * k, FIG_FEET * k, FIG_CX * k; x0f, x1f = cx - 0.3 * (feet - top), cx + 0.3 * (feet - top)
        if mp.endswith(".webm"):      # 透明の素材: 最初のコマのアルファから人物の上端・下端・中心・左右の端を測る（キャラで背が揃う）
            raw = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libvpx-vp9", "-i", mp, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout
            if len(raw) == mw * mh * 4:
                al = np.frombuffer(raw, np.uint8).reshape(mh, mw, 4)[:, :, 3] > 128; ys, xs = np.where(al)
                if len(ys):
                    top, feet = float(ys.min()), float(ys.max()); cx = float(np.median(xs[ys > ys.min() + 0.6 * (ys.max() - ys.min())]))
                    x0f, x1f = float(xs.min()), float(xs.max())
        s = {"L": 880, "S": 560}[size] / (feet - top)
        half = max(cx - x0f, x1f - cx)                # 体の中心から遠い方の端まで（身振りで少し広がる分は見込まない）
        if 2 * half * s > room:
            s2 = room / (2 * half); print(f"注意: 余白 {margin}px に収めるため、全身の高さを {round((feet - top) * s)}px から {round((feet - top) * s2)}px に縮めた", flush=True); s = s2
        sw, sh = round(mw * s), round(mh * s); x = round(cx_m - cx * s); y = round(1050 - feet * s)
        return sw, sh, x, y, round(y + top * s)
    want = {"L": margin, "S": 340}[size]
    if want > room: print(f"注意: 余白 {margin}px に収めるため、胸から上の幅を {want}px から {room}px に縮めた", flush=True); want = room
    s = want / mw; sw, sh = round(mw * s), round(mh * s)
    return sw, sh, round(cx_m - sw / 2), H - sh, H - sh


def first_frame(mp):
    """最初のコマの (幅, 高さ, 人物の画素の真偽の配列)。透明の webm はアルファ、白背景の mp4 は白でない所。"""
    mw, mh, _ = probe(mp); alpha = mp.endswith(".webm")
    raw = subprocess.run(["ffmpeg", "-v", "error"] + (["-c:v", "libvpx-vp9"] if alpha else []) + ["-i", mp, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgba" if alpha else "rgb24", "-"], capture_output=True).stdout
    nc = 4 if alpha else 3
    if len(raw) != mw * mh * nc: die(f"最初のコマが読めない: {mp}")
    a = np.frombuffer(raw, np.uint8).reshape(mh, mw, nc)
    return mw, mh, (a[:, :, 3] > 128) if alpha else (a.min(axis=2) < 235)


def face_box(fg):
    """人物の画素から、ワイプに切り抜く正方形 (x, y, 辺)（lib.wipe_box。vm render --crop face と同じ決め方）。"""
    box = wipe_box(fg)
    if box is None: die("最初のコマに人物が無い（--wipe-box で切り抜く所を渡す）")
    return box


def wipe_layers(d, pad=26):
    """ワイプの (下に敷く影の RGBA, 上に重ねる縁の RGBA, 丸の濃さ d x d)。影と縁の絵は (d+2pad) 角。screen-explainer の
    ワイプと同じ見た目（橙の太い縁と白の細い縁、下に影）。"""
    from PIL import Image, ImageDraw, ImageFilter
    n = d + 2 * pad
    sh = Image.new("RGBA", (n, n), (0, 0, 0, 0)); ImageDraw.Draw(sh).ellipse([pad - 2, pad + 6, pad + d + 2, pad + d + 14], fill=(0, 0, 0, 150))
    ring = Image.new("RGBA", (n, n), (0, 0, 0, 0)); dr = ImageDraw.Draw(ring)
    dr.ellipse([pad - 4, pad - 4, pad + d + 4, pad + d + 4], outline=ACC + (255,), width=8)
    dr.ellipse([pad + 4, pad + 4, pad + d - 4, pad + d - 4], outline=(255, 255, 255, 230), width=3)
    m = Image.new("L", (d * 4, d * 4), 0); ImageDraw.Draw(m).ellipse([0, 0, d * 4 - 1, d * 4 - 1], fill=255)
    return (np.asarray(sh.filter(ImageFilter.GaussianBlur(9))).copy(), np.asarray(ring).copy(),
            np.asarray(m.resize((d, d), Image.LANCZOS)).astype(np.float32)[:, :, None] / 255.0)


def main():
    global FPS
    FPS = opt("--fps", FPS, int)
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    vals = {sys.argv[i + 1] for i, x in enumerate(sys.argv[:-1]) if x.startswith("--") and x not in ("--full", "--place-only")}
    a = [x for x in a if x not in vals]
    if len(a) < 2: die(__doc__.split("\n\n")[0])
    bg, proj = a[0], a[1]
    outp = opt("--out")
    if not outp and "--place-only" not in sys.argv: die("--out が要る")
    mp = opt("--mascot", os.path.join(proj, "out", "mascot.webm"))
    lay = {}                                       # screen-explainer の compose.py --layout margin が書いた割り付け（余白の幅など）
    lp = os.path.splitext(bg)[0] + ".layout.json"
    if os.path.exists(lp): lay = json.load(open(lp))
    frame, size, margin = opt("--frame", "full"), opt("--size", "S"), opt("--margin", int(lay.get("margin", 496)), int)
    style = opt("--style", "full")
    if frame not in ("full", "bust") or size not in ("S", "L") or style not in ("full", "wipe"): die("--frame は full|bust、--size は S|L、--style は full|wipe")
    for p in (bg, mp):
        if not os.path.exists(p): die(f"無い: {p}")
    WIPE = style == "wipe"
    if WIPE:                                      # 顔の周りの正方形を切り抜き、直径 d の丸にして余白の左下（下から 48px）に置く
        cj = os.path.splitext(mp)[0] + ".crop.json"    # vm render --crop で、もう顔の周りだけを書き出した動画
        if opt("--wipe-box"): box = tuple(int(v) for v in opt("--wipe-box").split(","))
        elif os.path.exists(cj) and os.path.getmtime(cj) >= os.path.getmtime(mp):
            mw_, mh_, _ = probe(mp)
            if mw_ != mh_: die(f"切り抜き済みの動画が正方形でない（{mw_}x{mh_}）: {mp}")
            box = (0, 0, mw_); print(f"wipe: 切り抜き済みの動画を使う（{cj}: {json.load(open(cj)).get('box')}）", flush=True)
        else:
            box = face_box(first_frame(mp)[2])
        if len(box) != 3 or box[2] <= 0: die("--wipe-box は x,y,辺")
        sw = sh = opt("--wipe-size", min(400, (margin - 80) // 2 * 2), int)
        if sw < 120: die(f"余白が狭すぎてワイプを置けない（直径 {sw}px）。--scale を下げるか --wipe-size を渡す")
        lim = min(margin - 2 * 30, H - 48 - 300)  # 縁と影（26px）が余白の中、上は見出しの区画（〜300px）より下
        if sw > lim: die(f"--wipe-size {sw} が余白 {margin}px に入らない（{lim} まで）")
        x, y = round(margin / 2 - sw / 2), H - 48 - sw; fig_top = y
        print(f"wipe: 切り抜き {box[0]},{box[1]} 辺 {box[2]} → 直径 {sw} at ({x},{y})", flush=True)
    else:
        sw, sh, x, y, fig_top = place(mp, frame, size, margin)
        print(f"{frame} {size}: → {sw}x{sh} at ({x},{y})", flush=True)
    x0, y0 = max(0, x), max(0, y); cw, ch_ = min(x + sw, W) - x0, min(y + sh, H) - y0
    print(f"CROP {x0},{y0},{cw},{ch_}", flush=True)
    plan, credits, heads, creds, cred_y = [], [], [], [], CREDIT_Y
    if opt("--chapters") and lay.get("chapters"): print("注意: 主動画にもう章の見出しが描いてある（compose.py --chapters）。二重に出る", flush=True)
    if opt("--chapters"):
        tp = os.path.join(proj, "voice", "timing.json")
        starts = {x_["n"]: x_["start"] for x_ in json.load(open(tp))["lines"]} if os.path.exists(tp) else {}
        plan, credits = chapter_plan(json.load(open(opt("--chapters"))), starts)
        heads, creds, cred_y = heading_layers(plan, credits, margin)
        bot = heading_bottom(credits, max([RULE_Y] + [h[3] for h in heads]))
        print(f"見出し: {len(plan)} 章（{'・'.join(t for _, _, t in plan)}）、出どころ {len(credits)} 件。区画の下端 {bot}px、マスコットの頭 {fig_top}px", flush=True)
        if bot + 10 > fig_top: print(f"注意: 見出しの区画（下端 {bot}px）がマスコットの頭（{fig_top}px）に近い・重なる", flush=True)
    if "--place-only" in sys.argv: return
    audio = opt("--audio") or next((p for p in (os.path.join(proj, "voice", "master_clean.wav"), os.path.join(proj, "voice", "master.wav")) if os.path.exists(p)), None)
    if not audio: die("声が無い（--audio で渡す）")
    full_len = "--full" in sys.argv; _, _, dur = probe(mp); bg_from = opt("--bg-from", 0.0, float)

    rd_bg = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", str(bg_from)] + ([] if full_len else ["-t", f"{dur:.3f}"]) + ["-i", bg, "-vf", f"scale={W}:{H}",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-r", str(FPS), "-"], stdout=subprocess.PIPE)
    ALPHA = mp.endswith(".webm"); ch = 4 if ALPHA else 3
    vf = (f"crop={box[2]}:{box[2]}:{box[0]}:{box[1]}," if WIPE else "") + f"scale={sw}:{sh}:flags=lanczos"
    if WIPE: w_under, w_over, w_mask = wipe_layers(sw); WP = 26
    rd_m = subprocess.Popen(["ffmpeg", "-v", "error"] + (["-c:v", "libvpx-vp9"] if ALPHA else []) + ["-i", mp, "-vf", vf,
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
        if plan or credits: draw_heading(img, n / FPS, plan, heads, credits, creds, cred_y)
        if WIPE:                                  # 影 → 白地に重ねた顔を丸く → 縁
            blend(img, w_under, x - WP, y - WP)
            if ALPHA:
                rgba = np.frombuffer(m, np.uint8).reshape(sh, sw, 4).astype(np.float32); al = rgba[:, :, 3:] / 255.0
                face = rgba[:, :, :3] * al + 255.0 * (1 - al)
            else:
                face = np.frombuffer(m, np.uint8).reshape(sh, sw, 3).astype(np.float32)
            reg = img[y:y + sh, x:x + sw].astype(np.float32); img[y:y + sh, x:x + sw] = (face * w_mask + reg * (1 - w_mask)).astype(np.uint8)
            blend(img, w_over, x - WP, y - WP)
        elif ALPHA:
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
