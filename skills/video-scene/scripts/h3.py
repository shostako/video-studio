"""h3.py — MiniMax H3（この PC の ComfyUI、無料）で素材の動画を1本作る。映像と声（日本語可）が同時に出る。

使い方:
  vs h3 --prompt-file prompt.txt --first start.png [--last end.png] [--seconds 8] [--aspect 16:9|9:16|1:1]
        [--mp 0.4] [--quality] [--seed N] [--name 名前 | --out 出力.mp4]
  vs h3 --server status|start|free|stop

  - 画像は縦横比が合わなければ端の色を伸ばして合わせる（veo と同じ。控えの _first.png・_pad.json は指示文のフォルダへ）
  - 既定は 864x480（0.4MP）・8 ステップ（turbo LoRA）。--quality で 20 ステップ（時間は約 2.5 倍）
  - 長さは 4〜15 秒。8GB で実測 5 秒 3 分強、8 秒 6 分半（2026-10-12、RTX 5070 Laptop）
  - ComfyUI が動いていなければ窓なしで起動する（初回のモデル読み込みで 1〜2 分余計にかかる）。
    終わってもサーバーは残す（続けて作るときに速い）。VRAM を空けたいときは --server free、止めるなら --server stop

終了コード: 0 成功（標準出力に保存先） 2 引数・グラフが受け付けられない 3 ComfyUI が無い・起動しない
           5 時間切れ 6 生成に失敗 8 メモリ不足（--seconds か --mp を下げる）
"""
import argparse, json, math, os, subprocess, sys, time, uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import out_path, die, probe
from veo import fit_aspect

ROOT = os.environ.get("VS_COMFY_ROOT", "/mnt/c/ComfyUI/ComfyUI_windows_portable")
WIN_PY = os.path.join(ROOT, "python_embeded", "python.exe")
VS_DIR = os.path.join(os.path.dirname(ROOT), "vs")           # ジョブと係の置き場（Windows 側）
SERVER_ARGS = ["--disable-pinned-memory", "--disable-async-offload", "--reserve-vram", "1"]   # 8GB + Blackwell の VAE decode 落ち対策
MODELS = {
    "unet": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae": "minimax_h3_video_vae_int8_convrot.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "lora": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
}
MODEL_DIRS = {"unet": "diffusion_models", "clip": "text_encoders", "vae": "vae", "audio_vae": "vae", "lora": "loras"}


def winpath(p):
    return subprocess.run(["wslpath", "-w", p], capture_output=True, text=True, check=True).stdout.strip()


def client(*args, check=False):
    """Windows の同梱 Python で h3_client.py を動かす。標準エラーはそのまま流す。"""
    os.makedirs(VS_DIR, exist_ok=True)
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h3_client.py")
    dst = os.path.join(VS_DIR, "h3_client.py")
    if not os.path.exists(dst) or open(src, "rb").read() != open(dst, "rb").read():
        tmp = dst + ".part"; open(tmp, "wb").write(open(src, "rb").read()); os.replace(tmp, dst)
    r = subprocess.run([WIN_PY, "-s", winpath(dst)] + list(args), cwd=VS_DIR)
    if check and r.returncode != 0:
        die(f"h3_client {args[0]} が失敗 (code {r.returncode})", 3)
    return r.returncode


def size_for(aspect, mp):
    """ComfyUI の ResolutionSelector と同じ決め方（1MP=1024x1024、32 の倍数）。0.4MP・16:9 → 864x480。"""
    aw, ah = map(int, aspect.split(":")); px = mp * 1024 * 1024
    w = math.sqrt(px * aw / ah); h = w * ah / aw
    return max(32, round(w / 32) * 32), max(32, round(h / 32) * 32)


def frames_for(seconds):
    """テンプレートの式: 24fps で 17n+5 コマにそろえる。"""
    n = max(5, round(seconds * 24)); return n + (5 - n % 17) % 17


