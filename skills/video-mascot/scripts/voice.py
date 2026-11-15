"""台詞から声を作る（Irodori-TTS、手元で動く、無料）。
  vm voice <作業フォルダ> check                   Irodori が使えるか確かめる
  vm voice <作業フォルダ> candidates              config.voice.candidates の声の説明文ごとに、試し2行を読ませる → voice/cand/ に wav と聞き比べの1本
  vm voice <作業フォルダ> synth [行番号 ...]       全行（か指定の行）を読ませて voice/l<N>.wav を作る。聞き取りで台本との一致も出す。全行のときは master も作り、語の時刻（書き出しが使う）も残す
  vm voice <作業フォルダ> master                  各行を開始時刻に置いて voice/master.wav と voice/timing.json を作る
  vm voice <作業フォルダ> lint [行番号 ...] [--all]  say の書き方を字幕と比べる（声は作らない）。漢字を仮名に開いた所・字幕に無い読点を出す（say_lint.py）
  vm voice <作業フォルダ> reading [行番号 ...]     作った声を音素で書き起こし、字幕の読みと比べる（reading_check.py）。voice/phones.json に音素と時刻を残す
  vm voice <作業フォルダ> accent [行番号 ...] [--all] [--clips 出力.mp3] [--top N]  声の高さを字幕の読みの高低と比べる（accent_check.py）。既定は say で仮名に開いた語だけ（--all で全部の語）。--clips で警告の語を切り出した聞き取り用の音声（上位 N 件、既定 20）
  vm voice <作業フォルダ> retry [行番号 ...] [--n 本数] [--no-kanji] [--clips 出力.mp3]  読みの「!」か、仮名に開いた語の高さの「!」がある行だけ、seed を替えた候補を本数（既定 4）作り、
                                                警告がいちばん少ない声を l<N>.wav にする（同じ数なら元を残す。候補と元の声は voice/retry/。master は作り直さない。voice_retry.py）。
                                                高さの警告の語を say で仮名に開いていれば、そこを漢字に戻した say の候補も同じ本数作る（--no-kanji で作らない）
config.voice: {caption, seed, ref(手本の wav、あれば全行をこの声で), lines:[{text, say(合成に渡す文。漢字を読み違えるならひらがなを混ぜる), start(秒、省略可), seed(その行だけの seed、省略可。retry で選んだ声を残すとき)}], gap(行の間、既定0.5), candidates:[説明文...],
              terms(lint で使う作業フォルダの用語辞書。video-scene の data/terms.yaml と同じ形、省略可)}
声の設計は説明文（caption）で行い、気に入った1本を ref にして全行を同じ声にそろえる。"""
import difflib, json, os, re, subprocess, sys, tempfile
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


HERE = os.path.dirname(os.path.realpath(__file__))
SCENE_SCRIPTS = os.path.join(HERE, "..", "..", "video-scene", "scripts")
HEAR_CODE = """
import json, sys
sys.path.insert(0, sys.argv[1])
from common import read_audio
from faster_whisper import WhisperModel
m = WhisperModel('medium', device='cpu', compute_type='int8')
for path in sys.argv[2:]:
    s, _ = m.transcribe(read_audio(path), language='ja', vad_filter=False, condition_on_previous_text=False)
    print(json.dumps(''.join(x.text for x in s)), flush=True)
"""


def hear_all(paths):
    """声のファイルを順に聞き取って、1 件ずつ文字を返す。モデルを読むのは 1 回（行ごとに読むと、読むだけで 1 行数秒かかる）。
    聞き取りは確認なので、失敗しても声は残す。読めなかった分は "" を返して、理由をログに出す。"""
    with tempfile.TemporaryFile() as err:    # 終わるまで読まないので、パイプにしない（溢れると相手が止まる）
        p = subprocess.Popen([WS, "-c", HEAR_CODE, SCENE_SCRIPTS, *paths], stdout=subprocess.PIPE, stderr=err, text=True, encoding="utf-8", errors="replace",
                             env=dict(os.environ, PYTHONUTF8="1"))
        got = 0
        for line in p.stdout:
            try: text = json.loads(line)
            except ValueError: continue    # ライブラリが標準出力に書いた行
            if not isinstance(text, str): continue
            got += 1; yield text
        p.wait()
        if got < len(paths):
            err.seek(0); tail = err.read().decode("utf-8", "replace").strip().splitlines()[-3:]
            print(f"聞き取りが {len(paths) - got} 件できなかった（声はできている）: " + " / ".join(tail), flush=True)
    for _ in range(len(paths) - got): yield ""


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


