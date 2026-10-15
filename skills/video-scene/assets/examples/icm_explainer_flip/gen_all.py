"""残りの姿勢の口・目の差分と、姿勢どうしの中割りを /img で並列に描く（4並列、あるものは飛ばす、1回だけやり直す）。
  python gen_all.py [並列数]
出力: parts/<pose>_m1..m6 / e1,e2.png、ib/ib_<a>_<b>_<k>.png（k=1..5）。終了コード 4（使用量の上限）が出たら止める。"""
import os, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here); os.makedirs("ib", exist_ok=True)
IMG = os.path.expanduser("~/.claude/skills/img/scripts/img.sh"); POSES = "../hedra/poses"
BASE = {p: f"{POSES}/pose_{p}.png" for p in ("home", "point", "gap", "gassho", "open", "arms")}
DESC = {"home": "hands lightly clasped in front of her waist, facing the camera almost straight on",
        "point": "her left arm extended toward the viewer's right with an open palm, presenting",
        "open": "both hands spread apart to the sides at chest height with palms up",
        "gassho": "both palms pressed flat together in front of her chest in a prayer-like gassho gesture",
        "gap": "both palms raised vertical and facing each other with a narrow gap about one finger wide, not touching",
        "arms": "arms crossed over her chest with a smug smile"}
KEEP = ("Edit this exact image. Keep EVERYTHING identical to the input image: the same figurine, same pose, same hands, same hair, same clothes, same lighting, "
        "same camera framing, same position and size, same plain white background. Change ONLY")
M = {"m1": "the mouth: lips slightly parted with a small gap, as when speaking softly. The eyes stay exactly as they are.",
     "m2": "the mouth: half open, as when saying a short 'a' sound. The eyes stay exactly as they are.",
     "m3": "the mouth: open wide, as when saying a loud 'a' sound, inside of the mouth visible. The eyes stay exactly as they are.",
     "m4": "the mouth: a small round 'o' shape. The eyes stay exactly as they are.",
     "m5": "the mouth: lips pushed forward into a small round pout, as when saying 'u'. The eyes stay exactly as they are.",
     "m6": "the mouth: stretched wide and flat with the upper teeth slightly visible, as when saying 'i' or 'e'. The eyes stay exactly as they are.",
     "e1": "the eyes: three-quarters closed, in the middle of a blink. The mouth stays exactly as it is.",
     "e2": "the eyes: fully closed, blinking. The mouth stays exactly as it is."}
PAIRS = [("home", "point"), ("home", "open"), ("open", "gassho"), ("gassho", "gap"), ("gap", "point"), ("home", "arms")]
FR = {1: "one sixth", 2: "one third", 3: "exactly halfway", 4: "two thirds", 5: "five sixths"}
jobs = []
for p in ("gap", "gassho", "open", "arms"):
    for k, txt in M.items(): jobs.append((f"parts/{p}_{k}.png", f"{KEEP} {txt}", [BASE[p]]))
for a, b in PAIRS:
    for k in range(1, 6):
        jobs.append((f"ib/ib_{a}_{b}_{k}.png",
                     "Same figurine, same face, same clothes, same lighting, same camera framing, position and size, same plain white background as both reference images, "
                     f"vertical 9:16, full body on the clear display base. The pose is {FR[k]} of the way from the first reference image ({DESC[a]}) to the second reference image "
                     f"({DESC[b]}), a natural in-between frame of the movement. Her face and expression stay the same, mouth closed.", [BASE[a], BASE[b]]))
stop = threading.Event(); lock = threading.Lock(); done = [0]
def run(job):
    out, prompt, refs = job
    if os.path.exists(out) or stop.is_set(): return
    for attempt in range(2):
        cmd = [IMG, "-p", prompt] + sum([["-r", r] for r in refs], []) + ["-o", out]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=700)
        if r.returncode == 0 and os.path.exists(out): break
        if r.returncode == 4: stop.set(); print("使用量の上限（終了コード 4）、止める", flush=True); return
        time.sleep(5)
    with lock:
        done[0] += 1; print(f"[{done[0]}/{len(jobs)}] {'ok' if os.path.exists(out) else 'FAIL'} {out}", flush=True)
n = int(sys.argv[1]) if len(sys.argv) > 1 else 4
with ThreadPoolExecutor(n) as ex: list(ex.map(run, jobs))
print("終わり", sum(os.path.exists(j[0]) for j in jobs), "/", len(jobs))
