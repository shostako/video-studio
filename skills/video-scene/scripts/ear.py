"""ear.py — 音を2つの文字起こし（Whisper と Gemini）に聞かせる。声を直したあとの確かめに使う。

使い方:
  vs ear 入力(動画/音声) [--start 秒] [--dur 秒] [--expect "これで通る"] [--repeat 3] [--no-gemini]

  - 私（Claude）は音を聞けない。セリフの確認は必ずこれで2つの耳に通す
  - --expect を付けると、各結果にその文字列が含まれるかを表示する
  - Gemini は揺れることがある。境目の判定は --repeat 3 で多数決を見る
"""
import argparse, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import gemini_ask, read_audio


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("--start", type=float); ap.add_argument("--dur", type=float)
    ap.add_argument("--expect"); ap.add_argument("--repeat", type=int, default=1); ap.add_argument("--no-gemini", action="store_true")
    a = ap.parse_args()
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get("VS_WHISPER_MODEL", "medium"), device="cpu", compute_type="int8")
    segs, _ = m.transcribe(read_audio(a.src, start=a.start, dur=a.dur), language="ja", vad_filter=False, condition_on_previous_text=False)
    w = "".join(s.text for s in segs)
    mark = lambda t: "" if not a.expect else ("  [含む]" if a.expect in t else "  [含まない]")
    print(f"whisper: {w}{mark(w)}")
    if a.no_gemini: return
    tmp = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + (["-ss", str(a.start)] if a.start else []) + ["-i", a.src] +
                   (["-t", str(a.dur)] if a.dur else []) + ["-vn", tmp], check=True)
    q = "この音声の話し声を、聞こえたとおり一字一句書き起こして。台本や文脈から補わず、聞こえた音だけで。書き起こしだけを返す。"
    try:
        for i in range(a.repeat):
            g = gemini_ask(tmp, q).strip().replace("\n", " ")
            print(f"gemini{'' if a.repeat == 1 else f'#{i+1}'}: {g}{mark(g)}")
    finally:
        os.remove(tmp)


if __name__ == "__main__":
    main()