def graph(prompt, first, last, w, h, length, steps, turbo, seed, prefix, audio=None):
    model = ["121", 0] if turbo else ["6", 0]
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": first}},
        "6": {"class_type": "UNETLoader", "inputs": {"unet_name": MODELS["unet"], "weight_dtype": "default"}},
        "13": {"class_type": "CLIPLoader", "inputs": {"clip_name": MODELS["clip"], "type": "minimax", "device": "default"}},
        "11": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS["vae"]}},
        "24": {"class_type": "VAELoader", "inputs": {"vae_name": MODELS["audio_vae"]}},
        "104": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["13", 0], "vae": ["11", 0], "first_frame": ["1", 0],
                "prompt": prompt, "width": w, "height": h, "length": length}},
        "15": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "17": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "16": {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": ["104", 0]}},
        "14": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["15", 0], "guider": ["16", 0], "sampler": ["17", 0],
               "sigmas": ["9", 0], "latent_image": ["104", 1]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["14", 0], "vae": ["11", 0]}},
        "23": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["14", 0], "vae": ["24", 0]}},
        "91": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "audio": ["23", 0], "fps": 24}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["91", 0], "filename_prefix": "vs/" + prefix, "format": "auto", "codec": "auto"}},
    }
    if turbo:
        g["121"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["6", 0], "lora_name": MODELS["lora"], "strength_model": 1.0}}
    if last:
        g["2"] = {"class_type": "LoadImage", "inputs": {"image": last}}
        g["104"]["inputs"]["last_frame"] = ["2", 0]
    if audio:   # 声を固定して、絵だけを声に合わせて作る（音声を 0 コマ目から全長に当てる）
        g["30"] = {"class_type": "LoadAudio", "inputs": {"audio": audio}}
        g["31"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": ["104", 0], "latent": ["104", 1], "audio_vae": ["24", 0],
                   "audio": ["30", 0], "frame_idx": 0}}
        g["16"]["inputs"]["conditioning"] = ["31", 0]
    return g


def check_install(models=True):
    """ComfyUI があるか。models=True なら H3 の重みもそろっているか（生成とサーバーの起動に要る）。"""
    if not os.path.exists(WIN_PY):
        die(f"ComfyUI portable が無い: {ROOT}（references/h3.md の「入れ方」）", 3)
    if not models: return
    missing = [f for k, f in MODELS.items() if not os.path.exists(os.path.join(ROOT, "ComfyUI", "models", MODEL_DIRS[k], f))]
    if missing:
        die("H3 の重みが足りない: " + ", ".join(missing) + "（references/h3.md の「入れ方」）", 3)


