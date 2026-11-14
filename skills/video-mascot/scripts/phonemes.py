"""phonemes.py — 声を音素で書き起こす（日本語の音素の CTC モデル、prj-beatrice/japanese-hubert-base-phoneme-ctc-v4）。

torch と transformers が要るので、Irodori-TTS の venv で動かす（スキルの venv には入れない。DECISIONS.md 2026-11-14）。
  hear(paths) -> [{"path", "phones": [[音素, 始め秒, 終わり秒], ...]}, ...]
長い間（0.2 秒以上）の手前の句を丸ごと落とすことがあるので、間ごとに切り、さらに 5 秒以内（VM_PHONEME_MAXLEN）にして句ごとに書き起こす。
音素は OpenJTalk の記号（a i u e o N cl、k sh ch ts j、ky hy …）。無声化の I・U は小文字にそろえて返す。
モデルは初めて使うときに Hugging Face から取る（約 380MB、~/.cache/huggingface）。
"""
import json, os, subprocess, sys, tempfile

MAXLEN = float(os.environ.get("VM_PHONEME_MAXLEN", "5"))   # 1 回に渡す声の長さの上限（秒）
MODEL = os.environ.get("VM_PHONEME_MODEL", "prj-beatrice/japanese-hubert-base-phoneme-ctc-v4")
IRO = os.environ.get("IRODORI_DIR", os.path.expanduser("~/.local/share/voice-engines/Irodori-TTS"))

RUNNER = r'''
import json, subprocess, sys
import numpy as np, torch
from transformers import AutoProcessor, HubertForCTC
model_id, files, maxlen = sys.argv[1], json.load(open(sys.argv[2], encoding="utf-8")), float(sys.argv[3])
proc = AutoProcessor.from_pretrained(model_id); model = HubertForCTC.from_pretrained(model_id).eval()
inv = {v: k for k, v in proc.tokenizer.get_vocab().items()}
SR = 16000; PAD = 2400   # 前後に 0.15 秒の無音（音を切り詰めた声だと最初の音を落とす）


def chunks(x):
    # 長い間（0.2 秒以上）の手前の句を丸ごと落とすので、間ごとに切って句ごとに書き起こす。
    # 間は 10 ミリ秒ごとの大きさが、声の大きさ（95 パーセンタイル）の 3%（約 -30dB）未満の続き。間の真ん中で切る
    hop = SR // 100
    e = np.array([float(np.sqrt(np.mean(x[i:i + hop] ** 2) + 1e-12)) for i in range(0, len(x), hop)])
    quiet = e < np.percentile(e, 95) * 0.03
    cuts, i = [], 0
    while i < len(e):
        if quiet[i]:
            j = i
            while j < len(e) and quiet[j]: j += 1
            if j - i >= 20 and i > 0 and j < len(e): cuts.append((i + j) // 2)
            i = j
        else: i += 1
    bounds = [0] + cuts + [len(e)]
    segs = [(a_ * hop, min(len(x), b_ * hop)) for a_, b_ in zip(bounds[:-1], bounds[1:])]
    out = []
    for a_, b_ in segs:      # まだ長い塊は maxlen ごとに、静かな所で切る
        while b_ - a_ > maxlen * SR:
            lo, hi = a_ // hop + int(maxlen * 50), a_ // hop + int(maxlen * 100)
            c = (lo + int(np.argmin(e[lo:hi]))) * hop; out.append((a_, c)); a_ = c
        out.append((a_, b_))
    return out


for p in files:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    ph = []
    for a, b in chunks(x):
        y = np.concatenate([np.zeros(PAD, np.float32), x[a:b], np.zeros(PAD, np.float32)])
        with torch.no_grad(): lg = model(torch.from_numpy(y)[None]).logits[0]
        step = len(y) / SR / lg.shape[0]
        ids = lg.argmax(-1).tolist(); seg = []; prev = None
        for f, i in enumerate(ids):
            if i != prev and i != 0: seg.append([inv[i], f, f + 1])
            elif i == prev and i != 0: seg[-1][2] = f + 1
            prev = i
        ph += [[t if t in ("N", "cl") else t.lower(), round(u * step + (a - PAD) / SR, 3), round(v * step + (a - PAD) / SR, 3)]
               for t, u, v in seg if t not in ("sil", "pau", "SOS", "EOS", "UNK")]
    print(json.dumps({"path": p, "phones": ph}, ensure_ascii=False), flush=True)
'''


def available():
    return os.path.isdir(IRO)


def hear(paths):
    """声のファイルを順に音素で書き起こす。1 回の起動でモデルを 1 回読む。"""
    if not available(): raise RuntimeError(f"Irodori-TTS が無い: {IRO}（音素の書き起こしは Irodori の venv を借りる）")
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "runner.py"); open(src, "w", encoding="utf-8").write(RUNNER)
        jf = os.path.join(td, "files.json"); json.dump([os.path.abspath(p) for p in paths], open(jf, "w", encoding="utf-8"))
        r = subprocess.run(["uv", "run", "--no-sync", "python", src, MODEL, jf, str(MAXLEN)], cwd=IRO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONUTF8="1", HF_HUB_DISABLE_TELEMETRY="1"))
        res = []
        for line in r.stdout.splitlines():
            try: res.append(json.loads(line))
            except ValueError: pass
        if r.returncode != 0 or len(res) != len(paths):
            raise RuntimeError("音素の書き起こしに失敗:\n" + "\n".join(r.stderr.splitlines()[-8:]))
        return res
