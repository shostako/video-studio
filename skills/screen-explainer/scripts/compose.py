"""画面操作の解説動画を組む。撮った画面（<名前>.png）に、寄り（カメラ）・目立つカーソル・枠の強調・クリックの波紋・キーの札・字幕・
口パクのワイプを重ね、声（master.wav）を付けて mp4 にする。場面の割り付けは別のファイル（scenes.py）に書く。

usage:
  python3 compose.py --shots <撮影フォルダ> --voice <声の作業フォルダ> --scenes <scenes.py> --out <出力.mp4>
                     [--wipe <口の絵のフォルダ>] [--wipe-home BR] [--clip-bottom 948] [--clip-right 1895]
                     [--from 秒 --to 秒] [--preview 秒,秒,...] [--layout full|margin] [--scale 0.73] [--chapters 章.json]
  撮影フォルダ : <名前>.png（1920×1020 か、それ以上の高さ。上 1020 を使う）と rects.json（{名前: {キー: [x0,y0,x1,y1]}}）
  声の作業フォルダ: config.json（voice.lines[].text が字幕）、voice/master.wav、voice/timing.json（vm voice master の出力）
  --wipe        : mouth0.png〜mouth3.png（440×440、円 (220,238) 半径 200 に顔と肩）。閉じ→小→中→大の順。無ければワイプを出さない
  --wipe-home   : ワイプを置く角の第一候補（BR・BL・TR・TL、既定 BR）。右に操作パネルのあるアプリは BL にする。
                  強調の枠・カーソル・キーの札に重なる場面だけ、ほかの角へ移る
  --clip-bottom : 強調の枠の下端をここで切る（Excel はシート見出しの上 948、ブラウザは 1016）
  --preview     : 指定の時刻のコマを <出力>_t<秒>.png に書くだけ（動画は作らない）
  --layout      : full（既定。画面を全面に出し、下に字幕の帯）か margin（画面を --scale の倍率に縮めて右に寄せ、字幕はその下。
                  左の余白にはマスコット（vm layout で全身かワイプ）を置く）。margin では --wipe は使えない
  --scale       : margin の画面の倍率（0.5〜0.9、既定 0.73＝幅 1400・余白 496）。上げると画面の字は大きく、余白は狭くなる
  --chapters    : 章の見出しの JSON（video-mascot の chapters.py の形）。full は章が替わった所で左上に数秒出して消し、
                  margin は余白の左上に出し続ける（サンプルの出どころ credits も余白に出す）
  書き出すと <出力>.layout.json（割り付け: 余白の幅、画面の位置、見出しを描いたか）も書く。vm layout はこれを読んで合わせる

scenes.py の中で使える名前: R（rects.json）, rc(画像, キー), ctr(画像, キー), box(*枠, pad=), FULL, W, VIEW_H, add(...)
add(imgs=[(割合, 画像名)], cam=[(割合, 枠)], cur=[(割合, (x, y))], hl=[(割合の始め, 割合の終わり, 枠)],
    click=[割合], key=[(割合, "文字")], film=[(割合の始め, 割合の終わり, "名前")])
  1 行の台詞に 1 回 add する。割合は、その行の声の長さに対する位置（0〜1、1 を超えると次の行の頭まで残る）。
  film は web_capture.py の drag_film / wheel_film で撮った連番（<名前>_000.png…）を、その間に重ねずに順に流す。
  カーソルも film.json の位置をたどる。流し終えた後は imgs の絵に戻るので、film の始めから終わりまでのどこかで imgs を動きの後の撮影に
  切り替える（その切り替えは重ねない）。
"""
import argparse, array, json, math, os, subprocess, sys, wave
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("--shots", required=True); ap.add_argument("--voice", required=True)
ap.add_argument("--scenes", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--wipe"); ap.add_argument("--wipe-home", default="BR", choices=["BR", "BL", "TR", "TL"]); ap.add_argument("--clip-bottom", type=float, default=1016); ap.add_argument("--clip-right", type=float, default=1920)
ap.add_argument("--from", dest="t_from", type=float, default=0.0); ap.add_argument("--to", dest="t_to", type=float)
ap.add_argument("--preview", default="")
ap.add_argument("--layout", default="full", choices=["full", "margin"]); ap.add_argument("--scale", type=float, default=0.73)
ap.add_argument("--chapters")
A = ap.parse_args()

W, H, VIEW_H, FPS = 1920, 1080, 1020, 30
BAND = H - VIEW_H
FONT = next((p for p in (os.environ.get("SCREEN_EXPLAINER_FONT"), "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                          "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc") if p and os.path.exists(p)), None)
if not FONT: sys.exit("ERROR: 日本語の太字フォント（Noto Sans CJK Bold）が無い。fonts-noto-cjk を入れるか、SCREEN_EXPLAINER_FONT に太字のフォントを指定する")

# 割り付け。margin: 画面を縮めて右に寄せ（右の隙間 24、上 34）、左の余白にマスコットを置く。字幕は画面の下に濃い字で
MARGIN = A.layout == "margin"
if MARGIN:
    if A.wipe: sys.exit("ERROR: --layout margin ではワイプを compose で重ねない（余白に vm layout で置く）。--wipe を外す")
    if not 0.5 <= A.scale <= 0.9: sys.exit(f"ERROR: --scale は 0.5〜0.9: {A.scale}")
    PW = int(W * A.scale / 2) * 2; PH = int(round(PW * VIEW_H / W / 2)) * 2   # 0.73 で幅 1400・余白 496
    PX, PY = W - 24 - PW, 34
    if PX < 200: sys.exit(f"ERROR: --scale {A.scale} では余白が {PX}px しか無い（マスコットを置けない）")
LIGHT, INK, ACC, SUBC = (247, 246, 244), (28, 33, 44), (232, 120, 30), (110, 114, 122)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "video-mascot", "scripts"))
import chapters as CH  # noqa: E402

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
    k.setdefault("hl", []); k.setdefault("click", []); k.setdefault("key", []); k.setdefault("film", []); S.append(k)
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

FILM = json.load(open(os.path.join(A.shots, "film.json"), encoding="utf-8")) if os.path.exists(os.path.join(A.shots, "film.json")) else {}
for s in S:
    for a, b, name in s["film"]:
        if name not in FILM: sys.exit(f"ERROR: film {name} が film.json に無い（web_capture.py の drag_film / wheel_film で撮る）")

def film_at(s, u):
    """その場面で流している連番の (コマの絵の名前, カーソルの位置)。流していなければ None"""
    for a, b, name in s["film"]:
        if a <= u < b:
            n = len(FILM[name]); k = min(n - 1, int((u - a) / (b - a) * n))
            return f"{name}_{k:03d}", FILM[name][k]
    return None

def film_img(n):                                                     # 連番は枚数が多いので覚えておかない
    return Image.open(os.path.join(A.shots, n + ".png")).convert("RGB").crop((0, 0, W, VIEW_H))

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

def text_w(f, t):
    b = f.getbbox(t); return b[2] - b[0]

def fit(text, size, maxw, min_size=16):
    """maxw に収まる (フォント, 文字)。字を 2px ずつ小さくし、min_size でも広ければ末尾を「…」で切る。"""
    while size > min_size and text_w(ImageFont.truetype(FONT, size, index=0), text) > maxw: size -= 2
    f = ImageFont.truetype(FONT, size, index=0)
    if text_w(f, text) > maxw:
        while text and text_w(f, text + "…") > maxw: text = text[:-1]
        text += "…"
    return f, text

def text_img(text, f, color):
    b = f.getbbox(text); im = Image.new("RGBA", (max(1, b[2] - b[0]), max(1, b[3] - b[1])), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((-b[0], -b[1]), text, font=f, fill=color + (255,)); return im

def faded(im, a):
    if a >= 1: return im
    im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * a))); return im

