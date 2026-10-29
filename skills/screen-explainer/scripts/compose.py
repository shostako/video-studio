"""画面操作の解説動画を組む。撮った画面（<名前>.png）に、寄り（カメラ）・目立つカーソル・枠の強調・クリックの波紋・キーの札・字幕・
口パクのワイプを重ね、声（master.wav）を付けて mp4 にする。場面の割り付けは別のファイル（scenes.py）に書く。

usage:
  python3 compose.py --shots <撮影フォルダ> --voice <声の作業フォルダ> --scenes <scenes.py> --out <出力.mp4>
                     [--wipe <口の絵のフォルダ>] [--clip-bottom 948] [--clip-right 1895]
                     [--from 秒 --to 秒] [--preview 秒,秒,...]
  撮影フォルダ : <名前>.png（1920×1020 か、それ以上の高さ。上 1020 を使う）と rects.json（{名前: {キー: [x0,y0,x1,y1]}}）
  声の作業フォルダ: config.json（voice.lines[].text が字幕）、voice/master.wav、voice/timing.json（vm voice master の出力）
  --wipe        : mouth0.png〜mouth3.png（440×440、円 (220,238) 半径 200 に顔と肩）。閉じ→小→中→大の順。無ければワイプを出さない
  --clip-bottom : 強調の枠の下端をここで切る（Excel はシート見出しの上 948、ブラウザは 1016）
  --preview     : 指定の時刻のコマを <出力>_t<秒>.png に書くだけ（動画は作らない）

scenes.py の中で使える名前: R（rects.json）, rc(画像, キー), ctr(画像, キー), box(*枠, pad=), FULL, W, VIEW_H, add(...)
add(imgs=[(割合, 画像名)], cam=[(割合, 枠)], cur=[(割合, (x, y))], hl=[(割合の始め, 割合の終わり, 枠)],
    click=[割合], key=[(割合, "文字")])
  1 行の台詞に 1 回 add する。割合は、その行の声の長さに対する位置（0〜1、1 を超えると次の行の頭まで残る）。
"""
import argparse, array, json, math, os, subprocess, sys, wave
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("--shots", required=True); ap.add_argument("--voice", required=True)
ap.add_argument("--scenes", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--wipe"); ap.add_argument("--clip-bottom", type=float, default=1016); ap.add_argument("--clip-right", type=float, default=1920)
ap.add_argument("--from", dest="t_from", type=float, default=0.0); ap.add_argument("--to", dest="t_to", type=float)
ap.add_argument("--preview", default="")
A = ap.parse_args()

W, H, VIEW_H, FPS = 1920, 1080, 1020, 30
BAND = H - VIEW_H
FONT = next((p for p in (os.environ.get("SCREEN_EXPLAINER_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                          "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc") if p and os.path.exists(p)), None)
if not FONT: sys.exit("ERROR: 日本語の太字フォント（Noto Sans CJK Bold）が無い。fonts-noto-cjk を入れるか、SCREEN_EXPLAINER_FONT に太字のフォントを指定する")

R = json.load(open(os.path.join(A.shots, "rects.json"), encoding="utf-8"))
timing = json.load(open(os.path.join(A.voice, "voice", "timing.json")))
texts = [l["text"] for l in json.load(open(os.path.join(A.voice, "config.json"), encoding="utf-8"))["voice"]["lines"]]
LINES = timing["lines"]; END = timing["end"] + 0.8

_img = {}
def img(n):
    if n not in _img: _img[n] = Image.open(os.path.join(A.shots, n + ".png")).convert("RGB").crop((0, 0, W, VIEW_H))
    return _img[n]

def rc(s, k):
    x0, y0, x1, y1 = R[s][k]
    return [max(0, x0), max(0, y0), min(x1, A.clip_right), min(y1, A.clip_bottom)]
def ctr(s, k):
    x0, y0, x1, y1 = rc(s, k); return ((x0 + x1) / 2, (y0 + y1) / 2)
def box(*rs, pad=60):
    return [min(r[0] for r in rs) - pad, min(r[1] for r in rs) - pad, max(r[2] for r in rs) + pad, max(r[3] for r in rs) + pad]
FULL = [0, 0, W, VIEW_H]

S = []
def add(**k):
    for key in ("imgs", "cam", "cur"):
        if not k.get(key): sys.exit(f"ERROR: 場面 {len(S) + 1} に {key} が無い")
    k.setdefault("hl", []); k.setdefault("click", []); k.setdefault("key", []); S.append(k)
ns = dict(R=R, rc=rc, ctr=ctr, box=box, FULL=FULL, W=W, VIEW_H=VIEW_H, add=add)
exec(compile(open(A.scenes, encoding="utf-8").read(), A.scenes, "exec"), ns)
if len(S) != len(LINES): sys.exit(f"ERROR: 場面の数 {len(S)} と台詞の行の数 {len(LINES)} が合わない")

# 場面の時刻：行の頭の 0.25 秒前から、次の行の頭の 0.25 秒前まで。割合は行の声の長さで測る
for i, s in enumerate(S):
    s["t0"] = 0.0 if i == 0 else LINES[i]["start"] - 0.25
    s["t1"] = (LINES[i + 1]["start"] - 0.25) if i + 1 < len(LINES) else END
    s["d"] = LINES[i]["start"] + LINES[i]["dur"] - s["t0"]

def ease(u):
    u = max(0.0, min(1.0, u)); return u * u * (3 - 2 * u)

def track(keys, u, mv=0.18, d=1.0):
    """keys=[(割合, 値)] を、各キーに向かって mv 秒かけて動く線にする。値は数の組。"""
    cur = keys[0][1]
    for k, (a, v) in enumerate(keys):
        if u < a: break
        span = mv / d if d else 0
        dur = min(span, (keys[k + 1][0] - a) if k + 1 < len(keys) else span) or 1e-6
        e = ease((u - a) / dur)
        cur = tuple(c + (n - c) * e for c, n in zip(cur, v))
    return cur

def scene_at(t):
    for s in S:
        if s["t0"] <= t < s["t1"]: return s
    return S[-1]

# 字幕：行を句点で切り、文字数の割合で時間を配る
SUBS = []
for i, l in enumerate(LINES):
    parts = [p + "。" for p in texts[i].split("。") if p]
    tot = sum(len(p) for p in parts) or 1; t = l["start"]
    for j, p in enumerate(parts):
        d = l["dur"] * len(p) / tot
        SUBS.append((t, t + d + (0.35 if j == len(parts) - 1 else 0), p)); t += d
f_sub = ImageFont.truetype(FONT, 36, index=0)
f_key = ImageFont.truetype(FONT, 40, index=0)

# カーソル：太い橙の矢印（白縁・影）と、先端の黄色の光の輪
def make_cursor(sc=2):
    im = Image.new("RGBA", (140 * sc, 140 * sc), (0, 0, 0, 0))
    pts = [(20 * sc + x * sc * 1.05, 20 * sc + y * sc * 1.05) for x, y in [(0, 0), (0, 74), (18, 58), (31, 88), (45, 82), (32, 53), (56, 53)]]
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).polygon([(x + 6 * sc, y + 8 * sc) for x, y in pts], fill=(0, 0, 0, 120))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5 * sc)))
    d = ImageDraw.Draw(im)
    d.polygon(pts, fill=(255, 255, 255, 255)); d.line(pts + [pts[0]], fill=(255, 255, 255, 255), width=12 * sc, joint="curve")
    d.polygon(pts, fill=(255, 92, 0, 255)); d.line(pts + [pts[0]], fill=(255, 255, 255, 255), width=4 * sc, joint="curve")
    return im.resize((140, 140), Image.LANCZOS), (20, 20)
CUR, HOT = make_cursor()
def halo(r, a):
    im = Image.new("RGBA", (2 * r + 20, 2 * r + 20), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([10, 10, 10 + 2 * r, 10 + 2 * r], fill=(255, 225, 0, int(95 * a)), outline=(255, 170, 0, int(230 * a)), width=5)
    return im

# ワイプ：丸く切り抜いた顔（口の絵 4 枚）。場面ごとに、強調の枠とカーソルに一番かからない角へ置き、場面の頭 0.6 秒で滑らせる
WD = 300
def make_wipe(path):
    face = Image.open(path).convert("RGB").crop((20, 38, 420, 438)).resize((WD, WD), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", (WD * 4, WD * 4), 0); ImageDraw.Draw(m).ellipse([0, 0, WD * 4 - 1, WD * 4 - 1], fill=255)
    face.putalpha(m.resize((WD, WD), Image.LANCZOS))
    P = 26; out = Image.new("RGBA", (WD + 2 * P, WD + 2 * P), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).ellipse([P - 2, P + 6, P + WD + 2, P + WD + 14], fill=(0, 0, 0, 150))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9))); out.alpha_composite(face, (P, P))
    ImageDraw.Draw(out).ellipse([P - 4, P - 4, P + WD + 4, P + WD + 4], outline=(255, 92, 0, 255), width=8)
    ImageDraw.Draw(out).ellipse([P + 4, P + 4, P + WD - 4, P + WD - 4], outline=(255, 255, 255, 230), width=3)
    return out