def build_master(P, V, lines, gap):
    """各行を開始時刻に置いて master.wav と timing.json を作り、行の時刻を返す。中身が同じなら master.wav を書き換えない
    （更新時刻が変わらなければ、聞き取り済みの語の時刻 master.words.json がそのまま使える）。"""
    t = 0.0; info = []
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
    out = P.p("voice", "master.wav"); tmp = P.p("voice", "master.part.wav")
    subprocess.run(args + ["-filter_complex", ";".join(flt), "-map", "[out]", "-ar", "48000", "-ac", "1", tmp], check=True)
    if same_bytes(tmp, out): os.remove(tmp)
    else: os.replace(tmp, out)
    json.dump({"lines": info, "end": end}, open(P.p("voice", "timing.json"), "w"), indent=1)
    return info


def same_bytes(a, b):
    if not os.path.exists(b) or os.path.getsize(a) != os.path.getsize(b): return False
    with open(a, "rb") as f, open(b, "rb") as g: return f.read() == g.read()


def heard_by_line(words, info, margin=0.3):
    """全体の語の時刻 [[語, 始め, 終わり], ...] を行ごとの文字に分ける。行の間の無音に出た語はどの行にも入れない。"""
    out = {x["n"]: "" for x in info}
    for w, s, e in words:
        mid = (s + e) / 2
        for x in info:
            if x["start"] - margin <= mid <= x["start"] + x["dur"] + margin: out[x["n"]] += w; break
    return out


def hear_master(P):
    """master.wav を 1 回聞いて master.words.json を作り、語の時刻を返す。書き出し（render.py）が同じものを読むので、聞き取りが 2 回にならない。
    聞き取りは確認なので、失敗しても声は残す（None を返して理由を出す。語の時刻は書き出しのときに作り直される）。"""
    wav = P.p("voice", "master.wav"); out = P.p("voice", "master.words.json")
    with tempfile.TemporaryFile() as err:
        r = subprocess.run([WS, os.path.join(HERE, "words.py"), wav, out], stdout=subprocess.DEVNULL, stderr=err, env=dict(os.environ, PYTHONUTF8="1"))
        if r.returncode != 0:
            err.seek(0); print("聞き取りができなかった（声はできている）: " + " / ".join(err.read().decode("utf-8", "replace").strip().splitlines()[-3:]), flush=True)
            return None
    return json.load(open(out, encoding="utf-8"))


LOW_MATCH = 0.9


def reading_match(script, heard):
    """台本と聞き取りの一致。かなに直して比べる（「一人」と「1人」、「試して」と「ためして」のような書き方の違いでは下げない）。"""
    import pykakasi
    from lib import num_to_kanji
    kk = pykakasi.kakasi()
    kana = lambda t: re.sub(r"[^ぁ-ゖa-z0-9]", "", "".join(x["hira"] for x in kk.convert(num_to_kanji(t))).lower())    # かなにならない英字は残す（消すと ICM が抜けても気づかない）
    return difflib.SequenceMatcher(None, kana(script), kana(heard)).ratio()


def report_match(P, lines, only, V, gap):
    """作った声を聞き取って、台本との一致を出す。全行を作ったときは、つないだ声を 1 回だけ聞く（行ごとに聞くより速く、書き出しでもう一度聞かずに済む）。"""
    if len(only) == len(lines):
        info = build_master(P, V, lines, gap); words = hear_master(P)
        if words is None: return
        by_line = heard_by_line(words, info)
        heard_list = [by_line[n] for n in only]
    else: heard_list = hear_all([P.p("voice", f"l{n}.wav") for n in only])
    for n, heard in zip(only, heard_list):
        r = reading_match(lines[n - 1]["text"], heard)
        print(f"行{n} 台本との一致 {r:.2f}: {heard}", flush=True)
        if r < LOW_MATCH: print(f"  行{n} は読みが崩れているかもしれない。聴いて確かめ、崩れていれば、その言葉をかなで書いた文を voice.lines の say に入れる", flush=True)


def line_seed(V, line):
    """行の seed。行に seed があればそれ（vm voice retry で選んだ声を synth でも作れるように）、無ければ voice.seed。"""
    return int(line.get("seed", V.get("seed", 1234)))


