"""喋るマスコットを「Codex の姿勢の絵（止めて話す所）＋ Wan の姿勢の切り替え」で書き出す（キャラに依らない）。
  止めて話す所: <作業フォルダ>/poses/pose_<姿勢>.png ＋ parts_<姿勢>/（口・目の透過 PNG と parts.json。vm parts の形）
  切り替え    : Wan2.2 I2V の First-Last-Frame のコマ（<WAN>/<prefix>_<前>__<次>_*.png）を RIFE で 4 倍にし、
                明るさを始点と終点の絵に合わせ、元の切り替えの秒で再生。最後の 2 割で行き先の絵へ重ねて渡す。
                口は顔（目のあたり）を追って、近い方の姿勢の口の部品を重ねる
  姿勢の絵の無いうなずき（nod）: 前の姿勢→nod→次の姿勢 を 1 本の Wan（<前>__nod__<次>）にまとめる
  下半身: 全部 home の下半身に固定（lock_legs、横のずらしは 0）
  .webm に書くと背景を透明にする（解説画面に重ねる素材）。.mp4 は白背景
使い方:
  <venv python> render_wan.py <out> --work <作業フォルダ> --wan <prefix> [--events <config.json>] [--lip] [--frame full|bust]
                              [--from 秒 --to 秒] [--emit-spec <wan の設定.json> --style "..."]
  --lip: 身振りなし（home のまま口と瞬きだけ）
  --emit-spec: 書き出さずに、足りない Wan の切り替えを gen_wan14b_mascot_flf.py の設定として書く
"""
import glob, inspect, json, math, os, shutil, subprocess, sys
from collections import OrderedDict

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mascot_variants as mv  # noqa: E402
import lib  # noqa: E402

WAN = "/mnt/c/ComfyUI/ComfyUI_windows_portable/ComfyUI/output/mascot_tr"
CIN = "/mnt/c/ComfyUI/ComfyUI_windows_portable/ComfyUI/input"
SRC_W, SRC_H = 941, 1672
FRAMES = {"full": {"box": (0, 0, 941, 1672), "out": (720, 1280), "pad_w": 874},
          "bust": {"box": (0, 130, 941, 1004), "out": (1008, 936), "pad_w": None}}
_src = inspect.getsource(lib.lock_legs).replace(
    "dx = max(range(-40, 41), key=lambda s_: (float((a * np.roll(b, s_)).sum()), -abs(s_)))", "dx = 0")
assert "dx = 0" in _src
_ns = {}; exec(_src, lib.__dict__, _ns); lock_legs = _ns["lock_legs"]


def opt(name, default=None, typ=str):
    return typ(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


class Parts:
    def __init__(self, folder, sc):
        self.p = {}
        if not os.path.exists(folder + "parts.json"): return
        for k, (x, y) in json.load(open(folder + "parts.json")).items():
            im = cv2.imread(folder + k + ".png", cv2.IMREAD_UNCHANGED)
            if im is None or im.ndim != 3 or im.shape[2] != 4: continue
            h, w = im.shape[:2]
            im = cv2.resize(im, (max(1, round(w * sc)), max(1, round(h * sc))), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LANCZOS4).astype(np.float32)
            a = np.clip(im[:, :, 3:] / 255.0, 0, 1)
            core = (a[:, :, 0] > 0.05).astype(np.uint8)
            ring = cv2.dilate(core, np.ones((7, 7), np.uint8)).astype(bool) & ~core.astype(bool)
            self.p[k] = (round(x * sc), round(y * sc), np.clip(im[:, :, :3], 0, 255), a, ring)
        # 切り替え中に使う絞ったアルファ: 口の部品は唇と口の中（暗い所・囲まれた歯）だけ。肌まで貼ると、向きの変わる途中で四角く浮いた
        self.tight = {}
        for k, (x, y, rgb, a, ring) in self.p.items():
            if not k.startswith("m"): continue
            u8 = rgb.astype(np.uint8); b_, g_, r_ = [u8[:, :, i].astype(np.int16) for i in range(3)]
            m = (((r_ - g_ > 40) & (r_ > 110) & (r_ - b_ > 30)) | (u8.max(2) < 110)) & (a[:, :, 0] > 0.3)
            m = m.astype(np.uint8)
            if m.sum() < 4: continue
            kk = max(3, round(7 * sc)) | 1
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk)))   # 歯（唇に囲まれた白）も入れる
            m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, round(3 * sc)) | 1,) * 2))
            t = cv2.GaussianBlur(m.astype(np.float32), (0, 0), max(0.8, 1.2 * sc))[:, :, None]
            self.tight[k] = np.minimum(a, t)

    def paste(self, fr, key, dx=0, dy=0, ref=None, tight=False):
        if key not in self.p: return False
        x, y, rgb, a, ring = self.p[key]; x += dx; y += dy; h, w = rgb.shape[:2]
        if tight and key in self.tight: a = self.tight[key]
        if x < 0 or y < 0 or x + w > fr.shape[1] or y + h > fr.shape[0]: return False
        reg = fr[y:y + h, x:x + w].astype(np.float32)
        if ref is not None and ring.any():               # Wan のコマの上: 部品の周りの肌の平均の差だけ色を合わせる
            rr = ref[y - dy:y - dy + h, x - dx:x - dx + w].astype(np.float32)
            if rr.shape == reg.shape: rgb = np.clip(rgb + (reg[ring].mean(0) - rr[ring].mean(0)), 0, 255)
        fr[y:y + h, x:x + w] = (rgb * a + reg * (1 - a)).astype(np.uint8)
        return True


