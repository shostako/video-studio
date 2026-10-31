"""姿勢の切り替えを Wan2.2 I2V の First-Last-Frame で動かす（config.interp.engine: "wan"、opt-in）。vm render が使う。単独では動かさない。
  1. 組 a→b ごとに、始点＝姿勢 a の絵、終点＝姿勢 b の絵で Wan のコマを作る（新PC の ComfyUI。wanflf_comfy.py を ComfyUI の Python で回す）
     ためる所: <作業フォルダ>/ib_wan/<a>__<b>/raw/w<NN>.png（元の絵か interp.wan の生成に効く値が変わったら作り直す。stamp.json）
  2. Wan の FLF は最後のまとまり（4 コマ）で明るさが崩れる。背景の明るさが 1 コマ目から cut_tol を超えてずれたコマから後ろを捨て、
     姿勢 b の絵を置いて、その間を RIFE で rife_mult 倍に細かくする
  3. 各コマの明るさと色味を、姿勢 a と b の絵の間（位置に応じて重ねた絵）に合わせる
  4. 動きの量で割り付けて n 枚にする（Wan は動きを後ろに寄せがちなので、時刻の割合で選ぶと止まっては跳ぶ）。位置の前後 2 枚を重ねる
  5. 始まりと終わりの edge の幅は、姿勢 a・b の絵と重ねる
  できた列（<...>/n<n>/f<j>.png、j=1..n）を、RIFE の中割りと同じ形で render に返す（口と目の重ね・足元・下半身は render の側）。"""
import glob, json, os, shutil, subprocess

import cv2
import numpy as np

from lib import die, edge_weight, motion_positions, wan_cut

_GEN_KEYS = ("width", "height", "length", "seed", "style", "head_poses", "unet_high", "unet_low", "lora_high", "lora_low", "clip", "vae", "clip_vision")
_POST_KEYS = ("rife_mult", "cut_tol", "edge")


