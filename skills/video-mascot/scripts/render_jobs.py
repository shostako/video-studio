"""vm render --jobs N: 書き出す範囲を短い区間に分けて並列に書き出し、1 本につなぐ。
各区間は render.py を別のプロセスで動かす（コマの中身は時刻だけで決まり、前のコマに頼らない）。
区間の切れ目は圧縮の切れ目になるだけで、絵は変わらない。つなぎはコピーなので圧縮し直さない。"""
import json, math, os, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

from lib import die

HERE = os.path.dirname(os.path.realpath(__file__))
MIN_CHUNK, MAX_CHUNK = 5.0, 30.0   # 区間の秒。短いと起動の分が無駄になり、長いと切り替えの多い区間に引きずられる
VALUE_FLAGS = ("--jobs", "--from", "--to", "--out", "--crop")


def plan_chunks(f0, f1, jobs, fps):
    """コマの範囲 [f0, f1) を区間 [(a, b), ...] に分ける。worker より多く分けて、重い区間に引きずられにくくする。"""
    if f1 <= f0: return []
    secs = (f1 - f0) / fps
    n = max(1, round(secs / min(MAX_CHUNK, max(MIN_CHUNK, secs / (jobs * 2)))))
    cuts = [f0 + (f1 - f0) * i // n for i in range(n + 1)]
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]


def frame_times(a, b, fps):
    """render.py の int(T0 * fps) と ceil(T1 * fps) が a と b に戻る秒。コマの中央の時刻なら小数の丸めで隣へずれない。"""
    return (a + 0.5) / fps, (b - 0.5) / fps


def child_args(argv, t0, t1, out, crop=None, video_only=False):
    """親の引数から区間の引数を作る。範囲・出力・並列・切り抜きは差し替え、検査の --strict は親が見る。
    video_only: 白地の区間に声を付けない（区間ごとの声は秒の丸めで短く、-shortest がコマを落とす）。"""
    args = []; it = iter(argv)
    for x in it:
        if x in VALUE_FLAGS: next(it, None); continue
        if x == "--strict": continue
        args.append(x)
    args += ["--from", f"{t0:.6f}", "--to", f"{t1:.6f}", "--out", out]
    if crop: args += ["--crop", crop]
    if video_only: args.append("--video-only")
    return args


def merged_check(precheck, out):
    """下見の検査の結果を、書き出した動画の検査の結果にする（時間割の計算は同じなので区間ごとに集めない）。"""
    d = dict(precheck); d["video"] = os.path.abspath(out); d.pop("cache_todo", None); return d


def must_run_serial(precheck):
    """Wan・RIFE の列を新しく作るときは並列にしない。同じ列を複数の区間が同時に作ると、作業の置き場を消し合う。"""
    return bool(precheck.get("cache_todo"))


def without_jobs(argv):
    args = []; it = iter(argv)
    for x in it:
        if x == "--jobs": next(it, None); continue
        args.append(x)
    return args


def concat_list(paths):
    return "".join("file '" + p.replace("'", "'\\''") + "'\n" for p in paths)


def _run(cmd, env, log):
    with open(log, "w", encoding="utf-8") as f:
        return subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT).returncode


def _tail(log, n=8):
    try: return "".join(open(log, encoding="utf-8", errors="replace").readlines()[-n:])
    except OSError: return ""


def frame_count(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v", "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path], capture_output=True, text=True)
    try: return int(r.stdout.strip().split(",")[0])
    except ValueError: return -1


COMPOSE_FPS = 30   # compose.py の FPS
COMPOSE_TAIL = 0.8  # compose.py の END = timing["end"] + 0.8


def compose_frames(end):
    """compose.py が書くコマ数（range(int(from * FPS), int(to * FPS))）。"""
    return int((end + COMPOSE_TAIL) * COMPOSE_FPS)


def compose_times(a, b):
    """compose.py の int(t * FPS) が a と b に戻る秒。"""
    return (a + 0.5) / COMPOSE_FPS, (b + 0.5) / COMPOSE_FPS