def wrap(text, f, maxw):
    """字幕の折り返し: 句読点・』」・空白の後ろで切る（幅が収まる最後の区切り）。"""
    out, cur = [], ""
    for ch in text:
        cur += ch
        if text_w(f, cur) > maxw:
            cut = max(cur.rfind(c) for c in "、。』」 ")
            if cut <= 0: cut = len(cur) - 2
            out.append(cur[:cut + 1]); cur = cur[cut + 1:]
    if cur: out.append(cur)
    return out

CHP, CRD = CH.load(A.chapters, os.path.join(A.voice, "voice", "timing.json")) if A.chapters else ([], [])
if MARGIN:
    # 背景（影つきの角丸の枠）と角丸のマスク
    BGM = Image.new("RGB", (W, H), LIGHT); shd = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shd).rectangle([PX + 6, PY + 14, PX + PW - 6, PY + PH + 10], fill=int(255 * 0.28))
    BGM.paste((0, 0, 0), (0, 0), shd.filter(ImageFilter.GaussianBlur(18)))
    PMASK = Image.new("L", (PW * 2, PH * 2), 0); ImageDraw.Draw(PMASK).rounded_rectangle([0, 0, PW * 2 - 1, PH * 2 - 1], radius=32, fill=255)
    PMASK = PMASK.resize((PW, PH), Image.LANCZOS)
    # 字幕: 行ごとに全文を、画面の下の空きに収まる大きさで（字が多ければ小さく）。出す時間は隣の行と重ならない窓にし、
    # 18px でも入らない行は文（。）ごとに分けて、声の長さを字数で割り振る。1 文でも入らなければ止める
    CAP_TOP = PY + PH + 30; room = H - CAP_TOP - 12

    def cap_img(tx):
        size = 40
        while True:
            f = ImageFont.truetype(FONT, size, index=0); rows = wrap(tx, f, PW - 120); lh = int(size * 1.45)
            if lh * len(rows) <= room: break
            if size <= 18: return None
            size -= 2
        im = Image.new("RGBA", (PW, lh * len(rows)), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        for k, r in enumerate(rows): d_.text(((PW - text_w(f, r)) / 2, k * lh), r, font=f, fill=INK + (255,))
        return im

    CAPS = []                                                       # [(出し始め, 消す, 絵)]。時刻の順で、重ならない
    prev_end = -1e9
    for i, (tx, l) in enumerate(zip(texts, LINES)):
        s0, s1 = l["start"], l["start"] + l["dur"]
        ws = max(s0 - 0.15, prev_end)
        we = min(s1 + 0.35, LINES[i + 1]["start"] - 0.15) if i + 1 < len(LINES) else s1 + 0.35
        im = cap_img(tx)
        if im is not None: CAPS.append((ws, we, im))
        else:
            parts = [p_ + "。" for p_ in tx.split("。") if p_]; tot = sum(len(p_) for p_ in parts) or 1; t_ = s0
            for j, p_ in enumerate(parts):
                pim = cap_img(p_)
                if pim is None: sys.exit(f"ERROR: 行 {i + 1} の字幕が --scale {A.scale} の画面の下（{room}px）に入らない。台詞を短く切るか --scale を下げる")
                t1_ = t_ + (s1 - s0) * len(p_) / tot
                CAPS.append((ws if j == 0 else t_, we if j == len(parts) - 1 else t1_, pim)); t_ = t1_
        prev_end = we
    # 章の見出し（余白の左上に出し続ける）とサンプルの出どころ
    HMAX = PX - 80
    HEADS = []                                                      # (番号, [(行の絵, y)], 下線の長さ, 下線の y)。長い見出しは 2 行に折る
    for _, num, title in CHP:
        sz, rows = CH.fit_heading(title, lambda t_, z_: text_w(ImageFont.truetype(FONT, z_, index=0), t_), HMAX)
        if rows[-1].endswith("…") and not title.endswith("…"): print(f"注意: 見出し「{title}」が余白（{HMAX}px）に収まらず末尾を切った。短くするか --scale を下げる", file=sys.stderr)
        ys, ry = CH.heading_block(sz, len(rows)); f_ = ImageFont.truetype(FONT, sz, index=0)
        ims = [(text_img(r, f_, INK), y_) for r, y_ in zip(rows, ys)]
        HEADS.append((text_img(num, ImageFont.truetype(FONT, 22, index=0), ACC), ims, min(HMAX, max([120] + [im.size[0] for im, _ in ims])), ry))
    CRED_Y = max([128] + [h[3] for h in HEADS]) + 20               # 出どころは、いちばん下の下線のさらに下（章で位置が跳ねない）
    CREDS = [[text_img(*fit(x, 20, HMAX)[::-1], SUBC) for x in c[2]] for c in CRD]
else:
    # 章の見出し（章が替わった所で左上に数秒出して消す）: 濃い角丸の札に、橙の縦線・番号・見出し
    FLASH = []
    for _, num, title in CHP:
        ft, tt = fit(title, 46, W - 400); ti = text_img(tt, ft, (255, 255, 255)); nu = text_img(num, ImageFont.truetype(FONT, 26, index=0), ACC)
        bw, bh = max(ti.size[0], nu.size[0]) + 72, nu.size[1] + ti.size[1] + 58
        card = Image.new("RGBA", (bw, bh), (0, 0, 0, 0)); dc = ImageDraw.Draw(card)
        dc.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=16, fill=(20, 22, 28, 220)); dc.rectangle([0, 14, 7, bh - 14], fill=ACC + (255,))
        card.alpha_composite(nu, (36, 20)); card.alpha_composite(ti, (36, 20 + nu.size[1] + 14)); FLASH.append(card)

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
    # コマの頭は round(f * sr / FPS)。sr // FPS の歩幅で進めると、割り切れない sr で後ろほど声とずれる
    hop = sr / FPS; starts = [round(f * hop) for f in range(math.ceil(len(pcm) / hop))]
    env = [math.sqrt(sum(x * x for x in pcm[i:i + round(hop)]) / max(1, len(pcm[i:i + round(hop)]))) / 32768 for i in starts]
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
    fm = film_at(s, u)
    x, y = fm[1] if fm else track(s["cur"], u, mv=0.55, d=s["d"]); return ((x - vx) * z, (y - vy) * z)

