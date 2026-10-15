"""analyze.py — 素材の動画から、重ね表示を合わせるための時刻を拾う（下書き）。

使い方:
  vs analyze clip.mp4 [--ask "key=質問"]... [--flash red|white|none] [--whisper] [--out events.json]

  - セリフ: Gemini に一字一句（台本で補わず）と開始・終了時刻を書き起こさせる
  - --whisper: Whisper の単語ごとの時刻も付ける（ずれることがある。直すときは ear で確かめる）
  - --flash: コマごとの赤み/明るさの急な上がりを測る（光った瞬間）
  - --ask: 動きの時刻を Gemini に答えさせる（例: --ask "grab_head=両手で頭を抱え始める時刻"）
  出力の JSON は下書き。scene.json に移すときに、コマを見て確かめる
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import gemini_ask, probe, read_frames, read_audio


def flash_times(path, mode):
    import numpy as np
    info = probe(path); fr = read_frames(path, scale=(160, 90)).astype(np.float32)
    if mode == "red": sig = (fr[..., 2] - (fr[..., 1] + fr[..., 0]) / 2).mean(axis=(1, 2))
    else: sig = fr.mean(axis=(1, 2, 3))
    base = float(np.median(sig[: max(3, int(info["fps"] / 2))])); thr = base + (6 if mode == "red" else 25)
    hot = np.where(sig > thr)[0]
    if not len(hot): return None
    return {"start": round(hot[0] / info["fps"], 3), "end": round(hot[-1] / info["fps"], 3), "peak": round(float(np.argmax(sig)) / info["fps"], 3)}


def whisper_words(path):
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get("VS_WHISPER_MODEL", "medium"), device="cpu", compute_type="int8")
    segs, _ = m.transcribe(read_audio(path), language="ja", word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
    return [{"text": s.text, "start": round(s.start, 2), "end": round(s.end, 2),
             "words": [{"w": w.word, "start": round(w.start, 2), "end": round(w.end, 2)} for w in s.words]} for s in segs]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("clip"); ap.add_argument("--ask", action="append", default=[])
    ap.add_argument("--flash", default="red", choices=["red", "white", "none"]); ap.add_argument("--whisper", action="store_true")
    ap.add_argument("--out"); a = ap.parse_args()
    info = probe(a.clip)
    ev = {"clip": os.path.abspath(a.clip), "duration": round(info["duration"], 3), "fps": info["fps"]}
    if info["has_audio"]:
        q = ('この動画の話し声を、聞こえたとおり一字一句（助詞・語尾・「っ」も含め、台本や文脈で補わずに）書き起こして。'
             '各セリフの開始・終了時刻を秒（小数2桁）で。話し声が無ければ空配列。JSON配列だけ返す: [{"text":"","start":0.00,"end":0.00}]')
        ev["speech"] = gemini_ask(a.clip, q, json_out=True)
        if a.whisper: ev["whisper"] = whisper_words(a.clip)
    if a.flash != "none": ev["flash"] = flash_times(a.clip, a.flash)
    if a.ask:
        keys = [s.split("=", 1) for s in a.ask]
        q = "この動画を見て、次の各項目が起きる時刻（秒、小数1桁）を JSON オブジェクトで返して。起きないなら null。\n" + \
            "\n".join(f'- "{k}": {v}' for k, v in keys)
        ev["asks"] = gemini_ask(a.clip, q, json_out=True)
    s = json.dumps(ev, ensure_ascii=False, indent=1)
    if a.out: open(a.out, "w", encoding="utf-8").write(s)
    print(s)


if __name__ == "__main__":
    main()
