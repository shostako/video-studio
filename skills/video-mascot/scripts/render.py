"""マスコットが喋る動画を、1コマずつ組み立てて書き出す（パラパラ方式）。
  vm render <作業フォルダ> [--mode alpha|white] [--from 秒 --to 秒] [--out ファイル] [--mouth-scale 1.0]
    alpha（既定）: 背景を透明にした webm（out/mascot.webm、声は入れない）。どんな主動画にも重ねられる
    white       : 背景が白の mp4（声入り、out/mascot_white.mp4）。白っぽい主動画に「乗算」で重ねる用
  --mouth-scale  口の開きを全体に小さく(0.8)・大きく(1.2)する。--from/--to は一部だけ書き出して確かめる用
体は姿勢の絵1枚を固定し、口7形・目2段の部品を声の大きさと母音で毎コマ選んで貼る。姿勢の変わり目は中割り5枚（15fps）。
config の fps を 60、inbetween_div を 12、inbetween_fps を 30 にすると倍の細かさ（中割り11枚・まばたきは段の間を溶かす）。
姿勢の切り替え時刻は config.events（台詞のキーワードの声の時刻）で決める。軸足（向かって左の靴）の底を全部の絵でそろえる。"""
import json, math, os, random, re, subprocess, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, MOUTHS, EYES, defloor, bake_shadow, boot_anchor, body_height, matte, die
from parts import map_rois

a = [x for x in sys.argv[1:]]
if not a or a[0].startswith("-"): die("使い方: vm render <作業フォルダ> [--mode alpha|white] [--from 秒 --to 秒] [--out ファイル]")
P = Proj(a[0]); C = P.cfg
def opt(name, default=None, cast=str): return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
MODE = opt("--mode", "alpha"); T0 = opt("--from", 0.0, float); MS = opt("--mouth-scale", float(C.get("mouth_scale", 1.0)), float)
FPS = P.fps; PAD = P.pad; OH = int(C.get("out_height", 1280)); random.seed(int(C.get("seed", 5)))
timing = json.load(open(P.p("voice", "timing.json"))); L = {x["n"]: x["start"] for x in timing["lines"]}; LDUR = {x["n"]: x["dur"] for x in timing["lines"]}; END = timing["end"]
T1 = opt("--to", END, float)
OUTF = opt("--out", P.p("out", "mascot.webm" if MODE == "alpha" else "mascot_white.mp4"))
VOICE = P.p("voice", "master.wav")

