"""声の wav を書き起こして、語ごとの長さを出す。読み違いと「溜め」（例: 「電気」が「でんーき」と伸びる）を見つけるのに使う。
台本との一致だけでは、文字は合っていても一語だけ不自然に長い読みを見逃すため。

usage（faster-whisper の入った Python で。video-scene の venv にある）:
  ~/.local/share/video-scene/venv/bin/python word_timing.py <wav> [<wav> ...] [--long 0.6] [--model medium]
出力: ファイルごとに、書き起こしと「語[秒]」の並び。--long 秒より長い語には ← を付ける。
直し方: ← の付いた語を含む行だけ、ふりがな（say）を足すか、読点の位置を変えて作り直し、もう一度ここで測る。
"""
import argparse, os, sys
from faster_whisper import WhisperModel

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "video-scene", "scripts"))
from common import read_audio  # noqa: E402

def words_of(model, path):
    segs, _ = model.transcribe(read_audio(path), language="ja", word_timestamps=True, vad_filter=False,
                               condition_on_previous_text=False)
    return [(w.word.strip(), w.end - w.start) for s in segs for w in s.words]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", nargs="+"); ap.add_argument("--long", type=float, default=0.6); ap.add_argument("--model", default="medium")
    A = ap.parse_args()
    m = WhisperModel(A.model, device="cpu", compute_type="int8")
    for p in A.wav:
        ws = words_of(m, p)
        print(os.path.basename(p), "".join(w for w, _ in ws))
        print("  " + " ".join(f"{w}[{d:.2f}]{'←' if d > A.long else ''}" for w, d in ws), flush=True)
