"""全編（約69秒）をパラパラで組み立てる。声は master.wav（9行を3Dパネルと同じ位置に置いたもの）。
  python render_full.py out.mp4 [--from 0 --to 69]      （--from/--to で一部だけ書き出して確かめられる）
姿勢の切り替えは、台詞のキーワードの声の時刻（Whisper の語の時刻）にそろえる。口は声の大きさと母音で毎コマ選び、形が変わる所は1コマ溶かす。
中割り（ib/）は、前後どちらか近い姿勢の口・目の部品を顔に合わせて移植するので、話しながら動く間も口が動く。"""
import difflib, json, math, os, random, subprocess, sys
import cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
sys.path.insert(0, "/tmp/claude-1000/-home-shostako-ClaudeCode-lab/541c4cad-da5d-4f54-a790-3d59b100c57d/scratchpad/pylib")
OUT = sys.argv[1]; T0 = float(sys.argv[sys.argv.index("--from") + 1]) if "--from" in sys.argv else 0.0
FPS = 30; OW, OH = 720, 1280; random.seed(5)
L = {int(k): v for k, v in json.load(open("line_offsets.json")).items()}; END = 69.0
T1 = float(sys.argv[sys.argv.index("--to") + 1]) if "--to" in sys.argv else END
SCRIPT = json.load(open("../tts/lines_v2.json", encoding="utf-8"))
def probe(p): return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout)
LDUR = {n: probe(f"../tts/out/irodori_final_v2/l{n}.wav") for n in L}

# ---------- 声 ----------
def load_audio(p, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768, sr
x, SR = load_audio("master.wav"); NALL = int(math.ceil(END * FPS)); hop = SR / FPS   # コマの頭は round(i * hop)（SR // FPS だと後ろほど声とずれる）
rms = np.array([np.sqrt(np.mean(x[round(i * hop): round(i * hop) + round(hop * 2)] ** 2)) if round(i * hop) < len(x) else 0 for i in range(NALL)])
lvl = np.clip(rms / (np.percentile(rms[rms > 0], 95) + 1e-6), 0, 1.5)
if not os.path.exists("master.words.json"):
    from faster_whisper import WhisperModel
    sys.path.insert(0, os.path.expanduser("~/.claude/skills/video-scene/scripts")); from ear import read_audio
    segs, _ = WhisperModel("medium", device="cpu", compute_type="int8").transcribe(read_audio("master.wav"), language="ja", word_timestamps=True, condition_on_previous_text=False)
    json.dump([[w.word, w.start, w.end] for s in segs for w in s.words], open("master.words.json", "w"), ensure_ascii=False)
words = json.load(open("master.words.json"))
import pykakasi; KK = pykakasi.kakasi()
def to_hira(s): return "".join(ch for ch in "".join(t["hira"] for t in KK.convert(s)) if "ぁ" <= ch <= "ゖ" or ch == "ー")
VOW = {}
for row, v in (("あかさたなはまやらわがざだばぱぁゃ", "a"), ("いきしちにひみりぎじぢびぴぃ", "i"), ("うくすつぬふむゆるぐずづぶぷぅゅ", "u"),
               ("えけせてねへめれげぜでべぺぇ", "e"), ("おこそとのほもよろをごぞどぼぽぉょ", "o")):
    for ch in row: VOW[ch] = v
vowel_at = [None] * NALL; hira_stream = []        # (かな, 時刻)
for w, s, e in words:
    h = to_hira(w)
    if not h: continue
    seq = []; last = None
    for ch in h:
        if ch in "ゃゅょぁぃぅぇぉ" and seq: seq[-1] = (seq[-1][0], VOW.get(ch, seq[-1][1])); continue
        v = "n" if ch == "ん" else ("-" if ch == "っ" else (last if ch == "ー" else VOW.get(ch)))
        seq.append((ch, v)); last = v or last
    for k, (ch, v) in enumerate(seq):
        a = s + (e - s) * k / len(seq); b = s + (e - s) * (k + 1) / len(seq); hira_stream.append((ch, a))
        for f in range(int(a * FPS), min(NALL, int(math.ceil(b * FPS)))): vowel_at[f] = v
def find_time(line, kw, fallback_frac):
    """行の時間窓の中で、キーワード（ひらがな）の最初の音の時刻。見つからなければ行の中の割合で見積もる。"""
    a, b = L[line] - 0.2, L[line] + LDUR[line] + 0.2
    idx = [i for i, (_, t) in enumerate(hira_stream) if a <= t <= b]
    s = "".join(hira_stream[i][0] for i in idx); k = s.find(kw)
    if k >= 0: return hira_stream[idx[k]][1], "ok"
    return L[line] + LDUR[line] * fallback_frac, "推定"
mouth = []
for f in range(NALL):
    Lv = lvl[f]; v = vowel_at[f]
    if Lv < 0.12 or v in (None, "-"): m = None
    elif v == "a": m = "m3" if Lv > 0.75 else "m2"
    elif v in ("i", "e"): m = "m6"
    elif v == "u": m = "m5"
    elif v == "o": m = "m4"
    else: m = "m1"
    if m in ("m2", "m3", "m4", "m6") and Lv < 0.3: m = "m1"
    mouth.append(m)
for f in range(1, NALL - 1):
    if mouth[f] != mouth[f - 1] and mouth[f] != mouth[f + 1]: mouth[f] = mouth[f - 1]
blink = [None] * NALL; t = 1.2
while t < END:
    f0 = int(t * FPS)
    for k, e in enumerate(["e1", "e1", "e2", "e2", "e1", "e1"]):
        if f0 + k < NALL: blink[f0 + k] = e
    t += random.uniform(2.6, 4.6)

# ---------- 姿勢・部品・中割り ----------
POSES = ["home", "point", "gap", "gassho", "open", "arms"]
PB = {p: cv2.imread(f"../hedra/poses/pose_{p}.png") for p in POSES}
PARTS = {}
for p in POSES:
    PARTS[p] = {}
    meta = json.load(open(f"parts_{p}/parts.json"))
    for k, (px, py) in meta.items(): PARTS[p][k] = (cv2.imread(f"parts_{p}/{k}.png", cv2.IMREAD_UNCHANGED), px, py)
def face_affine(src, dst, roi):
    x0, y0, x1, y1 = roi
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = np.zeros(g0.shape, np.uint8); mask[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), mask, 5)
    except cv2.error: pass
    return cv2.invertAffineTransform(M), cc
