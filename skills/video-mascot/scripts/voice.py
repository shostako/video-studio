"""台詞から声を作る（Irodori-TTS、手元で動く、無料）。
  vm voice <作業フォルダ> check                   Irodori が使えるか確かめる
  vm voice <作業フォルダ> candidates              config.voice.candidates の声の説明文ごとに、試し2行を読ませる → voice/cand/ に wav と聞き比べの1本
  vm voice <作業フォルダ> synth [行番号 ...]       全行（か指定の行）を読ませて voice/l<N>.wav を作る。聞き取りで台本との一致も出す
  vm voice <作業フォルダ> master                  各行を開始時刻に置いて voice/master.wav と voice/timing.json を作る
config.voice: {caption, seed, ref(手本の wav、あれば全行をこの声で), lines:[{text, say(合成に渡す文。漢字を読み違えるならひらがなを混ぜる), start(秒、省略可)}], gap(行の間、既定0.5), candidates:[説明文...]}
声の設計は説明文（caption）で行い、気に入った1本を ref にして全行を同じ声にそろえる。"""
import difflib, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, die, partial_voice_ref

IRO = os.environ.get("IRODORI_DIR", os.path.expanduser("~/.local/share/voice-engines/Irodori-TTS"))
_VENV = os.path.join(os.environ.get("VIDEO_SCENE_HOME") or os.path.expanduser("~/.local/share/video-scene"), "venv")
WS = next((p_ for p_ in (os.path.join(_VENV, "bin", "python"), os.path.join(_VENV, "Scripts", "python.exe")) if os.path.exists(p_)), sys.executable)   # 聞き取り（faster-whisper）の Python。Windows の venv は Scripts/python.exe


def ff(*a): subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
def dur(p): return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p], capture_output=True, text=True).stdout)


RUNNER = r'''
import json, os, sys
sys.path.insert(0, %IRO%)
from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, SamplingRequest, default_runtime_device, download_hf_checkpoint, save_wav
jobs = json.load(open(sys.argv[1], encoding="utf-8")); dev = default_runtime_device()
rt = InferenceRuntime.from_key(RuntimeKey(checkpoint=download_hf_checkpoint("Aratako/Irodori-TTS-v4.1-Small"), model_device=dev,
    codec_repo="Aratako/Semantic-DACVAE-Japanese-32dim", model_precision="fp32", codec_device=dev, codec_precision="fp32",
    codec_deterministic_encode=True, codec_deterministic_decode=True, compile_model=False, compile_dynamic=False))
for j in jobs:
    ref = j.get("ref")
    r = rt.synthesize(SamplingRequest(text=j["text"], caption=j["caption"], seed=j.get("seed", 1234), duration_scale=j.get("duration_scale", 1.0),
                                      no_ref=(ref is None), ref_wav=ref), log_fn=None)
    save_wav(j["out"], r.audio, r.sample_rate); print("ok", j["out"], f"{r.audio.shape[-1] / r.sample_rate:.1f}s", flush=True)
'''