def run_compose(cmd, out, jobs, voice_dir):
    """screen-explainer の compose.py（cmd は --out より前まで）を区間に分けて並列に動かし、つないで声を 1 回だけ付ける。"""
    timing = json.load(open(os.path.join(voice_dir, "voice", "timing.json")))
    n = compose_frames(timing["end"]); end = n / COMPOSE_FPS
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=os.path.splitext(os.path.basename(out))[0] + "_jobs_", dir=os.path.dirname(os.path.abspath(out)))
    try:
        chunks = plan_chunks(0, n, jobs, COMPOSE_FPS)
        def one(i):
            a, b = chunks[i]; ta, tb = compose_times(a, b); p = os.path.join(tmp, f"c{i:04d}.mp4"); log = os.path.join(tmp, f"c{i:04d}.log")
            rc_ = _run(cmd + ["--out", p, "--from", f"{ta:.6f}", "--to", f"{tb:.6f}", "--video-only"], dict(os.environ), log)
            if rc_ != 0: raise RuntimeError(f"組み立ての区間 {a / COMPOSE_FPS:.2f}〜{b / COMPOSE_FPS:.2f} 秒で止まった（終了コード {rc_}）:\n" + _tail(log))
            return p
        with ThreadPoolExecutor(jobs) as ex:
            try: parts = list(ex.map(one, range(len(chunks))))
            except RuntimeError as e: die(str(e))
        lst = os.path.join(tmp, "list.txt"); open(lst, "w", encoding="utf-8").write(concat_list(parts))
        joined = os.path.join(tmp, "joined.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v", "-c", "copy", joined], check=True)
        got = frame_count(joined)
        if got != n: die(f"組み立てのコマ数が合わない: {got}（{n} のはず）")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", joined, "-i", os.path.join(voice_dir, "voice", "master.wav"), "-map", "0:v", "-map", "1:a", "-af", "apad",
                        "-t", f"{end:.3f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", "-f", "mp4", out + ".part"], check=True)
        os.replace(out + ".part", out)
        shutil.copy(os.path.splitext(parts[0])[0] + ".layout.json", os.path.splitext(out)[0] + ".layout.json")
        print("out", out, f"{end:.1f}s", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(argv, jobs, f0, f1, fps, mode, out, crop, voice, t0, t1):
    """argv は render.py の引数（作業フォルダから）。終了コードで終わる。"""
    render = os.path.join(HERE, "render.py"); py = [sys.executable, "-B", render]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    ext = os.path.splitext(out)[1] or (".webm" if mode == "alpha" else ".mp4")
    tmp = tempfile.mkdtemp(prefix=os.path.splitext(os.path.basename(out))[0] + "_jobs_", dir=os.path.dirname(os.path.abspath(out)))
    env = dict(os.environ, OPENCV_NUM_THREADS="1", OMP_NUM_THREADS="1")   # 並列は区間で取る。中でも広げると CPU を取り合う
    try:
        pre_out = os.path.splitext(out)[0] + ext
        rc = subprocess.run(py + [a for a in child_args(argv, t0, t1, pre_out, crop if crop != "face" else None)] + ["--check-only"]).returncode
        if rc != 0: die(f"下見で止まった（終了コード {rc}）", rc)
        pref = os.path.splitext(pre_out)[0] + ".precheck.json"; pre = json.load(open(pref, encoding="utf-8"))
        if must_run_serial(pre):
            print(f"作り置きを新しく作る分（{len(pre['cache_todo'])} 件）があるので、今回は 1 本で書き出す。作り置きができた次からは並列になる", file=sys.stderr, flush=True)
            sys.exit(subprocess.run(py + without_jobs(argv)).returncode)
        box = crop
        if crop == "face":                 # 枠は最初のコマで 1 回だけ決める。区間ごとに測るとつないだ所でずれる
            head = os.path.join(tmp, "head" + ext); a_, b_ = frame_times(f0, f0 + 1, fps)
            log = os.path.join(tmp, "head.log")
            if _run(py + child_args(argv, a_, b_, head, "face", video_only=mode != "alpha"), env, log) != 0: die("切り抜く枠を決められない:\n" + _tail(log))
            box = ",".join(map(str, json.load(open(os.path.splitext(head)[0] + ".crop.json"))["box"]))
        chunks = plan_chunks(f0, f1, jobs, fps); parts = []
        print(f"{len(chunks)} 区間を {jobs} 並列で書き出す（{(f1 - f0) / fps:.1f} 秒）", file=sys.stderr, flush=True)
        def one(i):
            a, b = chunks[i]; ta, tb = frame_times(a, b, fps); p = os.path.join(tmp, f"c{i:04d}{ext}"); log = os.path.join(tmp, f"c{i:04d}.log")
            rc_ = _run(py + child_args(argv, ta, tb, p, box, video_only=mode != "alpha"), env, log)
            if rc_ != 0: raise RuntimeError(f"区間 {a / fps:.2f}〜{b / fps:.2f} 秒で止まった（終了コード {rc_}）:\n" + _tail(log))
            print(f"  区間 {i + 1}/{len(chunks)} 済み", file=sys.stderr, flush=True); return p
        with ThreadPoolExecutor(jobs) as ex:
            try: parts = list(ex.map(one, range(len(chunks))))
            except RuntimeError as e: die(str(e))
        lst = os.path.join(tmp, "list.txt"); open(lst, "w", encoding="utf-8").write(concat_list(parts))
        joined = os.path.join(tmp, "joined" + ext)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v", "-c", "copy", joined], check=True)
        n = frame_count(joined)
        if n != f1 - f0: die(f"つないだ動画のコマ数が合わない: {n}（{f1 - f0} のはず）")
        if mode == "alpha": shutil.move(joined, out)
        else: subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", joined, "-ss", f"{t0}", "-t", f"{t1 - t0}", "-i", voice, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out], check=True)
        if crop:
            first = next(os.path.splitext(p)[0] + ".crop.json" for p in parts); c = json.load(open(first)); c["from"] = t0
            json.dump(c, open(os.path.splitext(out)[0] + ".crop.json", "w"))
        chk = merged_check(pre, out); json.dump(chk, open(os.path.splitext(out)[0] + ".check.json", "w"), ensure_ascii=False, indent=1)
        print(out)
        if chk.get("problems") and "--strict" in argv: die(f"切り替えの検査・口の検査で問題が {chk['problems']} 件（{os.path.splitext(out)[0]}.check.json）", 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
