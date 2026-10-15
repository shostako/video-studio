"""audio_cut.py — セリフの一部（声の音域だけ）を消す。打鍵音など、声より高い音と低い音は残す。

使い方:
  vs audio_cut 入力(動画/音声) 出力.wav --cut 1.48:1.86 [--cut 開始:終了]... [--band 150:4000] [--fade 0.02]

  - 入力が動画なら音だけ取り出して処理する。出力は wav（scene.json の base.audio に指定する）
  - 消す位置は文字起こしの時刻を鵜呑みにしない。候補を何通りか作って vs ear で確かめ、
    「消したい音が消え、残したい音が残る」いちばん遅い開始点を選ぶ
"""
import argparse, os, subprocess, sys, tempfile, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import die


def main():
    import numpy as np
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("out"); ap.add_argument("--cut", action="append", required=True)
    ap.add_argument("--band", default="150:4000"); ap.add_argument("--fade", type=float, default=0.02); a = ap.parse_args()
    lo, hi = map(float, a.band.split(":"))
    tmp = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.src, "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", tmp], check=True)
    w = wave.open(tmp); sr, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch).astype(np.float32); w.close(); os.remove(tmp)
    fade = int(a.fade * sr)
    for c in a.cut:
        t0, t1 = map(float, c.split(":"))
        if not t0 < t1: die(f"--cut の順序が逆: {c}", 2)
        i0, i1 = max(0, int(t0 * sr) - fade), min(len(x), int(t1 * sr) + fade)
        seg = x[i0:i1].copy()
        F = np.fft.rfft(seg, axis=0); f = np.fft.rfftfreq(len(seg), 1 / sr); F[(f >= lo) & (f <= hi)] = 0
        voiceless = np.fft.irfft(F, len(seg), axis=0)
        g = np.zeros(len(seg)); g[:fade] = np.linspace(1, 0, fade); g[-fade:] = np.linspace(0, 1, fade)   # 1=元の音 0=声を消した音
        x[i0:i1] = seg * g[:, None] + voiceless * (1 - g[:, None])
        print(f"cut {t0:.3f}-{t1:.3f}s ({lo:.0f}-{hi:.0f}Hz)")
    part = a.out + ".part.wav"
    o = wave.open(part, "wb"); o.setnchannels(ch); o.setsampwidth(2); o.setframerate(sr)
    o.writeframes(np.clip(x, -32768, 32767).astype(np.int16).tobytes()); o.close(); os.replace(part, a.out)
    print(a.out)


if __name__ == "__main__":
    main()
