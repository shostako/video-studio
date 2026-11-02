"""声の全体を聞き取って語の時刻を出す。書き出し（render.py）と声の確認（voice.py）が同じ条件で使う。条件を変えると口の形が変わる。
  python words.py <master.wav> <master.words.json>"""
import json, os, sys

HERE = os.path.dirname(os.path.realpath(__file__))


def transcribe_words(wav):
    """[[語, 始め, 終わり], ...]"""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "video-scene", "scripts"))
    from common import read_audio
    from faster_whisper import WhisperModel
    segs, _ = WhisperModel("medium", device="cpu", compute_type="int8").transcribe(read_audio(wav), language="ja", word_timestamps=True, condition_on_previous_text=False)
    return [[w.word, w.start, w.end] for s in segs for w in s.words]


def write_words(wav, out):
    words = transcribe_words(wav); tmp = out + ".part"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(words, f, ensure_ascii=False)
    os.replace(tmp, out)


if __name__ == "__main__":
    write_words(sys.argv[1], sys.argv[2])