def _corner(s):
    vx, vy, vw, vh = view_of(s["cam"][-1][1]); z = W / vw
    rs = [[(r[0] - vx) * z, (r[1] - vy) * z, (r[2] - vx) * z, (r[3] - vy) * z] for a, b, r in s["hl"] if b > 0.5]
    if s["key"]: rs.append([W - 600, 60, W - 80, 160])                  # キーの札（右上）の所にはワイプを置かない
    pts = [((x - vx) * z, (y - vy) * z) for a, (x, y) in s["cur"] if a >= 0.3]
    pts += [((x - vx) * z, (y - vy) * z) for _, _, name in s["film"] for x, y in FILM[name][::3]]   # 連番を流す間のカーソル
    best = None
    for name in [A.wipe_home] + [c for c in ("BR", "TR", "BL", "TL") if c != A.wipe_home]:
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
        if any(fa <= names[k][0] <= fb for fa, fb, _ in s["film"]): a = 1   # 連番の間か終わりでの切り替えは重ねない（動きの前の絵に戻らない）
        if a < 1: base = Image.blend(img(names[k - 1][1]), base, max(0, a))
    else:
        si = S.index(s)
        if si > 0 and (t - s["t0"]) < 0.25 and S[si - 1]["imgs"][-1][1] != names[0][1]:
            base = Image.blend(img(S[si - 1]["imgs"][-1][1]), base, (t - s["t0"]) / 0.25)
    fm = film_at(s, u)
    if fm: base = film_img(fm[0])                                    # 連番は重ねずにそのまま流す
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
    if MARGIN:                                                       # 画面を縮めて右に寄せ、字幕は画面の下、見出しは余白の左上
        out = BGM.copy(); out.paste(fr.convert("RGB").resize((PW, PH), Image.LANCZOS), (PX, PY), PMASK)
        for a0, a1, im in CAPS:                                      # 字幕は 1 つだけ（窓は重ならない）
            if a0 <= t < a1:
                a = max(0.0, min(1, (t - a0) / 0.12, (a1 - t) / 0.12)); out.paste(im, (PX, CAP_TOP), faded(im, a)); break
        k = CH.chapter_at(t, CHP)
        if k is not None:
            nu, ims, rule, ry = HEADS[k]; out.paste(nu, (40, 44), nu)
            for im, y_ in ims: out.paste(im, (40, y_), im)
            ImageDraw.Draw(out).rectangle([40, ry - 1, 40 + rule, ry + 1], fill=ACC)
        for (c0, c1, _), rows in zip(CRD, CREDS):
            a = CH.credit_alpha(t, c0, c1)
            if a > 0:
                for j, r in enumerate(rows): out.paste(r, (40, CRED_Y + 30 * j), faded(r, a))
        return out
    out = Image.new("RGB", (W, H), (22, 24, 28)); out.paste(fr.convert("RGB"), (0, 0)); dd = ImageDraw.Draw(out)
    for a, b, txt in SUBS:                                           # 字幕の帯
        if a <= t < b:
            dd.text(((W - dd.textlength(txt, font=f_sub)) / 2, VIEW_H + (BAND - 46) / 2), txt, font=f_sub, fill=(255, 255, 255)); break
    k = CH.chapter_at(t, CHP)                                        # 章が替わった所だけ、左上に今の章の札（次の章が来たら前の札は消す）
    if k is not None:
        a = CH.flash_alpha(t, CHP[k][0])
        if a > 0: c_ = faded(FLASH[k], a); out.paste(c_, (36, 36), c_)
    return out

