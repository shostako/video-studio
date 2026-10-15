"""video-mascot の共通部分: 設定の読み込み、足元の台座消し、軸足の靴の位置、背景の切り抜き、口パクと姿勢の時間割の純関数。"""
import json, math, os, sys
import cv2, numpy as np

BG = 253          # マスコットの絵の背景（/img が描く「ほぼ白」）の明るさ
MOUTHS = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"]   # 少し開き・半開き・大開き・お・う・い/え・小さい開き
EYES = ["e1", "e2"]                                    # 4分の3閉じ・閉じ


class Proj:
    """作業フォルダ（config.json のある所）。標準の配置:
    poses/pose_<名前>.png  parts/<姿勢>_<m1..m7,e1,e2>.png（描いた差分）  parts_<姿勢>/（切り抜いた部品）
    ib/ib_<a>_<b>_<k>.png（中割り k=1..5）  voice/（l<N>.wav と master.wav、timing.json）  out/"""
    def __init__(self, path):
        self.root = os.path.abspath(path)
        cfg = os.path.join(self.root, "config.json")
        if not os.path.exists(cfg): sys.exit(f"ERROR: config.json が無い: {self.root}")
        self.cfg = json.load(open(cfg, encoding="utf-8"))
        self.poses = list(self.cfg["poses"].keys())
        self.home = self.cfg.get("home", self.poses[0])
        self.pairs = [tuple(p) for p in self.cfg.get("pairs", [])]
        self.pad = int(self.cfg.get("pad", 100))
        self.fps = int(self.cfg.get("fps", 30))
        self.ib_div = int(self.cfg.get("inbetween_div", 6))     # 姿勢の間を何等分するか。中割りは div-1 枚（既定 6 → 5枚）
        for d in ("out", "voice", "parts", "ib", "poses"): os.makedirs(self.p(d), exist_ok=True)

    def p(self, *a): return os.path.join(self.root, *a)
    def pose_path(self, n): return self.p("poses", f"pose_{n}.png")
    def read_pose(self, n):
        im = cv2.imread(self.pose_path(n))
        if im is None: sys.exit(f"ERROR: 姿勢の絵が無い: {self.pose_path(n)}")
        return im

    def ib_path(self, a, b, k):
        """中割り k（1..div-1）の絵。既定の6等分は ib_<a>_<b>_<k>.png、それ以外は ib_<a>_<b>_<k>_<div>.png。"""
        return self.p("ib", f"ib_{a}_{b}_{k}.png" if self.ib_div == 6 else f"ib_{a}_{b}_{k}_{self.ib_div}.png")

    def pair_dir(self, a, b):
        """中割りの向き。 (a,b) が pairs にあれば順方向、(b,a) があれば逆方向。無ければ None。"""
        if (a, b) in self.pairs: return (a, b, False)
        if (b, a) in self.pairs: return (b, a, True)
        return None


def die(msg, code=2):
    print("ERROR:", msg, file=sys.stderr); sys.exit(code)


# ---------- 足元（台座・靴の反射）を消す ----------
def defloor(img, y0=1180):
    """透明な台座と靴の反射を消し、靴の下に薄い接地の影を足す。靴（黒）とズボン（紺）の形は残す。
    戻り値: (きれいな絵 BGR（影なし・背景は BG）, 影の濃さ 0..1)。影は別に持ち、重ねる時に焼き込むか透明の影にする。"""
    H, W = img.shape[:2]; g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    dark = (g < 105).astype(np.uint8); blue = ((hsv[:, :, 1] > 70) & (g < 170)).astype(np.uint8)
    fg = (dark | blue); fg[:y0 - 40] = 0
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(fg); keep = np.zeros_like(fg)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] > 600: keep[lab == i] = 1
    a = np.clip(cv2.GaussianBlur(cv2.dilate(keep, np.ones((5, 5), np.uint8)).astype(np.float32), (0, 0), 1.6) * 1.15, 0, 1)
    shoe = ((g < 70) & (np.arange(H)[:, None] > y0 + 60)).astype(np.float32)
    sh = cv2.GaussianBlur(cv2.warpAffine(shoe, np.float32([[1, 0, 0], [0, 1, 14]]), (W, H)), (0, 0), 15); sh = np.clip(sh * 0.34, 0, 0.34)
    bgc = np.full((H, W, 3), BG, np.float32)
    res = img.astype(np.float32) * a[:, :, None] + bgc * (1 - a[:, :, None])
    below = np.zeros((H, W, 1), np.float32); below[y0:] = 1; below[y0 - 30:y0] = np.linspace(0, 1, 30)[:, None, None]
    clean = (img.astype(np.float32) * (1 - below) + res * below).astype(np.uint8)
    shadow = (sh * below[:, :, 0] * (1 - a)).astype(np.float32)          # 影は足元の外側だけ
    return clean, shadow