# ---------- 声: 大きさ・語・母音 ----------
def load_audio(p, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768, sr
x, SR = load_audio(VOICE); NALL = int(math.ceil(END * FPS)); hop = SR // FPS; WIN = SR * 2 // 30; R = max(1, round(FPS / 30))   # 窓は時間で固定（30fps の2コマ分）。R = 30fps に対する倍率
rms = np.array([np.sqrt(np.mean(x[i * hop: i * hop + WIN] ** 2)) if i * hop < len(x) else 0 for i in range(NALL)])
lvl = np.clip(rms / (np.percentile(rms[rms > 0], 95) + 1e-6), 0, 1.5) * MS
WORDS = P.p("voice", "master.words.json")
if not os.path.exists(WORDS) or os.path.getmtime(WORDS) < os.path.getmtime(VOICE):
    from faster_whisper import WhisperModel
    sys.path.insert(0, os.path.expanduser("~/.claude/skills/video-scene/scripts")); from ear import read_audio
    segs, _ = WhisperModel("medium", device="cpu", compute_type="int8").transcribe(read_audio(VOICE), language="ja", word_timestamps=True, condition_on_previous_text=False)
    json.dump([[w.word, w.start, w.end] for s in segs for w in s.words], open(WORDS, "w"), ensure_ascii=False)
words = json.load(open(WORDS))
import pykakasi; KK = pykakasi.kakasi()
def to_hira(s): return "".join(ch for ch in "".join(t["hira"] for t in KK.convert(s)) if "ぁ" <= ch <= "ゖ" or ch == "ー")
VOW = {}
for row, v in (("あかさたなはまやらわがざだばぱぁゃ", "a"), ("いきしちにひみりぎじぢびぴぃ", "i"), ("うくすつぬふむゆるぐずづぶぷぅゅ", "u"),
               ("えけせてねへめれげぜでべぺぇ", "e"), ("おこそとのほもよろをごぞどぼぽぉょ", "o")):
    for ch in row: VOW[ch] = v
vowel_at = [None] * NALL; hira_stream = []
for w, s, e in words:
    h = to_hira(w)
    if not h: continue
    seq = []; last = None
    for ch in h:
        if ch in "ゃゅょぁぃぅぇぉ" and seq: seq[-1] = (seq[-1][0], VOW.get(ch, seq[-1][1])); continue
        v = "n" if ch == "ん" else ("-" if ch == "っ" else (last if ch == "ー" else VOW.get(ch)))
        seq.append((ch, v)); last = v or last
    for k, (ch, v) in enumerate(seq):
        s0 = s + (e - s) * k / len(seq); s1 = s + (e - s) * (k + 1) / len(seq); hira_stream.append((ch, s0))
        for f in range(int(s0 * FPS), min(NALL, int(math.ceil(s1 * FPS)))): vowel_at[f] = v

def find_time(line, kw, frac):
    """行の時間窓の中で、キーワード（ひらがな）の最初の音の時刻。見つからなければ行の中の割合で見積もる。"""
    a0, b0 = L[line] - 0.2, L[line] + LDUR[line] + 0.2
    idx = [i for i, (_, t) in enumerate(hira_stream) if a0 <= t <= b0]; s = "".join(hira_stream[i][0] for i in idx); k = s.find(kw)
    return (hira_stream[idx[k]][1], "声") if k >= 0 else (L[line] + LDUR[line] * frac, "推定")
def find_word(line, cands, frac):
    a0, b0 = L[line] - 0.2, L[line] + LDUR[line] + 0.2
    for w, s, e in words:
        if a0 <= s <= b0 and to_hira(w) in cands: return s, "語"
    return L[line] + LDUR[line] * frac, "推定"

# ---------- 口・まばたき ----------
def choose(Lv, v):
    """声の大きさと母音から口の形。小さい声は小さく、いちばん大きい開き(m3)は強い「あ」の山だけ。"""
    if Lv < 0.15 or v in (None, "-"): return None
    if v == "n": return "m1"
    if v == "a": return "m1" if Lv < 0.42 else ("m7" if Lv < 0.8 else ("m2" if Lv < 1.15 else "m3"))
    if v in ("i", "e"): return "m1" if Lv < 0.45 else ("m7" if Lv < 1.1 else "m6")
    if v == "u": return "m1" if Lv < 0.3 else "m5"
    if v == "o": return "m1" if Lv < 0.3 else "m4"
    return "m1"
lvl_s = np.array([np.median(lvl[max(0, f - R):f + R + 1]) for f in range(NALL)])
mouth = [choose(lvl_s[f], vowel_at[f]) for f in range(NALL)]
if R == 1:
    for f in range(1, NALL - 1):
        if mouth[f] != mouth[f - 1] and mouth[f] != mouth[f + 1]: mouth[f] = mouth[f - 1]
else:                                             # 30fps の1コマ（R コマ）以下しか続かない形は直前の形にする
    f = 1
    while f < NALL:
        g = f
        while g < NALL and mouth[g] == mouth[f]: g += 1
        if g - f <= R and g < NALL and mouth[f] != mouth[f - 1]: mouth[f:g] = [mouth[f - 1]] * (g - f)
        f = g
print("口の形のコマ数:", {str(m): mouth.count(m) for m in sorted(set(mouth), key=str)}, file=sys.stderr)
blink = [None] * NALL; t = 1.2                  # まばたき: None か "e1"/"e2"、細かい時は (下の段, 上の段, 上の段の割合)
BL = [0, 1, 1, 2, 2, 1, 1, 0]; BK = {0: None, 1: "e1", 2: "e2"}   # 30fps の6コマ（e1 e1 e2 e2 e1 e1）を、前後の「開き」込みの閉じ具合で表す
while t < END:
    f0 = int(t * FPS)
    if R == 1:
        for k, e in enumerate(["e1", "e1", "e2", "e2", "e1", "e1"]):
            if f0 + k < NALL: blink[f0 + k] = e
    else:                                         # 30fps の各コマの中心を結んだ閉じ具合を R 倍の細かさで取り、段の間は溶かす
        for k in range(6 * R + 1):
            u = (k + 0.5) / R - 0.5 + 1           # BL 上の位置（BL[1] が 30fps の1コマ目）
            i0 = int(math.floor(u)); fr = u - i0; lv = BL[min(i0, 7)] * (1 - fr) + BL[min(i0 + 1, 7)] * fr
            lo = int(math.floor(lv)); hi = min(2, lo + 1); a_ = lv - lo
            if f0 + k < NALL and lv > 0.01: blink[f0 + k] = BK[lo] if a_ < 0.02 else (BK[lo], BK[hi], a_)
    t += random.uniform(2.6, 4.6)
sm = np.convolve(lvl, np.ones(5 * R) / (5 * R), mode="same")

# ---------- 姿勢・部品・軸足 ----------
FL = C.get("floor", {"clean": True}); H0, W0 = P.read_pose(P.home).shape[:2]; Y0 = int(FL.get("y0", round(H0 * 0.705)))
PB, SH = {}, {}
for p in P.poses:
    img = P.read_pose(p)
    if FL.get("clean", False): PB[p], SH[p] = defloor(img, Y0)
    else: PB[p], SH[p] = img, np.zeros(img.shape[:2], np.float32)
AN = C.get("anchor", {"mode": "boot"}); AMODE = AN.get("mode", "boot")
if AMODE == "boot":
    ANCH = {p: boot_anchor(PB[p]) for p in P.poses}
    miss = [p for p, v in ANCH.items() if v is None]
    if miss: die(f"軸足の靴が見つからない姿勢: {miss}（config.anchor を manual にするか none に）")
    HT = {p: body_height(PB[p], ANCH[p]) for p in P.poses}; SCALE = {p: HT[P.home] / HT[p] for p in P.poses}
elif AMODE == "manual":
    ANCH = {p: tuple(v) for p, v in AN["points"].items()}; SCALE = {p: float(AN.get("scales", {}).get(p, 1.0)) for p in P.poses}
else:
    ANCH = {p: (W0 / 2, H0 * 0.9) for p in P.poses}; SCALE = {p: 1.0 for p in P.poses}
REF = ANCH[P.home]
print("軸足:", {p: tuple(round(float(v), 1) for v in a_) for p, a_ in ANCH.items()}, "大きさ:", {p: round(float(v), 3) for p, v in SCALE.items()}, file=sys.stderr)
PARTS = {}
for p in P.poses:
    PARTS[p] = {}; mp = P.p(f"parts_{p}", "parts.json")
    if not os.path.exists(mp): die(f"部品が無い: parts_{p}（先に vm parts）")
    for k, (px, py) in json.load(open(mp)).items(): PARTS[p][k] = (cv2.imread(P.p(f"parts_{p}", f"{k}.png"), cv2.IMREAD_UNCHANGED), px, py)
FB = {"m7": "m1", "m3": "m2", "m6": "m1"}      # 無い形は近い形で代用
def part_of(parts, k):
    while k and k not in parts: k = FB.get(k)
    return parts.get(k) if k else None

def shift_m(a_, sc): return np.float32([[sc, 0, REF[0] - sc * a_[0] + PAD], [0, sc, REF[1] - sc * a_[1]]])
def shift(img, a_, sc, interp=cv2.INTER_LINEAR, val=(253, 253, 253)):
    """軸足の靴の底の中心 a_ を REF に重ね、その点を中心に sc 倍する。左右に PAD の余白を足した画面に置く。"""
    return cv2.warpAffine(img, shift_m(a_, sc), (img.shape[1] + 2 * PAD, img.shape[0]), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=val)
KEEP = {}
for p_ in P.poses:                       # 顔（目と口）の矩形。この中の白（白目・歯）は背景にしない
    mr, er, _ = map_rois(P, p_); KEEP[p_] = [(er[0] - 10, er[1] - 10, er[2] + 10, er[3] + 10), (mr[0] - 10, mr[1] - 10, mr[2] + 10, mr[3] - 24)]   # 目と口を別々の箱に（口はあごの下へ広げない）

def face_affine(src, dst, roi):
    x0, y0, x1, y1 = roi
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = np.zeros(g0.shape, np.uint8); mask[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), mask, 5)
    except cv2.error: pass
    return cv2.invertAffineTransform(M), cc
