"""Wan2.2 S2V-14B（GGUF）: 画像＋声 → 声に合わせて話す動画。マスコット解説動画の試し。
使い方: python gen_wan_s2v.py <ref_image> <audio.wav> <prefix> [steps] [cfg] [seed]
"""
import json, sys, time, urllib.request

ref, audio, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
STEPS = int(sys.argv[4]) if len(sys.argv) > 4 else 20
CFG = float(sys.argv[5]) if len(sys.argv) > 5 else 6.0
SEED = int(sys.argv[6]) if len(sys.argv) > 6 else 2024
LORA = sys.argv[7] if len(sys.argv) > 7 else ''   # 4 ステップ高速化: wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors（steps 4・cfg 1）
WIDTH, HEIGHT, LENGTH = 448, 800, 77

POS = ('a glossy resin chibi figurine woman with a big head, black hair tied in a low bun, wearing a navy suit and a white blouse, '
       'stands on a plain white background and talks calmly to the viewer, explaining something, '
       'her lips move clearly with the speech, small natural hand gestures at chest height, '
       'her head stays mostly still and level, eyes open looking at the viewer, same face, same hairstyle, '
       'stable fixed camera, full body visible, feet stay on the same spot')
NEG = ('blurry, low quality, worst quality, deformed, bad anatomy, extra limbs, extra fingers, face distortion, changing face, '
       'morphing, flickering, text, watermark, subtitles, camera movement, zoom, pan, head shaking, nodding, swaying, '
       'bouncing, walking, closed eyes, winking, looking away, static, motionless')

wf = {
    '1': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': 'Wan2.2-S2V-14B-Q4_K_M.gguf'}},
    '2': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['1', 0], 'shift': 8.0}},
    '3': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': 'umt5_xxl_fp8_e4m3fn_scaled.safetensors', 'type': 'wan', 'device': 'default'}},
    '4': {'class_type': 'VAELoader', 'inputs': {'vae_name': 'wan_2.1_vae.safetensors'}},
    '5': {'class_type': 'LoadImage', 'inputs': {'image': ref, 'upload': 'image'}},
    '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['3', 0], 'text': POS}},
    '7': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['3', 0], 'text': NEG}},
    '20': {'class_type': 'AudioEncoderLoader', 'inputs': {'audio_encoder_name': 'wav2vec2_large_english_fp16.safetensors'}},
    '21': {'class_type': 'LoadAudio', 'inputs': {'audio': audio}},
    '22': {'class_type': 'AudioEncoderEncode', 'inputs': {'audio_encoder': ['20', 0], 'audio': ['21', 0]}},
    '8': {'class_type': 'WanSoundImageToVideo', 'inputs': {
        'positive': ['6', 0], 'negative': ['7', 0], 'vae': ['4', 0], 'width': WIDTH, 'height': HEIGHT, 'length': LENGTH,
        'batch_size': 1, 'audio_encoder_output': ['22', 0], 'ref_image': ['5', 0]}},
    '9': {'class_type': 'KSampler', 'inputs': {'model': ['2', 0], 'positive': ['8', 0], 'negative': ['8', 1], 'latent_image': ['8', 2],
                                               'seed': SEED, 'steps': STEPS, 'cfg': CFG, 'sampler_name': 'uni_pc', 'scheduler': 'simple', 'denoise': 1.0}},
    '13': {'class_type': 'VAEDecode', 'inputs': {'samples': ['9', 0], 'vae': ['4', 0]}},
    '14': {'class_type': 'SaveImage', 'inputs': {'images': ['13', 0], 'filename_prefix': prefix}},
}
if LORA:
    wf['30'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['1', 0], 'lora_name': LORA, 'strength_model': 1.0}}
    wf['2']['inputs']['model'] = ['30', 0]
req = urllib.request.Request('http://127.0.0.1:8188/prompt', data=json.dumps({'prompt': wf}).encode(), headers={'Content-Type': 'application/json'})
try:
    pid = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())['prompt_id']
except urllib.error.HTTPError as e:
    print('SUBMIT ERROR', e.read().decode()[:3000], flush=True); sys.exit(1)
print('queued', pid, f'steps={STEPS} cfg={CFG} seed={SEED}', flush=True)
t0 = time.time()
while time.time() - t0 < 4 * 3600:
    try:
        d = json.loads(urllib.request.urlopen('http://127.0.0.1:8188/history/' + pid, timeout=5).read().decode())
        if pid in d:
            st = d[pid]['status']
            if st['status_str'] == 'success': print('DONE %.0fs' % (time.time() - t0), flush=True); break
            if st['status_str'] == 'error': print('ERROR', json.dumps(st)[:3000], flush=True); break
    except Exception:
        pass
    time.sleep(5)
print('END', flush=True)