def run_irodori(jobs, tmp):
    if not os.path.isdir(IRO): die(f"Irodori-TTS が無い: {IRO}（vm の setup.sh を実行）")
    src = os.path.join(tmp, "runner.py"); open(src, "w", encoding="utf-8").write(RUNNER.replace("%IRO%", json.dumps(IRO)))   # Python の文字列として埋める（Windows の \U などをエスケープと読ませない）
    jf = os.path.join(tmp, "jobs.json"); json.dump(jobs, open(jf, "w", encoding="utf-8"), ensure_ascii=False)
    env = dict(os.environ, HF_HUB_DISABLE_TELEMETRY="1")
    r = subprocess.run(["uv", "run", "--no-sync", "python", src, jf], cwd=IRO, env=dict(env, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8", errors="replace")
    for l in r.stdout.splitlines():
        if l.startswith("ok"): print(l)
    if r.returncode != 0: die("Irodori の実行に失敗:\n" + "\n".join(r.stderr.splitlines()[-12:]), 6)


def hear(path):
    code = ("import sys,os; sys.path.insert(0, os.path.expanduser('~/.claude/skills/video-scene/scripts'));"
            "from ear import read_audio; from faster_whisper import WhisperModel;"
            "m=WhisperModel('medium',device='cpu',compute_type='int8');"
            f"s,_=m.transcribe(read_audio({path!r}),language='ja',vad_filter=False,condition_on_previous_text=False); print(''.join(x.text for x in s))")
    out = subprocess.run([WS, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=dict(os.environ, PYTHONUTF8="1")).stdout.strip().splitlines()
    return out[-1] if out else ""


def clean_tail(src, dst, n):
    """行の声の終わりのゴミの音（lib.tail_blip）を無音にした写しを dst に書いて、そのパスを返す（長さは変えない＝行の時刻はずれない）。
    無ければ src をそのまま返す。消したときはログに出す。"""
    import numpy as np
    from lib import tail_blip
    sr = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", src],
                            capture_output=True, text=True).stdout.strip() or 0) or 48000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).copy(); bl = tail_blip(x, sr)
    if bl is None: return src
    a, b = bl; f = min(int(sr * 0.005), a)
    if f: x[a - f:a] *= np.linspace(1, 0, f, dtype=np.float32)
    pk = float(np.abs(x[a:b]).max()); x[a:b] = 0
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-c:a", "pcm_s16le", dst], input=x.tobytes(), check=True)
    print(f"行{n}: 終わりのゴミの音を消した（{a / sr:.2f}〜{b / sr:.2f} 秒、{(b - a) / sr * 1000:.0f} ミリ秒、大きさ {pk:.2f}。長さは変えない）")
    return dst


