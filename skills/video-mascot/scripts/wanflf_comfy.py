"""ComfyUI に Wan2.2 I2V-A14B（GGUF）＋ Lightning 4step の First-Last-Frame を 1 本投げ、終わるまで待つ。
wanflf.py が ComfyUI の Python（Windows 側の python_embeded）で走らせる。WSL からは ComfyUI の 127.0.0.1 に届かないため。
使い方: python.exe wanflf_comfy.py <spec.json>
spec: url, start, end（ComfyUI/input の名前）, prefix, prompt, width, height, length, seed, unet_high, unet_low, lora_high, lora_low, clip, vae, clip_vision
終了コード: 0 済み / 1 ComfyUI のエラー / 2 ComfyUI に届かない / 3 時間切れ"""
import json, sys, time, urllib.error, urllib.request

NEG = ("blurry, low quality, worst quality, deformed, bad anatomy, extra limbs, extra fingers, missing fingers, face distortion, changing face, "
       "morphing, flickering, text, watermark, camera movement, zoom, pan, head shaking, nodding, head tilt, breathing, swaying, bouncing, "
       "walking, open mouth, talking, looking away, side glance, squinting, closed eyes, winking")
STEPS, BOUNDARY, CFG = 4, 2, 1.0


def workflow(s):
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": s["unet_high"]}},
        "101": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": s["lora_high"], "strength_model": 1.0}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": s["unet_low"]}},
        "201": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["2", 0], "lora_name": s["lora_low"], "strength_model": 1.0}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": s["clip"], "type": "wan", "device": "default"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": s["vae"]}},
        "5": {"class_type": "LoadImage", "inputs": {"image": s["start"], "upload": "image"}},
        "25": {"class_type": "LoadImage", "inputs": {"image": s["end"], "upload": "image"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": s["prompt"]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": NEG}},
        "15": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": s["clip_vision"]}},
        "16": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["15", 0], "image": ["5", 0], "crop": "none"}},
        "26": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["15", 0], "image": ["25", 0], "crop": "none"}},
        "8": {"class_type": "WanFirstLastFrameToVideo", "inputs": {
            "positive": ["6", 0], "negative": ["7", 0], "vae": ["4", 0], "width": s["width"], "height": s["height"], "length": s["length"],
            "batch_size": 1, "clip_vision_start_image": ["16", 0], "clip_vision_end_image": ["26", 0], "start_image": ["5", 0], "end_image": ["25", 0]}},
        "9": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["101", 0], "add_noise": "enable", "noise_seed": s["seed"], "steps": STEPS, "cfg": CFG,
                                                           "sampler_name": "euler", "scheduler": "simple", "positive": ["8", 0], "negative": ["8", 1],
                                                           "latent_image": ["8", 2], "start_at_step": 0, "end_at_step": BOUNDARY, "return_with_leftover_noise": "enable"}},
        "10": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["201", 0], "add_noise": "disable", "noise_seed": s["seed"], "steps": STEPS, "cfg": CFG,
                                                            "sampler_name": "euler", "scheduler": "simple", "positive": ["8", 0], "negative": ["8", 1],
                                                            "latent_image": ["9", 0], "start_at_step": BOUNDARY, "end_at_step": STEPS, "return_with_leftover_noise": "disable"}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "14": {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": s["prefix"]}},
    }


def main():
    s = json.load(open(sys.argv[1], encoding="utf-8")); url = s["url"].rstrip("/")
    req = urllib.request.Request(url + "/prompt", data=json.dumps({"prompt": workflow(s)}).encode(), headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())["prompt_id"]
    except urllib.error.HTTPError as e:
        print("ComfyUI が受け付けない:", e.read().decode()[:1500]); sys.exit(1)
    except OSError as e:
        print(f"ComfyUI に届かない（{url}。run_nvidia_gpu.bat で起動しておく）:", e); sys.exit(2)
    t0 = time.time()
    while time.time() - t0 < 3600:
        try:
            d = json.loads(urllib.request.urlopen(f"{url}/history/{pid}", timeout=10).read().decode())
            if pid in d:
                st = d[pid]["status"]
                if st.get("status_str") == "success": print(f"DONE {time.time() - t0:.0f}s"); return
                if st.get("status_str") == "error": print("ERROR", json.dumps(st)[:1500]); sys.exit(1)
        except OSError:
            pass
        time.sleep(3)
    print("時間切れ"); sys.exit(3)


if __name__ == "__main__":
    main()