WIPE = [make_wipe(os.path.join(A.wipe, f"mouth{i}.png")) for i in range(4)] if A.wipe else None
if WIPE:
    WWD, WHT = WIPE[0].size
    CORNERS = {"BR": (W - WWD - 14, VIEW_H - WHT - 6), "TR": (W - WWD - 14, 6), "BL": (14, VIEW_H - WHT - 6), "TL": (14, 6)}

# 声の大きさ（1/30 秒ごと）→ 口の段（0 閉じ〜3）。変えたら 2 コマは保つ
def mouth_shapes(path):
    w = wave.open(path); sr = w.getframerate(); ch = w.getnchannels()
    pcm = array.array("h", w.readframes(w.getnframes())); w.close()
    if ch > 1: pcm = pcm[::ch]
    hop = sr // FPS; env = [math.sqrt(sum(x * x for x in pcm[i:i + hop]) / max(1, len(pcm[i:i + hop]))) / 32768 for i in range(0, len(pcm), hop)]
    pk = sorted(env)[int(len(env) * 0.97)] if env else 1
    out, last, hold = [], 0, 0
    for i, e in enumerate(env):
        v = e / (pk or 1)
        want = 0 if v < 0.10 else 1 if v < 0.35 else 2 if v < 0.7 else 3
        if want > 0 and want == last and i % 4 == 0: want = max(1, want - 1)   # 長い母音でも少し動かす
        if hold > 0 and want != 0: want, hold = last, hold - 1
        elif want != last: hold = 1
        out.append(want); last = want
    return out