IBCACHE = {}
def ib_item(item, src_pose):
    """中割りの絵と、その上に移植した部品（顔に合わせられなければ部品なし）、軸足の位置、大きさの補正。"""
    path, a_, b_, k_ = item; key = (path, src_pose)
    if key in IBCACHE: return IBCACHE[key]
    img = cv2.imread(path)
    if img is None: die(f"中割りの絵が無い: {path}")
    ref = PB[src_pose]
    if img.shape != ref.shape: img = cv2.resize(img, (ref.shape[1], ref.shape[0]))
    clean, shadow = defloor(img, Y0) if FL.get("clean", False) else (img, np.zeros(img.shape[:2], np.float32))
    anc = boot_anchor(clean) if AMODE == "boot" else None
    sc = SCALE[a_] + (SCALE[b_] - SCALE[a_]) * k_ / DIV
    if anc is None: anc = tuple(np.array(ANCH[a_]) + (np.array(ANCH[b_]) - np.array(ANCH[a_])) * k_ / DIV)
    allp = list(PARTS[src_pose].values()); xs = [p_[1] for p_ in allp] + [p_[1] + p_[0].shape[1] for p_ in allp]; ys = [p_[2] for p_ in allp] + [p_[2] + p_[0].shape[0] for p_ in allp]
    roi = (max(0, min(xs) - 80), max(0, min(ys) - 100), min(img.shape[1], max(xs) + 80), min(img.shape[0], max(ys) + 60))
    A, cc = face_affine(PB[src_pose], clean, roi); parts = {}
    if cc >= 0.80:
        H, W = clean.shape[:2]
        for k, (im, px, py) in PARTS[src_pose].items():
            T = A.copy(); T[:, 2] += A[:, 0] * px + A[:, 1] * py
            full = cv2.warpAffine(im, T, (W, H), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0)); yy, xx = np.where(full[:, :, 3] > 0)
            if len(xx): parts[k] = (full[yy.min():yy.max() + 1, xx.min():xx.max() + 1], int(xx.min()), int(yy.min()))
    IBCACHE[key] = (clean, shadow, parts, anc, sc); return IBCACHE[key]

