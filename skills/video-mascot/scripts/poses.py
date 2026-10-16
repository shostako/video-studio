"""マスコットの姿勢の絵・口と目の差分・中割りを /img（ChatGPT の枠、追加料金なし）で並列に描く。あるものは飛ばす。
  vm poses <作業フォルダ> poses         mascot.png から姿勢の絵 poses/pose_<名前>.png を描く（既にあれば飛ばす）
  vm poses <作業フォルダ> parts         姿勢ごとに口7形・目2段の差分 parts/<姿勢>_<m1..m7,e1,e2>.png を描く（config.gaze があれば視線 g_* も）
  vm poses <作業フォルダ> inbetweens    pairs の姿勢どうしの中割り5枚 ib/ib_<a>_<b>_<k>.png を描く
  vm poses <作業フォルダ> all           上の3つを順に
  オプション: -j N（並列数、既定4）  --dry-run（描く予定だけ出す）  --only 語（出力名にその語を含むものだけ）
使用量の上限（img の終了コード 4）が出たら止める。止まったら時間をおいて同じコマンドをもう一度（描けた分は飛ばす）。"""
import os, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, die, gaze_keys, pose_view

IMG = os.path.expanduser("~/.claude/skills/img/scripts/img.sh")
KEEP = ("Edit this exact image. Keep EVERYTHING identical to the input image: the same character, same pose, same hands, same hair, same clothes, same lighting, "
        "same camera framing, same position and size, same plain white background. Change ONLY")
M = {"m1": "the mouth: lips slightly parted with a small gap, as when speaking softly. The eyes stay exactly as they are.",
     "m2": "the mouth: half open, as when saying a short 'a' sound. The eyes stay exactly as they are.",
     "m3": "the mouth: open wide, as when saying a loud 'a' sound, inside of the mouth visible. The eyes stay exactly as they are.",
     "m4": "the mouth: a small round 'o' shape. The eyes stay exactly as they are.",
     "m5": "the mouth: lips pushed forward into a small round pout, as when saying 'u'. The eyes stay exactly as they are.",
     "m6": "the mouth: stretched wide and flat with the upper teeth slightly visible, as when saying 'i' or 'e'. The eyes stay exactly as they are.",
     "m7": ("the mouth: slightly open, a small narrow gap between the lips with only a hint of the upper teeth, as when speaking quietly; "
            "clearly LESS open than a half-open mouth. The eyes stay exactly as they are."),
     "e1": "the eyes: three-quarters closed, in the middle of a blink. The mouth stays exactly as it is.",
     "e2": "the eyes: fully closed, blinking. The mouth stays exactly as it is."}
G = {"g_l": ("the eyes: the irises and pupils moved toward the LEFT edge of the image (they sit near the corners of the eyes on the image-left side), glancing left; "
            "do not copy the eye direction of the input image. The head, face direction and mouth stay exactly as they are."),
     "g_r": ("the eyes: the irises and pupils moved toward the RIGHT edge of the image (they sit near the corners of the eyes on the image-right side), glancing right; "
            "do not copy the eye direction of the input image. The head, face direction and mouth stay exactly as they are."),
     "g_u": "the eyes: the irises and pupils moved slightly upward, as when thinking. The head, face direction and mouth stay exactly as they are.",
     "g_c": ("the eyes: the irises and pupils turned to look straight at the camera (at the viewer), while the head keeps facing the same direction as now. "
             "The mouth stays exactly as it is.")}
FR = {1: "one sixth", 2: "one third", 3: "exactly halfway", 4: "two thirds", 5: "five sixths"}


def jobs_poses(P):
    desc = P.cfg["mascot"]["description"]; base = P.p("mascot.png"); out = []
    common = (f"Same character as the reference image: {desc} Full body, centered, vertical 9:16 portrait, plain white studio background, soft studio lighting, "
              "exactly the same rendering style, face and proportions as the reference. No text, no logos.")
    for n, c in P.cfg["poses"].items():
        refs = [base] + [P.pose_path(r) for r in c.get("refs", [])]
        out.append((P.pose_path(n), f"{common} Pose: {c['desc']}", refs))
    return out


def jobs_parts(P):
    """口7形・目2段。config.gaze があれば視線の部品も（顔の向きで決まる: 正面は g_l g_r g_u、斜めは g_c g_u）。face: false の姿勢は作らない。"""
    out = []
    for n in P.poses:
        pc = P.cfg["poses"][n]; face = pc.get("face", True) is not False
        if not face: continue
        out += [(P.p("parts", f"{n}_{k}.png"), f"{KEEP} {txt}", [P.pose_path(n)]) for k, txt in M.items()]
        if "gaze" in P.cfg and P.cfg["gaze"] is not False:
            out += [(P.p("parts", f"{n}_{k}.png"), f"{KEEP} {G[k]}", [P.pose_path(n)]) for k in gaze_keys(pose_view(pc)[1], face)]
    return out