PAIRS = {("home", "point"), ("home", "open"), ("open", "gassho"), ("gassho", "gap"), ("gap", "point"), ("home", "arms")}
IBCACHE = {}
def ib_item(path, src_pose):
    """中割りの絵と、その上に移植した部品（顔に合わせられなければ部品なし）。"""
    key = (path, src_pose)
    if key in IBCACHE: return IBCACHE[key]
    img = cv2.imread(path); img = cv2.resize(img, (PB[src_pose].shape[1], PB[src_pose].shape[0])) if img.shape != PB[src_pose].shape else img
    allp = list(PARTS[src_pose].values()); xs = [p[1] for p in allp] + [p[1] + p[0].shape[1] for p in allp]; ys = [p[2] for p in allp] + [p[2] + p[0].shape[0] for p in allp]
    roi = (max(0, min(xs) - 80), max(0, min(ys) - 100), min(img.shape[1], max(xs) + 80), min(img.shape[0], max(ys) + 60))
    A, cc = face_affine(PB[src_pose], img, roi); parts = {}
    if cc >= 0.80:
        H, W = img.shape[:2]
        for k, (im, px, py) in PARTS[src_pose].items():
            T = A.copy(); T[:, 2] += A[:, 0] * px + A[:, 1] * py
            full = cv2.warpAffine(im, T, (W, H), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0)); yy, xx = np.where(full[:, :, 3] > 0)
            if len(xx): parts[k] = (full[yy.min():yy.max() + 1, xx.min():xx.max() + 1], int(xx.min()), int(yy.min()))
    print(f"  中割り {os.path.basename(path)} ←{src_pose}: 顔の合い cc={cc:.3f} {'部品あり' if parts else '部品なし'}", file=sys.stderr)
    IBCACHE[key] = (img, parts); return IBCACHE[key]
def ib_seq(a, b):
    if (a, b) in PAIRS: return [f"ib/ib_{a}_{b}_{k}.png" for k in range(1, 6)]
    if (b, a) in PAIRS: return [f"ib/ib_{b}_{a}_{k}.png" for k in range(5, 0, -1)]
    raise KeyError((a, b))

# ---------- 時間割 ----------
IBFPS = 15; IBDUR = 5 / IBFPS
ev = []   # (開始秒, 前の姿勢, 次の姿勢)
def find_word(line, cands, fallback_frac):
    """語単位（Whisper の語のひらがなが cands のどれかに一致する最初の語）の開始時刻。"""
    a, b = L[line] - 0.2, L[line] + LDUR[line] + 0.2
    for w, s, e in words:
        if a <= s <= b and to_hira(w) in cands: return s, "語"
    return L[line] + LDUR[line] * fallback_frac, "推定"
