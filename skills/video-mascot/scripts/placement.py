"""vm overlay の置き方（プリセット・安全領域）と、登場・退場の動き。どれも opt-in で、指定しなければ overlay.py は今までどおり。
純関数だけを置く（ffmpeg は呼ばない）。tests/test_mascot_placement.py で確かめている。

座標はすべて主動画の画素。マスコットの「枠」は out/mascot.webm（または mascot_white.mp4）の1コマ全体で、
config.pad の白い余白を含む。プリセットと安全領域が揃えるのは枠の端で、キャラの輪郭ではない。"""
import math

# 主動画の画面比で決める置き方。h: 主動画の高さに対する枠の高さ、ax: 横の位置（0 = 安全領域の左端に枠の左端、1 = 右端に右端、0.5 = 中央）、
# bottom: 枠の下端を主動画の下端から上げる量（主動画の高さに対する割合。負にすると下へはみ出して切れる）
PRESETS = {
    "left":         {"h": 0.9,  "ax": 0.0, "bottom": 0.0},
    "right":        {"h": 0.9,  "ax": 1.0, "bottom": 0.0},
    "center":       {"h": 0.9,  "ax": 0.5, "bottom": 0.0},
    "corner-left":  {"h": 0.55, "ax": 0.0, "bottom": 0.0},
    "corner-right": {"h": 0.55, "ax": 1.0, "bottom": 0.0},
}
SAFE_DEFAULT = 0.05     # プリセットを使うときの安全領域（主動画の幅・高さに対する、上下左右の余白の割合）

EASES = ("linear", "out-cubic", "in-out-sine", "out-back")
MOVES = ("none", "fade", "slide")


def even(v):
    return int(round(v / 2) * 2)


def frame_size(MH, OW, OH, h):
    """枠の高さの割合 h から、重ねる大きさ (W, H)。偶数にそろえる（yuv420p の都合）。overlay.py の既定の計算と同じ式。"""
    H = even(MH * h); W = even(OW * H / OH)
    return W, H


def preset_geometry(name, MW, MH, OW, OH, safe=SAFE_DEFAULT, height=None, bottom=None):
    """プリセット name の置き方 → (W, H, X, Y, 注意の文の list)。height / bottom を渡すとプリセットの値より優先する（bottom は画素）。
    横の位置は安全領域 [safe*MW, MW - safe*MW] の中で ax に従って決める。枠が安全領域より広いときは中央に置く。
    枠の上端が安全領域の上に出るときは、位置は変えずに注意の文を返す（大きさを勝手に縮めない）。"""
    if name not in PRESETS: raise ValueError(f"知らないプリセット: {name}（{', '.join(PRESETS)}）")
    ps = PRESETS[name]
    W, H = frame_size(MH, OW, OH, ps["h"] if height is None else height)
    mx, my = int(round(MW * safe)), int(round(MH * safe))
    room = MW - 2 * mx - W
    X = mx + int(round(room * ps["ax"])) if room >= 0 else (MW - W) // 2
    b = int(round(MH * ps["bottom"])) if bottom is None else bottom
    Y = MH - H - b
    notes = []
    if room < 0: notes.append(f"枠の幅 {W} が安全領域の幅 {MW - 2 * mx} より広いので、中央に置いた")
    if Y < my: notes.append(f"枠の上端 {Y} が安全領域の上端 {my} より上に出ている（--height を下げるか、枠の上の余白を確かめる）")
    return W, H, X, Y, notes


# ---------- 登場・退場の動き ----------
def ease(name, u):
    """0..1 → 0..1 のイージング（u は 0..1 にクリップ）。out-back は途中で 1 を少し越えてから戻る（行き過ぎて戻る動き）。"""
    u = min(max(u, 0.0), 1.0)
    if name == "linear": return u
    if name == "out-cubic": return 1 - (1 - u) ** 3
    if name == "in-out-sine": return (1 - math.cos(math.pi * u)) / 2
    if name == "out-back": return 1 + 2.70158 * (u - 1) ** 3 + 1.70158 * (u - 1) ** 2
    raise ValueError(f"知らないイージング: {name}（{', '.join(EASES)}）")