def _winpath(p):
    r = subprocess.run(["wslpath", "-w", p], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else p


def _file_stamp(paths):
    return [[os.path.basename(p), os.path.getmtime(p), os.path.getsize(p)] for p in paths]


def _read_stamp(path):
    try: return json.load(open(path))
    except (OSError, ValueError): return None


def bg_level(img):
    """四隅（背景）の明るさの平均。"""
    s = max(4, min(img.shape[:2]) // 30)
    return float(np.mean([img[:s, :s].mean(), img[:s, -s:].mean(), img[-s:, :s].mean(), img[-s:, -s:].mean()]))


def match_color(img, ref):
    """img の明るさと色味（色ごとの平均とばらつき）を ref に合わせる。"""
    x = img.astype(np.float32); r = ref.astype(np.float32)
    mf, sf = x.reshape(-1, 3).mean(0), x.reshape(-1, 3).std(0) + 1e-3
    mr, sr = r.reshape(-1, 3).mean(0), r.reshape(-1, 3).std(0)
    return np.clip((x - mf) / sf * sr + mr, 0, 255).astype(np.uint8)


def prompt_of(cfg, wan, a, b):
    """Wan に渡す文（キャラの説明＋動き＋保つもの）。"""
    style = wan.get("style") or cfg.get("mascot", {}).get("description") or "a chibi mascot character standing on a plain white background"
    head = a in wan["head_poses"] or b in wan["head_poses"]
    desc = cfg["poses"].get(b, {}).get("desc") or b
    move = f"She smoothly turns only her head into the next pose: {desc}." if head else f"She smoothly moves her arms and hands into the next pose: {desc}."
    keep = (" Her head turns but stays level and does not tilt sideways, her shoulders and hands do not move," if head
            else " Her head stays still and level, her eyes stay open and look straight at the viewer,")
    keep += " calm faint smile, mouth closed, same face, same hairstyle, smooth natural motion, stable fixed camera, full body visible, her feet and legs do not move."
    return f"{style.rstrip('. ')}. {move}{keep}"


def generate(P, a, b, wan, raw_dir, log=None):
    """ComfyUI で a→b の Wan のコマを作り、raw_dir に w01.png… として置く。ComfyUI が起動していないと止まる。"""
    comfy = wan["comfy"]; py = os.path.join(comfy, "python_embeded", "python.exe")
    if not os.path.exists(py): die(f"ComfyUI の Python が無い: {py}（interp.wan.comfy を直す。Wan の切り替えは新PC の ComfyUI で作る）")
    tag = "vm_wan_" + "".join(ch if ch.isalnum() else "_" for ch in os.path.basename(P.root))
    inp = os.path.join(comfy, "ComfyUI", "input")
    names = {}
    for p in (a, b):
        names[p] = f"{tag}_{p}.png"
        im = cv2.resize(P.read_pose(p), (wan["width"], wan["height"]), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(inp, names[p]), im)
    prefix = f"{tag}/{a}__{b}"
    spec = {"url": wan["url"], "start": names[a], "end": names[b], "prefix": prefix, "prompt": prompt_of(P.cfg, wan, a, b),
            **{k: wan[k] for k in ("width", "height", "length", "seed", "unet_high", "unet_low", "lora_high", "lora_low", "clip", "vae", "clip_vision")}}
    tmp = os.path.join(comfy, "ComfyUI", "output", tag); os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, f"{a}__{b}_*.png")): os.remove(f)          # 前の失敗の残りを使わない
    sp = os.path.join(tmp, f"{a}__{b}.spec.json"); json.dump(spec, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wanflf_comfy.py")
    shutil.copyfile(script, os.path.join(tmp, "wanflf_comfy.py"))                  # Windows の Python が読める所に写して走らせる
    if log: log(f"Wan: {a}→{b} を作る（{wan['width']}x{wan['height']}・{wan['length']} コマ）")
    r = subprocess.run([py, _winpath(os.path.join(tmp, "wanflf_comfy.py")), _winpath(sp)], capture_output=True, text=True, errors="replace")
    if r.returncode != 0: die(f"Wan の生成に失敗（{a}→{b}、終了コード {r.returncode}）: {(r.stdout + r.stderr)[-800:]}")
    outs = sorted(glob.glob(os.path.join(tmp, f"{a}__{b}_[0-9][0-9][0-9][0-9][0-9]_.png")))
    if len(outs) < 2: die(f"Wan のコマが出てこない（{a}→{b}、{len(outs)} 枚）")
    shutil.rmtree(raw_dir, ignore_errors=True); os.makedirs(raw_dir)
    for i, f in enumerate(outs, 1): shutil.move(f, os.path.join(raw_dir, f"w{i:02d}.png"))
    if log: log(f"Wan: {a}→{b} {len(outs)} コマ（{r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ''}）")


def rife_frames(frames, mult, icfg, tag):
    """BGR の絵の列を RIFE で mult 倍に細かくした列（(len-1)*mult+1 枚）。"""
    if mult <= 1 or len(frames) < 2: return list(frames)
    if not os.path.exists(icfg["exe"]): die(f"RIFE が無い: {icfg['exe']}（config.interp.exe を直す）")
    tmp = os.path.join(icfg["tmp"], tag)
    shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp + "/in"); os.makedirs(tmp + "/out")
    for i, im in enumerate(frames): cv2.imwrite(f"{tmp}/in/{i:04d}.png", im)
    n_out = (len(frames) - 1) * mult + 1
    r = subprocess.run([icfg["exe"], "-i", _winpath(tmp + "/in"), "-o", _winpath(tmp + "/out"), "-m", icfg["model"], "-n", str(n_out + mult - 1)],
                       cwd=os.path.dirname(icfg["exe"]), capture_output=True, text=True, errors="replace")
    outs = sorted(os.listdir(tmp + "/out"))[:n_out]
    if r.returncode != 0 or len(outs) < n_out: die(f"RIFE が失敗した（{tag}、終了コード {r.returncode}）: {(r.stdout + r.stderr)[-600:]}")
    res = [cv2.imread(os.path.join(tmp, "out", f)) for f in outs]
    shutil.rmtree(tmp, ignore_errors=True)
    return res