SHAPE = mouth_shapes(os.path.join(A.voice, "voice", "master.wav")) if WIPE else []
def mouth_at(t):
    i = int(t * FPS); return SHAPE[i] if 0 <= i < len(SHAPE) else 0

def view_of(cam):
    x0, y0, x1, y1 = cam; w, h = x1 - x0, y1 - y0; asp = W / VIEW_H
    if w / h > asp: h = w / asp
    else: w = h * asp
    w = min(max(w, W / 2.3), W); h = w / asp                      # 寄りは 2.3 倍まで
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return min(max(cx - w / 2, 0), W - w), min(max(cy - h / 2, 0), VIEW_H - h), w, h

def cur_screen(t):
    s = scene_at(t); u = (t - s["t0"]) / s["d"]
    vx, vy, vw, vh = view_of(track(s["cam"], u, mv=0.9, d=s["d"])); z = W / vw
    x, y = track(s["cur"], u, mv=0.55, d=s["d"]); return ((x - vx) * z, (y - vy) * z)

def _corner(s):
    vx, vy, vw, vh = view_of(s["cam"][-1][1]); z = W / vw
    rs = [[(r[0] - vx) * z, (r[1] - vy) * z, (r[2] - vx) * z, (r[3] - vy) * z] for a, b, r in s["hl"] if b > 0.5]
    pts = [((x - vx) * z, (y - vy) * z) for a, (x, y) in s["cur"] if a >= 0.3]
    best = None
    for name in ("BR", "TR", "BL", "TL"):
        x0, y0 = CORNERS[name]; x1, y1 = x0 + WWD, y0 + WHT
        ov = sum(max(0, min(x1, r[2]) - max(x0, r[0])) * max(0, min(y1, r[3]) - max(y0, r[1])) for r in rs)
        ov += sum(4e4 for px, py in pts if x0 - 60 < px < x1 + 20 and y0 - 60 < py < y1 + 20)
        if best is None or ov < best[0] - 1: best = (ov, name)
    return best[1]
if WIPE:
    for s in S: s["corner"] = s.get("corner") or _corner(s)
def wipe_pos(t):
    s = scene_at(t); i = S.index(s); cur = CORNERS[s["corner"]]
    if i == 0: return cur
    prev = CORNERS[S[i - 1]["corner"]]; e = ease((t - s["t0"]) / 0.6)
    return (prev[0] + (cur[0] - prev[0]) * e, prev[1] + (cur[1] - prev[1]) * e)

