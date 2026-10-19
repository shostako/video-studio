"""qwenimg — 手元の ComfyUI（新PC の GPU）の Qwen-Image-Edit-2511 で、参照画像を描き変えて1枚作る。/img（img.sh）と同じ引数・終了コード。
Codex の枠を使わない。細かい所（手のアップの指の本数など）を描き直すのに向く。全身の姿勢や中割りのように、キャラを保ったまま大きく動かす絵は /img の方が良い。
  qwenimg.sh -p "指示" -o 出力パス -r 参照画像 [-r 参照画像 ...]
  参照は 1〜3 枚（1枚目を描き変える。2枚目以降は形の手本）。参照なしは使えない（このモデルは描き変え用）。
  環境変数: QWENIMG_SEED（種、既定 0）、QWENIMG_STEPS（既定 4）、QWENIMG_TRIES（左右が反転した絵を外して描き直す回数、既定 3）
終了コード（img.sh と同じ意味）:
  0 成功（標準出力に保存先の絶対パスを1行）
  2 引数の誤り / ComfyUI・モデルが無い（新PC だけで動く。video-scene の setup.sh --h3 と、下の MODELS を入れる）
  5 タイムアウト
  1 その他（描けなかった、左右が反転した絵しか出なかった）
モデル（ComfyUI の models/ の下）: unet/qwen-image-edit-2511-Q4_K_M.gguf（diffusion_models/ でも可。custom_nodes に ComfyUI-GGUF）、
  text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors、vae/qwen_image_vae.safetensors、loras/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors
分かったこと（2026-10-18、8GB の RTX 5070 で1枚 60〜100 秒）:
  - 指の本数は、参照を「グーの手」にして「その本数だけ伸ばす」と書くと合う。1本の手から指を足させると、曲げた指が残る
  - 3本は4本に倒れやすい。1枚目を4本の手、2枚目を正しい3本の手本にして形を写させると合う
  - 種によっては構図が左右反転する。出た絵が参照を反転した方に似ていれば外して、種を変えて描き直す"""
import argparse
import json
import os
import shutil
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "..", "video-scene", "scripts")))

MODELS = {"unet": "qwen-image-edit-2511-Q4_K_M.gguf", "clip": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
          "vae": "qwen_image_vae.safetensors", "lora": "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"}