def line_phones(P, ns, again=False):
    """行番号 → 声の音素と時刻。voice/phones.json に {行番号: {phones, md5}} で控える。中身が同じ（md5 が同じ）声は控えを使う。
    again なら控えがあっても聞き直す。"""
    import phonemes, voice_retry as VR
    paths = {n: P.p("voice", f"l{n}.wav") for n in ns}
    miss = [p_ for p_ in paths.values() if not os.path.exists(p_)]
    if miss: die(f"声が無い: {miss[0]}（先に synth）")
    pj = P.p("voice", "phones.json"); old = json.load(open(pj, encoding="utf-8")) if os.path.exists(pj) else {}
    md5 = {n: VR.md5(paths[n]) for n in ns}
    need = [n for n in ns if again or old.get(str(n), {}).get("md5") != md5[n]]
    if need:
        try: res = phonemes.hear([paths[n] for n in need])
        except RuntimeError as x: die(str(x))
        for n, r in zip(need, res): old[str(n)] = {"phones": r["phones"], "md5": md5[n]}
        json.dump(old, open(pj, "w", encoding="utf-8"), ensure_ascii=False)
    return {n: old[str(n)]["phones"] for n in ns}


def retry(P, V, lines, args):
    """vm voice retry: 読み・高さの警告が出た行だけ、seed を替えた候補を作り、警告のいちばん少ない声を l<N>.wav にする（voice_retry.py）。"""
    import shutil, say_lint, ojt, phonemes, accent_check, voice_retry as VR
    if V.get("engine") == "voicevox": die("retry は Irodori の声だけ（VOICEVOX は同じ文から同じ声しか作らない）")
    if not ojt.available(): die("pyopenjtalk-plus が無い（字幕の読みの見本に使う）。video-scene の setup.sh を VS_ACCENT_CHECK=1 で流して入れる")
    try: terms = say_lint.load_all_terms(V.get("terms"), P.root)
    except (ValueError, OSError) as x: die(f"用語辞書が読めない: {x}")
    rest = list(args); n_cand, clips = 4, None
    plain = "--no-kanji" in rest; rest = [x for x in rest if x != "--no-kanji"]
    if "--n" in rest: k = rest.index("--n"); n_cand = int(rest[k + 1]); del rest[k:k + 2]
    if "--clips" in rest: k = rest.index("--clips"); clips = rest[k + 1]; del rest[k:k + 2]
    if n_cand < 1: die("--n は 1 以上")
    only = [int(x) for x in rest] or list(range(1, len(lines) + 1))
    wav = lambda n: P.p("voice", f"l{n}.wav")
    phones = line_phones(P, only)
    now = {n: VR.warnings(lines[n - 1], phones[n], wav(n), terms) for n in only}
    targets = [n for n in only if now[n]]
    print(f"警告のある行: {len(targets)} 行（{len(only)} 行のうち）" + (f" → {', '.join(map(str, targets))}" if targets else ""), flush=True)
    rd = P.p("voice", "retry"); os.makedirs(rd, exist_ok=True)
    gref = V.get("ref"); gref = P.p(gref) if gref and not os.path.isabs(gref) else gref
    cand = {}; jobs = []; also = {}
    for n in targets:
        ref = gref    # synth <N> と同じ手本（voice.ref、無ければ作り直さない行のうち最初の行の声）
        if ref is None:
            k = partial_voice_ref([n], len(lines), lambda m: os.path.exists(wav(m)))
            ref = wav(k) if k is not None else None
        l = lines[n - 1]; say0 = l.get("say", l["text"])
        hit = sorted({w["word"] for w in now[n] if w["kind"] == "accent"}); also[n] = set(hit)
        ks = VR.kanji_say(l.get("text", ""), l.get("say"), hit, terms) if hit and not plain else None
        cand[n] = []
        for say in ([ks] if ks else []) + [say0]:    # 漢字に戻した say を先に試す（同じ数なら漢字の方を選ぶ）
            for s in VR.seeds(line_seed(V, l), n_cand):
                j = {"text": say, "caption": V["caption"], "seed": s, "ref": ref, "duration_scale": V.get("duration_scale", 1.0)}
                o = os.path.join(rd, f"l{n}_s{s}_{VR.job_key(j)}.wav")    # 名前に入力の鍵。say・手本などを変えれば別の候補になる
                cand[n].append(((s, None if say == say0 else say), o))
                if not os.path.exists(o): jobs.append(dict(j, out=o))    # 同じ入力の作り置きは作り直さない
    if jobs:
        print(f"候補を作る: {len(jobs)} 本", flush=True); run_irodori(jobs, rd)
    # 候補の音素も控える（中身が同じなら聞き直さない）
    cj = os.path.join(rd, "phones.json"); cp = json.load(open(cj, encoding="utf-8")) if os.path.exists(cj) else {}
    allc = [o for n in targets for _, o in cand[n]]; cm = {o: VR.md5(o) for o in allc}
    need = [o for o in allc if cp.get(os.path.basename(o), {}).get("md5") != cm[o]]
    if need:
        try: res = phonemes.hear(need)
        except RuntimeError as x: die(str(x))
        for o, r in zip(need, res): cp[os.path.basename(o)] = {"phones": r["phones"], "md5": cm[o]}
        json.dump(cp, open(cj, "w", encoding="utf-8"), ensure_ascii=False)
    changed = []
    for n in targets:
        sc = [(c, VR.warnings(lines[n - 1] if c[1] is None else dict(lines[n - 1], say=c[1]), cp[os.path.basename(o)]["phones"], o, terms, also[n]))
              for c, o in cand[n]]
        same = VR.stuck(now[n], [w for _, w in sc])    # 元にもどの候補にも出た警告
        pick = VR.choose(len(now[n]), [(s, len(w)) for s, w in sc])
        name = lambda c: f"{'漢字に戻した say・' if c[1] else ''}seed {c[0]}"
        tally = "、".join(f"{name(c)}: {len(w)}" for c, w in sc)
        if pick is None:
            print(f"行{n}: 元の声を残す（元 {len(now[n])} 件、{tally}）", flush=True)
            for w in now[n]: w["stuck"] = VR.key(w) in same
            continue
        o = dict(cand[n])[pick]; keep = os.path.join(rd, f"l{n}_was_{VR.md5(wav(n))[:8]}.wav")
        if not os.path.exists(keep): shutil.copy2(wav(n), keep)    # 差し替える前の声を残す（名前は中身の md5）
        print(f"行{n}: {name(pick)} の声にした（元 {len(now[n])} 件 → {len(dict(sc)[pick])} 件。{tally}。元の声は {os.path.relpath(keep, P.root)}）", flush=True)
        shutil.copy2(o, wav(n)); now[n] = dict(sc)[pick]; changed.append((n, pick))
        for w in now[n]: w["stuck"] = VR.key(w) in same
        pj = P.p("voice", "phones.json"); old = json.load(open(pj, encoding="utf-8")) if os.path.exists(pj) else {}
        old[str(n)] = {"phones": cp[os.path.basename(o)]["phones"], "md5": cm[o]}    # 差し替えた声の書き起こし（次の reading・accent で使い回す）
        json.dump(old, open(pj, "w", encoding="utf-8"), ensure_ascii=False)
    left = [dict(w, line=n) for n in targets for w in now[n]]
    for w in left:
        t = "" if w["t"] is None else f"{w['t']:.2f} 秒、"
        tag = "。どの候補にも出た" if w.get("stuck") else ""
        print(f"! 行{w['line']}: {w['word']}（{'読み' if w['kind'] == 'reading' else '高さ'}。{t}{w['why']}{tag}）", flush=True)
    k = sum(bool(w.get("stuck")) for w in left)
    print(f"作り直し: {len(changed)} 行を差し替え、残った警告 {len(left)} 件（{len(targets)} 行、候補は各 {n_cand} 本、{os.path.relpath(rd, P.root)}/）", flush=True)
    if k:
        print(f"  {k} 件は元の声にもどの候補にも出た。seed を替えても直らないので、say の書き方か用語辞書で直すか、見本の読み違い"
              "（描く→えがく など）か書き起こしの誤りを疑う", flush=True)
    if changed:
        print("  master は作り直していない。聴いて決めたら vm voice <作業フォルダ> master。"
              "synth でその行を作り直すと元に戻るので、残すなら config の voice.lines のその行に seed（と say）を書く: "
              + "、".join(f"行{n} seed {c[0]}" + (f" say「{c[1]}」" if c[1] else "") for n, c in changed), flush=True)
    if clips and left:
        accent_check.make_clips(left, wav, clips, lambda n: lines[n - 1]["text"])
        print(f"聞き取り: {clips}（一覧 {os.path.splitext(clips)[0]}.md、{sum(w['t'] is not None for w in left)} か所）", flush=True)


