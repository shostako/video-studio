"""sfx.py — 効果音をコードで合成して1本の wav にする（パラパラ版など、素材に音が無いとき）。

使い方:
  vs sfx cues.json 出力.wav

cues.json:
  {"duration": 10.0,
   "typing": [{"from": 0.05, "to": 4.2, "rate": 11}],     # 打鍵音を from〜to に1秒 rate 回くらい（ばらつきあり）
   "cues": [{"t": 4.5, "type": "enter"}, {"t": 5.5, "type": "beep"}, {"t": 5.67, "type": "beep", "freq": 440, "dur": 0.25},
            {"t": 6.5, "type": "alarm", "count": 5}, {"t": 8.33, "type": "boom"},
            {"t": 1.0, "type": "click", "gain": 0.4}, {"t": 2.0, "type": "whoosh"}, {"t": 3.0, "type": "pop"}]}
  type: click enter beep alarm boom whoosh pop。gain で音量（既定 1.0）
  打鍵音の時刻は決まった乱数で決まる（何度作っても同じ）。terminal の文字送りとは別なので、
  ぴったり合わせたいときは typing を使わず click を並べる
"""
import argparse, json, os, sys, wave


def main():
    import numpy as np
    ap = argparse.ArgumentParser(); ap.add_argument("cues"); ap.add_argument("out"); a = ap.parse_args()
    c = json.load(open(a.cues, encoding="utf-8")); SR = 48000; dur = float(c["duration"])
    audio = np.zeros(int(SR * (dur + 1)), np.float32); rng = np.random.default_rng(3)

    def put(sig, t, gain=1.0):
        i = int(t * SR)
        if 0 <= i < len(audio): audio[i:i + len(sig)] += sig[:len(audio) - i] * gain
    env = lambda n, tau: np.exp(-np.arange(n) / (tau * SR))
    tt = lambda d: np.arange(int(d * SR)) / SR
    def click(p=1.0):
        n = int(0.03 * SR); hp = np.diff(rng.standard_normal(n), prepend=0)
        return (hp * 0.5 + np.sin(2 * np.pi * 3200 * p * tt(0.03)[:n]) * 0.4) * env(n, 0.004)
    def enter():
        n = int(0.09 * SR); return np.sin(2 * np.pi * 140 * tt(0.09)[:n]) * env(n, 0.02) * 0.9 + rng.standard_normal(n) * env(n, 0.006) * 0.5
    def beep(freq=660, d=0.12):
        n = int(d * SR); k = np.arange(n); sq = np.sign(np.sin(2 * np.pi * freq * k / SR)) * 0.25
        return sq * np.minimum(1, k / (0.005 * SR)) * np.minimum(1, (n - k) / (0.02 * SR))
    def boom():
        n = int(0.5 * SR); t = tt(0.5)[:n]; f = 60 + 40 * np.exp(-t * 12)
        return np.sin(2 * np.cumsum(np.pi * f) / SR) * env(n, 0.15) + rng.standard_normal(n) * env(n, 0.01) * 0.6
    def whoosh():
        n = int(0.4 * SR); x = rng.standard_normal(n); k = np.arange(n) / n
        return np.convolve(x, np.ones(40) / 40, "same") * np.sin(np.pi * k) ** 2 * 1.5
    def pop():
        n = int(0.08 * SR); t = tt(0.08)[:n]; return np.sin(2 * np.pi * (900 - 5000 * t) * t) * env(n, 0.02)

    for ty in c.get("typing", []):
        t = ty["from"]
        while t < ty["to"]:
            put(click(rng.uniform(0.85, 1.2)), t, rng.uniform(0.5, 0.8) * ty.get("gain", 1.0))
            t += rng.uniform(0.5, 1.5) / ty.get("rate", 11)
    for q in c.get("cues", []):
        g = q.get("gain", 1.0); ty = q["type"]
        if ty == "click": put(click(), q["t"], 0.7 * g)
        elif ty == "enter": put(enter(), q["t"], g)
        elif ty == "beep": put(beep(q.get("freq", 660), q.get("dur", 0.12)), q["t"], 0.7 * g)
        elif ty == "alarm":
            for k in range(q.get("count", 5)): put(beep(880 if k % 2 == 0 else 700, 0.09), q["t"] + k * 0.3, 0.35 * g)
        elif ty == "boom": put(boom(), q["t"], g)
        elif ty == "whoosh": put(whoosh(), q["t"], 0.6 * g)
        elif ty == "pop": put(pop(), q["t"], 0.6 * g)
        else: sys.exit(f"ERROR: 知らない type: {ty}")
    audio = audio[:int(SR * dur)]; peak = float(np.abs(audio).max())
    if peak > 0: audio *= 0.8 / peak
    st = np.repeat((audio * 32767).astype(np.int16)[:, None], 2, axis=1)
    part = a.out + ".part.wav"; w = wave.open(part, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(st.tobytes()); w.close(); os.replace(part, a.out); print(a.out)


if __name__ == "__main__":
    main()
