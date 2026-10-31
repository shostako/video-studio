"""マスコット解説動画用: Wan2.2 I2V-A14B + Lightning(4step) の First-Last-Frame 生成を連続で回す。
始点・終点とも同じ立ち姿にして、本と本の継ぎ目で姿勢が飛ばないようにする。
成人向けの動きの LoRA（missionary/bounce）は使わない。Lightning だけ。
使い方: python gen_wan14b_mascot_flf.py <clips.json>
clips.json = {"base": "mascot_suit_base.png", "prefix": "mascot_wan/flf", "clips": [{"id": "c00", "seed": 1, "motion": "..."}]}
すでに出力がある id は飛ばす（やり直し安全）。
"""
import json, urllib.request, time, sys, os

spec = json.load(open(sys.argv[1], encoding='utf-8'))
BASE = spec['base']; PREFIX = spec['prefix']
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ComfyUI', 'output', os.path.dirname(PREFIX))

STYLE = spec.get('style') or ('a glossy resin chibi figurine woman with a black chin-length bob haircut, wearing a navy suit, '
                              'stands on a plain white background and explains something to the viewer. ')
KEEP = spec.get('keep') or (' Her head stays still and level, her eyes stay open and look straight at the viewer, '
                            'calm faint smile, mouth closed, same face, same hairstyle, smooth slow natural motion, '
                            'stable fixed camera, full body visible, her feet stay on the same spot.')
NEG = ('blurry, low quality, worst quality, deformed, bad anatomy, extra limbs, extra fingers, missing fingers, '
       'face distortion, changing face, morphing, flickering, text, watermark, camera movement, zoom, pan, '
       'head shaking, nodding, head tilt, breathing, swaying, bouncing, walking, open mouth, talking, '
       'looking away, side glance, squinting, closed eyes, winking')

WIDTH, HEIGHT, LENGTH, STEPS, BOUNDARY, CFG = spec.get('width', 448), spec.get('height', 800), 81, 4, 2, 1.0
HIGH = 'Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf'; LOW = 'Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf'
LGT_H = 'wan22_i2v_high_lightning.safetensors'; LGT_L = 'wan22_i2v_low_lightning.safetensors'


def workflow(clip):
    pos = STYLE + clip['motion'] + clip.get('keep', KEEP)
    pfx = f"{PREFIX}_{clip['id']}"
    wf = {
        '1': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': HIGH}},
        '101': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': LGT_H, 'strength_model': 1.0}},
        '2': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': LOW}},
        '201': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['2', 0], 'lora_name': LGT_L, 'strength_model': 1.0}},
        '3': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan', 'device': 'default'}},
        '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
        '5': {'class_type': 'LoadImage', 'inputs': {'image': BASE, 'upload': 'image'}},
        '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['3', 0], 'text': pos}},
        '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['3', 0], 'text': NEG + (', ' + clip['neg'] if clip.get('neg') else '')}},
        '15': {'class_type': 'CLIPVisionLoader', 'inputs': {'clip_name': 'CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors'}},
        '16': {'class_type': 'CLIPVisionEncode', 'inputs': {'clip_vision': ['15', 0], 'image': ['5', 0], 'crop': 'none'}},
        '8': {'class_type': 'WanFirstLastFrameToVideo', 'inputs': {
            'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['4', 0], 'width': WIDTH, 'height': HEIGHT,
            'length': LENGTH, 'batch_size': 1, 'clip_vision_start_image': ['16', 0], 'clip_vision_end_image': ['16', 0],
            'start_image': ['5', 0], 'end_image': ['5', 0]}},
        '9': {'class_type': 'KSamplerAdvanced', 'inputs': {'model': ['101', 0], 'add_noise': 'enable', 'noise_seed': clip['seed'], 'steps': STEPS, 'cfg': CFG, 'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['8', 0], 'negative': ['8', 1], 'latent_image': ['8', 2], 'start_at_step': 0, 'end_at_step': BOUNDARY, 'return_with_leftover_noise': 'enable'}},
        '10': {'class_type': 'KSamplerAdvanced', 'inputs': {'model': ['201', 0], 'add_noise': 'disable', 'noise_seed': clip['seed'], 'steps': STEPS, 'cfg': CFG, 'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['8', 0], 'negative': ['8', 1], 'latent_image': ['9', 0], 'start_at_step': BOUNDARY, 'end_at_step': STEPS, 'return_with_leftover_noise': 'disable'}},
        '13': {'class_type': 'VAEDecode', 'inputs': {'samples': ['10', 0], 'vae': ['4', 0]}},
        '14': {'class_type': 'SaveImage', 'inputs': {'images': ['13', 0], 'filename_prefix': pfx}},
    }
    # 姿勢から姿勢へ: 終点の絵（clip['end']）とコマ数（clip['length']）を本ごとに指定できる
    if clip.get('start'):
        wf['5']['inputs']['image'] = clip['start']
    if clip.get('end'):
        wf['25'] = {'class_type': 'LoadImage', 'inputs': {'image': clip['end'], 'upload': 'image'}}
        wf['26'] = {'class_type': 'CLIPVisionEncode', 'inputs': {'clip_vision': ['15', 0], 'image': ['25', 0], 'crop': 'none'}}
        wf['8']['inputs']['end_image'] = ['25', 0]; wf['8']['inputs']['clip_vision_end_image'] = ['26', 0]
    if clip.get('length'):
        wf['8']['inputs']['length'] = clip['length']
    return pfx, wf


def done(pfx):
    stem = os.path.basename(pfx)
    if not os.path.isdir(OUTDIR): return False
    return sum(1 for f in os.listdir(OUTDIR) if f.startswith(stem + '_') and f.endswith('.png')) >= LENGTH


def run(wf):
    payload = json.dumps({'prompt': wf}).encode()
    req = urllib.request.Request('http://127.0.0.1:8188/prompt', data=payload, headers={'Content-Type': 'application/json'})
    pid = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())['prompt_id']
    t0 = time.time()
    while time.time() - t0 < 3600:
        try:
            d = json.loads(urllib.request.urlopen('http://127.0.0.1:8188/history/' + pid, timeout=5).read().decode())
            if pid in d:
                st = d[pid]['status']['status_str']
                if st == 'success': return True, time.time() - t0, ''
                if st == 'error': return False, time.time() - t0, json.dumps(d[pid]['status'])[:1500]
        except Exception:
            pass
        time.sleep(3)
    return False, time.time() - t0, 'timeout'


T = time.time()
for clip in spec['clips']:
    pfx, wf = workflow(clip)
    if done(pfx):
        print(f"[{clip['id']}] skip (already done)", flush=True); continue
    ok, sec, err = run(wf)
    print(f"[{clip['id']}] {'OK' if ok else 'ERROR'} {sec:.0f}s {err}", flush=True)
print(f'ALL END {time.time() - T:.0f}s', flush=True)
