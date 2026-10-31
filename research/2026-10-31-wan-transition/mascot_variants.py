"""マスコットの見比べ用バージョンを作る。キャラ × 構図（全身 / 胸から上）× 動かし方（口パクのみ / 身振り）。
  口パクのみ: 立ち姿の絵は止めたまま、口（声の大きさ＋母音）と瞬きだけを貼る。生成なし
  身振り    : Wan I2V で作ったコマ（16fps）を RIFE で 60fps にし、毎コマ顔を追って口を貼る
口の規則は video-mascot の lib.py（choose_mouth / smooth_mouth、amp）と同じ。声は元の動画の master.wav。
使い方: <video-scene venv の python> mascot_variants.py <A|B> <full|bust> <lip|gesture> <out.mp4> [--from 秒] [--to 秒]
"""
import glob, json, math, os, random, shutil, subprocess, sys

import cv2
import numpy as np

sys.path.insert(0, os.path.expanduser("~/ClaudeCode/video-studio/skills/video-mascot/scripts"))
from lib import blink_times, choose_mouth, smooth_mouth, vowel_frames  # noqa: E402

SCR = os.path.dirname(os.path.abspath(__file__))
MA = os.path.expanduser("~/.local/share/video-scene/work/mascot-howto-v2/mascot")
VDIR = f"{MA}/voice"; VOICE = f"{VDIR}/master.wav"
WAN = "/mnt/c/ComfyUI/ComfyUI_windows_portable/ComfyUI/output/mascot_var"
RIFE = "/mnt/c/ComfyUI/tools/rife-ncnn-vulkan-20221029-windows/rife-ncnn-vulkan.exe"
RTMP = "/mnt/c/Users/shost/AppData/Local/Temp/vm_rife_var"
FPS, SRC_FPS, MULT = 60, 16, 4

# キャラの設定（座標はどれも 941x1672 の立ち姿の座標）
CHARS = {
    "A": {"base": f"{MA}/poses/pose_home.png",
          "mouth": {k: f"{MA}/parts/home_{k}.png" for k in ("m1", "m2", "m3", "m4", "m5", "m6", "m7")},
          "eyes": {k: f"{MA}/parts/home_{k}.png" for k in ("e1", "e2")},
          "mouth_box": (408, 552, 552, 652), "mouth_ell": [(428, 572, 532, 632)],
          "eye_box": (326, 460, 634, 575), "eye_ell": [(336, 470, 624, 566)],
          "face_box": (330, 440, 630, 558)},
    "B": {"base": f"{SCR}/cand_04.png",
          "mouth": {}, "eyes": {},                      # cand04_parts.json で埋める
          "mouth_box": (430, 525, 526, 600), "mouth_ell": [(442, 538, 514, 588)],
          "eye_box": (330, 405, 625, 520), "eye_ell": [(340, 436, 448, 512), (498, 416, 614, 500)],
          "face_box": (330, 410, 630, 535)},
}
FRAMES = {"full": {"box": (0, 0, 941, 1672), "out": (720, 1280), "wan": (448, 800)},
          "bust": {"box": (0, 130, 941, 1004), "out": (1008, 936), "wan": (672, 624)}}