def main():
    a = [x for x in sys.argv[1:]]
    if len(a) < 2: die("使い方: vm voice <作業フォルダ> check|candidates|synth|master|lint|reading|accent|retry")
    P = Proj(a[0]); cmd = a[1]; V = P.cfg["voice"]; vd = P.p("voice"); os.makedirs(vd, exist_ok=True)
    lines = V["lines"]; gap = float(V.get("gap", 0.5))
    if cmd == "lint":
        import say_lint
        args = [x for x in a[2:] if x != "--all"]
        only = {int(x) for x in args} or None
        try: terms = say_lint.load_all_terms(V.get("terms"), P.root)
        except (ValueError, OSError) as x: die(f"用語辞書が読めない: {x}")
        say_lint.report(say_lint.lint_lines(lines, only, terms), show_all="--all" in a[2:]); return
    if cmd == "retry": return retry(P, V, lines, a[2:])
    if cmd in ("reading", "accent"):
        import reading_check, say_lint, ojt
        if not ojt.available(): die("pyopenjtalk-plus が無い（字幕の読みの見本に使う）。video-scene の setup.sh を VS_ACCENT_CHECK=1 で流して入れる")
        try: terms = say_lint.load_all_terms(V.get("terms"), P.root)
        except (ValueError, OSError) as x: die(f"用語辞書が読めない: {x}")
        rest = list(a[2:]); clips = top = None; show_all = "--all" in rest
        rest = [x for x in rest if x != "--all"]
        if "--clips" in rest: k = rest.index("--clips"); clips = rest[k + 1]; del rest[k:k + 2]
        if "--top" in rest: k = rest.index("--top"); top = int(rest[k + 1]); del rest[k:k + 2]
        only = [int(x) for x in rest] or list(range(1, len(lines) + 1))
        phones = line_phones(P, only, again=(cmd == "reading"))    # reading は毎回聞き直す。accent は中身が同じ声なら控えを使う
        if cmd == "reading": reading_check.report(lines, phones, terms); return
        import accent_check
        found = accent_check.report(lines, phones, lambda n: P.p("voice", f"l{n}.wav"), terms, show_all=show_all)
        if clips and found:
            accent_check.make_clips(found[:top or 20], lambda n: P.p("voice", f"l{n}.wav"), clips, lambda n: lines[n - 1]["text"])
            print(f"聞き取り: {clips}（一覧 {os.path.splitext(clips)[0]}.md、{min(len(found), top or 20)} か所）", flush=True)
        return
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
    if cmd == "synth" and V.get("engine") == "voicevox":
        import voice_voicevox
        only = [int(x) for x in a[2:]] or list(range(1, len(lines) + 1))
        voice_voicevox.synth_jobs([{"text": lines[n - 1].get("say", lines[n - 1]["text"]), "out": P.p("voice", f"l{n}.wav")} for n in only], V)
        report_match(P, lines, only, V, gap)
        return
    if cmd == "synth":
        only = [int(x) for x in a[2:]] or list(range(1, len(lines) + 1)); ref = V.get("ref"); ref = P.p(ref) if ref and not os.path.isabs(ref) else ref
        if ref is None:    # 一部の行だけ作り直すときは、残す行の声を手本にする（手本なしで作ると別の声になる）
            k = partial_voice_ref(only, len(lines), lambda n: os.path.exists(P.p("voice", f"l{n}.wav")))
            if k is not None: ref = P.p("voice", f"l{k}.wav"); print(f"手本: 行{k} の声", flush=True)
        jobs = [{"text": lines[n - 1].get("say", lines[n - 1]["text"]), "caption": V["caption"], "seed": line_seed(V, lines[n - 1]), "ref": ref,
                 "duration_scale": V.get("duration_scale", 1.0), "out": P.p("voice", f"l{n}.wav")} for n in only]
        if ref is None:    # 手本が無ければ、最初に作った行を手本にして残りをそろえる
            run_irodori(jobs[:1], vd); r0 = jobs[0]["out"]
            for j in jobs[1:]: j["ref"] = r0
            run_irodori(jobs[1:], vd)
        else: run_irodori(jobs, vd)
        report_match(P, lines, only, V, gap)
        return
    if cmd == "master":
        info = build_master(P, V, lines, gap)
        for x in info: print(f"行{x['n']}: {x['start']:.2f}s〜{x['start'] + x['dur']:.2f}s")
        print("master.wav", round(dur(P.p("voice", "master.wav")), 2), "秒"); return
    die(f"知らないコマンド: {cmd}")


if __name__ == "__main__":
    main()