def ib_seq(a_, b_):
    d = P.pair_dir(a_, b_)
    if d is None: return None
    pa, pb, rev = d; seq = [(P.ib_path(pa, pb, k), pa, pb, k) for k in range(1, DIV)]
    return seq[::-1] if rev else seq

# ---------- 時間割 ----------
DIV = P.ib_div; NIB = DIV - 1; IBFPS = int(C.get("inbetween_fps", 15)); IBDUR = NIB / IBFPS; ev = []; cur_pose = P.home
for e in C.get("events", []):
    to = e["pose"]
    if "kw" in e or "word" in e:
        t, how = find_word(e["line"], tuple(e["word"]), e.get("fallback", 0.5)) if "word" in e else find_time(e["line"], e["kw"], e.get("fallback", 0.5))
        st = t - IBDUR - 0.04 + float(e.get("offset", 0.0)); print(f"行{e['line']} {cur_pose}→{to}: 「{e.get('kw') or e['word']}」 {t:.2f}s（{how}）→ 開始 {st:.2f}s", file=sys.stderr)
    elif "at" in e: st = float(e["at"])
    elif "line_start" in e: st = L[e["line_start"]] + float(e.get("offset", 0.0))
    elif "line_end" in e: st = L[e["line_end"]] + LDUR[e["line_end"]] + float(e.get("offset", 0.05))
    else: die(f"events に開始の指定が無い: {e}")
    ev.append((st, cur_pose, to)); cur_pose = to
ev.sort()
def plan(f):
    t = f / FPS; cur = P.home
    for (s, a_, b_) in ev:
        if t < s: break
        seq = ib_seq(a_, b_); k = int((t - s) * IBFPS) if seq else 99
        if seq and k < NIB: return ("ib", seq[k], a_ if k < int(NIB * 0.4 + 0.5) else b_)
        cur = b_
    return ("pose", cur)

# ---------- 描画 ----------
def paste(img, part):
    if part is None: return
    im, px, py = part; h, w = im.shape[:2]
    if py < 0 or px < 0 or py + h > img.shape[0] or px + w > img.shape[1]: return
    al = im[:, :, 3:4].astype(np.float32) / 255; roi = img[py:py + h, px:px + w].astype(np.float32); img[py:py + h, px:px + w] = (roi * (1 - al) + im[:, :, :3] * al).astype(np.uint8)