def at_end(line, kw, frac, a, b, word=None):      # キーワードの手前で切り替えが終わるように
    t, how = find_word(line, word, frac) if word else find_time(line, kw, frac); ev.append((t - IBDUR - 0.04, a, b)); print(f"L{line} {a}→{b}: 「{kw}」 {t:.2f}s ({how}) → 開始 {t - IBDUR - 0.04:.2f}s", file=sys.stderr)
at_end(1, "そこで", 0.65, "home", "point")
ev.append((L[3] - 0.5, "point", "home")); print(f"L2→3 point→home 開始 {L[3] - 0.5:.2f}s", file=sys.stderr)
at_end(3, "", 0.12, "home", "open", word=("しゃ",))                  # 「射出待機位置」の直前に両手を開く
at_end(3, "ばねが", 0.72, "open", "gassho")              # 「バネが縮む」で合掌
at_end(4, "", 0.55, "gassho", "gap", word=("あつ",))           # 「圧縮ストローク」で隙間
ev.append((L[5] - 0.4, "gap", "point")); print(f"L4→5 gap→point 開始 {L[5] - 0.4:.2f}s", file=sys.stderr)
at_end(6, "ばね", 0.2, "point", "gap")
at_end(6, "ぜろ", 0.78, "gap", "gassho")
at_end(7, "", 0.52, "gassho", "open", word=("おう", "おし"))                # 「押し広げられる」で両手を開く
ev.append((L[8] + LDUR[8] + 0.05, "open", "home")); print(f"L8→9 open→home 開始 {L[8] + LDUR[8] + 0.05:.2f}s", file=sys.stderr)
ev.append((L[8] + LDUR[8] + 0.05 + IBDUR, "home", "arms"))
ev.sort()
def plan(f):
    t = f / FPS; cur = "home"
    for (s, a, b) in ev:
        if t < s: break
        k = int((t - s) * IBFPS)
        if k < 5:
            seq = ib_seq(a, b); return ("ib", seq[k], a if k < 2 else b, a, b)
        cur = b
    return ("pose", cur)
# ---------- 描画 ----------
def paste(img, part, alpha=1.0):
    if part is None: return
    im, px, py = part; h, w = im.shape[:2]
    if py < 0 or px < 0 or py + h > img.shape[0] or px + w > img.shape[1]: return
    a = im[:, :, 3:4].astype(np.float32) / 255 * alpha
    roi = img[py:py + h, px:px + w].astype(np.float32); img[py:py + h, px:px + w] = (roi * (1 - a) + im[:, :, :3] * a).astype(np.uint8)
def compose(pl, mth, blk):
    if pl[0] == "ib":
        img0, parts = ib_item(pl[1], pl[2]); img = img0.copy()
    else:
        img = PB[pl[1]].copy(); parts = PARTS[pl[1]]
    if mth and mth in parts: paste(img, parts[mth])
    if blk and blk in parts: paste(img, parts[blk])
    return img
sm = np.convolve(lvl, np.ones(5) / 5, mode="same")
f0, f1 = int(T0 * FPS), int(math.ceil(T1 * FPS)); tmp = OUT + ".noaudio.mp4"
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                        "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
for f in range(f0, min(f1, NALL)):
    pl = plan(f); img = compose(pl, mouth[f], blink[f])
    if f > 0 and mouth[f] != mouth[f - 1]:        # 口の形が変わるコマは前後を半々に溶かす（なめらかに）
        img = cv2.addWeighted(img, 0.5, compose(pl, mouth[f - 1], blink[f]), 0.5, 0)
    H, W = img.shape[:2]; tt = f / FPS
    s = 1 + 0.004 * math.sin(2 * math.pi * tt / 3.6); dx = 1.5 * math.sin(2 * math.pi * tt / 5.3); dy = -2.0 * math.sin(2 * math.pi * tt / 3.6) - 2.5 * sm[f]
    M = np.array([[s, 0, (1 - s) * W / 2 + dx], [0, s, (1 - s) * H + dy]], np.float32)
    img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    enc.stdin.write(cv2.resize(img, (OW, OH), interpolation=cv2.INTER_AREA).tobytes())
    if f % 300 == 0: print(f"  {f}/{NALL}", file=sys.stderr, flush=True)
enc.stdin.close(); enc.wait()
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-ss", f"{T0}", "-t", f"{T1 - T0}", "-i", "master.wav", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", OUT], check=True)
os.remove(tmp); print(OUT)