def frame(t):
    s = scene_at(t); u = (t - s["t0"]) / s["d"]
    names = s["imgs"]; k = max((i for i, (a, _) in enumerate(names) if u >= a), default=0)
    base = img(names[k][1])
    if k > 0:                                                        # 場面の中の切り替えは 0.25 秒で重ねる
        a = (u - names[k][0]) * s["d"] / 0.25
        if a < 1: base = Image.blend(img(names[k - 1][1]), base, max(0, a))
    else:
        si = S.index(s)
        if si > 0 and (t - s["t0"]) < 0.25 and S[si - 1]["imgs"][-1][1] != names[0][1]:
            base = Image.blend(img(S[si - 1]["imgs"][-1][1]), base, (t - s["t0"]) / 0.25)
    vx, vy, vw, vh = view_of(track(s["cam"], u, mv=0.9, d=s["d"])); z = W / vw
    fr = base.crop((int(vx), int(vy), int(vx + vw), int(vy + vh))).resize((W, VIEW_H), Image.BILINEAR).convert("RGBA")
    tr = lambda x, y: ((x - vx) * z, (y - vy) * z)
    ov = Image.new("RGBA", (W, VIEW_H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    for a, b, r in s["hl"]:                                          # 強調の枠（現れて 0.35 秒で太さが落ち着く）
        if not (a <= u <= b): continue
        el = (u - a) * s["d"]; al = min(1, el / 0.25) * (min(1, (b - u) * s["d"] / 0.25) if b <= 1 else 1)
        x0, y0 = tr(r[0], r[1]); x1, y1 = tr(r[2], r[3]); g = 6 + 10 * max(0, 1 - el / 0.35)
        d.rounded_rectangle([x0 - g, y0 - g, x1 + g, y1 + g], radius=12, fill=(255, 60, 40, int(28 * al)), outline=(255, 50, 30, int(235 * al)), width=6)
    for c in s["click"]:                                             # クリックの波紋
        el = (u - c) * s["d"]
        if 0 <= el < 0.6:
            cx, cy = tr(*track(s["cur"], c, mv=0.55, d=s["d"])); r = 18 + 70 * (el / 0.6)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 90, 0, int(255 * (1 - el / 0.6))), width=8)
    for a, txt in s["key"]:                                          # 打ち込んだキーの札
        el = (u - a) * s["d"]
        if 0 <= el < 1.1:
            al = min(1, el / 0.15) * min(1, (1.1 - el) / 0.3); tw = d.textlength(txt, font=f_key); bx = W - 120 - tw
            d.rounded_rectangle([bx - 30, 70, W - 90, 150], radius=14, fill=(30, 30, 30, int(220 * al)), outline=(255, 140, 0, int(255 * al)), width=4)
            d.text((bx, 84), txt, font=f_key, fill=(255, 255, 255, int(255 * al)))
    fr.alpha_composite(ov)
    if WIPE:                                                         # ワイプはカーソルより下に描く
        wx, wy = wipe_pos(t); fr.alpha_composite(WIPE[mouth_at(t)], (int(wx), int(wy)))
    cx, cy = cur_screen(t); p = 0.5 + 0.5 * math.sin(t * 2 * math.pi * 1.2); hr = int(40 + 6 * p)
    fr.alpha_composite(halo(hr, 0.8 + 0.2 * p), (int(cx - hr - 10), int(cy - hr - 10)))
    fr.alpha_composite(CUR, (int(cx - HOT[0]), int(cy - HOT[1])))
    out = Image.new("RGB", (W, H), (22, 24, 28)); out.paste(fr.convert("RGB"), (0, 0)); dd = ImageDraw.Draw(out)
    for a, b, txt in SUBS:                                           # 字幕の帯
        if a <= t < b:
            dd.text(((W - dd.textlength(txt, font=f_sub)) / 2, VIEW_H + (BAND - 46) / 2), txt, font=f_sub, fill=(255, 255, 255)); break
    return out

if A.preview:
    for t in [float(x) for x in A.preview.split(",") if x]:
        p = os.path.splitext(A.out)[0] + f"_t{t:06.2f}.png"; frame(t).save(p); print("preview", p)
    sys.exit(0)

t_to = A.t_to if A.t_to is not None else END
cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
       "-ss", str(A.t_from), "-t", str(t_to - A.t_from), "-i", os.path.join(A.voice, "voice", "master.wav"),
       "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest",
       "-f", "mp4", A.out + ".part"]                                  # 書き終えてから名前を付け替える（途中で止まっても前の動画を壊さない）
pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
for n in range(int(A.t_from * FPS), int(t_to * FPS)):
    pr.stdin.write(frame(n / FPS).tobytes())
    if n % 300 == 0: print(f"{n / FPS:.1f}s / {t_to:.1f}s", flush=True)
pr.stdin.close()
if pr.wait() != 0: sys.exit("ERROR: ffmpeg が失敗した")
os.replace(A.out + ".part", A.out)
print("out", A.out, f"{t_to - A.t_from:.1f}s")