def main():
    a = [x for x in sys.argv[1:]]
    if len(a) < 2: die("使い方: vm voice <作業フォルダ> check|candidates|synth|master")
    P = Proj(a[0]); cmd = a[1]; V = P.cfg["voice"]; vd = P.p("voice"); os.makedirs(vd, exist_ok=True)
    lines = V["lines"]; gap = float(V.get("gap", 0.5))
    if cmd == "check":
        print("Irodori:", "ある" if os.path.isdir(IRO) else "無い", IRO); sys.exit(0 if os.path.isdir(IRO) else 1)
    if cmd == "candidates":
        cands = V.get("candidates") or die("config.voice.candidates（声の説明文の一覧）が無い")
        cd = P.p("voice", "cand"); os.makedirs(cd, exist_ok=True); test = V.get("test_lines", [0, min(3, len(lines) - 1)]); jobs = []
        for i, cap in enumerate(cands, 1):
            ref = None
            for j in test:
                out = os.path.join(cd, f"C{i}_l{j + 1}.wav")
                jobs.append({"text": lines[j].get("say", lines[j]["text"]), "caption": cap, "seed": V.get("seed", 1234), "ref": ref, "out": out})
                ref = ref or out    # 1行目の声を手本に2行目を読む（声がそろうか見るため）
        # ref は1行目ができてから決まるので、行ごとに分けて実行
        first = [j for j in jobs if j["ref"] is None]; rest = [j for j in jobs if j["ref"] is not None]
        run_irodori(first, cd); run_irodori(rest, cd)
        sil = os.path.join(cd, "_sil.wav"); ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.8", sil)
        beep = os.path.join(cd, "_beep.wav"); ff("-f", "lavfi", "-i", "sine=frequency=1200:sample_rate=48000:duration=0.12", "-af", "volume=0.25", beep)
        lst = os.path.join(cd, "_l.txt"); parts = []
        for i in range(1, len(cands) + 1):
            parts += [beep, sil]
            for j in test:
                n = os.path.join(cd, f"C{i}_l{j + 1}_n.wav"); ff("-i", os.path.join(cd, f"C{i}_l{j + 1}.wav"), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "1", n); parts += [n, sil]
        open(lst, "w").write("".join(f"file '{p}'\n" for p in parts)); out = os.path.join(cd, "聞き比べ.wav")
        ff("-f", "concat", "-safe", "0", "-i", lst, "-ar", "48000", "-ac", "1", out); print("聞き比べ:", out, "（「ピッ」のあと C1 → C2 … の順）"); return
    if cmd == "synth":
        only = [int(x) for x in a[2:]] or list(range(1, len(lines) + 1)); ref = V.get("ref"); ref = P.p(ref) if ref and not os.path.isabs(ref) else ref
        if ref is None:    # 一部の行だけ作り直すときは、残す行の声を手本にする（手本なしで作ると別の声になる）
            k = partial_voice_ref(only, len(lines), lambda n: os.path.exists(P.p("voice", f"l{n}.wav")))
            if k is not None: ref = P.p("voice", f"l{k}.wav"); print(f"手本: 行{k} の声", flush=True)
        jobs = [{"text": lines[n - 1].get("say", lines[n - 1]["text"]), "caption": V["caption"], "seed": V.get("seed", 1234), "ref": ref,
                 "duration_scale": V.get("duration_scale", 1.0), "out": P.p("voice", f"l{n}.wav")} for n in only]
        if ref is None:    # 手本が無ければ、最初に作った行を手本にして残りをそろえる
            run_irodori(jobs[:1], vd); r0 = jobs[0]["out"]
            for j in jobs[1:]: j["ref"] = r0
            run_irodori(jobs[1:], vd)
        else: run_irodori(jobs, vd)
        norm = lambda t: re.sub(r"[\s、。，．,.!?！？「」…ー〜]", "", t)
        for n in only:
            heard = hear(P.p("voice", f"l{n}.wav")); r = difflib.SequenceMatcher(None, norm(lines[n - 1]["text"]), norm(heard)).ratio()
            print(f"行{n} 台本との一致 {r:.2f}: {heard}")
        return
    if cmd == "master":
        starts = []; t = 0.0; info = []
        for i, l in enumerate(lines, 1):
            p = P.p("voice", f"l{i}.wav")
            if not os.path.exists(p): die(f"行{i} の声が無い: {p}（先に synth）")
            d = dur(p); st = float(l["start"]) if l.get("start") is not None else t
            info.append({"n": i, "start": round(st, 3), "dur": round(d, 3)}); t = st + d + gap
        end = float(V.get("end") or max(x["start"] + x["dur"] for x in info) + 0.6)
        args = ["ffmpeg", "-v", "error", "-y"]; flt = []; labs = []
        cd_ = P.p("voice", "_clean"); os.makedirs(cd_, exist_ok=True)
        for k, x in enumerate(info):
            args += ["-i", clean_tail(P.p("voice", f"l{x['n']}.wav"), os.path.join(cd_, f"l{x['n']}.wav"), x["n"])]
            flt.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=mono,loudnorm=I=-18:TP=-1.5:LRA=11,adelay={int(x['start'] * 1000)}:all=1,asetpts=N/SR/TB,apad=whole_dur={end}[a{k}]"); labs.append(f"[a{k}]")
        flt.append("".join(labs) + f"amix=inputs={len(info)}:normalize=0:duration=longest,atrim=0:{end},loudnorm=I=-16:TP=-1.5:LRA=11[out]")
        subprocess.run(args + ["-filter_complex", ";".join(flt), "-map", "[out]", "-ar", "48000", "-ac", "1", P.p("voice", "master.wav")], check=True)
        json.dump({"lines": info, "end": end}, open(P.p("voice", "timing.json"), "w"), indent=1)
        for x in info: print(f"行{x['n']}: {x['start']:.2f}s〜{x['start'] + x['dur']:.2f}s")
        print("master.wav", round(dur(P.p("voice", "master.wav")), 2), "秒"); return
    die(f"知らないコマンド: {cmd}")


if __name__ == "__main__":
    main()