def ease_expr(name, u):
    """ease(name, ·) と同じ式を ffmpeg の式で。u は ffmpeg の式の文字列。if は使わない（テストで Python の eval にかけるため）。"""
    if name == "linear": return f"({u})"
    if name == "out-cubic": return f"(1-pow(1-({u}),3))"
    if name == "in-out-sine": return f"((1-cos(PI*({u})))/2)"
    if name == "out-back": return f"(1+2.70158*pow(({u})-1,3)+1.70158*pow(({u})-1,2))"
    raise ValueError(f"知らないイージング: {name}（{', '.join(EASES)}）")


def fit_durations(span, d_in, d_out):
    """登場 d_in 秒と退場 d_out 秒が、マスコットが出ている span 秒に収まるようにする。足りなければ比で縮める。"""
    d_in, d_out = max(0.0, d_in), max(0.0, d_out)
    if span <= 0: return 0.0, 0.0
    if d_in + d_out > span:
        k = span / (d_in + d_out); d_in, d_out = d_in * k, d_out * k
    return d_in, d_out


def slide_from(ax, X, Y, w, h, MW, MH):
    """滑り込む向きと、画面の外の位置 (X0, Y0)。左寄り（ax < 0.5）は左の外から、右寄りは右の外から、中央は下の外から。
    w, h は実際に重ねる大きさ（はみ出しを切り落とした後）。"""
    if ax < 0.5: return -w, Y
    if ax > 0.5: return MW, Y
    return X, MH


def anchor_of(X, W, MW):
    """プリセットを使わないときの横の位置の比（滑り込む向きを決めるため）。枠の中心が画面のどちら寄りか。"""
    c = (X + W / 2) / MW
    return 0.0 if c < 0.45 else 1.0 if c > 0.55 else 0.5


def slide_expr(p, p_off, t_in0, d_in, t_out0, d_out, enter_ease, slide_in, slide_out):
    """座標1つ（x か y）の ffmpeg の式。t は主動画の時刻。
    登場: t_in0 から d_in 秒で p_off → p（enter_ease）。退場: t_out0 から d_out 秒で p → p_off（登場の逆再生と同じ形）。
    どちらも動かないときは p をそのまま文字列で返す。"""
    terms = [str(p)]
    dp = p_off - p
    if slide_in and d_in > 0:
        u = f"clip((t-{t_in0:.4f})/{d_in:.4f},0,1)"
        terms.append(f"{dp}*(1-{ease_expr(enter_ease, u)})")
    if slide_out and d_out > 0:
        u = f"clip(({t_out0 + d_out:.4f}-t)/{d_out:.4f},0,1)"     # 退場は時間を逆にした登場
        terms.append(f"{dp}*(1-{ease_expr(enter_ease, u)})")
    return "+".join(terms) if len(terms) > 1 else str(p)


def slide_value(p, p_off, t, t_in0, d_in, t_out0, d_out, enter_ease, slide_in, slide_out):
    """slide_expr と同じものを Python で（テストと、書き出し前の確認用）。"""
    v = p; dp = p_off - p
    if slide_in and d_in > 0: v += dp * (1 - ease(enter_ease, (t - t_in0) / d_in))
    if slide_out and d_out > 0: v += dp * (1 - ease(enter_ease, (t_out0 + d_out - t) / d_out))
    return v


def fade_filters(mode, d_in, end_local, d_out, fade_in, fade_out):
    """マスコットの流れ（時刻はマスコットの動画の中の時刻）に足す fade。alpha は透明度で、multiply は背景の白へ溶かす（乗算で白は透ける）。"""
    tail = ":alpha=1" if mode == "alpha" else ":color=0xfdfdfd"
    f = []
    if fade_in and d_in > 0: f.append(f"fade=t=in:st=0:d={d_in:.4f}{tail}")
    if fade_out and d_out > 0: f.append(f"fade=t=out:st={max(0.0, end_local - d_out):.4f}:d={d_out:.4f}{tail}")
    return f