def graph(prompt, names, steps=4, cfg=1.0, seed=0, prefix="qwen", lora=True):
    """ComfyUI の雛形 Image Edit (Qwen 2511) と同じつなぎ方。names は ComfyUI の input/ からの名前（1〜3枚）。"""
    if not 1 <= len(names) <= 3: raise ValueError("参照は 1〜3 枚")
    g = {"4": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": MODELS["unet"]}},
         "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": MODELS["clip"], "type": "qwen_image", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS["vae"]}}}
    model = ["4", 0]
    if lora:
        g["20"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": MODELS["lora"], "strength_model": 1.0}}; model = ["20", 0]
    g["2"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model, "shift": 3.1}}
    g["7"] = {"class_type": "CFGNorm", "inputs": {"model": ["2", 0], "strength": 1}}
    imgs = {}
    for i, n in enumerate(names):
        g[f"10{i}"] = {"class_type": "LoadImage", "inputs": {"image": n}}; imgs[f"image{i + 1}"] = [f"10{i}", 0]
    g["16"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": imgs["image1"]}}; imgs["image1"] = ["16", 0]
    for k, p in (("13", prompt), ("9", "")):
        g[k] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"clip": ["1", 0], "vae": ["3", 0], "prompt": p, **imgs}}
    g["6"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["13", 0], "reference_latents_method": "index_timestep_zero"}}
    g["5"] = {"class_type": "FluxKontextMultiReferenceLatentMethod", "inputs": {"conditioning": ["9", 0], "reference_latents_method": "index_timestep_zero"}}
    g["14"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["16", 0], "vae": ["3", 0]}}
    g["15"] = {"class_type": "KSampler", "inputs": {"model": ["7", 0], "positive": ["6", 0], "negative": ["5", 0], "latent_image": ["14", 0],
                                                      "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}}
    g["12"] = {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["3", 0]}}
    g["90"] = {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": "vm/" + prefix}}
    return g


def flipped(out, ref, margin=0.05):
    """出た絵が、参照をそのまま写した向きより、左右反転した向きに似ているか。ぼかした濃淡の相関で比べる。"""
    def prep(im):
        g = cv2.cvtColor(cv2.resize(im, (64, 64), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
        g = cv2.GaussianBlur(g, (0, 0), 2); return (g - g.mean()) / (g.std() + 1e-6)
    o, r = prep(out), prep(ref)
    same = float((o * r).mean()); flip = float((o * r[:, ::-1]).mean())
    return flip > same + margin


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("-p", "--prompt"); ap.add_argument("-o", "--out"); ap.add_argument("-r", "--ref", action="append", default=[])
    ap.add_argument("-h", "--help", action="store_true"); ap.add_argument("--force", action="store_true"); ap.add_argument("-n", "--name")
    a = ap.parse_args()
    if a.help: print(__doc__); sys.exit(0)
    if not a.prompt or not a.out or not a.ref: print("ERROR: -p・-o・-r（1〜3枚）が要る", file=sys.stderr); sys.exit(2)
    if len(a.ref) > 3: print("ERROR: 参照は 3 枚まで", file=sys.stderr); sys.exit(2)
    for r in a.ref:
        if not os.path.exists(r): print(f"ERROR: 参照が無い: {r}", file=sys.stderr); sys.exit(2)
    try:
        import h3
    except ImportError as e:
        print(f"ERROR: video-scene の h3.py を読めない: {e}", file=sys.stderr); sys.exit(2)
    if not os.path.isdir(os.path.join(h3.ROOT, "ComfyUI")):
        print(f"ERROR: ComfyUI が無い: {h3.ROOT}（新PC だけで動く）", file=sys.stderr); sys.exit(2)
    for kind, subs in (("unet", ("unet", "diffusion_models")), ("clip", ("text_encoders", "clip")), ("vae", ("vae",)), ("lora", ("loras",))):
        if not any(os.path.exists(os.path.join(h3.ROOT, "ComfyUI", "models", s, MODELS[kind])) for s in subs):
            print(f"ERROR: モデルが無い: models/{subs[0]}/{MODELS[kind]}", file=sys.stderr); sys.exit(2)
    inp = os.path.join(h3.ROOT, "ComfyUI", "input", "vm"); os.makedirs(inp, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"; names = []
    for i, r in enumerate(a.ref):
        n = f"{stamp}_{i}{os.path.splitext(r)[1] or '.png'}"; shutil.copy(r, os.path.join(inp, n)); names.append("vm/" + n)
    seed = int(os.environ.get("QWENIMG_SEED", "0")); steps = int(os.environ.get("QWENIMG_STEPS", "4")); tries = int(os.environ.get("QWENIMG_TRIES", "3"))
    try:
        if h3.client("ensure", h3.winpath(h3.ROOT), *h3.SERVER_ARGS) != 0: print("ERROR: ComfyUI を起こせない", file=sys.stderr); sys.exit(2)
    except SystemExit: raise
    except Exception as e:
        print(f"ERROR: ComfyUI を起こせない: {e}", file=sys.stderr); sys.exit(2)
    ref = cv2.imread(a.ref[0])
    for t in range(tries):
        prefix = f"qwen_{stamp}_{t}"; job = {"graph": graph(a.prompt, names, steps, 1.0, seed + t, prefix), "timeout": 1800}
        jp, rp = os.path.join(h3.VS_DIR, f"{prefix}.json"), os.path.join(h3.VS_DIR, f"{prefix}_res.json")
        json.dump(job, open(jp, "w", encoding="utf-8"))
        h3.client("run", h3.winpath(jp), h3.winpath(rp))
        if not os.path.exists(rp): print("ERROR: ComfyUI から結果が返らない", file=sys.stderr); sys.exit(1)
        res = json.load(open(rp, encoding="utf-8"))
        if res.get("status") == "timeout": print("ERROR: タイムアウト", file=sys.stderr); sys.exit(5)
        imgs = [o for o in res.get("outputs", []) if o["filename"].lower().endswith(".png")]
        if res.get("status") != "success" or not imgs: print(json.dumps(res, ensure_ascii=False)[:2000], file=sys.stderr); sys.exit(1)
        o = imgs[0]; src = os.path.join(h3.ROOT, "ComfyUI", "output", o["subfolder"], o["filename"])
        out = cv2.imread(src)
        if out is not None and ref is not None and flipped(out, ref):
            print(f"種 {seed + t}: 左右が反転した絵が出た。種を変えて描き直す", file=sys.stderr); continue
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True); shutil.copy(src, a.out)
        print(f"{res.get('seconds')}s VRAM {res.get('vram_peak_mib')}MiB 種 {seed + t}", file=sys.stderr); print(os.path.abspath(a.out))
        sys.exit(0)
    print(f"ERROR: {tries} 回とも左右が反転した絵だった", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
