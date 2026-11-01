"""video-mascot の共通部分: 設定の読み込み、足元の台座消し、軸足の靴の位置、背景の切り抜き、口パクと姿勢の時間割の純関数。"""
import json, math, os, random, sys
import cv2, numpy as np

BG = 253          # マスコットの絵の背景（/img が描く「ほぼ白」）の明るさ
MOUTHS = ["m1", "m2", "m3", "m4", "m5", "m6", "m7"]   # 少し開き・半開き・大開き・お・う・い/え・小さい開き
EYES = ["e1", "e2"]                                    # 4分の3閉じ・閉じ
GAZES = ["g_l", "g_r", "g_u", "g_c"]                    # 視線: 画面の左・右・上・カメラ（config.gaze がある時だけ描く。目の範囲で切り抜く）


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


def file_sig(paths):
    """作り置きの判定に使うファイルの中身の印 [[名前, 大きさ, md5], ...]。更新時刻を使わないので、パックを zip で
    別の PC に運んでも、元の絵が同じなら作り置きをそのまま使える。"""
    import hashlib
    out = []
    for p in paths:
        h = hashlib.md5()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
        out.append([os.path.basename(p), os.path.getsize(p), h.hexdigest()])
    return out


def file_sig_mtime(paths):
    """前の形の印 [[名前, 更新時刻, 大きさ], ...]。前に作った作り置きを捨てずに、中身の印へ書き換えるために比べる。"""
    return [[os.path.basename(p), os.path.getmtime(p), os.path.getsize(p)] for p in paths]


READONLY = ".readonly"                    # パックの作り置きの置き場（ib_wan/・ib_interp/）に置く印。ここでは作り直さない


def frame_paths(out_dir, n):
    """作り置きの列のコマ f1..fn のパスと、全部そろっているか。.png が全部あればそれ、無くて .webp が全部あれば .webp
    （パックは WebP で持つ）。どちらもそろっていなければ .png（作る所）。"""
    for ext in (".png", ".webp"):
        ps = [os.path.join(out_dir, f"f{j}{ext}") for j in range(1, n + 1)]
        if ps and all(os.path.exists(p) for p in ps): return ps, True
    return [os.path.join(out_dir, f"f{j}.png") for j in range(1, n + 1)], False


def readonly_guard(root, what):
    """root（ib_wan/ か ib_interp/）がパックの作り置き（.readonly がある）なら、作り直さずに止める。"""
    if os.path.exists(os.path.join(root, READONLY)):
        die(f"{what} がパックの作り置きに無いか、元の絵・設定と合わない。パックの作り置きは書き換えない（{os.path.realpath(root)}）。"
            "新PC（Wan・RIFE のある PC）でパックの元の作業フォルダに作り足して vm pack し直すか、この作業フォルダの "
            "ib_wan/・ib_interp/ をパックへのリンクでなく自分の置き場にして作る")


def stamp_ok(path, make):
    """作り置きの stamp.json が今の元の絵と設定に合うか。make(sig) は印の関数を受けて stamp の dict を返す。
    中身の印で合えば真。前の形（更新時刻）で合えば、中身の印に書き換えて真。どちらでもなければ偽。"""
    try: old = json.load(open(path))
    except (OSError, ValueError): return False
    new = json.loads(json.dumps(make(file_sig)))
    if old == new: return True
    if old == json.loads(json.dumps(make(file_sig_mtime))):
        if not under_readonly(path):              # パックの作り置き（.readonly）には書かない。書けない所でも合っていれば使う
            try: json.dump(new, open(path, "w"))
            except OSError: pass
        return True
    return False


def under_readonly(path, levels=3):
    """path（stamp.json など）の上の levels 段のどこかに .readonly があるか（パックの作り置きの置き場か）。"""
    d = os.path.dirname(os.path.abspath(path))
    for _ in range(levels):
        if os.path.exists(os.path.join(d, READONLY)): return True
        d = os.path.dirname(d)
    return False


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