IB_HEAD = ("Same character, same face, same clothes, same lighting, same camera framing, position and size, same plain white background as both reference images, "
           "vertical 9:16, full body. ")


def jobs_ib(P):
    """中割り。div=6（既定）は両端の姿勢から k/6 の位置を描く。div を増やした細かい中割り（例 12）は、
    両隣の絵（姿勢か、描けている中割り）が揃っている枚を「両隣のちょうど中間」として描く。揃っていない枚は両端の姿勢から割合で描く。"""
    out = []; D = {n: c["desc"] for n, c in P.cfg["poses"].items()}; div = P.ib_div
    def at(a, b, k): return P.pose_path(a) if k == 0 else (P.pose_path(b) if k == div else P.ib_path(a, b, k))
    for a, b in P.pairs:
        for k in range(1, div):
            frac = FR.get(k) if div == 6 else f"{k}/{div} (about {round(100 * k / div)}%)"
            prev, nxt = at(a, b, k - 1), at(a, b, k + 1)
            if div != 6 and os.path.exists(prev) and os.path.exists(nxt):
                prompt = (IB_HEAD + f"The movement goes from {D[a]} to {D[b]}. The pose is exactly halfway between the first reference image and the second reference image: "
                          "every arm, hand and finger position is the average of the two. A natural in-between frame of the movement. Her face and expression stay the same, mouth closed.")
                refs = [prev, nxt]
            else:
                prompt = (IB_HEAD + f"The pose is {frac} of the way from the first reference image ({D[a]}) to the second reference image ({D[b]}), "
                          "a natural in-between frame of the movement. Her face and expression stay the same, mouth closed.")
                refs = [P.pose_path(a), P.pose_path(b)]
            out.append((P.ib_path(a, b, k), prompt, refs))
    return out


LIMIT = threading.Event()   # /img が使用量の上限（終了コード 4）を返した


def run_jobs(jobs, nworkers, dry, only=None):
    if only: jobs = [j for j in jobs if only in os.path.basename(j[0])]
    todo = [j for j in jobs if not os.path.exists(j[0])]
    print(f"描く {len(todo)} 枚（済み {len(jobs) - len(todo)}）")
    if dry:
        for j in todo: print("  ", os.path.relpath(j[0]))
        return True
    stop = threading.Event(); lock = threading.Lock(); done = [0]
    def run(job):
        out, prompt, refs = job
        if stop.is_set() or os.path.exists(out): return
        os.makedirs(os.path.dirname(out), exist_ok=True)
        for _ in range(2):
            cmd = [IMG, "-p", prompt] + sum([["-r", r] for r in refs], []) + ["-o", out]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=700)
            if r.returncode == 0 and os.path.exists(out): break
            if r.returncode == 4: stop.set(); LIMIT.set(); print("使用量の上限（終了コード 4）。時間をおいて、同じコマンドをもう一度", flush=True); return
            time.sleep(5)
        with lock:
            done[0] += 1; print(f"[{done[0]}/{len(todo)}] {'ok' if os.path.exists(out) else 'FAIL'} {os.path.basename(out)}", flush=True)
    with ThreadPoolExecutor(nworkers) as ex: list(ex.map(run, todo))
    miss = [j for j in todo if not os.path.exists(j[0])]
    print("終わり", len(todo) - len(miss), "/", len(todo), "（足りない分は同じコマンドを再実行）" if miss else "")
    return not miss


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("-")]
    if len(a) < 2: die("使い方: vm poses <作業フォルダ> poses|parts|inbetweens|all [-j N] [--dry-run] [--only 語]")
    P = Proj(a[0]); what = a[1]; nw = int(sys.argv[sys.argv.index("-j") + 1]) if "-j" in sys.argv else 4
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None; dry = "--dry-run" in sys.argv
    if not os.path.exists(P.p("mascot.png")) and what in ("poses", "all"): die("mascot.png（元のマスコットの絵）が無い")
    steps = {"poses": [jobs_poses], "parts": [jobs_parts], "inbetweens": [jobs_ib], "all": [jobs_poses, jobs_parts, jobs_ib]}[what]
    ok = True
    for f in steps:
        ok = run_jobs(f(P), nw, dry, only) and ok
        if not ok and not dry and f is jobs_poses: print("姿勢の絵が足りないので、続きは止める"); break
    sys.exit(0 if ok else (4 if LIMIT.is_set() else 1))   # 足りない絵があれば失敗で返す（4 は /img の使用量の上限）
