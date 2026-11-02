"""声のエンジンの選択肢: VOICEVOX ENGINE（CPU で動く。GPU が要らない）。config.voice.engine が "voicevox" のときだけ使う。

config.voice: {"engine": "voicevox", "speaker": 話者の番号, "speed": 1.0, "pitch": 0.0, "intonation": 1.0,
               "host": "http://127.0.0.1:50021"}。speaker に既定は無い（どの声を使うかは利用者が決める）。
エンジンは別に動かしておく。話者ごとの利用規約に従い、動画には「VOICEVOX:話者の名前」と書く。
このファイルと voice.py の呼び出しの数行を消せば、エンジンごと外せる。"""
import json, os, urllib.error, urllib.parse, urllib.request

from lib import die

DEFAULT_HOST = "http://127.0.0.1:50021"
SAMPLE_RATE = 48000
TIMEOUT = 300


def _request(host, path, data=None):
    req = urllib.request.Request(host + path, data=data, method="POST" if data is not None else "GET", headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def speakers(host):
    """[(番号, "名前（スタイル）"), ...]"""
    return [(st["id"], f"{sp['name']}（{st['name']}）") for sp in json.loads(_request(host, "/speakers")) for st in sp["styles"]]


def build_query(query, voice):
    """audio_query の結果に config の調整を足す。"""
    return {**query, "speedScale": float(voice.get("speed", 1.0)), "pitchScale": float(voice.get("pitch", 0.0)), "intonationScale": float(voice.get("intonation", 1.0)),
            "outputSamplingRate": SAMPLE_RATE, "outputStereo": False}


def synth_jobs(jobs, voice):
    """jobs: [{"text": 合成する文, "out": 出力の wav}, ...]。エンジンに繋がらない・話者が無いときは、直し方を出して止まる。"""
    host = voice.get("host", DEFAULT_HOST).rstrip("/")
    try: known = speakers(host)
    except (urllib.error.URLError, OSError, ValueError) as e:
        die(f"VOICEVOX ENGINE に繋がらない（{host}）: {e}。エンジンを起動してから、もう一度")
    sp = voice.get("speaker")
    if sp not in {i for i, _ in known}:
        die("config.voice.speaker に話者の番号を書く。使える話者:\n" + "\n".join(f"  {i}: {n}" for i, n in known))
    for j in jobs:
        qs = urllib.parse.urlencode({"text": j["text"], "speaker": sp})
        try:
            q = json.loads(_request(host, f"/audio_query?{qs}", data=b""))
            wav = _request(host, f"/synthesis?speaker={sp}", data=json.dumps(build_query(q, voice)).encode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            die(f"VOICEVOX の合成に失敗（{j['text'][:20]}…）: {e}")
        tmp = j["out"] + ".part"
        with open(tmp, "wb") as f: f.write(wav)
        os.replace(tmp, j["out"]); print("ok", j["out"], flush=True)