def compose(pl, mth, blk):
    if pl[0] == "ib":
        clean, shadow, parts, anc, sc = ib_item(pl[1], pl[2]); img = clean.copy()
    else:
        img = PB[pl[1]].copy(); shadow = SH[pl[1]]; parts = PARTS[pl[1]]; anc = ANCH[pl[1]]; sc = SCALE[pl[1]]
    paste(img, part_of(parts, mth))
    if isinstance(blk, tuple):                    # 細かいまばたき: 2つの段を割合で溶かす
        lo_, hi_, al_ = blk; i_lo = img.copy(); paste(i_lo, part_of(parts, lo_)); paste(img, part_of(parts, hi_)); img = cv2.addWeighted(img, al_, i_lo, 1 - al_, 0)
    else: paste(img, part_of(parts, blk))
    k = KEEP[pl[2] if pl[0] == "ib" else pl[1]]; m1 = shift_m(anc, sc); pad_ = 30 if pl[0] == "ib" else 0     # 中割りは顔が少し動くので広めに
    return shift(img, anc, sc), shift(shadow, anc, sc, val=0), (m1, [(b[0] - pad_, b[1] - pad_, b[2] + pad_, b[3] + pad_) for b in k])

W1 = W0 + 2 * PAD; OW = 2 * round(OH * W1 / H0 / 2)
f0, f1 = int(T0 * FPS), int(math.ceil(T1 * FPS))
if min(f1, NALL) <= f0: die(f"書き出すコマが無い（{T0}〜{T1} 秒、声は {NALL / FPS:.2f} 秒まで。--from / --to を見直す）")
if MODE == "alpha":
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-auto-alt-ref", "0", OUTF], stdin=subprocess.PIPE)
else:
    tmp = OUTF + ".noaudio.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
for f in range(f0, min(f1, NALL)):
    pl = plan(f); img, sh, kinfo = compose(pl, mouth[f], blink[f])
    if f > 0 and mouth[f] != mouth[f - 1]:         # 口の形が変わるコマは前後を半々に溶かす
        i2, s2, _ = compose(pl, mouth[f - 1], blink[f]); img = cv2.addWeighted(img, 0.5, i2, 0.5, 0); sh = (sh + s2) / 2
    H, W = img.shape[:2]; tt = f / FPS
    s = 1 + 0.004 * math.sin(2 * math.pi * tt / 3.6); dx = 1.5 * math.sin(2 * math.pi * tt / 5.3); dy = -2.0 * math.sin(2 * math.pi * tt / 3.6) - 2.5 * sm[f]
    M = np.array([[s, 0, (1 - s) * W / 2 + dx], [0, s, (1 - s) * H + dy]], np.float32)     # 息づかい: 足元を中心にわずかに伸び縮み
    img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(253, 253, 253))
    sh = cv2.warpAffine(sh, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    img = cv2.resize(img, (OW, OH), interpolation=cv2.INTER_AREA); sh = cv2.resize(sh, (OW, OH), interpolation=cv2.INTER_AREA)
    if MODE == "alpha":
        m1, kbs = kinfo; fxs, fys = OW / W, OH / H; keep = []
        for kb in kbs:                                                                    # 顔の箱を、移動・息づかい・縮小の変換で最終の画素に写す
            pts = np.array([[kb[0], kb[1]], [kb[2], kb[3]]], np.float32); p1 = pts @ m1[:, :2].T + m1[:, 2]; p2 = p1 @ M[:, :2].T + M[:, 2]
            keep.append((int(p2[0, 0] * fxs), int(p2[0, 1] * fys), int(p2[1, 0] * fxs), int(p2[1, 1] * fys)))
        rgba = matte(img, sh, keep); enc.stdin.write(rgba.tobytes())
    else:
        enc.stdin.write(bake_shadow(img, sh).tobytes())
    if f % 300 == 0: print(f"  {f}/{NALL}", file=sys.stderr, flush=True)
enc.stdin.close(); rc_enc = enc.wait()
if rc_enc != 0: die(f"ffmpeg の書き出しに失敗（終了コード {rc_enc}）")
if MODE != "alpha":
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-ss", f"{T0}", "-t", f"{T1 - T0}", "-i", VOICE, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", OUTF], check=True)
    os.remove(tmp)
print(OUTF)