def bake_shadow(clean, shadow):
    return (clean.astype(np.float32) * (1 - shadow[:, :, None])).astype(np.uint8)


# ---------- 軸足（向かって左の靴）----------
def boot_anchor(img, min_area=2500):
    """向かって左の靴（マスコットの右足）の底の中心。足元の黒い塊のうち一番左のもの。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H = img.shape[0]; m = (g < 70).astype(np.uint8); m[:int(H * 0.775)] = 0
    n, lab, st, cen = cv2.connectedComponentsWithStats(m)
    cand = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > min_area]
    if not cand: return None
    i = min(cand, key=lambda j: cen[j][0]); x0, y0, w, h = st[i, :4]
    return (x0 + w / 2.0, float(y0 + h))


def body_height(img, anc):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); rows = np.where((g < 150).sum(1) > 3)[0]; return anc[1] - rows.min()


# ---------- 背景の切り抜き（透明にする）----------
def matte(clean, shadow, keeps=None, bg=BG, keep_max_area=600):
    """背景につながる白を透明にして、輪郭をやわらかくする。足元の影は黒の半透明で別に足す。
    keeps=[(x0,y0,x1,y1), ...]（出力の画素）の外にある、ほぼ白の領域（毛束に囲まれたすき間など）は、外とつながっていなくても背景にする。
    keeps の中（白目・歯）は守る。ただし箱の中でも面積が keep_max_area（画素）を超える白は、白目・歯ではなく背景。clean: BGR（背景は BG の白）。戻り値: BGRA（アルファ付き）。
    黒い物（髪・靴）の縁は、背景の白とのまざり具合を暗さから割り戻す。明るい物（肌）の縁は形からやわらげる。"""
    H, W = clean.shape[:2]; mn = clean.min(axis=2).astype(np.float32)
    cand = (mn >= bg - 12).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(cand, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]]))) - {0}
    isbg = np.zeros(n, bool); isbg[list(border)] = True
    dark_near = cv2.dilate((mn < 110).astype(np.uint8), np.ones((9, 9), np.uint8))                 # 近くに黒い毛がある所
    for i in range(1, n):
        if isbg[i] or st[i, cv2.CC_STAT_AREA] < 12: continue
        x, y, w, h, area = st[i]; region = lab[y:y + h, x:x + w] == i
        ring = cv2.dilate(region.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        ring_dark = float((dark_near[y:y + h, x:x + w][ring & ~region]).mean()) if (ring & ~region).any() else 0.0
        cx, cy = cen[i]
        inside = bool(keeps) and any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in keeps)
        # 顔の箱の外の白は背景。箱の中でも、大きな白（白目・歯より大きい）や、黒い毛にほとんど囲まれた細長い白は背景
        elong = max(w, h) / max(1.0, min(w, h))
        if (keeps and not inside) or area > keep_max_area or (inside and ring_dark > 0.85 and elong > 3.5): isbg[i] = True
    isbg[0] = False
    bgmask = isbg[lab] & (cand > 0)
    # 仕上げ: 肌や服の色を持たない「ほぼ白」の小さな塊（毛束の間に取り残された白）を、周りが黒い毛に囲まれていれば消す
    fg0 = (~bgmask) & (cand > 0); n2, lab2, st2, _ = cv2.connectedComponentsWithStats(fg0.astype(np.uint8), connectivity=4)
    for i in range(1, n2):
        x, y, w, h, area = st2[i]
        if area > keep_max_area: continue
        reg = lab2[y:y + h, x:x + w] == i
        ys_, xs_ = np.where(reg); cx = x + xs_.mean(); cy = y + ys_.mean()
        if keeps and any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in keeps): continue      # 白目・歯は守る
        pad = 6; y0_, y1_, x0_, x1_ = max(0, y - pad), min(H, y + h + pad), max(0, x - pad), min(W, x + w + pad)
        sub = lab2[y0_:y1_, x0_:x1_] == i; ringm = cv2.dilate(sub.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        ringm &= ~sub; dark_ring = (mn[y0_:y1_, x0_:x1_][ringm] < 110).mean() if ringm.any() else 0
        if dark_ring > 0.25: bgmask[y:y + h, x:x + w] |= reg
    fg = (~bgmask).astype(np.uint8)
    dist = cv2.distanceTransform(fg, cv2.DIST_L2, 3); band = (fg > 0) & (dist <= 3.0)
    a_geo = cv2.GaussianBlur(cv2.erode(fg, np.ones((2, 2), np.uint8)).astype(np.float32), (0, 0), 0.9)
    Lfg = cv2.erode(mn, np.ones((7, 7), np.uint8))                                   # 近くの一番暗い所＝中身の明るさ
    cover = np.clip((bg - mn) / np.maximum(bg - Lfg, 20.0), 0, 1)                    # 黒い物の縁: 暗さ＝覆っている割合
    a = np.where(band & (Lfg < 110), cover, a_geo); a[bgmask] = 0; a = np.clip(a, 0, 1)
    af = a[:, :, None]; col = np.clip((clean.astype(np.float32) - bg * (1 - af)) / np.maximum(af, 0.05), 0, 255)      # 白とのまざりを戻す
    col = np.where(af > 0.95, clean.astype(np.float32), col)
    sh = shadow * (1 - a)                                                           # 影は黒の半透明
    at = a + sh; rgb = (col * a[:, :, None]) / np.maximum(at[:, :, None], 1e-3)
    return np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), (np.clip(at, 0, 1) * 255).astype(np.uint8)])


# ---------- 声の語から母音の時刻列（render.py の口パク用。純関数）----------
VOW = {}
for _row, _v in (("あかさたなはまやらわがざだばぱぁゃ", "a"), ("いきしちにひみりぎじぢびぴぃ", "i"), ("うくすつぬふむゆるぐずづぶぷぅゅ", "u"),
                 ("えけせてねへめれげぜでべぺぇ", "e"), ("おこそとのほもよろをごぞどぼぽぉょ", "o")):
    for _ch in _row: VOW[_ch] = _v


def hira_vowels(h):
    """ひらがなの列を (音, 母音) の列にする。母音は a/i/u/e/o、「ん」は n、「っ」は -、「ー」は直前の母音。
    小書きの「ゃゅょぁぃぅぇぉ」は前の音にまとめ、母音をその音のものに置き換える。知らない字の母音は None。"""
    seq = []; last = None
    for ch in h:
        if ch in "ゃゅょぁぃぅぇぉ" and seq: seq[-1] = (seq[-1][0], VOW.get(ch, seq[-1][1])); continue
        v = "n" if ch == "ん" else ("-" if ch == "っ" else (last if ch == "ー" else VOW.get(ch)))
        seq.append((ch, v)); last = v or last
    return seq


def vowel_frames(words_hira, fps, nall):
    """words_hira=[(ひらがな, 開始秒, 終了秒), ...] から、コマごとの母音（無ければ None）と、音の並び [(音, 開始秒), ...]。
    語の時間は音の数で等分する。ひらがなが空の語は飛ばす。"""
    vowel_at = [None] * nall; hira_stream = []
    for h, s, e in words_hira:
        if not h: continue
        seq = hira_vowels(h)
        for k, (ch, v) in enumerate(seq):
            s0 = s + (e - s) * k / len(seq); s1 = s + (e - s) * (k + 1) / len(seq); hira_stream.append((ch, s0))
            for f in range(int(s0 * fps), min(nall, int(math.ceil(s1 * fps)))): vowel_at[f] = v
    return vowel_at, hira_stream


# ---------- events のキーワードの時刻（純関数）----------
def find_time(hira_stream, start, dur, kw, frac):
    """行（start 秒から dur 秒）の前後 0.2 秒を含む窓の中で、キーワード（ひらがな）の最初の音の時刻。
    見つからなければ行の中の割合 frac で見積もる。戻り値: (秒, "声" か "推定")。"""
    a0, b0 = start - 0.2, start + dur + 0.2
    idx = [i for i, (_, t) in enumerate(hira_stream) if a0 <= t <= b0]; s = "".join(hira_stream[i][0] for i in idx); k = s.find(kw)
    return (hira_stream[idx[k]][1], "声") if k >= 0 else (start + dur * frac, "推定")


def find_word(words_hira, start, dur, cands, frac):
    """行の窓の中で、ひらがなが cands のどれかと一致する最初の語の開始時刻。無ければ割合 frac で見積もる。戻り値: (秒, "語" か "推定")。"""
    a0, b0 = start - 0.2, start + dur + 0.2
    for h, s, e in words_hira:
        if a0 <= s <= b0 and h in cands: return s, "語"
    return start + dur * frac, "推定"


def resolve_events(events, home, starts, durs, ibdur, hira_stream, words_hira, log=None):
    """config.events を姿勢の切り替えの時間割 [(開始秒, 前の姿勢, 次の姿勢), ...]（開始の早い順）にする。
    開始の指定: kw（ひらがなの並び）/ word（語の候補）の声の時刻から中割りの長さ ibdur と 0.04 秒を引く、at（秒）、
    line_start（行頭）、line_end（行末。offset の既定 0.05）。offset はどれにも足す（at を除く）。starts/durs は {行番号: 秒}。"""
    ev = []; cur = home
    for e in events:
        to = e["pose"]
        if "kw" in e or "word" in e:
            t, how = find_word(words_hira, starts[e["line"]], durs[e["line"]], tuple(e["word"]), e.get("fallback", 0.5)) if "word" in e \
                else find_time(hira_stream, starts[e["line"]], durs[e["line"]], e["kw"], e.get("fallback", 0.5))
            st = t - ibdur - 0.04 + float(e.get("offset", 0.0))
            if log: log(f"行{e['line']} {cur}→{to}: 「{e.get('kw') or e['word']}」 {t:.2f}s（{how}）→ 開始 {st:.2f}s")
        elif "at" in e: st = float(e["at"])
        elif "line_start" in e: st = starts[e["line_start"]] + float(e.get("offset", 0.0))
        elif "line_end" in e: st = starts[e["line_end"]] + durs[e["line_end"]] + float(e.get("offset", 0.05))
        else: die(f"events に開始の指定が無い: {e}")
        ev.append((st, cur, to)); cur = to
    ev.sort()
    return ev


def plan_at(t, ev, home, ib_seq, ibfps, nib):
    """時刻 t に出す絵。("pose", 姿勢) か、切り替えの途中なら ("ib", 中割りの項目, 部品を借りる姿勢)。
    ib_seq(a, b) は中割りの列（無ければ None。その時は中割りなしで切り替える）。中割りの前の 4 割は元の姿勢の部品を使う。"""
    cur = home
    for (s, a_, b_) in ev:
        if t < s: break
        seq = ib_seq(a_, b_); k = int((t - s) * ibfps) if seq else 99
        if seq and k < nib: return ("ib", seq[k], a_ if k < int(nib * 0.4 + 0.5) else b_)
        cur = b_
    return ("pose", cur)


# ---------- 口の形（純関数）----------
def choose_mouth(Lv, v):
    """声の大きさと母音から口の形。小さい声は小さく、いちばん大きい開き(m3)は強い「あ」の山だけ。"""
    if Lv < 0.15 or v in (None, "-"): return None
    if v == "n": return "m1"
    if v == "a": return "m1" if Lv < 0.42 else ("m7" if Lv < 0.8 else ("m2" if Lv < 1.15 else "m3"))
    if v in ("i", "e"): return "m1" if Lv < 0.45 else ("m7" if Lv < 1.1 else "m6")
    if v == "u": return "m1" if Lv < 0.3 else "m5"
    if v == "o": return "m1" if Lv < 0.3 else "m4"
    return "m1"


def smooth_mouth(mouth, R):
    """すぐ消える口の形を直前の形にする（新しいリストを返す）。R=1（30fps 以下）は前後と違う1コマだけ、
    R>1 は 30fps の1コマ（R コマ）以下しか続かない形。R は 30fps に対する倍率。"""
    mouth = list(mouth); n = len(mouth)
    if R == 1:
        for f in range(1, n - 1):
            if mouth[f] != mouth[f - 1] and mouth[f] != mouth[f + 1]: mouth[f] = mouth[f - 1]
    else:
        f = 1
        while f < n:
            g = f
            while g < n and mouth[g] == mouth[f]: g += 1
            if g - f <= R and g < n and mouth[f] != mouth[f - 1]: mouth[f:g] = [mouth[f - 1]] * (g - f)
            f = g
    return mouth


# ---------- モーラ位置の口パク（config.lipsync: "mora"。純関数）----------
PAUSE = "、。，．,.！？!?…・　 「」『』（）()"   # 台本の句読点など。息つぎ（口を閉じる間）として扱う
LIPS = set("まみむめもばびぶべぼぱぴぷぺぽ")          # 唇を閉じてから出す音（両唇音）
VOWELS = ("a", "i", "u", "e", "o")


def kata_to_hira(s):
    """カタカナをひらがなにする（ヴ・ヵ・ヶ・ー と、それ以外の字はそのまま）。"""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" and c not in "ヵヶ" else c for c in s)


def kana_morae(kana):
    """かな台本をモーラの列 [(字, 種類, 唇を閉じて始まるか), ...] にする。
    種類: a/i/u/e/o（母音）、n（ん）、q（っ）、pause（句読点などの息つぎ。続く息つぎは1つにまとめる）。
    小書きの「ゃゅょぁぃぅぇぉ」は前の音と1モーラにまとめ、母音をその音のものにする（「みゃ」は唇を閉じて a）。
    「ー」は直前の母音を伸ばす1モーラ（直前が母音でなければ捨てる）。「ゔ」は u。前に母音の無い小書きは、その母音の1モーラ。ほかの字（漢字・英字）は捨てる。"""
    out = []
    for ch in kata_to_hira(kana):
        if ch in PAUSE:
            if out and out[-1][1] != "pause": out.append((ch, "pause", False))
        elif ch in "ゃゅょぁぃぅぇぉ" and out and out[-1][1] in VOWELS:
            c, _, lips = out[-1]; out[-1] = (c + ch, VOW[ch], lips)
        elif ch == "ー":
            if out and out[-1][1] in VOWELS: out.append((ch, out[-1][1], False))
        elif ch == "ん": out.append((ch, "n", False))
        elif ch == "っ": out.append((ch, "q", False))
        elif ch == "ゔ": out.append((ch, "u", False))
        elif ch in VOW: out.append((ch, VOW[ch], ch in LIPS))
    return out


def mora_track(kana, start, end, pause_weight=2.0, close_frac=0.3, min_close=0.067):
    """1行のかな台本を、行の start〜end 秒にモーラの数で割り付けて [(開始秒, 終了秒, 形), ...] にする。
    形: a/i/u/e/o/n と closed（口を閉じる）。息つぎは pause_weight モーラ分の長さの closed、「っ」は closed。
    両唇音（まみむめも・ばびぶべぼ・ぱぴぷぺぽ）と、その前の「ん」は、モーラの頭 close_frac（ただし min_close 秒以上、
    モーラの半分以下）を closed にする。行の頭と終わりの息つぎは捨てる。モーラが無ければ空のリスト。"""
    ms = kana_morae(kana)
    while ms and ms[0][1] == "pause": ms.pop(0)
    while ms and ms[-1][1] == "pause": ms.pop()
    if not ms or end <= start: return []
    w = [pause_weight if k == "pause" else 1.0 for _, k, _ in ms]; unit = (end - start) / sum(w)
    seg = []; t = start
    for i, (_, k, lips) in enumerate(ms):
        d = w[i] * unit; t1 = end if i == len(ms) - 1 else t + d
        if k == "n" and i + 1 < len(ms) and ms[i + 1][2]: k = "closed"             # 「さんぽ」の「ん」は唇を閉じる
        if k in ("pause", "q"): seg.append((t, t1, "closed"))
        elif lips:
            c = min(max(close_frac * d, min_close), d / 2); seg += [(t, t + c, "closed"), (t + c, t1, k)]
        else: seg.append((t, t1, k))
        t = t1
    merged = []
    for s in seg:                                                              # 続く同じ形は1つにまとめる
        if merged and merged[-1][2] == s[2]: merged[-1] = (merged[-1][0], s[1], s[2])
        else: merged.append(s)
    return merged


def voiced_span(levels, fps, start, end, thr=0.15):
    """コマごとの声の大きさ levels から、start〜end 秒の中で声が thr 以上の最初と最後のコマの範囲（秒）。
    合成の声は行の頭と終わりに無音を持つので、モーラを割り付ける前に削る。声が無ければ (start, end) のまま。"""
    f0 = max(0, int(math.floor(start * fps))); f1 = min(len(levels), int(math.ceil(end * fps)))
    on = [f for f in range(f0, f1) if levels[f] >= thr]
    if not on: return start, end
    return max(start, on[0] / fps), min(end, (on[-1] + 1) / fps)


def mora_frames(segments, fps, nall):
    """mora_track の区間（何行分でもつないだ列）から、コマごとの形（区間の外は None）。
    コマ f は時刻 f/fps を含む区間の形にする。後の区間が前を上書きする。"""
    shape = [None] * nall
    for s, e, k in segments:
        for f in range(max(0, int(math.ceil(s * fps - 1e-9))), min(nall, int(math.ceil(e * fps - 1e-9)))): shape[f] = k
    return shape


def mora_mouth(Lv, k):
    """モーラの形と声の大きさから口の形。closed と形の無いコマは閉じる（None）。開きの大きさは choose_mouth と同じ。"""
    if k in (None, "closed"): return None
    return choose_mouth(Lv, k)