def opt(name, default=None, typ=str):
    return typ(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def winpath(p):
    return subprocess.run(["wslpath", "-w", p], capture_output=True, text=True).stdout.strip()


def ell_mask(shape, ells, blur):
    m = np.zeros(shape, np.float32)
    for x0, y0, x1, y1 in ells:
        cv2.ellipse(m, ((x0 + x1) // 2, (y0 + y1) // 2), ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), blur)


class Layer:
    """部品（口や目）を出力の座標に合わせて持つ。box は立ち姿の座標、sc は立ち姿→出力の倍率、off は構図の切り出しの左上"""
    def __init__(self, base, parts, box, ells, sc, off, blend=None):
        x0, y0, x1, y1 = box
        self.w, self.h = round((x1 - x0) * sc), round((y1 - y0) * sc)
        self.x, self.y = round((x0 - off[0]) * sc), round((y0 - off[1]) * sc)
        rs = lambda im: cv2.resize(im[y0:y1, x0:x1], (self.w, self.h), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LANCZOS4).astype(np.float32)
        self.base = rs(base)
        self.parts = {k: rs(cv2.imread(p)) for k, p in parts.items()}
        m = ell_mask(base.shape[:2], ells, 3 / max(sc, 0.3))
        self.alpha = cv2.resize(m[y0:y1, x0:x1], (self.w, self.h))[:, :, None]
        self.ring = (self.alpha[:, :, 0] > 0.02) & (self.alpha[:, :, 0] < 0.5)
        # 貼る範囲を「部品と元の絵の差が大きい所」（唇・口の中・まぶた）に絞る。肌はほとんど貼り替えない
        self.blend = blend or os.environ.get("BLEND", "seg")
        self.sig = max(4.0, 9.0 * sc)              # 陰影（なだらかな明るさ）とみなすぼかしの幅
        self.tight = {}
        kc = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, round(5 * sc)) | 1,) * 2)
        kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, round(7 * sc)) | 1,) * 2)
        core = (self.alpha[:, :, 0] > 0.5).astype(np.uint8)
        for k, p in self.parts.items():
            diff = cv2.GaussianBlur(np.abs(p - self.base).max(2), (0, 0), 1.0)
            t = ((diff > 22) & (self.alpha[:, :, 0] > 0.25)).astype(np.uint8) * 255
            t = cv2.dilate(cv2.morphologyEx(t, cv2.MORPH_CLOSE, kc), kd)
            n, lab = cv2.connectedComponents((t > 0).astype(np.uint8))
            keep = [i for i in range(1, n) if (core[lab == i]).any()]      # 口（目）の中心につながる塊だけ。離れた肌の差は捨てる
            t = (np.isin(lab, keep) | (core > 0)).astype(np.uint8) * 255  # 楕円は常に入れて、下の唇（まぶた）を必ず覆う
            t[:2, :] = 0; t[-2:, :] = 0; t[:, :2] = 0; t[:, -2:] = 0
            self.tight[k] = t if t.any() else None
        self.parts_u8 = {k: np.clip(v, 0, 255).astype(np.uint8) for k, v in self.parts.items()}
        fb = max(1.0, 1.6 * sc)                    # 絞った範囲の縁のぼかし
        self.tight_a = {k: (cv2.GaussianBlur(t.astype(np.float32) / 255, (0, 0), fb)[:, :, None] if t is not None else None) for k, t in self.tight.items()}
        self.base_lo = cv2.GaussianBlur(self.base, (0, 0), self.sig)
        # 肌だけの陰影: 唇・口の中（部品側の範囲を広げた所）を除いてぼかす（正規化畳み込み）
        self.core = core.astype(np.float32)[:, :, None]
        self.sig2 = max(6.0, 14.0 * sc)
        self.wskin, self.wden, self.part_lo = {}, {}, {}
        for k, t in self.tight.items():
            if t is None: continue
            z = cv2.dilate(t, kd).astype(np.float32) / 255
            w = (1 - z)[:, :, None]
            self.wskin[k] = w
            self.wden[k] = cv2.GaussianBlur(w, (0, 0), self.sig2)[:, :, None] + 1e-4
            self.part_lo[k] = cv2.GaussianBlur(self.parts[k] * w, (0, 0), self.sig2) / self.wden[k]
        # seg: 部品からは唇と口の中の画素だけを取る。肌はコマの物だけを使う
        self.core_u8 = core
        self.k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, round(3 * sc)) | 1,) * 2)
        self.k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, round(5 * sc)) | 1,) * 2)
        self.ring_u8 = (cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(5, round(30 * sc)) | 1,) * 2)) & (1 - core)).astype(bool)
        self.seg_a, self.seg_lo = {}, {}
        bl = self.mouth_mask(np.clip(self.base, 0, 255).astype(np.uint8), largest=True, da=3, dl=18, no_hair=True)   # 元の絵の唇（端の細い所まで）
        self.base_lip = cv2.dilate(bl, self.k2) if bl is not None else None
        if bl is not None:
            ys, xs = np.nonzero(bl); self.lip_ref = (xs.mean(), ys.min())      # 唇の横の中心・上唇の上の端
        else:
            self.lip_ref = None
        self.align_lim = max(4, round(12 * sc))
        for k in self.parts:
            pu = self.parts_u8[k]
            mp = self.mouth_mask(pu, largest=True)
            if mp is None: continue
            self.seg_a[k] = cv2.GaussianBlur(cv2.dilate(mp, self.k1).astype(np.float32), (0, 0), max(0.8, 1.0 * sc))[:, :, None]
            skin = cv2.inpaint(pu, cv2.dilate(mp, self.k2) * 255, 3, cv2.INPAINT_TELEA)       # 部品の口を肌で埋めた物
            self.seg_lo[k] = cv2.GaussianBlur(skin.astype(np.float32), (0, 0), self.sig)

    def mouth_mask(self, roi_u8, largest, da=7, dl=30, no_hair=False):
        """楕円の中で、唇（周りの肌より赤い）と口の中（暗い）の画素。largest なら一番大きい塊だけ残し、穴（歯）を埋める。
        no_hair: 髪ほど暗い画素は除き、塊は楕円の中心に一番近い物を選ぶ（口を閉じた元の絵の唇を探すとき）"""
        lab = cv2.cvtColor(roi_u8, cv2.COLOR_BGR2LAB).astype(np.float32)
        L, A = lab[..., 0], lab[..., 1]
        if not self.ring_u8.any(): return None
        Ls, As = np.median(L[self.ring_u8]), np.median(A[self.ring_u8])
        m = ((self.core_u8 > 0) & (((A - As) > da) | (L < Ls - dl))).astype(np.uint8)
        if no_hair:
            m &= (L > Ls - 70).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, self.k2)
            n, lab_, st, cen = cv2.connectedComponentsWithStats(m)
            if n <= 1: return None
            ys, xs = np.nonzero(self.core_u8); c0 = np.array([xs.mean(), ys.mean()])
            i = 1 + int(np.argmin([np.hypot(*(cen[j] - c0)) for j in range(1, n)]))
            return (lab_ == i).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, self.k2)
        if not largest:                                   # コマ側: 楕円の上 3 割（鼻先）にかかる塊は拾わない
            ys = np.where(self.core_u8.any(1))[0]; ycut = ys[0] + 0.3 * (ys[-1] - ys[0])
            n, lab_, st, cen = cv2.connectedComponentsWithStats(m)
            keep = [i for i in range(1, n) if cen[i][1] >= ycut]
            m = np.isin(lab_, keep).astype(np.uint8)
        if largest:
            n, lab_, st, _ = cv2.connectedComponentsWithStats(m)
            if n <= 1: return None
            i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])); m = (lab_ == i).astype(np.uint8)
            ff = m.copy() * 255; h, w = m.shape; fm = np.zeros((h + 2, w + 2), np.uint8)
            cv2.floodFill(ff, fm, (0, 0), 128)
            m = ((ff != 128)).astype(np.uint8)            # 外から届かない所＝穴も口に含める
        return m if m.any() else None

    def paste(self, fr, key, dx=0, dy=0):
        px, py = self.x + dx, self.y + dy
        if key not in self.parts or px < 0 or py < 0 or px + self.w > fr.shape[1] or py + self.h > fr.shape[0]: return False
        if self.blend == "seg":
            if key not in self.seg_a: return False
            cur_u8 = np.ascontiguousarray(fr[py:py + self.h, px:px + self.w])
            mc = self.mouth_mask(cur_u8, largest=False)                     # コマ側の唇（Wan が描いた口）
            if mc is not None and self.lip_ref is not None:
                # 目で追った位置をもう一段合わせる: 横は唇の中心、縦は上唇の上の端（口を開けても動きにくい）
                ys, xs = np.nonzero(mc)
                ox, oy = round(xs.mean() - self.lip_ref[0]), round(ys.min() - self.lip_ref[1])
                if (ox or oy) and abs(ox) <= self.align_lim and abs(oy) <= self.align_lim:
                    nx, ny = px + ox, py + oy
                    if nx >= 0 and ny >= 0 and nx + self.w <= fr.shape[1] and ny + self.h <= fr.shape[0]:
                        px, py = nx, ny
                        cur_u8 = np.ascontiguousarray(fr[py:py + self.h, px:px + self.w])
                        mc = self.mouth_mask(cur_u8, largest=False)
            mz = cv2.dilate(mc, self.k2) if mc is not None else np.zeros(cur_u8.shape[:2], np.uint8)
            if self.base_lip is not None: mz = mz | self.base_lip          # 元の唇の位置（追跡でずらした所）も必ず塗る
            skin = cv2.inpaint(cur_u8, mz * 255, 3, cv2.INPAINT_TELEA) if mz.any() else cur_u8
            skin = skin.astype(np.float32)
            patch = np.clip(self.parts[key] + (cv2.GaussianBlur(skin, (0, 0), self.sig) - self.seg_lo[key]), 0, 255)
            a = self.seg_a[key]
            fr[py:py + self.h, px:px + self.w] = (patch * a + skin * (1 - a)).astype(np.uint8)
            return True
        if self.blend == "freq":
            a = self.tight_a[key]
            if a is None: return False
            cur = fr[py:py + self.h, px:px + self.w].astype(np.float32)
            # 部品 ＋（コマの肌の陰影 − 部品の肌の陰影）。陰影は唇・口の中を除いた肌だけから見積もるので、
            # Wan 自身の口の暗さや、描き直した部品の肌の白さが染みにならない
            cur_lo = cv2.GaussianBlur(cur * self.wskin[key], (0, 0), self.sig2) / self.wden[key]
            patch = np.clip(self.parts[key] + (cur_lo - self.part_lo[key]), 0, 255)
            # 口の中心から外れた所では、コマ側が髪（暗い）なら貼らない
            lum = cur.mean(2, keepdims=True)
            gate = np.maximum(self.core, np.clip((lum - 90) / 40, 0, 1))
            a = a * gate
            fr[py:py + self.h, px:px + self.w] = (patch * a + cur * (1 - a)).astype(np.uint8)
            return True
        if self.blend == "poisson":
            t = self.tight[key]
            if t is None: return False
            bx, by, bw, bh = cv2.boundingRect(t)
            # ポアソン合成: 明るさの変化だけを移す。縁は貼る先の肌の色につながるので、楕円や弧が浮かない
            p = (px + bx + bw // 2, py + by + bh // 2)
            try:
                fr[:] = cv2.seamlessClone(self.parts_u8[key], fr, t, p, cv2.NORMAL_CLONE)
            except cv2.error:
                return False
            return True
        cur = fr[py:py + self.h, px:px + self.w].astype(np.float32)
        shift = cur[self.ring].mean(0) - self.base[self.ring].mean(0) if self.ring.any() else 0   # 肌の色の差を合わせる
        patch = np.clip(self.parts[key] + shift, 0, 255)
        fr[py:py + self.h, px:px + self.w] = (patch * self.alpha + cur * (1 - self.alpha)).astype(np.uint8)
        return True


def mouth_track(n_all):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", VOICE, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768; SR = 16000
    hop = SR // FPS; WIN = SR * 2 // 30; R = max(1, round(FPS / 30))
    rms = np.array([np.sqrt(np.mean(x[i * hop: i * hop + WIN] ** 2)) if i * hop < len(x) else 0 for i in range(n_all)])
    lvl = np.clip(rms / (np.percentile(rms[rms > 0], 95) + 1e-6), 0, 1.5)
    import pykakasi
    KK = pykakasi.kakasi()
    def to_hira(s): return "".join(ch for ch in "".join(t["hira"] for t in KK.convert(s)) if "ぁ" <= ch <= "ゖ" or ch == "ー")
    words = json.load(open(f"{VDIR}/master.words.json"))
    vowel_at, _ = vowel_frames([(to_hira(w), s, e) for w, s, e in words], FPS, n_all)
    lvl_s = np.array([np.median(lvl[max(0, f - R):f + R + 1]) for f in range(n_all)])
    return smooth_mouth([choose_mouth(lvl_s[f], vowel_at[f]) for f in range(n_all)], R)


def blink_track(n_all, seed=5):
    """瞬きの目の部品の列（None=開いた目）。半目 3 コマ → 閉じ 4 コマ → 半目 3 コマ（60fps）"""
    eye = [None] * n_all
    for t in blink_times(n_all / FPS, random.Random(seed)):
        f = int(t * FPS)
        for k, key in enumerate(["e1"] * 3 + ["e2"] * 4 + ["e1"] * 3):
            if f + k < n_all: eye[f + k] = key
    return eye


def main():
    ch, fr_name, mode, outp = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    C = dict(CHARS[ch]); F = FRAMES[fr_name]
    if ch == "B":
        pj = json.load(open(f"{SCR}/cand04_parts.json")); C["mouth"] = pj["mouth"]; C["eyes"] = pj["eyes"]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", VOICE], capture_output=True, text=True).stdout)
    t0, t1 = opt("--from", 0.0, float), min(opt("--to", dur, float), dur)
    n_all = int(math.ceil(dur * FPS)); f0, f1 = int(round(t0 * FPS)), int(math.ceil(t1 * FPS))
    OW, OH = F["out"]; bx0, by0, bx1, by1 = F["box"]; sc = OH / (by1 - by0)
    base = cv2.imread(C["base"])
    mouth_l = Layer(base, C["mouth"], C["mouth_box"], C["mouth_ell"], sc, (bx0, by0))
    eye_l = Layer(base, C["eyes"], C["eye_box"], C["eye_ell"], sc, (bx0, by0), blend="alpha")
    mouth = mouth_track(n_all)
    eyes = blink_track(n_all) if mode == "lip" else [None] * n_all
    base_out = cv2.resize(base[by0:by1, bx0:bx1], (OW, OH), interpolation=cv2.INTER_AREA)

    dense = None
    if mode == "gesture":
        frames = []
        clips = sorted({os.path.basename(p).rsplit("_", 2)[0] for p in glob.glob(f"{WAN}/{ch}_{fr_name}_c*_*.png")})
        for i, c in enumerate(clips):
            alt = c.replace(f"{ch}_{fr_name}_", f"{ch}_{fr_name}_fold_")     # 作り直した版（腕組み）があればそちら
            if len(glob.glob(f"{WAN}/{alt}_*.png")) == 81: c = alt; print("  使う:", alt, flush=True)
            fs = sorted(glob.glob(f"{WAN}/{c}_*.png"))
            frames += fs if i == len(clips) - 1 else fs[:-1]
        i0 = max(0, int(t0 * SRC_FPS) - 1); i1 = min(len(frames), int(math.ceil(t1 * SRC_FPS)) + 2)
        seg = frames[i0:i1]
        shutil.rmtree(RTMP, ignore_errors=True); os.makedirs(RTMP + "/in"); os.makedirs(RTMP + "/out")
        for k, f in enumerate(seg): shutil.copyfile(f, f"{RTMP}/in/{k:05d}.png")
        r = subprocess.run([RIFE, "-i", winpath(RTMP + "/in"), "-o", winpath(RTMP + "/out"), "-m", "rife-v4.6", "-n", str(len(seg) * MULT)],
                           cwd=os.path.dirname(RIFE), capture_output=True, text=True, errors="replace")
        dense = sorted(glob.glob(RTMP + "/out/*.png"))[:(len(seg) - 1) * MULT + 1]
        if r.returncode != 0 or len(dense) < (len(seg) - 1) * MULT + 1: sys.exit(f"RIFE 失敗: {(r.stdout + r.stderr)[-600:]}")
        print(f"{ch} {fr_name}: Wan {len(clips)} 本・{len(frames)} コマ → RIFE {len(dense)} 枚", flush=True)
        ref = cv2.resize(cv2.imread(dense[0]), (OW, OH), interpolation=cv2.INTER_LANCZOS4)
    else:
        ref = base_out
    fx0, fy0, fx1, fy1 = [round((v - o) * sc) for v, o in zip(C["face_box"], (bx0, by0, bx0, by0))]
    tmpl = cv2.cvtColor(ref[fy0:fy1, fx0:fx1], cv2.COLOR_BGR2GRAY); SEARCH = round(60 * sc)
    ref_mouth = ref[mouth_l.y:mouth_l.y + mouth_l.h, mouth_l.x:mouth_l.x + mouth_l.w].astype(np.float32)

    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                           "-ss", f"{f0 / FPS:.4f}", "-t", f"{(f1 - f0) / FPS:.4f}", "-i", VOICE, "-map", "0:v", "-map", "1:a",
                           "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", outp], stdin=subprocess.PIPE)
    st = {"mouth": 0, "eyes": 0, "skip_track": 0, "skip_occl": 0}
    for f in range(f0, f1):
        if dense is None:
            fr = base_out.copy(); dx = dy = 0; ok = True
        else:
            di = min(len(dense) - 1, max(0, round((f / FPS * SRC_FPS - i0) * MULT)))
            fr = cv2.resize(cv2.imread(dense[di]), (OW, OH), interpolation=cv2.INTER_LANCZOS4)
            sx0, sy0 = max(0, fx0 - SEARCH), max(0, fy0 - SEARCH)
            win = cv2.cvtColor(fr[sy0:fy1 + SEARCH, sx0:fx1 + SEARCH], cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(win, tmpl, cv2.TM_CCOEFF_NORMED); _, score, _, loc = cv2.minMaxLoc(res)
            dx, dy = loc[0] + sx0 - fx0, loc[1] + sy0 - fy0; ok = score >= 0.55
        mk = mouth[f] if f < n_all else None
        if mk:
            if not ok: st["skip_track"] += 1
            else:
                px, py = mouth_l.x + dx, mouth_l.y + dy
                cur = fr[py:py + mouth_l.h, px:px + mouth_l.w].astype(np.float32)
                if dense is not None and cur.shape == ref_mouth.shape and np.mean(np.abs(cur - ref_mouth)[mouth_l.alpha[:, :, 0] > 0.5]) > 40:
                    st["skip_occl"] += 1                 # 手が口の前にある
                elif mouth_l.paste(fr, mk, dx, dy): st["mouth"] += 1
        if eyes[f] and eye_l.paste(fr, eyes[f]): st["eyes"] += 1
        frf = fr.astype(np.float32)                    # ほぼ白の背景を真っ白に
        w = np.clip((frf.min(2, keepdims=True) - 236) / 12, 0, 1)
        ff.stdin.write((frf + (255 - frf) * w).astype(np.uint8).tobytes())
    ff.stdin.close(); ff.wait()
    if dense is not None: shutil.rmtree(RTMP, ignore_errors=True)
    print(f"{ch} {fr_name} {mode}: {st} → {outp}", flush=True)


if __name__ == "__main__":
    main()
