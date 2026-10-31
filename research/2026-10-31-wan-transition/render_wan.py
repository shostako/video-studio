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

    def paste(self, fr, key, dx=0, dy=0, ref=None):
        if key not in self.p: return False
        x, y, rgb, a, ring = self.p[key]; x += dx; y += dy; h, w = rgb.shape[:2]
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
        sw.append([t, max(0.2, min(d, nxt - t - 0.05)), a, b, f"{a}__{b}"])
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
            seq_f = fs[:cut] + ([end_img] if os.path.exists(end_img) else [])
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
    st = {"hold_mouth": 0, "tr_mouth": 0, "tr_skip": 0}
    SEARCH = round(40 * SC)
    for f in range(f0, f1):
        t = f / mv.FPS
        cur = next((s for s in sw if s[0] <= t < s[0] + s[1]), None)
        if cur is None:
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