def build(frames, img_a, img_b, n, edge):
    """Wan（＋RIFE）の列から、render に渡す n 枚（端を除く）を作る。frames は姿勢の絵と同じ大きさの BGR の列。
    各コマを a と b の間の色に合わせ、動きの量で割り付けて前後 2 枚を重ね、始まりと終わりは a・b の絵と重ねる。"""
    m = len(frames)
    fr = [match_color(x, cv2.addWeighted(img_a, 1 - i / max(1, m - 1), img_b, i / max(1, m - 1), 0)) for i, x in enumerate(frames)]
    g = [cv2.resize(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), None, fx=0.25, fy=0.25).astype(np.float32) for x in fr]
    steps = [float(np.abs(g[i] - g[i - 1]).mean()) for i in range(1, m)]
    pos = motion_positions(steps, n + 2)[1:-1]
    out = []
    for j, p in enumerate(pos, 1):
        i0 = min(m - 2, int(p)) if m > 1 else 0; t = p - i0
        im = cv2.addWeighted(fr[i0], 1 - t, fr[i0 + 1], t, 0) if m > 1 else fr[0].copy()
        wa, wb = edge_weight(j / (n + 1), edge)
        if wa > 0: im = cv2.addWeighted(im, 1 - wa, img_a, wa, 0)
        if wb > 0: im = cv2.addWeighted(im, 1 - wb, img_b, wb, 0)
        out.append(im)
    return out


def dense_paths(P, a, b, n, icfg, log=None, gen=None, rife=None):
    """a→b の切り替えの列のパス（n 枚、端を除く）。無ければ作る。gen・rife は差し替え用（テスト）。"""
    wan = icfg["wan"]; gen = gen or generate; rife = rife or rife_frames
    base = P.p("ib_wan", f"{a}__{b}"); raw = os.path.join(base, "raw")
    src = [P.pose_path(a), P.pose_path(b)]
    st_gen = {"src": _file_stamp(src), "gen": {k: wan[k] for k in _GEN_KEYS}, "desc": P.cfg["poses"].get(b, {}).get("desc")}
    if _read_stamp(os.path.join(base, "raw_stamp.json")) != json.loads(json.dumps(st_gen)) or not glob.glob(os.path.join(raw, "w*.png")):
        gen(P, a, b, wan, raw, log=log)
        os.makedirs(base, exist_ok=True); json.dump(st_gen, open(os.path.join(base, "raw_stamp.json"), "w"))
    out_dir = os.path.join(base, f"n{n}")
    want = [os.path.join(out_dir, f"f{j}.png") for j in range(1, n + 1)]
    rp = sorted(glob.glob(os.path.join(raw, "w*.png")))
    st = {"raw": _file_stamp(rp), "src": _file_stamp(src), "post": {k: wan[k] for k in _POST_KEYS}, "model": icfg["model"]}
    if _read_stamp(os.path.join(out_dir, "stamp.json")) == json.loads(json.dumps(st)) and all(os.path.exists(p) for p in want): return want
    img_a, img_b = P.read_pose(a), P.read_pose(b)
    H, W = img_a.shape[:2]
    if img_b.shape != img_a.shape: img_b = cv2.resize(img_b, (W, H), interpolation=cv2.INTER_AREA)
    ws = [cv2.imread(p) for p in rp]
    keep = wan_cut([bg_level(x) for x in ws], wan["cut_tol"])
    end = cv2.resize(img_b, (ws[0].shape[1], ws[0].shape[0]), interpolation=cv2.INTER_AREA)
    seq = rife(ws[:keep] + [end], wan["rife_mult"], icfg, f"wan_{os.path.basename(P.root)}_{a}__{b}")
    seq = [cv2.resize(x, (W, H), interpolation=cv2.INTER_LANCZOS4) if x.shape[:2] != (H, W) else x for x in seq]
    frames = build(seq, img_a, img_b, n, wan["edge"])
    shutil.rmtree(out_dir, ignore_errors=True); os.makedirs(out_dir)
    for p, im in zip(want, frames): cv2.imwrite(p, im)
    json.dump(st, open(os.path.join(out_dir, "stamp.json"), "w"))
    if log: log(f"Wan の切り替え: {a}→{b}（Wan {len(ws)} コマのうち {keep} コマ＋終点の絵、RIFE {wan['rife_mult']} 倍 → {n} 枚）")
    return want