if A.preview:
    for t in [float(x) for x in A.preview.split(",") if x]:
        p = os.path.splitext(A.out)[0] + f"_t{t:06.2f}.png"; frame(t).save(p); print("preview", p)
    sys.exit(0)

t_to = A.t_to if A.t_to is not None else END
cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
       "-ss", str(A.t_from), "-t", str(t_to - A.t_from), "-i", os.path.join(A.voice, "voice", "master.wav"),
       "-af", "apad", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest",   # 声が絵より短くても、末尾を無音で伸ばして絵の長さで終える（声の終わりで ffmpeg が止まって書き込みが落ちていた）
       "-f", "mp4", A.out + ".part"]                                  # 書き終えてから名前を付け替える（途中で止まっても前の動画を壊さない）
pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
for n in range(int(A.t_from * FPS), int(t_to * FPS)):
    pr.stdin.write(frame(n / FPS).tobytes())
    if n % 300 == 0: print(f"{n / FPS:.1f}s / {t_to:.1f}s", flush=True)
pr.stdin.close()
if pr.wait() != 0: sys.exit("ERROR: ffmpeg が失敗した")
os.replace(A.out + ".part", A.out)
lay = {"layout": A.layout, "chapters": bool(CHP or CRD)}
if MARGIN: lay.update({"scale": A.scale, "margin": PX, "panel": [PX, PY, PW, PH]})
json.dump(lay, open(os.path.splitext(A.out)[0] + ".layout.json", "w"), ensure_ascii=False)
print("out", A.out, f"{t_to - A.t_from:.1f}s")