def feet_center(img, min_area=2500):
    """足元の黒い塊（靴）全部の、左右の端の真ん中と一番下の y。見つからなければ None。boot_anchor と同じ範囲（絵の下 22.5%）で探す。
    斜め・横の姿勢で、立ち位置（両足の真ん中）を home と揃えるための目安。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); H = img.shape[0]; m = (g < 70).astype(np.uint8); m[:int(H * 0.775)] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    cand = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > min_area]
    if not cand: return None
    x0 = min(st[i, 0] for i in cand); x1 = max(st[i, 0] + st[i, 2] for i in cand); y1 = max(st[i, 1] + st[i, 3] for i in cand)
    return ((x0 + x1) / 2.0, float(y1))


def fg_mask(img, bg=BG, thr=24):
    """背景（ほぼ白の無地）と違う所。色・服に依らない前景の目安。"""
    return (np.abs(img.astype(np.int16) - bg).max(axis=2) > thr).astype(np.uint8)


def feet_anchor(img, band=0.04, min_area=400):
    """足元の基準点（色に依らない）: 前景の一番下の y と、そこから絵の高さの band の帯の中の前景の左右の端の真ん中。
    靴が黒くないキャラ用（anchor.mode: feet）。両足の真ん中なので、斜めの姿勢でも立ち位置が揃う（斜めで片足が少し上がっても入るよう、帯は背の 4%）。見つからなければ None。"""
    m = fg_mask(img); n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    big = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] > min_area])
    rows = np.where(big.any(axis=1))[0]
    if not len(rows): return None
    y1 = int(rows.max()); y0 = max(0, y1 - max(2, int(round(img.shape[0] * band))))
    xs = np.where(big[y0:y1 + 1].any(axis=0))[0]
    return ((xs.min() + xs.max()) / 2.0, float(y1 + 1))


def fg_height(img, anc):
    """前景の一番上から基準点の y まで（anchor.mode: feet の背の高さ）。"""
    rows = np.where(fg_mask(img).sum(1) > 3)[0]; return anc[1] - rows.min()


def centered_anchor(boot_p, feet_p, boot_home, feet_home):
    """姿勢の anchor（render が home の軸足 boot_home に重ねる点）を、両足の真ん中が home の両足の真ん中に来るように選ぶ。
    横は feet_p.x − (feet_home.x − boot_home.x)、縦は靴の底（boot_p の y）。"""
    return (round(float(feet_p[0] - (feet_home[0] - boot_home[0])), 1), round(float(boot_p[1]), 1))


def body_height(img, anc):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); rows = np.where((g < 150).sum(1) > 3)[0]; return anc[1] - rows.min()


# ---------- 背景の切り抜き（透明にする）----------
MATTE_MARGIN = 16                                   # roi の周りに足して計算する幅（輪郭のやわらげ・縁の明るさの近傍は 5 画素ほど）


def matte(clean, shadow, keeps=None, bg=BG, keep_max_area=600, roi=None, enclosed="bg"):
    """背景につながる白を透明にして、輪郭をやわらかくする。足元の影は黒の半透明で別に足す。
    roi=(x0, y0, x1, y1) を渡すと、その範囲だけの BGRA を返す（ワイプ用。中身は全体で作って切り抜いたものと同じ）。
    背景につながるかの判定（連結成分）は全体の絵で行い、重い計算は roi の周り（MATTE_MARGIN）だけで行う。
    絵を先に切り抜くと、切り口に触れた白（白いシャツ）が背景につながって見えて抜けるので、切り抜いてから呼ばない。
    enclosed: 外（絵の縁）につながっていない、囲まれたほぼ白の扱い。"bg"（既定・今まで）は、顔の箱の外・大きい・毛に囲まれた
    細長い白を背景にする（白いシャツやおでこの光も抜ける）。"keep" は囲まれた白をキャラの一部として閉じ、内側（縁を 3 画素
    除く）の 9 割以上が背景の色そのもの（外につながる白の中央値 ±2）のときだけ背景にする（脚の間・腕と体の間のすき間）。
    keeps=[(x0,y0,x1,y1), ...]（出力の画素）の外にある、ほぼ白の領域（毛束に囲まれたすき間など）は、外とつながっていなくても背景にする。
    keeps の中（白目・歯）は守る。ただし箱の中でも面積が keep_max_area（画素）を超える白は、白目・歯ではなく背景。clean: BGR（背景は BG の白）。戻り値: BGRA（アルファ付き）。
    黒い物（髪・靴）の縁は、背景の白とのまざり具合を暗さから割り戻す。明るい物（肌）の縁は形からやわらげる。"""
    H, W = clean.shape[:2]; b_, g_, r_ = cv2.split(clean); mn = cv2.min(cv2.min(b_, g_), r_).astype(np.float32)   # numpy の min(axis=2) は 30 倍遅い
    cand = (mn >= bg - 12).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(cand, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]]))) - {0}
    isbg = np.zeros(n, bool); isbg[list(border)] = True
    dark_near = cv2.dilate((mn < 110).astype(np.uint8), np.ones((9, 9), np.uint8))                 # 近くに黒い毛がある所
    if roi is not None:                            # roi の周りの窓。成分の判定はその窓に掛かる成分だけでよい（結果は画素ごとに成分で決まる）
        rx0, ry0, rx1, ry1 = max(0, roi[0]), max(0, roi[1]), min(W, roi[2]), min(H, roi[3])
        if rx1 <= rx0 or ry1 <= ry0: raise ValueError(f"roi が絵の外: {roi}")
        wx0, wy0, wx1, wy1 = max(0, rx0 - MATTE_MARGIN), max(0, ry0 - MATTE_MARGIN), min(W, rx1 + MATTE_MARGIN), min(H, ry1 + MATTE_MARGIN)
    else:
        wx0, wy0, wx1, wy1 = 0, 0, W, H
    def hits(stat):                                # 成分の外接箱が窓に掛かるか
        x, y, w, h = stat[:4]; return x < wx1 and x + w > wx0 and y < wy1 and y + h > wy0
    if enclosed not in ("bg", "keep"): raise ValueError(f"enclosed は bg か keep: {enclosed}")
    if enclosed == "keep":                         # 囲まれた白はキャラ。ただし内側が背景の色そのもの（平ら）なら、透けて見えている背景
        bgc = np.median(clean[np.isin(lab, list(border))], axis=0) if border else np.full(3, bg, np.float32)
        for i in range(1, n):
            if isbg[i] or st[i, cv2.CC_STAT_AREA] < 12 or not hits(st[i]): continue
            x, y, w, h, area = st[i]; cx, cy = cen[i]
            if area <= keep_max_area and keeps and any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in keeps): continue   # 白目・歯は守る（bg と同じ）
            region = (lab[y:y + h, x:x + w] == i).astype(np.uint8)
            inner = cv2.erode(region, np.ones((7, 7), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
            if inner.sum() < 30: inner = region > 0
            px = clean[y:y + h, x:x + w][inner].astype(np.int16)
            if (np.abs(px - bgc.astype(np.int16)) <= 2).all(axis=1).mean() >= 0.9: isbg[i] = True
    for i in range(1, n):
        if enclosed == "keep": break
        if isbg[i] or st[i, cv2.CC_STAT_AREA] < 12 or not hits(st[i]): continue
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
        if area > keep_max_area or not hits(st2[i]): continue
        reg = lab2[y:y + h, x:x + w] == i
        ys_, xs_ = np.where(reg); cx = x + xs_.mean(); cy = y + ys_.mean()
        if keeps and any(x0 <= cx <= x1 and y0 <= cy <= y1 for (x0, y0, x1, y1) in keeps): continue      # 白目・歯は守る
        pad = 6; y0_, y1_, x0_, x1_ = max(0, y - pad), min(H, y + h + pad), max(0, x - pad), min(W, x + w + pad)
        sub = lab2[y0_:y1_, x0_:x1_] == i; ringm = cv2.dilate(sub.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        ringm &= ~sub; dark_ring = (mn[y0_:y1_, x0_:x1_][ringm] < 110).mean() if ringm.any() else 0
        if dark_ring > 0.25: bgmask[y:y + h, x:x + w] |= reg
    if roi is not None:                            # ここから先は近傍だけを見る計算なので、窓で行い最後に roi を切り出す
        clean, shadow, mn, bgmask = (v[wy0:wy1, wx0:wx1] for v in (clean, shadow, mn, bgmask))
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
    out = np.dstack([np.clip(rgb, 0, 255).astype(np.uint8), (np.clip(at, 0, 1) * 255).astype(np.uint8)])
    return out if roi is None else out[ry0 - wy0:ry1 - wy0, rx0 - wx0:rx1 - wx0]


def wipe_box(fg):
    """人物の画素（真偽の配列）から、ワイプに切り抜く正方形 (x, y, 辺)。辺は背の 0.44 倍、横は頭（上 25%）の真ん中、
    上は頭の少し上。3 頭身のキャラで、顔と肩の上が丸に収まる（凜で合わせた）。画面の外に出る分は内側へ寄せる。人物が無ければ None。"""
    mh, mw = fg.shape; ys, xs = np.where(fg)
    if not len(ys): return None
    top, fh = int(ys.min()), int(ys.max() - ys.min())
    cx = float(np.median(xs[ys < top + 0.25 * fh])); side = min(mw, mh, int(0.44 * fh) // 2 * 2)
    x = int(round(cx - side / 2)); y = int(round(top - 0.01 * fh))
    return max(0, min(mw - side, x)), max(0, min(mh - side, y)), side


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


VIAS = ("cut", "fade", "turn")     # events の via: 姿勢の切り替えのつなぎ方（中割りを使わない時）


def resolve_events(events, home, starts, durs, ibdur, hira_stream, words_hira, log=None, dur_of=None, with_via=False, route=None):
    """config.events を姿勢の切り替えの時間割 [(開始秒, 前の姿勢, 次の姿勢), ...]（開始の早い順）にする。
    開始の指定: kw（ひらがなの並び）/ word（語の候補）の声の時刻から中割りの長さ ibdur と 0.04 秒を引く、at（秒）、
    line_start（行頭）、line_end（行末。offset の既定 0.05）。offset はどれにも足す（at を除く）。starts/durs は {行番号: 秒}。
    dur_of(前, 次, via) を渡すと、kw/word で引く長さをその切り替えの長さにする（クロスフェードなど）。
    with_via=True は (開始秒, 前, 次, via か None) の4つ組で返す（via は "cut"・"fade"・"turn"）。
    route(前, 次, via)（home 経由の切り替え config.via_home の時だけ）: (前→home の秒, hold, home→次 の秒) か None。
    返した切り替えは (s, 前, home) と (s + 前→home + hold, home, 次) の2つに分け（4つ組なら via は None）、kw/word は
    3つの和だけ早く始める（語の直前に次の姿勢に着く）。時刻の順で前の切り替えが「前」の姿勢に着かないもの（events の
    順と時刻の順が食い違う時）、前の切り替えを終える前に始まるもの、home→次 を終える前に次の切り替えが始まるものは分けず、
    route が無い時と同じ長さで開始を決め直す（重なる組は時刻の遅い方から1つずつやめ、そのあと戻せるものは戻す）。"""
    def check(off):                               # その off での時間割と、収まらない経由（時刻の順）
        ev = _resolve(events, home, starts, durs, ibdur, hira_stream, words_hira, None, dur_of, route, off)
        end = lambda e_: e_[0] + (sum(e_[4]) if e_[4] else e_[6])   # その切り替えを終える時刻
        def fits(j, e_):                          # 前の切り替えで前の姿勢に着いていて、前が終わってから始まり、次の切り替えまでに終わる
            prev = ev[j - 1] if j else None
            return e_[1] == (prev[2] if prev else home) and not (prev and e_[0] < end(prev)) and not (j + 1 < len(ev) and ev[j + 1][0] < end(e_))
        return ev, [e_[5] for j, e_ in enumerate(ev) if e_[4] and not fits(j, e_)]
    off = set()                                   # home 経由をやめた切り替え（events の何番目か）
    ev, bad = check(off)
    while bad:                                    # 1つずつ（時刻の遅い方から）やめる。やめた分の開始と長さが変わると、残りは収まることがある
        off.add(bad[-1]); ev, bad = check(off)
    again = bool(off)
    while again:                                  # やめたものを1つずつ戻してみて、全部が収まるなら戻す（戻せるものが無くなるまで）
        again = False
        for i in sorted(off):
            ev2, bad2 = check(off - {i})
            if not bad2: off.discard(i); ev = ev2; again = True; break
    if log: _resolve(events, home, starts, durs, ibdur, hira_stream, words_hira, log, dur_of, route, off)
    out = []
    nv = (None,) if with_via else ()
    for st, a_, b_, via, legs, _, _ in ev:
        if legs: out += [(st, a_, home, *nv), (st + legs[0] + legs[1], home, b_, *nv)]
        else: out.append((st, a_, b_, *((via,) if with_via else ())))
    return out


def _resolve(events, home, starts, durs, ibdur, hira_stream, words_hira, log, dur_of, route, off):
    """resolve_events の1回分。[(開始秒, 前, 次, via, home 経由の (秒, hold, 秒) か None, events の何番目か,
    経由しない時の切り替えの秒), ...]（開始の早い順）。"""
    ev = []; cur = home
    for i, e in enumerate(events):
        to = e["pose"]; via = e.get("via")
        if via is not None and via not in VIAS: die(f"events の via は {'・'.join(VIAS)} のどれか: {via}")
        legs = route(cur, to, via) if (route is not None and i not in off) else None
        d1 = ibdur if dur_of is None else dur_of(cur, to, via)
        if "kw" in e or "word" in e:
            t, how = find_word(words_hira, starts[e["line"]], durs[e["line"]], tuple(e["word"]), e.get("fallback", 0.5)) if "word" in e \
                else find_time(hira_stream, starts[e["line"]], durs[e["line"]], e["kw"], e.get("fallback", 0.5))
            st = t - (sum(legs) if legs else d1) - 0.04 + float(e.get("offset", 0.0))
            if log: log(f"行{e['line']} {cur}→{to}{'（home 経由）' if legs else ''}: 「{e.get('kw') or e['word']}」 {t:.2f}s（{how}）→ 開始 {st:.2f}s")
        elif "at" in e: st = float(e["at"])
        elif "line_start" in e: st = starts[e["line_start"]] + float(e.get("offset", 0.0))
        elif "line_end" in e: st = starts[e["line_end"]] + durs[e["line_end"]] + float(e.get("offset", 0.05))
        else: die(f"events に開始の指定が無い: {e}")
        ev.append((st, cur, to, via, legs, i, d1)); cur = to
    ev.sort(key=lambda x: x[:3])
    return ev


def plan_at(t, ev, home, ib_seq, ibfps, nib, ease_name=None, trans_of=None, ib_dur=None):
    """時刻 t に出す絵。("pose", 姿勢) か、切り替えの途中なら ("ib", 中割りの項目, 部品を借りる姿勢)。
    ib_seq(a, b) は中割りの列（無ければ None。その時は中割りなしで切り替える）。中割りの前の 4 割は元の姿勢の部品を使う。
    ease_name（二次運動の時だけ）: 切り替えの長さ nib/ibfps は同じまま、何枚目を出すかをイージングで決める（None は等速）。
    trans_of(前, 次, via)（向きの切り替えを使う時だけ）: None なら今までどおり、("cut", 0, 0) は一瞬、("fade"|"turn", 秒, 縮み) なら
    その長さのあいだ ("mix", 前の姿勢, 次の姿勢, 溶かす割合 0..1, 横の縮み 0..) を返す（途中で次の切り替えが始まれば次へ移る）。ev は3つ組か4つ組（4つ目が via）。
    ib_dur(前, 次)（コマ補間の時だけ）: (秒, イージング名) を返す組は、中割りの列（補間で細かくした列。長さは nib と違ってよい）を
    その秒で出し、何枚目かをそのイージングで決める。None を返す組は今までどおり。"""
    cur = home
    for i, e_ in enumerate(ev):
        s, a_, b_ = e_[:3]
        if t < s: break
        tr = trans_of(a_, b_, e_[3] if len(e_) > 3 else None) if trans_of else None
        if tr is not None:
            _, d_, sq_ = tr
            if tr[0] == "cut": cur = b_; continue
            if t < s + d_ and not (i + 1 < len(ev) and ev[i + 1][0] <= t):   # 溶かしの途中で次の切り替えが始まったら、次を優先
                u = (t - s) / d_; return ("mix", a_, b_, smooth01(u), sq_ * math.sin(math.pi * u) if tr[0] == "turn" else 0.0)
            cur = b_; continue
        seq = ib_seq(a_, b_); n = nib; di = ib_dur(a_, b_) if (ib_dur is not None and seq) else None
        if not seq: k = 99
        elif di is not None:                      # コマ補間: 細かくした列を、その組の秒とイージングで出す
            n = len(seq); u = (t - s) / di[0]; k = min(n - 1, int(ease(di[1], u) * n)) if u < 1 else 99
            if i + 1 < len(ev) and ev[i + 1][0] <= t: k = 99   # 長い補間の途中で次の切り替えが始まったら、次を優先
        elif ease_name is None: k = int((t - s) * ibfps)
        else: u = (t - s) * ibfps / nib; k = min(nib - 1, int(ease(ease_name, u) * nib)) if u < 1 else 99
        if seq and k < n: return ("ib", seq[k], a_ if k < int(n * 0.4 + 0.5) else b_)
        cur = b_
    return ("pose", cur)


# ---------- 口の形（純関数）----------
def tail_blip(x, sr, gap=0.25, max_len=0.1, end_tol=0.1, hop=0.01):
    """Irodori が行の声の終わりに出すゴミの音の範囲 (始めの標本, 終わりの標本) か None。
    条件: 声が終わって gap 秒以上黙ったあとに、max_len 秒以内の短い音があり、それがファイルの端か端の手前 end_tol 秒以内で鳴っている
    （旧PC の l11 は端で切れ、l8 は端の 0.06 秒手前の 40 ミリ秒の音だった）。範囲は短い音の始めからファイルの端まで。
    行の途中の読点の間（黙ったあとに語が続き、端の前に終わる）は端で切れていないので触らない。音の大きさの境は、行の大きい所の 3%（0.01 以上）。"""
    import numpy as np
    x = np.asarray(x, dtype=np.float32); h = max(1, int(sr * hop)); n = len(x) // h
    if n < 4: return None
    env = np.sqrt(np.mean(x[:n * h].reshape(n, h) ** 2, axis=1))
    if len(x) > n * h:                            # 端の半端な区切りも、その中の標本だけで測る（そこだけで鳴る短い音を落とさない）
        env = np.append(env, np.sqrt(np.mean(x[n * h:] ** 2))); n += 1
    thr = max(0.01, 0.03 * float(env.max()))
    on = env >= thr
    tol = max(2, int(round(end_tol / hop)))
    if not on[-tol:].any(): return None           # 端の近くで鳴っていない
    e = n
    while e > 0 and not on[e - 1]: e -= 1         # 最後の音の終わり
    b = e
    while b > 0 and on[b - 1]: b -= 1             # その音の始め
    blen = (e - b) * hop
    if blen > max_len: return None                # 最後の音が長い＝本物の語
    s = b
    while s > 0 and not on[s - 1]: s -= 1         # その前の黙った所の始め（前の声の終わり）
    if s == 0 or (b - s) * hop < gap: return None   # 前に声が無い、黙りが短い
    return b * h, len(x)


def frame_levels(x, sr, fps, nall, win):
    """声の波形 x（sr Hz）から、コマごとの大きさ（コマ f の頭 f/fps 秒から win サンプルの RMS。波形の外は 0）。
    コマの頭は round(f * sr / fps) で求める。sr // fps の整数の歩幅で進めると、割り切れないとき（16000 Hz・60fps は
    266.67→266）後ろのコマほど早い時刻の声を読み、280 秒の動画の終わりで 0.69 秒ずれて口が声より先に動いた。"""
    out = np.zeros(nall, np.float32)
    for f in range(nall):
        i = int(round(f * sr / fps))
        if i < len(x): out[f] = np.sqrt(np.mean(x[i:i + win] ** 2))
    return out


_KDIG = "〇一二三四五六七八九"


def _kanji_number(n):
    """0〜9999億9999万9999 の整数を漢数字に（10 は「十」、1000 は「千」）。"""
    if n == 0: return "零"
    out = ""
    for unit, big in ((10 ** 8, "億"), (10 ** 4, "万"), (1, "")):
        q = (n // unit) % 10000
        if not q: continue
        for d, small in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
            k = (q // d) % 10
            if k: out += ("" if (k == 1 and small) else _KDIG[k]) + small
        out += big
    return out


_NUM_RE = r"[0-9０-９]{1,3}(?:[,，][0-9０-９]{3})+|[0-9０-９]+"   # 桁区切り（1,000）か、数字の並び


def _num_spans(text):
    """text の中の、漢数字に直す数の [(始め, 終わり, 漢数字), ...]。小数（前後が . の数）と 1 兆以上は直さない。"""
    import re
    fw = str.maketrans("０１２３４５６７８９，", "0123456789,")
    out = []
    for m in re.finditer(_NUM_RE, text):
        a, b = m.start(), m.end()
        if (a > 0 and text[a - 1] in ".．") or (b < len(text) and text[b] in ".．"): continue
        n = int(m.group(0).translate(fw).replace(",", ""))
        if n < 10 ** 12: out.append((a, b, _kanji_number(n)))
    return out


def num_to_kanji(text):
    """文の中の算用数字を漢数字にする（「2つ」→「二つ」、「100」→「百」、「1,000」→「千」、「2026」→「二千二十六」）。
    かなに直すとき、数字のままだと読みが付かない。小数と 1 兆以上はそのまま。"""
    out, pos = "", 0
    for a, b, k in _num_spans(text): out += text[pos:a] + k; pos = b
    return out + text[pos:]


def words_hira(words, convert):
    """聞き取りの語の並び（表記）を、つないで文脈ごとにひらがなに直し、語ごとに配り直す（ひらがなと「ー」だけ）。
    1 語ずつ直すと、Whisper が「見える」を「見」「える」に分けたとき「見」が「けん」になり、キーワードの「みえる」と合わなかった。
    数字もつないだ文の上で漢数字にする（「20」「26」「年」を語ごとに直すと「二十二十六年」になる）。
    convert(text) は [{"orig": 表記, "hira": ひらがな}, ...]（pykakasi の convert）。表記の長さが合わなければ 1 語ずつ直す。"""
    keep = lambda h: "".join(ch for ch in h if "ぁ" <= ch <= "ゖ" or ch == "ー")
    text = "".join(words)
    norm, cover, pos = "", [], 0                     # cover[i]: 直した文の i 字目が元の文のどこ（始め, 終わり）にあたるか
    for a, b, k in _num_spans(text):
        for c in range(pos, a): norm += text[c]; cover.append((c, c + 1))
        for q, ch in enumerate(k): norm += ch; cover.append((a + (b - a) * q / len(k), a + (b - a) * (q + 1) / len(k)))
        pos = b
    for c in range(pos, len(text)): norm += text[c]; cover.append((c, c + 1))
    toks = convert(norm)
    if sum(len(t["orig"]) for t in toks) != len(norm):
        return [keep("".join(t["hira"] for t in convert(num_to_kanji(w)))) for w in words]
    bounds = []; p = 0
    for w in words: bounds.append((p, p + len(w))); p += len(w)
    out = [""] * len(words); p = 0
    for t in toks:
        na, nb = p, p + len(t["orig"]); p = nb; h = keep(t["hira"])
        if not h or nb <= na: continue
        a, b = cover[na][0], cover[nb - 1][1]       # この読みが元の文で占める範囲
        for i, (wa, wb) in enumerate(bounds):
            lo, hi = max(a, wa), min(b, wb)
            if hi <= lo: continue
            out[i] += h[round((lo - a) / (b - a) * len(h)):round((hi - a) / (b - a) * len(h))]
    return out


def word_hira(hira, word):
    """口パク（音量式）の母音に使う語のひらがな。かなが無く、英字・数字・記号（空白と句読点以外）を含む語は「あ」1 つにする。
    聞き取りの語が「CAD」「IGES」「100」「%」「×」のままだと母音が付かず、声が出ていても口が閉じたままだった。
    「あ」なら開きの大きさは声の大きさで決まる（choose_mouth）。"""
    if hira: return hira
    return "あ" if any(not ch.isspace() and ch not in PAUSE for ch in word) else ""


def fill_vowel_gaps(vowel_at, loud, fps, max_gap=0.4):
    """母音の無いコマのうち、声が出ている（loud）コマで、前後どちらかの語の端から max_gap 秒以内のものに、近い側の語の母音を入れた
    新しいリストを返す。聞き取りの語の時刻は声より短めに出ることがあり（文の頭で語の始まりが声より 0.3 秒ほど遅いなど）、
    語の間で声が出ているのに口が閉じた。語から max_gap より離れたコマと、声の無いコマは変えない。"""
    out = list(vowel_at); n = len(out); f = 0; lim = max_gap * fps
    while f < n:
        if out[f] is not None: f += 1; continue
        g = f
        while g < n and out[g] is None: g += 1
        prev = out[f - 1] if f > 0 else None; nxt = out[g] if g < n else None
        for k in range(f, g):
            if not loud[k]: continue
            dp = k - f + 1 if prev is not None else None; dn = g - k if nxt is not None else None
            if dp is not None and dp <= lim and (dn is None or dp <= dn): out[k] = prev
            elif dn is not None and dn <= lim: out[k] = nxt
        f = g
    return out


def speech_loud(level, vowel, thr=0.15):
    """口の検査で「声が出ている」とみなすコマか。声の大きさが thr（choose_mouth の閉じの境）以上で、母音が「っ」（"-"）でないこと。
    「っ」は口を閉じる音として choose_mouth が閉じるので、閉じていても不具合ではない。"""
    return bool(level >= thr) and vowel != "-"


SHORT_HOLD = 0.0                          # 着く前（これ未満）に次の切り替えが始まると、身振りが着かずに上書きされる。指を振るような素早い行き来（着いて 0.05 秒で次）は見えるので数えない


def short_holds(switches, home, min_hold=SHORT_HOLD):
    """切り替え [(開始秒, 長さ, 前, 次), ...]（時刻の順）のうち、姿勢（home 以外）に着く前に次の切り替えが始まる所（重なり、hold < min_hold）。[{"at": 着く切り替えの開始, "pose": 姿勢, "hold": 見せる秒（負は重なり）, "next": 次の切り替えの開始}, ...]。
    台本の身振りの語が行の頭の home の指定より前に来ると、身振りが着く前に home に上書きされた（旧PC の 29.04 秒の point_r など）。
    home を通る経路で一瞬 home に寄るのはわざとなので数えない。"""
    out = []
    for (t0, d0, _, b0), (t1, _, a1, _) in zip(switches, switches[1:]):
        hold = t1 - (t0 + d0)
        if b0 != home and hold < min_hold - 1e-6:   # ちょうど接する切り替え（0.1+0.2 と 0.3）を浮動小数点の誤差で重なりと見ない
            out.append({"at": round(t0, 3), "pose": b0, "hold": round(hold, 3), "next": round(t1, 3)})
    return out


def short_hold_report(spans):
    if not spans: return []
    lines = [f"身振りの検査: 着く前に次の切り替えに上書きされる身振り {len(spans)} 件（重なり。身振りが見えない）"]
    for s in spans: lines.append(f"  ✗ {s['at']:.2f} 秒に {s['pose']} へ → 着く前の {s['next']:.2f} 秒に次の切り替え（{s['hold']:+.2f} 秒）。kw を後ろの語にするか、前後の指定の時刻をずらす")
    return lines


def mouth_shut_spans(loud, speak, fps, f0, long_s=0.2):
    """声が出ている（loud）のに口が閉じている（speak が偽）コマが long_s 秒以上続く所。[{"from", "to", "dur"}, ...]。
    loud・speak は f0 コマ目から書き出した順。母音の取れない語や、声と口の時刻のずれで起きる。"""
    out, i, n = [], 0, len(loud)
    while i < n:
        if not (loud[i] and not speak[i]): i += 1; continue
        j = i
        while j < n and loud[j] and not speak[j]: j += 1
        if (j - i) / fps >= long_s: out.append({"from": round((i + f0) / fps, 3), "to": round((j + f0) / fps, 3), "dur": round((j - i) / fps, 3)})
        i = j
    return out


def mouth_shut_report(spans, problem=True):
    """mouth_shut_spans の結果を人が読む行のリストに。無ければ空。problem が偽なら知らせるだけ（△）。"""
    if not spans: return []
    lines = [f"口の検査: 声が出ているのに口が閉じている所 {len(spans)} か所" + ("" if problem else "（モーラ式。台本の区切りの割り付けなので知らせるだけ）")]
    for s in spans: lines.append(f"  {'✗' if problem else '△'} {s['from']:.2f}〜{s['to']:.2f} 秒（{s['dur']:.2f} 秒）")
    return lines


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


# ---------- 二次運動（config.motion。opt-in。純関数）----------
MOTION_DEFAULTS = {
    "breath": {"period": 3.6, "jitter": 0.12, "inhale": 0.4, "scale": 0.004, "lift": 2.0},   # 呼吸: 周期のゆらぎ、吸う側の割合、伸び縮み、持ち上がり（画素）
    "body": {"sway": 1.5, "period": 5.3},                                                      # 体の左右の揺れ（画素）
    "head": {"roll": 0.8, "period": 4.1, "nod": 2.0, "neck": 0.6, "radius": 0.9},            # 首: 傾き（度）、声の出だしでうなずく（画素）、首と頭の大きさの目安
    "blink": {"mean": 3.4, "spread": 0.35, "min": 1.6, "max": 7.0, "double": 0.15, "on_switch": True},   # まばたきの間隔のゆらぎ、2回続ける割合、姿勢の切り替えでまばたく
    "switch": {"ease": "in_out", "anticipate": 0.15, "anticipate_px": 5.0, "overshoot_px": 4.0, "settle": 0.45},  # 姿勢の切り替え: イージング、予備動作、オーバーシュート
}


def motion_config(value, flag=None):
    """config.motion と --motion on|off から、二次運動の設定（既定を埋めた辞書）か None（使わない）。
    value: 無し・false は使わない、true と {} は全部既定、辞書は項目ごとに上書き（項目を false にするとその動きだけ止める）。
    flag: "on" は value が無くても既定で使う、"off" は使わない。"""
    if flag not in (None, "on", "off"): raise ValueError(f"--motion は on か off: {flag}")
    if flag == "off" or (flag is None and (value is None or value is False)): return None
    if not isinstance(value, (dict, bool, type(None))): raise ValueError(f"motion は true/false か辞書: {value!r}")
    user = value if isinstance(value, dict) else {}
    unknown = set(user) - set(MOTION_DEFAULTS)
    if unknown: raise ValueError(f"motion に知らない項目: {sorted(unknown)}")
    out = {}
    for k, d in MOTION_DEFAULTS.items():
        u = user.get(k, {})
        if u is False: out[k] = None; continue
        if u is True: u = {}
        if not isinstance(u, dict): raise ValueError(f"motion.{k} は辞書か true/false: {u!r}")
        bad = set(u) - set(d)
        if bad: raise ValueError(f"motion.{k} に知らない項目: {sorted(bad)}")
        out[k] = {**d, **u}
    if out["switch"] is not None: ease(out["switch"]["ease"], 0.5)          # 名前の検査
    for k in ("breath", "body", "head"):                                    # 周期で割るので 0 以下は止める
        if out[k] is not None and not out[k]["period"] > 0: raise ValueError(f"motion.{k}.period は 0 より大きく: {out[k]['period']}")
    if out["head"] is not None and not (out["head"]["radius"] > 0 and out["head"]["neck"] >= 0):   # 半幅で割るので 0 以下は止める（止めるのは head: false）
        raise ValueError(f"motion.head は radius > 0、neck >= 0: radius={out['head']['radius']} neck={out['head']['neck']}")
    br = out["breath"]
    if br is not None and not (0 <= br["jitter"] < 1 and 0 < br["inhale"] < 1):
        raise ValueError(f"motion.breath は 0 <= jitter < 1、0 < inhale < 1: jitter={br['jitter']} inhale={br['inhale']}")
    b = out["blink"]
    if b is not None and not (b["mean"] > 0 and 0 < b["min"] <= b["max"]):  # 間隔が進まないと書き出しが終わらない
        raise ValueError(f"motion.blink は mean > 0 かつ 0 < min <= max: mean={b['mean']} min={b['min']} max={b['max']}")
    return out


def smooth01(u):
    """0..1 に切ってから 3u²-2u³（端で傾き 0）。"""
    u = min(1.0, max(0.0, u)); return u * u * (3 - 2 * u)


def ease(name, u):
    """イージング。u（0..1、外は切る）を 0..1 に写す。linear / in（3乗）/ out / in_out（3乗の前後）/ sine。"""
    u = min(1.0, max(0.0, u))
    if name == "linear": return u
    if name == "in": return u ** 3
    if name == "out": return 1 - (1 - u) ** 3
    if name == "in_out": return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2
    if name == "sine": return (1 - math.cos(math.pi * u)) / 2
    raise ValueError(f"知らないイージング: {name}")


_WOB = ((1.0, 1.0), (1.618034, 0.5), (2.718282, 0.25))   # 周波数の比（互いに割り切れない）と重み


def wobble(t, period, seed=0):
    """周期 period 秒を基本に、割り切れない周波数の正弦を3つ重ねた -1..1 のなめらかなゆらぎ。seed で位相が変わる。"""
    r = random.Random(seed); ph = [r.uniform(0, 2 * math.pi) for _ in _WOB]
    return sum(a * math.sin(2 * math.pi * k * t / period + p) for (k, a), p in zip(_WOB, ph)) / sum(a for _, a in _WOB)


def breath_phase(t, period=3.6, jitter=0.12, seed=0):
    """呼吸の位相（回数、単調に増える）。周期は ±jitter の割合でゆっくりゆらぐ（ゆらぎの周期は呼吸の 4.3 倍と 7.1 倍）。
    φ(t) = t/T + Σ c_i sin(2π t / S_i + p_i)。dφ/dt = (1/T)(1 + jitter·c(t))、|c(t)| ≤ 1 なので jitter < 1 なら逆戻りしない。"""
    if not 0 <= jitter < 1: raise ValueError(f"breath.jitter は 0 以上 1 未満: {jitter}")
    r = random.Random(seed); out = t / period
    for S, wgt in ((4.3, 0.6), (7.1, 0.4)):
        Sp = S * period; out += jitter * wgt * Sp / (2 * math.pi * period) * math.sin(2 * math.pi * t / Sp + r.uniform(0, 2 * math.pi))
    return out


def breath_wave(t, period=3.6, jitter=0.12, inhale=0.4, seed=0):
    """呼吸の深さ 0（吐ききった）..1（吸いきった）。1回の呼吸のうち inhale の割合で吸い、残りでゆっくり吐く。つなぎ目もなめらか。"""
    if not 0 < inhale < 1: raise ValueError(f"breath.inhale は 0 と 1 の間: {inhale}")
    u = breath_phase(t, period, jitter, seed) % 1.0
    return smooth01(u / inhale) if u < inhale else 1 - smooth01((u - inhale) / (1 - inhale))


def onset_env(levels, fps, tau=0.25):
    """コマごとの声の大きさから、声の出だし（大きくなる所）で立ち上がり tau 秒で減る包絡 0..1。うなずきに使う。"""
    k = math.exp(-1.0 / max(1e-6, tau * fps)); env = []; e = 0.0; prev = levels[0] if len(levels) else 0.0
    for v in levels:
        e = e * k + max(0.0, float(v) - prev); prev = float(v); env.append(e)
    env = np.array(env, np.float32)
    top = float(np.percentile(env[env > 0], 95)) if (env > 0).any() else 0.0
    return np.clip(env / top, 0, 1) if top > 0 else env


def head_weight(x, y, pivot, rx, band):
    """頭の中で 1、首 pivot より下と頭の横の外で 0 になる重み（x, y は配列可）。
    縦は首の高さ pivot[1]（0）から 2·band 上（1）へつなぎ、横は頭の半幅 rx（1）から 1.6rx（0）へつなぐ。肩は首より下なので動かない。"""
    px, py = pivot
    uy = np.clip((py - np.asarray(y, np.float32)) / (2 * band), 0, 1); wy = uy * uy * (3 - 2 * uy)
    ux = np.clip((np.abs(np.asarray(x, np.float32) - px) - rx) / (0.6 * rx), 0, 1); wx = 1 - ux * ux * (3 - 2 * ux)
    return wy * wx


def head_move(x, y, pivot, angle, dy, rx, band):
    """点 (x, y) を、首 pivot を中心に angle 度（画面で時計回りが正）回して dy 画素下げた位置へ動かす。
    重み head_weight の割合だけ動くので、首より下は動かない。戻り値 (x', y')。"""
    w = head_weight(x, y, pivot, rx, band); th = np.radians(angle) * w; c, s = np.cos(th), np.sin(th)
    X = np.asarray(x, np.float32) - pivot[0]; Y = np.asarray(y, np.float32) - pivot[1]
    return pivot[0] + c * X - s * Y, pivot[1] + s * X + c * Y + dy * w


def head_maps(x0, y0, x1, y1, pivot, angle, dy, rx, band):
    """cv2.remap 用の写像。出力の矩形 [x0,x1)×[y0,y1) の各画素を、元の絵のどこから取るか（head_move の逆）。
    重みは出力の点で取る近似（角度が小さいので十分）。戻り値 (map_x, map_y)、形は (y1-y0, x1-x0)。"""
    xs, ys = np.meshgrid(np.arange(x0, x1, dtype=np.float32), np.arange(y0, y1, dtype=np.float32))
    w = head_weight(xs, ys, pivot, rx, band); th = -np.radians(angle) * w; c, s = np.cos(th), np.sin(th)
    X = xs - pivot[0]; Y = ys - pivot[1] - dy * w
    return (pivot[0] + c * X - s * Y).astype(np.float32), (pivot[1] + s * X + c * Y).astype(np.float32)


def head_rig(mouth_roi, eye_roi, neck=0.6, radius=0.9):
    """口と目の範囲から、首の位置（回す中心）・頭の半幅・首のつなぎの幅を見積もる。
    首は口の下端から「目の中心→口の中心」の neck 倍下、頭の半幅は目の範囲の幅の radius 倍、つなぎは目→口の距離の半分。"""
    mcx, mcy = (mouth_roi[0] + mouth_roi[2]) / 2, (mouth_roi[1] + mouth_roi[3]) / 2
    ecx, ecy = (eye_roi[0] + eye_roi[2]) / 2, (eye_roi[1] + eye_roi[3]) / 2
    d = max(1.0, mcy - ecy)
    return ((mcx + ecx) / 2, mouth_roi[3] + neck * d), radius * (eye_roi[2] - eye_roi[0]), d / 2


def rig_affine(rig, A):
    """head_rig の結果 (首, 頭の半幅, つなぎの幅) を 2×3 のアフィン A で写す（中割りで顔が動いた分）。
    首は A で写し、長さは A の線形部分の面積の倍率の平方根で伸び縮みさせる。rig が None なら None。"""
    if rig is None: return None
    (px, py), rx, band = rig; A = np.asarray(A, np.float64); k = math.sqrt(abs(float(np.linalg.det(A[:, :2]))))
    return (float(A[0, 0] * px + A[0, 1] * py + A[0, 2]), float(A[1, 0] * px + A[1, 1] * py + A[1, 2])), rx * k, band * k


_SETTLE = 0.0
for _i in range(1, 1000): _SETTLE = max(_SETTLE, math.sin(2 * math.pi * _i / 1000) * (1 - _i / 1000) ** 2)


def switch_offset(t, switches, anticipate=0.15, anticipate_px=5.0, overshoot_px=4.0, settle=0.45):
    """姿勢の切り替えに足す縦のずれ（画素、下が正）。switches=[(開始秒, 長さ秒), ...]。
    予備動作: 開始の anticipate 秒前から沈み（最大 anticipate_px）、動きの前半で戻る。
    オーバーシュート: 終わってから settle 秒、上へ行き過ぎて（最大 overshoot_px）少し戻り、0 で止まる。"""
    out = 0.0
    for s, d in switches:
        if anticipate > 0 and s - anticipate <= t < s: out += anticipate_px * smooth01((t - (s - anticipate)) / anticipate)
        elif s <= t < s + d / 2 and d > 0: out += anticipate_px * (1 - smooth01((t - s) / (d / 2)))
        e = s + d
        if settle > 0 and e <= t < e + settle:
            x = (t - e) / settle; out -= overshoot_px * math.sin(2 * math.pi * x) * (1 - x) ** 2 / _SETTLE
    return out


def blink_times(end, rng, mean=3.4, spread=0.35, lo=1.6, hi=7.0, double=0.15, start=1.2, extra=(), gap=0.3):
    """まばたきの時刻（秒）の列。間隔は中央値 mean・ばらつき spread の対数正規を [lo, hi] に切ったもの。
    double の割合で 0.3〜0.45 秒後にもう1回。extra（姿勢の切り替えなど）にも足し、前と gap 秒未満の所は捨てる。rng は random.Random。"""
    if not (mean > 0 and 0 < lo <= hi): raise ValueError(f"まばたきの間隔は mean > 0 かつ 0 < lo <= hi: {mean}, {lo}, {hi}")
    ts = []; t = start
    while t < end:
        ts.append(t)
        if rng.random() < double: ts.append(t + rng.uniform(0.3, 0.45))
        t += min(hi, max(lo, rng.lognormvariate(math.log(mean), spread)))
    out = []
    for t in sorted(ts + [x for x in extra if 0 <= x < end]):
        if t < end and (not out or t - out[-1] >= gap): out.append(t)
    return out


# ---------- 向き・視線（config.transition / config.gaze。純関数）----------
TRANSITION_DEFAULTS = {"mode": "fade", "dur": 0.25, "squash": 0.06}
LOOKS = ("c", "l", "r", "u")            # 視線: カメラ・画面の左・画面の右・上
GAZE_DEFAULTS = {"lead": 0.15, "hold": 1.0}


def transition_config(value):
    """config.transition を (mode, dur, squash) の辞書か None（今までどおり＝中割りが無い組は一瞬で切り替える）に。
    mode: cut（一瞬）・fade（溶かす）・turn（溶かしながら横に少し縮めて回って見せる）。"""
    if value is None or value is False: return None
    if value is True: value = {}
    if not isinstance(value, dict): raise ValueError(f"transition は true/false か辞書: {value!r}")
    bad = set(value) - set(TRANSITION_DEFAULTS)
    if bad: raise ValueError(f"transition に知らない項目: {sorted(bad)}")
    out = {**TRANSITION_DEFAULTS, **value}
    if out["mode"] not in VIAS: raise ValueError(f"transition.mode は {'・'.join(VIAS)} のどれか: {out['mode']}")
    if not out["dur"] > 0: raise ValueError(f"transition.dur は 0 より大きく: {out['dur']}")
    if not 0 <= out["squash"] < 0.5: raise ValueError(f"transition.squash は 0 以上 0.5 未満: {out['squash']}")
    return out


def switch_kind(has_ib, via, trans, ibdur):
    """1つの切り替えのつなぎ方。戻り値 None（今までの処理: 中割りか一瞬）か ("fade"|"turn", 秒, 縮み)。
    via（events の指定）が最優先（via: "cut" は中割りがあっても一瞬で切り替える）。via が無ければ、中割りがある組は中割り（None）、
    無い組は trans（config.transition）。cut は ("cut", 0, 0)（長さ 0 の一瞬）。trans も via も無ければ None（今までどおり）。"""
    mode = via if via is not None else (None if has_ib else (trans["mode"] if trans else None))
    if mode is None: return None
    if mode == "cut": return ("cut", 0.0, 0.0)
    t = trans or TRANSITION_DEFAULTS
    return (mode, float(t["dur"]), float(t["squash"]) if mode == "turn" else 0.0)


def pose_view(pcfg):
    """姿勢の設定から (体の向き yaw, 顔の向き head_yaw)（度、画面の左が負）。無ければ正面 0。"""
    y = float(pcfg.get("yaw", 0)); return y, float(pcfg.get("head_yaw", y))


def gaze_keys(head_yaw, face=True):
    """その姿勢で描く視線の部品。顔が正面（|顔の向き| < 15 度）は g_l g_r g_u、斜め（< 60 度）は g_c g_u、横・後ろ・顔なしは無し。"""
    if not face: return []
    a = abs(((head_yaw + 180) % 360) - 180)
    return ["g_l", "g_r", "g_u"] if a < 15 else (["g_c", "g_u"] if a < 60 else [])


def gaze_part(look, head_yaw, have=None):
    """視線 look（c/l/r/u か None）を、顔の向き head_yaw の姿勢で貼る部品の名前にする（None は元の絵の目のまま）。
    顔が正面: c は元の目、l/r/u は g_l/g_r/g_u。顔が左向き（負）: l は元の目（もう左を見ている）、c と r は g_c（見る人の方へ戻す）。右向きは逆。
    have（その姿勢にある部品の名前の集まり）を渡すと、無い部品は元の目にする。"""
    if look is None: return None
    if look not in LOOKS: raise ValueError(f"視線は {'・'.join(LOOKS)} のどれか: {look}")
    a = ((head_yaw + 180) % 360) - 180
    if abs(a) < 15: k = None if look == "c" else "g_" + look
    elif abs(a) < 60:
        side = "l" if a < 0 else "r"
        k = "g_u" if look == "u" else (None if look == side else "g_c")
    else: k = "g_u" if look == "u" and abs(a) < 120 else None
    return k if (k is None or have is None or k in have) else None


def gaze_config(value):
    """config.gaze を {lead, hold, events} の辞書か None（使わない）に。"""
    if value is None or value is False: return None
    if value is True: value = {}
    if not isinstance(value, dict): raise ValueError(f"gaze は true/false か辞書: {value!r}")
    bad = set(value) - set(GAZE_DEFAULTS) - {"events"}
    if bad: raise ValueError(f"gaze に知らない項目: {sorted(bad)}")
    out = {**GAZE_DEFAULTS, **{k: v for k, v in value.items() if k != "events"}, "events": list(value.get("events", []))}
    if not (out["lead"] >= 0 and out["hold"] > 0): raise ValueError(f"gaze は lead >= 0、hold > 0: lead={out['lead']} hold={out['hold']}")
    return out


def resolve_gaze(events, starts, durs, hira_stream, words_hira, hold=1.0, log=None):
    """config.gaze.events を [(開始秒, 終わり秒, 視線), ...]（開始の早い順）にする。開始は kw/word（その語の声の時刻）・at・line_start・line_end、
    offset で微調整（姿勢の events と違い at にも足す）。終わりは until（秒）か、開始から hold 秒（events ごとに hold を書ける）。"""
    out = []
    for e in events:
        lk = e.get("look")
        if lk not in LOOKS: die(f"gaze.events の look は {'・'.join(LOOKS)} のどれか: {e}")
        off = float(e.get("offset", 0.0))
        if "kw" in e or "word" in e:
            t, how = find_word(words_hira, starts[e["line"]], durs[e["line"]], tuple(e["word"]), e.get("fallback", 0.5)) if "word" in e \
                else find_time(hira_stream, starts[e["line"]], durs[e["line"]], e["kw"], e.get("fallback", 0.5))
            st = t + off
            if log: log(f"視線 行{e['line']} {lk}: 「{e.get('kw') or e['word']}」 {t:.2f}s（{how}）")
        elif "at" in e: st = float(e["at"]) + off
        elif "line_start" in e: st = starts[e["line_start"]] + off
        elif "line_end" in e: st = starts[e["line_end"]] + durs[e["line_end"]] + off
        else: die(f"gaze.events に開始の指定が無い: {e}")
        en = float(e["until"]) if "until" in e else st + float(e.get("hold", hold))
        if en <= st: die(f"gaze.events の終わりが開始より前: {e}")
        out.append((st, en, lk))
    return sorted(out)


def gaze_track(nall, fps, spans, switches=(), yaw_of=None, lead=0.15):
    """コマごとの視線（c/l/r/u か None）。spans=[(開始, 終わり, 視線), ...]（台本の指定）が最優先。
    switches=[(開始, 長さ, 前の姿勢, 次の姿勢), ...] と yaw_of(姿勢)→顔の向き を渡すと、顔の向きが変わる切り替えの
    lead 秒前から切り替えの終わりまで、目が先に新しい向きへ動く（左へ回るなら l、右へなら r）。lead が 0 なら先回りしない。"""
    out = [None] * nall
    if yaw_of is not None and lead > 0:
        for s, d, a, b in switches:
            dy = yaw_of(b) - yaw_of(a)
            if abs(dy) < 1e-6: continue
            lk = "l" if dy < 0 else "r"
            for f in range(max(0, int(math.floor((s - lead) * fps))), min(nall, int(math.ceil((s + d) * fps)))): out[f] = lk
    for s, e, lk in spans:
        for f in range(max(0, int(math.floor(s * fps))), min(nall, int(math.ceil(e * fps)))): out[f] = lk
    return out


# ---------- 下半身の差し替え（config.legs_lock。opt-in）----------
LEGS_DEFAULTS = {"from": None, "cut": 0.38, "feather": 0.03, "hand_zone": 0.45, "poses": None, "fix_x": False}


def legs_config(value, poses_cfg, home):
    """config.legs_lock を辞書か None（今までどおり）に。from は下半身を写す元の姿勢（既定 home）、
    poses は差し替える姿勢（既定は正面の姿勢＝ yaw が無いか 0。元の姿勢は除く）。cut は切れ目の高さ（背の割合、足元から）、
    feather は切れ目の上で溶かす帯（背の割合）、hand_zone は切れ目から足元までのうち、元の絵の手を残す上の割合。
    fix_x: 下半身を横にずらして腰に合わせるのをやめる（true）。カメラ固定で描いた絵（Wan の切り替え）を毎コマ通すと、
    ずらしの量がコマごとに変わって足元が数 px 揺れる。"""
    if value is None or value is False: return None
    if value is True: value = {}
    if not isinstance(value, dict): raise ValueError(f"legs_lock は true/false か辞書: {value!r}")
    bad = set(value) - set(LEGS_DEFAULTS)
    if bad: raise ValueError(f"legs_lock に知らない項目: {sorted(bad)}")
    out = {**LEGS_DEFAULTS, **value}
    if out["from"] is None: out["from"] = home
    if out["from"] not in poses_cfg: raise ValueError(f"legs_lock.from の姿勢が無い: {out['from']}")
    if not 0.1 <= out["cut"] <= 0.7: raise ValueError(f"legs_lock.cut は 0.1〜0.7: {out['cut']}")
    if not 0 < out["feather"] < out["cut"]: raise ValueError(f"legs_lock.feather は 0 より大きく cut より小さく: {out['feather']}")
    if not 0 <= out["hand_zone"] <= 1: raise ValueError(f"legs_lock.hand_zone は 0〜1: {out['hand_zone']}")
    if not isinstance(out["fix_x"], bool): raise ValueError(f"legs_lock.fix_x は true か false: {out['fix_x']!r}")
    if out["poses"] is None:
        out["poses"] = [p for p, c in poses_cfg.items() if not c.get("yaw")]
    else:
        miss = [p for p in out["poses"] if p not in poses_cfg]
        if miss: raise ValueError(f"legs_lock.poses の姿勢が無い: {miss}")
    out["poses"] = [p for p in out["poses"] if p != out["from"]]
    return out


def _skin_mask(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV); h, s, v = cv2.split(hsv)
    return ((h < 25) & (s > 30) & (s < 170) & (v > 120)).astype(np.uint8)


def _body_edges(m, y, cx, W):
    """行 y の前景のうち、真ん中 cx の近くにある塊（腰・脚）の (左端, 股の隙間の左, 股の隙間の右, 右端)。体の横に下ろした手は入れない。
    股の隙間が無い行は、隙間の左右を左右の端の真ん中にする。"""
    xs = np.where(m[y])[0]
    if not len(xs): return None
    near = xs[np.abs(xs - cx) < 0.18 * W]
    if not len(near): return None
    runs = np.split(xs, np.where(np.diff(xs) > 3)[0] + 1)
    sel = [r for r in runs if r.min() <= near.max() and r.max() >= near.min() and abs((r.min() + r.max()) / 2 - cx) < 0.15 * W]
    if not sel: return None
    L, R = int(min(r.min() for r in sel)), int(max(r.max() for r in sel))
    gaps = [(int(a.max()), int(b.min())) for a, b in zip(sel, sel[1:])]
    if gaps:
        gl, gr = max(gaps, key=lambda g: g[1] - g[0])
    else:
        gl = gr = (L + R) / 2.0
    return (L, gl, gr, R)


def _main_blob(m):
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2: return m.astype(bool)
    return lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))


def lock_legs(img, canon, cut=0.38, feather=0.03, hand_zone=0.45, canon_scale=1.0, dx=None):
    """img の腰から下を canon の下半身に差し替えた絵（同じ大きさの BGR）と、使った値の辞書を返す。
    切れ目の高さは canon の背で測る。canon は足元の y を img に合わせ、切れ目の帯で脚の重なりが一番大きくなるよう横に ±40px までずらす。
    切れ目の上の帯では、両方の絵の腰の輪郭を行ごとに途中の輪郭へ伸び縮みさせてから混ぜる（二重の輪郭を出さない）。
    元の絵の手（肌の色）と、腰・脚の外にある腕・手は、切れ目から足元までの上 hand_zone までは元のまま残す（足首の肌は canon）。
    canon_scale: 先に canon をその足元を中心にこの倍率にする（書き出しで img が canon と違う倍率で拡大縮小される時、出来上がりの脚の大きさを揃える）。
    辞書の M は canon の座標を出来上がりの絵の座標へ写す 2x3 の行列（canon の足元の点を写せば、差し替えた絵の足元になる）。
    dx: 横のずらしを決め打ちする（None は切れ目の帯で脚の重なりが一番大きくなる所を ±40px 探す）。"""
    H, W = img.shape[:2]
    if canon.shape != img.shape: raise ValueError(f"legs_lock: 絵の大きさが基準と違う（{img.shape[1]}x{img.shape[0]} と {canon.shape[1]}x{canon.shape[0]}）")
    pv = feet_anchor(canon) or (W / 2.0, float(H))
    M0 = np.float32([[canon_scale, 0, pv[0] * (1 - canon_scale)], [0, canon_scale, pv[1] * (1 - canon_scale)]])
    if canon_scale != 1.0: canon = cv2.warpAffine(canon, M0, (W, H), flags=cv2.INTER_AREA if canon_scale < 1 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(BG, BG, BG))
    mi0 = fg_mask(img); rows = np.where(_main_blob(mi0).any(1))[0]             # 足元と背は人物の塊だけで測る（床の薄い影を拾わない）
    crow = np.where(_main_blob(fg_mask(canon)).any(1))[0]
    if not len(rows) or not len(crow): return img.copy(), None
    fy = int(rows.max()) + 1; h = int(crow.max()) + 1 - int(crow.min())   # 背は基準の絵で測る（手を頭の上に挙げた絵で切れ目が上へずれない）
    cy = int(round(fy - cut * h)); fb = max(2, int(round(feather * h))); dy = fy - (int(crow.max()) + 1)
    y0 = max(0, cy - fb)                              # 帯は絵の中に収める（上へはみ出す分は帯を薄くする）
    if cy - y0 < 2: return img.copy(), None
    fb = cy - y0
    a = mi0[y0:cy].sum(0).astype(np.float32)
    cs = cv2.warpAffine(canon, np.float32([[1, 0, 0], [0, 1, dy]]), (W, H), borderMode=cv2.BORDER_CONSTANT, borderValue=(BG, BG, BG))
    b = fg_mask(cs)[y0:cy].sum(0).astype(np.float32)
    if dx is None: dx = max(range(-40, 41), key=lambda s_: (float((a * np.roll(b, s_)).sum()), -abs(s_)))
    else: dx = int(dx)                                # 横のずらしを決め打ち（legs_lock.fix_x。カメラ固定の絵で足元を揺らさない）
    c = cv2.warpAffine(canon, np.float32([[1, 0, dx], [0, 1, dy]]), (W, H), borderMode=cv2.BORDER_CONSTANT, borderValue=(BG, BG, BG))
    wr = np.clip((np.arange(H) - y0) / fb, 0, 1).astype(np.float32)
    imgW, cW, mc = img.copy(), c.copy(), fg_mask(c); cx = W / 2.0; X = np.arange(W, dtype=np.float32)
    def track(m):                                     # 帯の各行の輪郭。取れない行は近い行で埋め、9 行の中央値で滑らかにする（手が腿に触れた行で跳ばない）
        es = [_body_edges(m, y, cx, W) for y in range(y0, cy)]
        if all(e is None for e in es): return None
        idx = [i for i, e in enumerate(es) if e is not None]
        es = [es[min(idx, key=lambda j: abs(j - i))] if e is None else e for i, e in enumerate(es)]
        a = np.array(es, np.float32); pad = np.pad(a, ((4, 4), (0, 0)), mode="edge")
        return np.median(np.stack([pad[k:k + len(a)] for k in range(9)]), axis=0)
    tf, tc = track(mi0), track(mc)
    for i, y in enumerate(range(y0, cy)):
        if tf is None or tc is None: break
        t = wr[y]; ef, ec = tf[i], tc[i]
        if ef[3] - ef[0] < 10 or ec[3] - ec[0] < 10: continue
        E = (1 - t) * ef + t * ec                                       # 途中の輪郭（左端・股の左・股の右・右端）
        if np.any(np.diff(E) < 0): continue
        for src, dst, e in ((img, imgW, ef), (c, cW, ec)):
            mx = np.interp(X, E, e)                                       # 区分線形で、途中の輪郭の各点を自分の輪郭の各点へ
            mx = np.where(X < E[0], X - E[0] + e[0], np.where(X > E[3], X - E[3] + e[3], mx)).astype(np.float32)
            dst[y] = cv2.remap(src[y:y + 1], mx[None, :], np.zeros((1, W), np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]
    hz = min(H, int(round(cy + hand_zone * (fy - cy))))
    sk = _skin_mask(img) | _skin_mask(imgW); sk[hz:] = 0; sk[:y0] = 0   # 帯で伸び縮みさせた手の写しも残す範囲に（縞を出さない）
    keep = np.zeros((H, W), np.uint8)
    for y in range(y0, hz):
        e = _body_edges(mi0, y, cx, W)
        if e is None: continue
        row = mi0[y].copy(); row[max(0, e[0] - 2):e[3] + 3] = 0; keep[y] = row
    sk = np.clip(cv2.GaussianBlur(cv2.dilate(sk, np.ones((9, 9), np.uint8)).astype(np.float32), (0, 0), 3), 0, 1)
    keep = np.clip(cv2.GaussianBlur(cv2.dilate(keep, np.ones((7, 7), np.uint8)).astype(np.float32), (0, 0), 2), 0, 1)
    ck = _skin_mask(c); ck[hz:] = 0; ck[:y0] = 0                    # 基準の絵の手（腰の前で組んだ手など）は写さない
    ck = np.clip(cv2.GaussianBlur(cv2.dilate(ck, np.ones((15, 15), np.uint8)).astype(np.float32), (0, 0), 4), 0, 1)
    k = np.maximum(sk, keep)[..., None]; w = wr[:, None, None] * (1 - ck[..., None])
    out = (imgW.astype(np.float32) * (1 - w) + cW.astype(np.float32) * w) * (1 - k) + img.astype(np.float32) * k
    M = M0.copy(); M[0, 2] += dx; M[1, 2] += dy
    return np.clip(out + 0.5, 0, 255).astype(np.uint8), {"cut": cy, "feather": fb, "dx": int(dx), "dy": int(dy), "M": M}


# ---------- 中割りのコマ補間（config.interp、opt-in）----------
_WIN_HOME = None


def win_decode(b):
    """cmd.exe の出力（バイト）を文字にする。UTF-8 で読めなければ CP932（日本語の Windows の既定）で読む。"""
    for enc in ("utf-8", "cp932"):
        try: return b.decode(enc)
        except UnicodeDecodeError: pass
    return b.decode("utf-8", errors="replace")


def win_home():
    """Windows のユーザーのフォルダを WSL から見たパス（例 /mnt/c/Users/<名前>）。環境変数 VM_WIN_HOME → cmd.exe の %USERPROFILE%。
    Windows の無い所（CI など）では None。1 回調べたら覚えておく。"""
    global _WIN_HOME
    if _WIN_HOME is None:
        v = os.environ.get("VM_WIN_HOME", "")
        if not v:
            import shutil, subprocess
            if shutil.which("cmd.exe") and shutil.which("wslpath"):
                try:
                    w = win_decode(subprocess.run(["cmd.exe", "/C", "echo %USERPROFILE%"], capture_output=True, timeout=15,
                                                  cwd="/mnt/c" if os.path.isdir("/mnt/c") else None).stdout).strip().splitlines()
                    if w and "%" not in w[-1]: v = subprocess.run(["wslpath", "-u", w[-1].strip()], capture_output=True, text=True, timeout=15).stdout.strip()
                except (OSError, subprocess.SubprocessError): v = ""
        _WIN_HOME = v
    return _WIN_HOME or None


def rife_tmp(cfg):
    """RIFE（Windows の exe）に渡す絵を置く一時フォルダ。config.interp.tmp か VM_RIFE_TMP、無ければ Windows の %TEMP%/vm_rife、
    Windows が無ければこの PC の一時フォルダ。"""
    if cfg.get("tmp"): return cfg["tmp"]
    wh = win_home()
    if wh: return os.path.join(wh, "AppData", "Local", "Temp", "vm_rife")
    import tempfile
    return os.path.join(tempfile.gettempdir(), "vm_rife")


INTERP_DEFAULTS = {
    "engine": "rife",       # rife: 描いた絵の間を RIFE で細かくする。wan: 姿勢の切り替えを Wan2.2 の First-Last-Frame で動かす（interp.wan）
    "mult": 8,              # 描いた絵（端の姿勢と中割り）の間を何倍に細かくするか
    "dur": 0.6,             # 中割りのある組の切り替えの秒（描いた枚数によらない）
    "ease": "in_out",       # 何枚目を出すかのイージング（linear / in / out / in_out / sine）
    "durs": {},             # 組ごとの秒 {"gap>gassho": 1.2}（逆向きの組にも効く）
    "pairs": None,          # 補間する組 ["gap>gassho", ...]（None は中割りのある全部の組）
    "direct": False,        # 中割りの無い組も、端の姿勢2枚の間を直に補間する（向きの同じ組だけ。溶かしの代わり）
    "model": "rife-v4.6",
    "exe": os.environ.get("VM_RIFE_EXE", "/mnt/c/ComfyUI/tools/rife-ncnn-vulkan-20221029-windows/rife-ncnn-vulkan.exe"),   # 環境変数 VM_RIFE_EXE で変えられる
    "tmp": os.environ.get("VM_RIFE_TMP") or None,   # Windows の exe が読み書きできる所。無ければ Windows の %TEMP%/vm_rife（rife_tmp）
    "wan": None,            # engine: wan の設定（WAN_DEFAULTS を上書きする辞書）
}

# engine: wan の既定。新PC の ComfyUI（portable）と、その models に置いた Wan2.2 I2V-A14B（GGUF）・Lightning の LoRA を使う
WAN_DEFAULTS = {
    "comfy": os.environ.get("VM_COMFY_ROOT") or os.environ.get("VS_COMFY_ROOT") or "/mnt/c/ComfyUI/ComfyUI_windows_portable",   # ComfyUI portable の場所（python_embeded と ComfyUI/ がある所）
    "url": "http://127.0.0.1:8188",
    "width": 704, "height": 1248,   # Wan に渡す大きさ（16 の倍数。縦横比は姿勢の絵に近く）
    "length": 13,           # Wan のコマ数（4n+1）。16fps で 0.75 秒分。再生の秒は interp.dur / durs で決まる
    "seed": 400,
    "rife_mult": 16,        # Wan のコマの間を RIFE で何倍に細かくするか
    "cut_tol": 5.0,         # 背景の明るさが 1 コマ目からこれ以上ずれたコマから後ろを捨てる（Wan の FLF は最後のまとまりで崩れる）
    "edge": 0.15,           # 切り替えの始まりと終わりの何割を、止まった絵と重ねるか
    "rife_pairs": [],       # Wan を通さず、描いた 2 枚の間を RIFE で直に補間する組（会釈など頭が少し動くだけの組）["home>nod", ...]
    "blink_tol": 0.05,      # Wan が勝手に入れる瞬き（首を回すと振るたびに目を閉じた）のコマを捨てる。目のあたりが閉じた目の絵にこれ以上よく合うコマ。null は捨てない
    "head_poses": [],       # 頭だけが動く姿勢（横を見る・首振り）。その組は「頭だけを回す」と描かせ、「頭を動かさない」を外す
    "style": None,          # 描かせる文のキャラの説明（None は config.mascot.description）
    "unet_high": "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf", "unet_low": "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
    "lora_high": "wan22_i2v_high_lightning.safetensors", "lora_low": "wan22_i2v_low_lightning.safetensors",
    "clip": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "vae": "wan_2.1_vae.safetensors",
    "clip_vision": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
}


def wan_config(value):
    """interp.wan（辞書か None）を、既定を埋めた辞書に。知らない項目・おかしな値は ValueError。"""
    v = {} if value is None else value
    if not isinstance(v, dict): raise ValueError(f"interp.wan は辞書: {value!r}")
    bad = sorted(set(v) - set(WAN_DEFAULTS))
    if bad: raise ValueError(f"interp.wan に知らない項目: {bad}")
    out = dict(WAN_DEFAULTS); out.update(v)
    for k in ("width", "height"):
        if not isinstance(out[k], int) or isinstance(out[k], bool) or out[k] < 64 or out[k] % 16: raise ValueError(f"interp.wan.{k} は 64 以上の 16 の倍数: {out[k]!r}")
    if not isinstance(out["length"], int) or isinstance(out["length"], bool) or out["length"] < 5 or (out["length"] - 1) % 4: raise ValueError(f"interp.wan.length は 5 以上の 4n+1: {out['length']!r}")
    if not isinstance(out["rife_mult"], int) or isinstance(out["rife_mult"], bool) or out["rife_mult"] < 1: raise ValueError(f"interp.wan.rife_mult は 1 以上の整数: {out['rife_mult']!r}")
    if out["blink_tol"] is not None and (isinstance(out["blink_tol"], bool) or not isinstance(out["blink_tol"], (int, float)) or out["blink_tol"] < 0): raise ValueError(f"interp.wan.blink_tol は 0 以上の数か null: {out['blink_tol']!r}")
    for k in ("cut_tol", "edge"):
        if isinstance(out[k], bool) or not isinstance(out[k], (int, float)) or out[k] < 0: raise ValueError(f"interp.wan.{k} は 0 以上の数: {out[k]!r}")
    if out["edge"] >= 0.5: raise ValueError(f"interp.wan.edge は 0.5 未満: {out['edge']!r}")
    if not isinstance(out["rife_pairs"], list): raise ValueError("interp.wan.rife_pairs は [\"前>次\", ...]")
    out["rife_pairs"] = [_pair_key(k) for k in out["rife_pairs"]]
    if not isinstance(out["head_poses"], list) or not all(isinstance(p, str) for p in out["head_poses"]): raise ValueError("interp.wan.head_poses は [\"姿勢\", ...]")
    return out


def wan_cut(levels, tol):
    """Wan のコマの背景の明るさの列から、使うコマの数（1 コマ目から tol を超えてずれたコマの手前まで。最低 1）。"""
    for i in range(1, len(levels)):
        if abs(levels[i] - levels[0]) > tol: return i
    return len(levels)


def motion_positions(steps, n_out):
    """コマの間の変化の大きさの列 steps（コマ数 - 1 個）から、動きが等しい割合で進む n_out 個の位置（小数のコマ番号、0〜コマ数-1）。
    Wan は動きを後ろに寄せがちで、時刻の割合でコマを選ぶと、前半は止まって最後に跳ぶ。止まったコマも少しは進める。"""
    s = np.asarray(steps, dtype=float)
    if n_out < 2: raise ValueError("motion_positions: n_out は 2 以上")
    if len(s) == 0: return np.zeros(n_out)
    s = np.maximum(s, 0) + max(1e-3, 0.03 * float(s.mean()))
    c = np.concatenate([[0.0], np.cumsum(s)]); c /= c[-1]
    return np.interp(np.linspace(0, 1, n_out), c, np.arange(len(c), dtype=float))


def edge_weight(u, edge):
    """切り替えの位置 u（0〜1）で、端の止まった絵を重ねる割合 (前の絵の重み, 次の絵の重み)。始まりと終わりの edge の幅で滑らかに。"""
    if edge <= 0: return 0.0, 0.0
    if u < edge:
        k = (edge - u) / edge; return k * k * (3 - 2 * k), 0.0
    if u > 1 - edge:
        k = (u - (1 - edge)) / edge; return 0.0, k * k * (3 - 2 * k)
    return 0.0, 0.0


def _pair_key(k):
    if not isinstance(k, str) or k.count(">") != 1 or not all(k.split(">")): raise ValueError(f"interp の組は \"前>次\" の形: {k!r}")
    return k


def interp_config(value, flag=None):
    """config.interp と --interp rife|wan|off から、中割りのコマ補間の設定（既定を埋めた辞書）か None（使わない）。
    value: 無し・false は使わない、true と {} は全部既定、辞書は項目ごとに上書き。知らない項目・おかしな値は ValueError。
    --interp rife|wan は engine をその値にする（config に書いた他の項目は生かす）。"""
    if flag not in (None, "rife", "wan", "off"): raise ValueError(f"--interp は rife か wan か off: {flag}")
    if flag == "off": return None
    if value in (None, False) and flag is None: return None
    v = {} if value is None or isinstance(value, bool) else value
    if not isinstance(v, dict): raise ValueError(f"config.interp は true か辞書: {value!r}")
    bad = sorted(set(v) - set(INTERP_DEFAULTS))
    if bad: raise ValueError(f"config.interp に知らない項目: {bad}")
    out = dict(INTERP_DEFAULTS); out.update(v)
    if flag is not None: out["engine"] = flag
    if out["engine"] not in ("rife", "wan"): raise ValueError(f"interp.engine は rife か wan: {out['engine']}")
    out["wan"] = wan_config(out["wan"]) if out["engine"] == "wan" else None
    if not isinstance(out["mult"], int) or isinstance(out["mult"], bool) or out["mult"] < 2: raise ValueError(f"interp.mult は 2 以上の整数: {out['mult']!r}")
    if isinstance(out["dur"], bool) or not isinstance(out["dur"], (int, float)) or out["dur"] <= 0: raise ValueError(f"interp.dur は正の秒: {out['dur']!r}")
    ease(out["ease"], 0.5)                        # 名前の検査
    if not isinstance(out["direct"], bool): raise ValueError(f"interp.direct は true か false: {out['direct']!r}")
    if not isinstance(out["durs"], dict): raise ValueError("interp.durs は {\"前>次\": 秒}")
    out["durs"] = {_pair_key(k): float(d) for k, d in out["durs"].items()}
    if any(d <= 0 for d in out["durs"].values()): raise ValueError("interp.durs の秒は正")
    if out["pairs"] is not None:
        if not isinstance(out["pairs"], list): raise ValueError("interp.pairs は [\"前>次\", ...]")
        out["pairs"] = [_pair_key(k) for k in out["pairs"]]
    return out


def interp_on(cfg, a, b):
    """組 a↔b を補間するか（向きは問わない）。"""
    return cfg["pairs"] is None or f"{a}>{b}" in cfg["pairs"] or f"{b}>{a}" in cfg["pairs"]


def interp_dur(cfg, a, b):
    """a→b の切り替えの秒。durs の "a>b"、無ければ "b>a"、無ければ dur。"""
    d = cfg["durs"]; return float(d.get(f"{a}>{b}", d.get(f"{b}>{a}", cfg["dur"])))


def dense_ks(div, mult):
    """端の姿勢（k=0 と k=div）の間の、補間した列の位置（div 等分の単位。k が整数の所は描いた中割り）。"""
    return [j / mult for j in range(1, div * mult)]


# ---------- 頭の向きの列（config.head、opt-in。純関数）----------
HEAD_DEFAULTS = {"chain": None, "events": [], "mult": 6}


def head_config(value, poses_cfg):
    """config.head を辞書か None（使わない）に。chain は頭の向きの姿勢を一方の端から他方の端へ並べたもの（体は同じ姿勢で描く。
    例 ["shake_r", "look_r", "home", "look_l", "shake_l"]）。events は頭の動きの要所（events と同じ開始の書き方で、その時刻に
    その姿勢の向きにいる）。mult は隣り合う向きの間を、中割りの等分（inbetween_div）の何倍に細かくするか。"""
    if value is None or value is False: return None
    if not isinstance(value, dict): raise ValueError(f"head は辞書: {value!r}")
    bad = sorted(set(value) - set(HEAD_DEFAULTS))
    if bad: raise ValueError(f"head に知らない項目: {bad}")
    out = {**HEAD_DEFAULTS, **value}
    ch = out["chain"]
    if not isinstance(ch, list) or len(ch) < 2 or not all(isinstance(p, str) for p in ch): raise ValueError("head.chain は姿勢の名前を 2 つ以上並べたもの")
    if len(set(ch)) != len(ch): raise ValueError(f"head.chain に同じ姿勢が 2 回ある: {ch}")
    miss = [p for p in ch if p not in poses_cfg]
    if miss: raise ValueError(f"head.chain の姿勢が無い: {miss}")
    if not isinstance(out["events"], list): raise ValueError("head.events は [{...}, ...]")
    for e in out["events"]:
        if not isinstance(e, dict) or e.get("pose") not in ch: raise ValueError(f"head.events の pose は head.chain のどれか: {e!r}")
    if not isinstance(out["mult"], int) or isinstance(out["mult"], bool) or out["mult"] < 1: raise ValueError(f"head.mult は 1 以上の整数: {out['mult']!r}")
    return out


def head_pos(t, keys, index, rest=None):
    """頭の動きの要所 keys [(秒, 姿勢), ...]（時刻の順）と、列の中の各姿勢の位置 index {姿勢: 位置} から、t の列の位置（小数）。
    要所の間は始まりと終わりが緩やかに動く。最初の要所より前と、最後の要所以降は None（頭の動きの外）。
    rest（体の home と同じ向きの姿勢）を渡すと、rest から rest への区間（頭の動きと頭の動きの間で正面に戻っている所）も None。
    渡さないと、2 回の頭の動きの間もずっと頭の列が出て、その間の体の身振りが消える。"""
    if len(keys) < 2 or t < keys[0][0] or t >= keys[-1][0]: return None
    for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
        if t0 <= t < t1:
            if rest is not None and p0 == rest and p1 == rest: return None
            u = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return index[p0] + (index[p1] - index[p0]) * smooth01(u)
    return None


# ---------- 切り替えの検査（書き出しの後に、各切り替えが実際に動いたか。純関数）----------
def frame_tag(pl, head=False):
    """1 コマで出した絵の種類。("head",) / ("ib", 前, 次, 出どころ) / ("mix", 前, 次) / ("pose", 姿勢)。
    出どころは列のパスで決める: ib_wan/ の下は "wan"、ib_interp/ の下は "interp"、ほかは "drawn"（描いた中割り）。"""
    if head: return ("head",)
    if pl[0] == "ib":
        p = str(pl[1][0]).replace(os.sep, "/")
        return ("ib", pl[1][1], pl[1][2], "wan" if "/ib_wan/" in p else ("interp" if "/ib_interp/" in p else "drawn"))
    if pl[0] == "mix": return ("mix", pl[1], pl[2])
    return ("pose", pl[1])


SWITCH_PROBLEMS = {
    "head": "頭の動きに隠れて、体の切り替えが出ていない",
    "missing": "切り替えの列（中割り・補間・Wan）が一度も出ていない",
    "not_wan": "Wan で動かす組なのに、Wan の列が出ていない",
    "not_reached": "切り替えの後に、次の姿勢になっていない",
}


def switch_check(tags, f0, fps, switches):
    """書き出した各コマの種類 tags（frame_tag、f0 コマ目から順に）と、切り替えの一覧 switches
    [{"at": 開始秒, "dur": 秒, "from": 前, "to": 次, "kind": "ib"|"mix"|"instant", "engine": ...}, ...]（時刻の順）から、
    切り替えごとの結果。switches の各要素に "status" と "frames"（区間のコマの内訳）を足した新しいリストを返す。
    kind: "ib" は中割り・補間・Wan の列で動かす、"mix" は溶かす・回る、"instant" は一瞬。engine が "wan" なら Wan の列が出たかも見る。
    status: "ok" / "skip"（書き出した範囲の外）/ SWITCH_PROBLEMS のどれか。"""
    n = len(tags); out = []
    def fi(t): return int(math.ceil(t * fps - 1e-6)) - f0     # 時刻 t 以降の最初のコマ（tags の位置）
    for i, sw in enumerate(switches):
        r = dict(sw); s = float(sw["at"]); d = float(sw["dur"]) if sw["kind"] != "instant" else 0.0
        a, b = sw["from"], sw["to"]; nxt = float(switches[i + 1]["at"]) if i + 1 < len(switches) else math.inf
        w0, w1, aft = fi(s), fi(min(s + d, nxt)), fi(s + d)
        if fi(s + d) < 0 or w0 >= n:
            r["status"] = "skip"; r["frames"] = {}; out.append(r); continue
        cnt = {"own": 0, "head": 0, "from": 0, "to": 0, "other": 0, "wan": 0}
        for t_ in tags[max(0, w0):max(0, min(n, w1))]:
            if t_[0] == "head": cnt["head"] += 1
            elif t_[0] in ("ib", "mix") and {t_[1], t_[2]} == {a, b}:
                cnt["own"] += 1; cnt["wan"] += t_[0] == "ib" and t_[3] == "wan"
            elif t_ == ("pose", a): cnt["from"] += 1
            elif t_ == ("pose", b): cnt["to"] += 1
            else: cnt["other"] += 1
        st = "ok"
        whole = w0 >= 0 and w1 <= n                                # 区間が全部、書き出した範囲に入っている
        if cnt["head"]: st = "head"
        elif sw["kind"] != "instant" and whole and w1 > w0 and cnt["own"] == 0: st = "missing"
        elif sw.get("engine") == "wan" and cnt["own"] and not cnt["wan"]: st = "not_wan"
        else:                                                      # 切り替えの後（終わりのコマは丸めで列の最後の 1 枚のことがあるので 2 コマ先まで見る。次の切り替えの前だけ）
            js = [j for j in range(aft, aft + 3) if 0 <= j < n and (j + f0) / fps < nxt - 1e-9]
            seen = [tags[j] for j in js]
            if js and ("pose", b) not in seen:                     # 幅のどこかで次の姿勢に着いていれば良い（すぐ後に頭の動きが始まってもよい）
                st = "head" if ("head",) in seen else "not_reached"
        r["status"] = st; r["frames"] = {k: v for k, v in cnt.items() if v}; out.append(r)
    return out


def head_spans(keys, rest=None):
    """頭の動きの要所 keys [(秒, 姿勢), ...] から、頭が動いている（か rest 以外の向きで止まっている）区間 [(始め, 終わり), ...]。
    head_pos が None でない区間と同じ（rest から rest への区間は外）。続いている区間はつなげる。"""
    out = []
    for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
        if t1 <= t0 or (rest is not None and p0 == rest and p1 == rest): continue
        if out and abs(out[-1][1] - t0) < 1e-9: out[-1] = (out[-1][0], t1)
        else: out.append((t0, t1))
    return out


def motion_verdict(change, noise, strong=2.0, weak=1.2):
    """切り替えの直前と直後のコマで変わった画素の割合 change を、切り替えの無い区間（話しているだけ）の同じ間隔の変化 noise と比べる。
    "moved"（noise の strong 倍を超える）/ "weak"（weak 倍を超える。目で確かめる）/ "still"（動いていない）/ "unknown"（noise が無い）。"""
    if noise is None: return "unknown"
    base = max(float(noise), 1e-4)
    if change > strong * base: return "moved"
    if change > weak * base: return "weak"
    return "still"


def switch_spans(switches, gap, t_lo, t_hi, busy=()):
    """各切り替えの (直前の時刻, 直後の時刻)、"unclean"、None のどれか。直前は開始の gap 秒前で、前の切り替えと頭の動き（busy
    [(始め, 終わり), ...]）の終わりより後に収める。直後は終わりの gap 秒後で、次の切り替えと頭の動きの始まりより後にしない
    （ほかの動きを、こちらの動きと取り違えないため）。収まらない（重なっている）ものは "unclean"（測れない）。
    前後が同じ姿勢・書き出した範囲 [t_lo, t_hi) の外は None。"""
    def end_of(sw): return float(sw["at"]) + (float(sw["dur"]) if sw["kind"] != "instant" else 0.0)
    out = []
    for i, sw in enumerate(switches):
        s = float(sw["at"]); e = end_of(sw)
        prv = end_of(switches[i - 1]) if i > 0 else -math.inf
        nxt = float(switches[i + 1]["at"]) if i + 1 < len(switches) else math.inf
        hit = False
        for h0, h1 in busy:
            h0, h1 = float(h0), float(h1)
            if h1 <= s: prv = max(prv, h1)
            elif h0 >= e: nxt = min(nxt, h0)
            else: hit = True                                       # 頭の動きが切り替えに重なっている
        tb, ta = max(s - gap, prv), min(e + gap, nxt)
        if sw["from"] == sw["to"] or s - gap < t_lo or e + gap >= t_hi: out.append(None)
        elif hit or tb > s + 1e-9 or ta < e - 1e-9 or ta <= tb: out.append("unclean")
        else: out.append((tb, ta))
    return out


def rest_pairs(switches, busy, span, t_lo, t_hi, margin=0.15, step=0.5, limit=200):
    """切り替えも頭の動き（busy [(始め, 終わり), ...]）も無い区間から、間隔 span の時刻の組 [(t, t + span), ...]（多すぎれば間引く）。"""
    spans = sorted([(float(s["at"]), float(s["at"]) + (float(s["dur"]) if s["kind"] != "instant" else 0.0)) for s in switches] + [tuple(b) for b in busy])
    free, cur = [], t_lo
    for s0, s1 in spans:                            # 区間は [t_lo, t_hi) の中だけ（一部だけ書き出したとき、範囲の後の切り替えで外へはみ出さない）
        if cur >= t_hi: break
        if s0 - margin > cur: free.append((cur, min(s0 - margin, t_hi)))
        cur = max(cur, s1 + margin)
    if t_hi > cur: free.append((cur, t_hi))
    out = []
    for a, b in free:
        t = a
        while t + span < b - 1e-9: out.append((round(t, 4), round(t + span, 4))); t += step
    if len(out) > limit: out = [out[int(i * len(out) / limit)] for i in range(limit)]
    return out


MOUTH_OFF_LONG = 0.2                     # 口の部品の無い姿勢で、これ以上の秒を話していたら問題（短いものは知らせるだけ）。会釈しながら「…方を説明する」が 0.42 秒


def mouth_off_spans(speak, face, fps, f0, long_s=MOUTH_OFF_LONG):
    """口の部品の無い姿勢（config の face: false）で話している所。口が動かないので、話しているのに口が止まって見える。
    speak[i]: そのコマで声が出ているか（口の形が閉じ以外）。face[i]: (口の部品があるか, 姿勢の名前)。どちらも f0 コマ目から書き出した順。
    口の部品の無いコマが続く区間ごとに、話している秒を数える。戻り値 [{"from", "to", "pose", "talk", "long"}, ...]（話していない区間は入れない）。"""
    out, i, n = [], 0, len(face)
    while i < n:
        if face[i][0]: i += 1; continue
        j = i
        while j < n and not face[j][0]: j += 1
        talk = sum(1 for k in range(i, j) if speak[k]) / fps
        if talk > 0:
            poses = sorted({face[k][1] for k in range(i, j)})
            out.append({"from": round((i + f0) / fps, 3), "to": round((j + f0) / fps, 3), "pose": "・".join(poses), "talk": round(talk, 3), "long": talk >= long_s})
        i = j
    return out


def mouth_report(spans, long_s=MOUTH_OFF_LONG):
    """mouth_off_spans の結果を人が読む行のリストに。無ければ空。"""
    if not spans: return []
    nl = sum(s["long"] for s in spans)
    lines = [f"口の検査: 口の部品の無い姿勢で話している所 {len(spans)} か所（{long_s} 秒以上は問題: {nl} か所）"]
    for s in spans:
        lines.append(f"  {'✗' if s['long'] else '△'} {s['from']:.2f}〜{s['to']:.2f} 秒 {s['pose']}: 話している {s['talk']:.2f} 秒（口が動かない）")
    return lines


def switch_report(results):
    """switch_check の結果を、人が読む行のリストに。1 行目は件数のまとめ、問題があれば 1 件 1 行で続ける。"""
    bad = [r for r in results if r["status"] not in ("ok", "skip")]
    n_in = sum(r["status"] != "skip" for r in results)
    eng = {}
    for r in results:
        if r["status"] != "skip": eng[r.get("engine") or r["kind"]] = eng.get(r.get("engine") or r["kind"], 0) + 1
    head = f"切り替えの検査: {n_in} 件（{'、'.join(f'{k} {v}' for k, v in sorted(eng.items()))}）"
    if not bad: return [head + " — 全部動いた"]
    lines = [head + f" — 問題 {len(bad)} 件"]
    for r in bad:
        lines.append(f"  ✗ {r['at']:.2f} 秒 {r['from']}→{r['to']}（{r.get('engine') or r['kind']}）: {SWITCH_PROBLEMS[r['status']]}  内訳 {r['frames']}")
    return lines


# ---------- home 経由の切り替え（config.via_home、opt-in。純関数）----------
VIA_HOME_DEFAULTS = {"hold": 0.0}       # hold: home に着いてから次へ動き出すまでの秒


def via_home_config(value):
    """config.via_home を {"hold": 秒} か None（使わない＝今までどおり）に。true と {} は既定。"""
    if value is None or value is False: return None
    v = {} if value is True else value
    if not isinstance(v, dict): raise ValueError(f"via_home は true/false か辞書: {value!r}")
    bad = sorted(set(v) - set(VIA_HOME_DEFAULTS))
    if bad: raise ValueError(f"via_home に知らない項目: {bad}")
    out = {**VIA_HOME_DEFAULTS, **v}
    h = out["hold"]
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or h < 0: raise ValueError(f"via_home.hold は 0 以上の秒: {h!r}")
    out["hold"] = float(h); return out


def home_route(a, b, home, has_pair):
    """a→b を home 経由でつなげるか。has_pair(x, y) は中割りの描いてある組か（向きは問わない）。
    a→b に中割りが無く、a→home と home→b の両方にある時だけ。home を含む組と、同じ姿勢どうしは経由しない。"""
    return a != b and home not in (a, b) and not has_pair(a, b) and has_pair(a, home) and has_pair(home, b)



def occlude(full, target, ref, thr=40.0, grow=7):
    """写した部品（絵全体の大きさの RGBA）の透明度を、写す先の絵 target が写す元の絵 ref（写す先の座標に合わせたもの）と
    大きく違う所で 0 にする。顔の前にある手（顎に手を当てる姿勢など）の上に、元の絵の顔（口・あご）を貼らないため。
    違う所は grow 画素だけ広げ、縁はぼかす。戻り値は新しい RGBA（full は書き換えない）。"""
    d = np.linalg.norm(target.astype(np.float32) - ref.astype(np.float32), axis=2)
    m = (cv2.GaussianBlur(d, (0, 0), 1.5) > thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(full[:, :, 3] > 0)
    if not len(xs): return full.copy()
    H, W = m.shape; mg = 25                          # 部品の範囲（少し広げた箱）
    bx0, by0, bx1, by1 = max(0, xs.min() - mg), max(0, ys.min() - mg), min(W, xs.max() + mg + 1), min(H, ys.max() + mg + 1)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m); keep_c = np.zeros(n, bool)
    for k in range(1, n):                            # 違う所の塊のうち、部品の箱の外まで続くもの（＝顔の外から入ってきた手）だけ
        x, y, w, h_, _a = st[k]
        if x < bx0 or y < by0 or x + w > bx1 or y + h_ > by1:
            if ((lab[by0:by1, bx0:bx1] == k).any()): keep_c[k] = True
    m = keep_c[lab].astype(np.uint8)                 # 顔の中で閉じた違い（目や口の描き方の差）は手と見なさない
    if grow: m = cv2.dilate(m, np.ones((grow, grow), np.uint8))
    keep = 1 - np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.5) * 1.5, 0, 1)
    out = full.copy(); out[:, :, 3] = (full[:, :, 3].astype(np.float32) * keep).astype(np.uint8)
    return out
