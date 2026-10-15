"""video-mascot の共通部分: 設定の読み込み、足元の台座消し、軸足の靴の位置、背景の切り抜き。"""
import json, os, sys
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