def main():
    ap = argparse.ArgumentParser(description="MiniMax H3（ローカル）で素材の動画を作る")
    ap.add_argument("--server", choices=["status", "start", "free", "stop"])
    ap.add_argument("--prompt-file"); ap.add_argument("--first"); ap.add_argument("--last")
    ap.add_argument("--seconds", type=float, default=8); ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--mp", type=float, default=0.4, help="画素数（メガピクセル）。0.4=864x480。0.6 以上は 8GB で遅い・落ちる恐れ")
    ap.add_argument("--quality", action="store_true", help="20 ステップ（turbo なし）。細部は良くなるが約 2.5 倍かかる")
    ap.add_argument("--steps", type=int, help="ステップ数を直接指定（turbo は --quality が無いとき 8 が目安）")
    ap.add_argument("--seed", type=int, default=1); ap.add_argument("--name", default="h3"); ap.add_argument("--out")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--audio", help="声の音声ファイル。渡すと H3 は声を作らず、この声に合わせて口と体を動かす。動画の長さに満たない分は無音で埋める")
    ap.add_argument("--side-dir", help="控え（_first.png・_pad.json）の置き場。既定は指示文のフォルダ＝作業フォルダ")
    a = ap.parse_args()

    check_install(models=a.server in (None, "start"))   # status / free / stop は重みが欠けていても動かせる
    if a.server:
        if a.server == "status":
            r = client("status"); print("running" if r == 0 else "stopped"); sys.exit(0)
        if a.server == "start": sys.exit(client("ensure", winpath(ROOT), *SERVER_ARGS))
        sys.exit(client(a.server) if a.server == "free" else client("stop", winpath(ROOT)))

    if not a.prompt_file or not a.first:
        die("--prompt-file と --first が要る", 2)
    if not 4 <= a.seconds <= 15:
        die("--seconds は 4〜15", 2)
    turbo = not a.quality
    steps = a.steps or (8 if turbo else 20)
    w, h = size_for(a.aspect, a.mp); length = frames_for(a.seconds)
    prompt = open(a.prompt_file, encoding="utf-8").read().strip()

    out = out_path(f"{a.name}_h3_{a.seconds:g}s", out=a.out)
    side_dir = a.side_dir or os.path.dirname(os.path.abspath(a.prompt_file)); os.makedirs(side_dir, exist_ok=True)
    side = os.path.join(side_dir, os.path.splitext(os.path.basename(out))[0])
    job_id = uuid.uuid4().hex[:12]
    inp = os.path.join(ROOT, "ComfyUI", "input", "vs"); os.makedirs(inp, exist_ok=True)
    pad = {"first": fit_aspect(a.first, f"{w}:{h}", side + "_first.png")}
    first_in = f"{job_id}_first.png"; open(os.path.join(inp, first_in), "wb").write(open(side + "_first.png", "rb").read())
    last_in = None
    if a.last:
        pad["last"] = fit_aspect(a.last, f"{w}:{h}", side + "_last.png")
        last_in = f"{job_id}_last.png"; open(os.path.join(inp, last_in), "wb").write(open(side + "_last.png", "rb").read())
    json.dump(pad, open(side + "_pad.json", "w"), indent=1)
    audio_in = None
    if a.audio:   # LoadAudio は input の直下しか見ないので、直下に置く。長さは動画にそろえる（足りない分は無音、はみ出す分は切る）
        if not os.path.exists(a.audio): die(f"--audio が無い: {a.audio}", 2)
        audio_in = f"vs_{job_id}_audio.wav"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.audio, "-af", "apad", "-t", f"{length / 24:.3f}", "-ac", "1", "-ar", "48000",
                            os.path.join(ROOT, "ComfyUI", "input", audio_in)], capture_output=True, text=True)
        if r.returncode: die(f"--audio を読めない: {r.stderr[-500:]}", 2)

    g = graph(prompt, "vs/" + first_in, "vs/" + last_in if last_in else None, w, h, length, steps, turbo, a.seed, job_id, audio_in)
    jobs = os.path.join(VS_DIR, "jobs"); os.makedirs(jobs, exist_ok=True)
    job_path = os.path.join(jobs, job_id + ".json"); res_path = os.path.join(jobs, job_id + "_result.json")
    json.dump({"graph": g, "timeout": a.timeout}, open(job_path, "w", encoding="utf-8"), ensure_ascii=False)

    client("ensure", winpath(ROOT), *SERVER_ARGS, check=True)
    print(f"H3: {w}x{h}, {length} コマ（{length / 24:.2f}s）, {steps} ステップ{'（turbo）' if turbo else ''}, seed {a.seed}", file=sys.stderr, flush=True)
    client("run", winpath(job_path), winpath(res_path))
    if not os.path.exists(res_path):
        die("結果ファイルが出なかった（h3_client が途中で落ちた）", 6)
    res = json.load(open(res_path, encoding="utf-8"))
    for f in (os.path.join(inp, first_in), os.path.join(inp, last_in) if last_in else None,
              os.path.join(ROOT, "ComfyUI", "input", audio_in) if audio_in else None):
        if f and os.path.exists(f): os.remove(f)

    st = res.get("status")
    if st == "rejected": die(f"グラフが受け付けられなかった: {res.get('detail', '')[:1500]}", 2)
    if st == "timeout": die(f"{a.timeout} 秒で終わらなかった（中断した）", 5)
    if st == "server_died": die(f"生成中に ComfyUI が落ちた。{ROOT}/vs_server.log を見る（メモリ不足の疑い）", 8)
    if st != "success":
        msg = json.dumps(res.get("messages"), ensure_ascii=False)
        if "out of memory" in msg.lower() or "OutOfMemory" in msg:
            die(f"メモリ不足。--seconds か --mp を下げる: {msg[-600:]}", 8)
        die(f"生成に失敗: {msg[-1500:]}", 6)
    vids = [o for o in res.get("outputs", []) if o["filename"].lower().endswith((".mp4", ".webm", ".mov"))]
    if not vids: die(f"動画が出力されていない: {res}", 6)
    v = vids[0]; src = os.path.join(ROOT, "ComfyUI", "output", v["subfolder"], v["filename"])
    tmp = out + ".part"; open(tmp, "wb").write(open(src, "rb").read()); os.replace(tmp, out); os.remove(src)
    info = probe(out)
    if not info.get("has_audio"):
        print("WARN: 音声が入っていない", file=sys.stderr)
    print(f"elapsed {res['seconds']:.0f}s, VRAM peak {res.get('vram_peak_mib', 0)} MiB, cost $0 "
          f"({info['width']}x{info['height']}, {info['duration']:.2f}s)", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