def matte(fr):
    """背景（外の縁につながる白〜薄い灰色）を透明にしたアルファ。白いブラウス・白目・歯は外につながらないので残る"""
    x = fr.astype(np.int16); mn, mx = x.min(2), x.max(2)
    cand = ((mn > 195) & (mx - mn < 10)).astype(np.uint8)
    h, w = cand.shape; ff = cand.copy(); fm = np.zeros((h + 2, w + 2), np.uint8)
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (0, h // 2), (w - 1, h // 2)):
        if ff[sy, sx] == 1: cv2.floodFill(ff, fm, (sx, sy), 2)
    bg = (ff == 2)
    soft = np.clip((250 - mn.astype(np.float32)) / 40, 0, 1)
    band = cv2.dilate(bg.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~bg
    a = np.where(bg, 0.0, 1.0).astype(np.float32); a[band] = soft[band]
    a = cv2.GaussianBlur(a, (0, 0), 0.7)
    a[bg & (cv2.erode(bg.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)] = 0
    return (a * 255).astype(np.uint8)


RMULT = 16                                   # RIFE の倍率（Wan の 16fps のコマの間を何倍に細かくするか）


def motion_curve(frames):
    """コマ列の動きの積み上げ（0〜1）。再生の割り付けを動きの量でならすのに使う。
    Wan は動きを後ろに寄せがちで、最後の 4 コマを捨てると残りの動きが終点への 1 区間に詰まって跳ぶ（会釈で目立った）"""
    g = [cv2.resize(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25).astype(np.float32) for x in frames]
    st = np.array([0.0] + [np.abs(g[i] - g[i - 1]).mean() for i in range(1, len(g))])
    st[1:] += max(1e-3, 0.03 * st[1:].mean())               # 止まったコマも少しは進める
    c = np.cumsum(st)
    return c / c[-1] if c[-1] > 0 else np.linspace(0, 1, len(frames))


def rife(frames, tag, size, mult=None):
    mult = mult or RMULT
    tmp = f"{mv.RTMP}_{tag}"
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp + "/in"); os.makedirs(tmp + "/out")
    for k, f in enumerate(frames): shutil.copyfile(f, f"{tmp}/in/{k:05d}.png")
    subprocess.run([mv.RIFE, "-i", mv.winpath(tmp + "/in"), "-o", mv.winpath(tmp + "/out"), "-m", "rife-v4.6", "-n", str(len(frames) * mult)],
                   cwd=os.path.dirname(mv.RIFE), capture_output=True, text=True, errors="replace")
    outs = sorted(glob.glob(tmp + "/out/*.png"))[:(len(frames) - 1) * mult + 1]
    res = [cv2.resize(cv2.imread(p), size, interpolation=cv2.INTER_LANCZOS4) for p in outs]
    shutil.rmtree(tmp, ignore_errors=True)
    return res


def plan(seq, pose_ok, idur, dur):
    """切り替えの表 [(始まり, 長さ, 前, 次, Wan の名前)]。姿勢の絵の無い姿勢（nod）は前後をまとめて 1 本にする"""
    dflt = float(idur.get("dur", 0.7)); durs = idur.get("durs", {})
    sw = []
    for i in range(1, len(seq)):
        a, b, t = seq[i - 1][0], seq[i][0], seq[i][1]
        if a == b: continue
        d = float(durs.get(f"{a}>{b}", durs.get(f"{b}>{a}", dflt)))
        nxt = seq[i + 1][1] if i + 1 < len(seq) else dur
        sw.append([t, min(max(0.2, min(d, nxt - t - 0.05)), max(0.05, nxt - t)), a, b, f"{a}__{b}"])   # 次の切り替えに重ねない（重なると、前が終わった瞬間に次の途中へ飛んだ）
    out = []; i = 0
    while i < len(sw):
        s = sw[i]
        if not pose_ok(s[3]) and i + 1 < len(sw) and sw[i + 1][2] == s[3]:
            n = sw[i + 1]; out.append([s[0], n[0] + n[1] - s[0], s[2], n[3], f"{s[2]}__{s[3]}__{n[3]}"]); i += 2
        else:
            out.append(s); i += 1
    return out


def main():
    outp = sys.argv[1]
    W = os.path.expanduser(opt("--work", mv.MA)); prefix = opt("--wan", "Afull")
    C = json.load(open(f"{W}/config.json"))
    EV = json.load(open(opt("--events", f"{W}/config.json")))
    F = FRAMES[opt("--frame", "full")]
    bx0, by0, bx1, by1 = F["box"]; OW, OH = F["out"]; SC = OH / (by1 - by0)
    FW, FH = round(SRC_W * SC), round(SRC_H * SC)                  # 立ち姿の絵全体を SC 倍した大きさ（ここで組んでから構図を切る）
    cx0, cy0 = round(bx0 * SC), round(by0 * SC)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", mv.VOICE], capture_output=True, text=True).stdout)
    t0, t1 = opt("--from", 0.0, float), min(opt("--to", dur, float), dur)
    seq = [("home", 0.0)] if "--lip" in sys.argv else [("home", 0.0)] + [(e["pose"], float(e["at"])) for e in EV["events"] if float(e["at"]) < t1]
    pose_ok = lambda p: os.path.exists(f"{W}/poses/pose_{p}.png")
    # 姿勢の絵の無い身振り（例: B のうなずき）は飛ばす。Wan に頭の動きを任せると首をかしげる動きになり、解説として不自然だった
    #（2026-10-31 のユーザーの判定）。飛ばした結果、同じ姿勢が続く所は 1 つにまとめる
    if "--wan-nod" not in sys.argv:
        dropped = sorted({p for p, _ in seq if not pose_ok(p)})
        if dropped: print("姿勢の絵が無いので飛ばす:", dropped, flush=True)
        s2 = []
        for p, t in seq:
            if pose_ok(p) and (not s2 or s2[-1][0] != p): s2.append((p, t))
        seq = s2
    sw = plan(seq, pose_ok, EV.get("interp", {}), dur)

    if "--emit-spec" in sys.argv:                                  # 足りない Wan の切り替えを設定に書く
        clips, seen = [], set()
        for s in sw:
            key = s[4]
            if key in seen or len(glob.glob(f"{WAN}/{prefix}_{key}_[0-9][0-9][0-9][0-9][0-9]_.png")) >= 13: continue
            seen.add(key); parts_ = key.split("__"); a, b = parts_[0], parts_[-1]
            for p in (a, b):
                dst = f"{CIN}/{prefix}_{p}.png"
                if not os.path.exists(dst): cv2.imwrite(dst, cv2.resize(cv2.imread(f"{W}/poses/pose_{p}.png"), (704, 1248), interpolation=cv2.INTER_AREA))
            keep = (" Her head stays still and level, her eyes stay open and look straight at the viewer, calm faint smile, mouth closed, same face, "
                    "same hairstyle, smooth natural motion, stable fixed camera, full body visible, her feet and legs do not move.")
            if "nod" in parts_ and pose_ok("nod"):                     # 会釈の絵がある: 絵どおりに腰から軽く倒す／起こす
                motion = ("She gives a light polite bow: her upper body leans slightly forward from the hips and her head lowers a little, keeping her hands clasped in front of her waist."
                          if b == "nod" else "She straightens up from a light polite bow back to standing upright, keeping her hands clasped in front of her waist.")
                keep = (" Her head does not tilt sideways, her eyes stay open, calm faint smile, mouth closed, same face, same hairstyle, "
                        "smooth natural motion, stable fixed camera, full body visible, her feet and legs do not move.")
                length = 13
            elif "nod" in parts_:
                motion = "She gives a small polite nod, tilting her head slightly forward and back up, keeping her hands clasped in front of her waist."
                keep = " Her eyes stay open, calm faint smile, mouth closed, same face, same hairstyle, smooth natural motion, stable fixed camera, full body visible, her feet and legs do not move."
                length = 25
            else:
                motion = "She smoothly moves her arms and hands into the next pose: " + C["poses"].get(b, {}).get("desc", EV["poses"].get(b, {}).get("desc", b)) + "."
                length = 13
            clips.append({"id": key, "seed": 500 + len(clips), "start": f"{prefix}_{a}.png", "end": f"{prefix}_{b}.png", "length": length, "motion": motion, "keep": keep})
        spec = {"base": f"{prefix}_home.png", "prefix": f"mascot_tr/{prefix}", "width": 704, "height": 1248, "style": opt("--style", ""), "clips": clips}
        json.dump(spec, open(opt("--emit-spec"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"足りない切り替え {len(clips)} 本 → {opt('--emit-spec')}", flush=True)
        return
    print(f"切り替え {len(sw)} か所", flush=True)

    canon = cv2.resize(cv2.imread(f"{W}/poses/pose_home.png"), (FW, FH), interpolation=cv2.INTER_AREA)
    legs = lambda img: lock_legs(img, canon)[0]
    hold, parts, face_t = {}, {}, {}
    er = C.get("face", {}).get("eye_roi", [340, 475, 620, 560])
    fx0, fy0, fx1, fy1 = [round(v * SC) for v in (er[0] - 10, er[1] - 35, er[2] + 10, er[3] - 2)]   # 目と眉（口は入れない）
    for p in sorted({p for p, _ in seq if pose_ok(p)}):
        img = cv2.resize(cv2.imread(f"{W}/poses/pose_{p}.png"), (FW, FH), interpolation=cv2.INTER_AREA if SC < 1 else cv2.INTER_LANCZOS4)
        hold[p] = img if p == "home" else legs(img)
        parts[p] = Parts(f"{W}/parts_{p}/", SC)       # 部品の無い姿勢（顔が横を向く首振り・会釈など）は口を貼らない
        face_t[p] = cv2.cvtColor(hold[p][fy0:fy1, fx0:fx1], cv2.COLOR_BGR2GRAY)
    n_all = int(math.ceil(dur * mv.FPS))
    mouth = mv.mouth_track(n_all); eyes = mv.blink_track(n_all)
    # 視線（目だけ動かす）: events.json の "gaze": [{"at": 秒, "until": 秒, "look": "l"|"r"|"u"}]。
    # 止めて話す所で、その姿勢に g_<look> の部品があれば目に貼る（瞬きが優先）
    gaze = [None] * n_all
    for g in EV.get("gaze", []):
        for f_ in range(int(g["at"] * mv.FPS), min(n_all, int(g["until"] * mv.FPS))): gaze[f_] = "g_" + g["look"]
    cache = OrderedDict()

    def match(fr, ref):
        x = fr.astype(np.float32); r = ref.astype(np.float32)
        mf, sf = x.reshape(-1, 3).mean(0), x.reshape(-1, 3).std(0) + 1e-3
        mr, sr = r.reshape(-1, 3).mean(0), r.reshape(-1, 3).std(0)
        return np.clip((x - mf) / sf * sr + mr, 0, 255).astype(np.uint8)

    DIRECT = ("nod",)    # 頭が少し動くだけの姿勢: Wan を通さず、描いた 2 枚の間を RIFE で直に補間する（Wan だと動きが後ろに詰まってかくついた）

    def eye_patches(p, size):
        """姿勢 p の目のあたり（開いた目・閉じた目）の灰色の絵。閉じた目は parts_<p>/e2.png を姿勢の絵に重ねて作る。無ければ None"""
        pj = f"{W}/parts_{p}/parts.json"
        if not pose_ok(p) or not os.path.exists(pj): return None
        pos = json.load(open(pj))
        if "e2" not in pos: return None
        base = cv2.imread(f"{W}/poses/pose_{p}.png"); closed = base.copy()
        e2 = cv2.imread(f"{W}/parts_{p}/e2.png", cv2.IMREAD_UNCHANGED); x, y = pos["e2"]; h, w = e2.shape[:2]
        al = e2[:, :, 3:] / 255.0; closed[y:y + h, x:x + w] = (e2[:, :, :3] * al + closed[y:y + h, x:x + w] * (1 - al)).astype(np.uint8)
        fc = C["poses"].get(p, {}).get("face"); er = (fc if isinstance(fc, dict) else C.get("face", {})).get("eye_roi")
        if not er: return None
        k = size[0] / base.shape[1]; X0, Y0, X1, Y1 = [round(v * k) for v in er]
        g = lambda im: cv2.cvtColor(cv2.resize(im, size, interpolation=cv2.INTER_AREA)[Y0:Y1, X0:X1], cv2.COLOR_BGR2GRAY)
        return g(base), g(closed), (Y0, Y1)

    def blink_frames(paths, ends, thr=0.05):
        """Wan のコマのうち、目を閉じているコマの番号（1 コマ目は始点の絵なので除く）。
        目のあたりが、前後の姿勢の閉じた目の絵に、開いた目の絵より thr 以上よく合うコマ"""
        if len(paths) < 3: return set()
        im0 = cv2.imread(paths[0]); size = (im0.shape[1], im0.shape[0])
        pats = [x for x in (eye_patches(p, size) for p in ends) if x]
        if not pats: return set()
        y0 = max(0, min(p[2][0] for p in pats) - 80); y1 = min(size[1], max(p[2][1] for p in pats) + 80)
        out = set()
        for i, pth in enumerate(paths[1:], 1):
            g = cv2.cvtColor(cv2.imread(pth), cv2.COLOR_BGR2GRAY)[y0:y1]
            so = max(cv2.minMaxLoc(cv2.matchTemplate(g, o, cv2.TM_CCOEFF_NORMED))[1] for o, _, _ in pats)
            sc_ = max(cv2.minMaxLoc(cv2.matchTemplate(g, c, cv2.TM_CCOEFF_NORMED))[1] for _, c, _ in pats)
            if sc_ - so > thr: out.add(i)
        return out

    def dense(a, b, key):
        if key not in cache and any(p in DIRECT for p in (a, b)) and pose_ok(a) and pose_ok(b):
            ends = []                                   # 止まった絵そのもの（出力と同じ大きさ）を補間する。縮めた絵だと入った瞬間に柔らかくなって跳ねた
            for p in (a, b):
                dst = f"{mv.RTMP}_ends_{prefix}_{p}.png"; cv2.imwrite(dst, hold[p]); ends.append(dst)
            frs = rife(ends, f"{prefix}_{key}_direct", (FW, FH), mult=64)
            cache[key] = (frs, motion_curve(frs))
            if len(cache) > 3: cache.popitem(last=False)
        if key not in cache:
            fs = sorted(glob.glob(f"{WAN}/{prefix}_{key}_[0-9][0-9][0-9][0-9][0-9]_.png"))
            if len(fs) < 5: raise SystemExit(f"Wan の切り替えが無い: {prefix}_{key}（{len(fs)} コマ）")
            # Wan の FLF は最後の 4 コマ（VAE の最後のまとまり）で明るさが崩れる（28 本中 27 本）。背景の明るさが
            # 1 コマ目から 5 以上ずれたコマから後ろを捨て、Codex の終点の絵を置いて、その間は RIFE でつなぐ
            def bglv(p):
                im = cv2.imread(p).astype(np.float32); s_ = 24
                return np.mean([im[:s_, :s_].mean(), im[:s_, -s_:].mean(), im[-s_:, :s_].mean(), im[-s_:, -s_:].mean()])
            lv = [bglv(p) for p in fs]
            cut = next((i for i in range(1, len(fs)) if abs(lv[i] - lv[0]) > 5), len(fs))
            end_img = f"{CIN}/{prefix}_{b}.png"
            blinks = blink_frames(fs[:cut], [a, b])                          # Wan が勝手に入れる瞬き（首振りで振るたびに目を閉じた）は捨てる
            if blinks: print(f"  {key}: 瞬きのコマを捨てる {[i + 1 for i in blinks]}", flush=True)
            seq_f = [f for i, f in enumerate(fs[:cut]) if i not in blinks] + ([end_img] if os.path.exists(end_img) else [])
            raw = rife(seq_f, f"{prefix}_{key}", (FW, FH)); n = len(raw)
            frs = [legs(match(x, cv2.addWeighted(hold[a], 1 - i / (n - 1), hold[b], i / (n - 1), 0))) for i, x in enumerate(raw)]
            cache[key] = (frs, motion_curve(frs))
            if len(cache) > 3: cache.popitem(last=False)
        return cache[key]

    f0, f1 = int(round(t0 * mv.FPS)), int(math.ceil(t1 * mv.FPS))
    ALPHA = outp.endswith(".webm")
    CW = OW if (ALPHA or not F["pad_w"]) else F["pad_w"]
    if ALPHA:
        enc = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "24", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4", "-auto-alt-ref", "0", "-c:a", "libopus", "-b:a", "128k"]
        canvas = np.zeros((OH, CW, 4), np.uint8); pf = "bgra"
    else:
        enc = ["-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        canvas = np.full((OH, CW, 3), 255, np.uint8); pf = "bgr24"
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", pf, "-s", f"{CW}x{OH}", "-r", str(mv.FPS), "-i", "-",
                           "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", mv.VOICE, "-map", "0:v", "-map", "1:a"] + enc + ["-shortest", outp], stdin=subprocess.PIPE)
    PX = (CW - OW) // 2
    st = {"hold_mouth": 0, "tr_mouth": 0, "tr_skip": 0, "lip_found": 0}
    LIP_R = round(45 * SC)                                          # 唇を探す半径（出力の画素）

    def lip_pixels(bgr):
        b_, g_, r_ = [bgr[:, :, i].astype(np.int16) for i in range(3)]
        return (r_ - g_ > 48) & (r_ > 110) & (r_ < 252) & (r_ - b_ > 35)   # 周りの肌より赤い所（唇。頬の赤みは拾わない程度に）

    lip_cache = {}

    def lip_ref(p):
        """姿勢 p の閉じた口の部品（m1）の唇の中心（出力の座標、ずらす前）。部品が無ければ None"""
        if p in lip_cache: return lip_cache[p]
        r = None
        if p in parts and "m1" in parts[p].p:
            x, y, rgb, al, _ = parts[p].p["m1"]
            m = lip_pixels(np.clip(rgb, 0, 255).astype(np.uint8)) & (al[:, :, 0] > 0.5)
            if m.sum() >= 4:
                ys, xs = np.nonzero(m); r = (x + xs.mean(), y + ys.mean())
        lip_cache[p] = r; return r

    def lip_in_frame(fr, cx, cy, rad):
        """(cx, cy) の周り rad の中で、Wan のコマの唇の塊。期待の位置に一番近い塊の (中心, (x0, y0, その塊の 0/1 の絵))。無ければ None"""
        x0, y0 = max(0, int(cx - rad)), max(0, int(cy - rad)); x1, y1 = min(fr.shape[1], int(cx + rad)), min(fr.shape[0], int(cy + rad))
        if x1 <= x0 or y1 <= y0: return None
        m = lip_pixels(fr[y0:y1, x0:x1]).astype(np.uint8)
        n, lab, sts, cen = cv2.connectedComponentsWithStats(m)
        best, bd = None, None
        win = fr[y0:y1, x0:x1].astype(np.int16)
        skin = (win.min(2) > 150) & (win[:, :, 2] >= win[:, :, 1]) & (win[:, :, 2] - win[:, :, 0] < 70)   # 明るい肌
        kr = max(3, round(5 * SC)) | 1
        for i in range(1, n):
            if sts[i, cv2.CC_STAT_AREA] < max(4, round(6 * SC * SC)): continue
            l_, t_, w_, h_, ar_ = sts[i]
            if l_ == 0 or t_ == 0 or l_ + w_ >= m.shape[1] or t_ + h_ >= m.shape[0]: continue   # 探す枠の端に触れる塊（頬の赤み・顔の輪郭が切れた物）は唇でない
            if ar_ > 0.12 * m.size or w_ > 0.8 * m.shape[1] or h_ > 0.5 * m.shape[0]: continue   # 大きすぎる塊も
            comp = (lab == i).astype(np.uint8)
            ring = (cv2.dilate(comp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kr, kr))) > 0) & (comp == 0)
            if ring.sum() == 0 or skin[ring].mean() < 0.7: continue      # 周りが肌に囲まれていない塊（顔の輪郭・髪の境）は唇でない
            gx, gy = cen[i][0] + x0, cen[i][1] + y0; dd = (gx - cx) ** 2 + (gy - cy) ** 2
            if bd is None or dd < bd: best, bd = ((gx, gy), (x0, y0, comp)), dd
        return best

    def erase_lips(fr, blob):
        """Wan のコマの唇の塊を少し広げて、周りの肌で埋める（部品の唇より広い唇の端が残って口が二重に見えないように）"""
        x0, y0, m = blob
        k = max(3, round(5 * SC)) | 1
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        roi = np.ascontiguousarray(fr[y0:y0 + m.shape[0], x0:x0 + m.shape[1]])
        fr[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] = cv2.inpaint(roi, m * 255, 3, cv2.INPAINT_TELEA)
    SEARCH = round(40 * SC)
    # ---------- 頭の向きの列（events.json の "head"、opt-in）----------
    # 描いた角度の絵（右から左へ並べた head_chain）を RIFE で 1 本の列につなぎ、頭の動きはその列の上を行き来させる。
    # Wan を使わない（勝手な瞬きが無い）。口・目は隣り合う角度の部品を、その間の位置に置く（唇を探さない）
    HEAD = EV.get("head") or []
    chain_frames, chain_idx = None, {}
    if HEAD:
        chain = EV.get("head_chain", ["shake_r", "look_r", "home", "look_l", "shake_l"])
        for p in chain:
            if p not in hold:
                img = cv2.resize(cv2.imread(f"{W}/poses/pose_{p}.png"), (FW, FH), interpolation=cv2.INTER_AREA if SC < 1 else cv2.INTER_LANCZOS4)
                hold[p] = img if p == "home" else legs(img); parts[p] = Parts(f"{W}/parts_{p}/", SC)
        chain_frames = [hold[chain[0]]]; chain_idx[chain[0]] = 0
        for p0, p1 in zip(chain, chain[1:]):
            ends = []
            for p in (p0, p1):
                dst = f"{mv.RTMP}_head_{prefix}_{p}.png"; cv2.imwrite(dst, hold[p]); ends.append(dst)
            seg = rife(ends, f"{prefix}_head_{p0}__{p1}", (FW, FH), mult=int(EV.get("head_mult", 32)))
            chain_frames += seg[1:-1] + [hold[p1]]; chain_idx[p1] = len(chain_frames) - 1
        print(f"頭の向きの列: {chain} → {len(chain_frames)} 枚", flush=True)
        HEAD = sorted((float(t_), p_) for t_, p_ in HEAD)

    def head_at(t):
        """t が頭の動きの中なら (列の位置)。外なら None"""
        if not HEAD or t < HEAD[0][0] or t >= HEAD[-1][0]: return None
        for (t0_, p0_), (t1_, p1_) in zip(HEAD, HEAD[1:]):
            if t0_ <= t < t1_:
                u_ = (t - t0_) / (t1_ - t0_); uu_ = u_ * u_ * (3 - 2 * u_)
                return chain_idx[p0_] + (chain_idx[p1_] - chain_idx[p0_]) * uu_
        return None

    def head_frame(pos, f):
        i0 = min(len(chain_frames) - 2, int(pos)); w_ = pos - i0
        fr = cv2.addWeighted(chain_frames[i0], 1 - w_, chain_frames[i0 + 1], w_, 0)
        drawn = sorted(chain_idx.items(), key=lambda kv: kv[1])          # 隣り合う角度の絵
        for (pa_, ia_), (pb_, ib_) in zip(drawn, drawn[1:]):
            if ia_ <= pos <= ib_: break
        k_ = (pos - ia_) / max(1e-6, ib_ - ia_); src = pa_ if k_ < 0.5 else pb_
        FB = {"m7": "m1", "m3": "m2", "m6": "m1"}                       # 無い形は近い形で（vm render と同じ）
        for key in [x for x in (mouth[f], eyes[f]) if x]:
            while key and not all(key in parts[q].p for q in (src, pa_, pb_)): key = FB.get(key)
            if not key: continue
            xa, ya = parts[pa_].p[key][:2]; xb, yb = parts[pb_].p[key][:2]; xs, ys = parts[src].p[key][:2]
            tx, ty = xa + (xb - xa) * k_, ya + (yb - ya) * k_                 # 部品の置き場所を角度の間で取る
            parts[src].paste(fr, key, round(tx - xs), round(ty - ys))
        return fr

    for f in range(f0, f1):
        t = f / mv.FPS
        hp = head_at(t)
        cur = None if hp is not None else next((s for s in sw if s[0] <= t < s[0] + s[1]), None)
        if hp is not None:
            fr = head_frame(hp, f); st["hold_mouth"] += bool(mouth[f])
        elif cur is None:
            p = max((x for x in seq if x[1] <= t + 1e-9 and pose_ok(x[0])), key=lambda x: x[1])[0]
            fr = hold[p].copy()
            if mouth[f] and parts[p].paste(fr, mouth[f]): st["hold_mouth"] += 1
            if eyes[f]: parts[p].paste(fr, eyes[f])
            elif gaze[f]: parts[p].paste(fr, gaze[f])
        else:
            s0, d, a, b, key = cur; u = (t - s0) / d
            dd, cm = dense(a, b, key)
            uu = u * u * (3 - 2 * u)                                       # 始まりと終わりを緩やかに
            pos = float(np.interp(uu, cm, np.arange(len(dd))))            # 時間の割合＝動きの割合になる位置
            i0 = min(len(dd) - 2, int(pos)); fr_ = pos - i0                # 前後の 2 枚を重ねる（1 枚を選ぶと止まっては跳ぶ）
            fr = cv2.addWeighted(dd[i0], 1 - fr_, dd[i0 + 1], fr_, 0) if len(dd) > 1 else dd[0].copy()
            if u > 0.85:                                                   # 終わりの 15% で行き先の止まった絵へ重ねて渡す
                k = (u - 0.85) / 0.15; k = k * k * (3 - 2 * k)
                fr = cv2.addWeighted(fr, 1 - k, hold[b], k, 0)
            elif u < 0.15:                                                 # 始まりの 15% は前の止まった絵から重ねて入る
                k = (0.15 - u) / 0.15; k = k * k * (3 - 2 * k)
                fr = cv2.addWeighted(fr, 1 - k, hold[a], k, 0)
            if mouth[f]:
                p = b if u >= 0.5 else a
                if not parts[p].p: p = a if p == b else b
                la, lb, lp = lip_ref(a), lip_ref(b), lip_ref(p)
                if lp is not None:
                    # 口は唇に合わせる: 前後の姿勢の唇の位置を動きの進み具合で間に取り、その周りで Wan のコマの唇を探す
                    #（目と眉の型で顔を追うと、首が回る途中で目の見え方が変わって口がずれた）
                    ex, ey = lp
                    if la is not None and lb is not None: ex, ey = la[0] + (lb[0] - la[0]) * uu, la[1] + (lb[1] - la[1]) * uu
                    found = lip_in_frame(fr, ex, ey, LIP_R)
                    if found is not None and not os.environ.get("NOERASE"): erase_lips(fr, found[1])
                    if found is not None: found = found[0]
                    if os.environ.get("NOPASTE"): continue_paste = False
                    else: continue_paste = True
                    tx, ty = found if found is not None else (ex, ey)
                    if continue_paste and parts[p].paste(fr, mouth[f], round(tx - lp[0]), round(ty - lp[1]), ref=hold[p], tight=True): st["tr_mouth"] += 1; st["lip_found"] += found is not None
                    else: st["tr_skip"] += 1
                else:
                    sx0, sy0 = max(0, fx0 - SEARCH), max(0, fy0 - SEARCH)
                    win = cv2.cvtColor(fr[sy0:fy1 + SEARCH, sx0:fx1 + SEARCH], cv2.COLOR_BGR2GRAY)
                    res = cv2.matchTemplate(win, face_t[p], cv2.TM_CCOEFF_NORMED); _, sc_, _, loc = cv2.minMaxLoc(res)
                    if sc_ >= 0.6 and parts[p].paste(fr, mouth[f], loc[0] + sx0 - fx0, loc[1] + sy0 - fy0, ref=hold[p]): st["tr_mouth"] += 1
                    else: st["tr_skip"] += 1
        fr = fr[cy0:cy0 + OH, cx0:cx0 + OW]
        if ALPHA:
            canvas[:, PX:PX + OW, :3] = fr; canvas[:, PX:PX + OW, 3] = matte(fr)
        else:
            frf = fr.astype(np.float32); w = np.clip((frf.min(2, keepdims=True) - 236) / 12, 0, 1)
            canvas[:, PX:PX + OW] = (frf + (255 - frf) * w).astype(np.uint8)
        ff.stdin.write(canvas.tobytes())
    ff.stdin.close(); ff.wait()
    print("口:", st, "→", outp, flush=True)


if __name__ == "__main__":
    main()
