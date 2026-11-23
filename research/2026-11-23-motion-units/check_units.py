"""動きの部品を登録する前の検査（2026-11-23）。部品ごとに、作り置きの Wan の列（home→X、X→home の n47）を見る。
  動きの量 : コマ間の平均の差。止まる続き（差 0.3 未満が 3 コマ以上）が無いこと
  目の閉じ : 目を閉じたコマ（wanflf.blink_frames と同じ照合、tol は config.interp.wan.blink_tol か 0.05）が無いこと
  着地     : 列の最後のコマと着く姿勢の絵の差（平均の絶対差）が 3 未満、背景（四隅）の明るさの差が 2 未満
  顔の位置 : 顔の合わせ（ECC）の合いが 0.85 以上で、1 コマ間に顔が 3 px より跳ばないこと
rife: true の部品（会釈など、描いた 2 枚の間を RIFE で直に補間する組）は Wan の列が無いので検査しない。
使い方: python check_units.py <パック> units.json   → 表と、units.checked.json（部品ごとの合否と数字）"""
import sys, os, glob, json, cv2, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../skills/video-mascot/scripts"))
from lib import Proj  # noqa: E402
from wanflf import eye_patches, blink_frames, bg_level  # noqa: E402

PK, UF = sys.argv[1], sys.argv[2]
P = Proj(PK); U = json.load(open(UF)); base = U["base"]
TOL = (P.cfg.get("interp", {}).get("wan", {}) or {}).get("blink_tol", 0.05)
pj = json.load(open(P.p(f"parts_{base}", "parts.json"))); m1 = cv2.imread(P.p(f"parts_{base}", "m1.png"), -1)
mx, my = pj["m1"][0] + m1.shape[1] // 2, pj["m1"][1] + m1.shape[0] // 2
ROI = (mx - 150, my - 200, mx + 150, my + 120)


def frames(a, b):
    fs = sorted(glob.glob(P.p("ib_wan", f"{a}__{b}", "n47", "f*.webp")), key=lambda s: int(os.path.basename(s)[1:-5]))
    return [cv2.imread(f) for f in fs]


def ecc(src, dst):
    x0, y0, x1, y1 = ROI
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = np.zeros(g0.shape, np.uint8); m[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1.0
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5), m, 5)
    except cv2.error: pass
    A = cv2.invertAffineTransform(M); return float(cc), A @ np.array([mx, my, 1.0])


def check_pair(a, b):
    fr = frames(a, b)
    if not fr: return {"ok": False, "why": f"作り置きが無い: ib_wan/{a}__{b}/n47"}
    pa, pb = P.read_pose(a), P.read_pose(b)
    seq = [pa] + fr + [pb]
    d = [float(np.abs(seq[i + 1].astype(np.int16) - seq[i].astype(np.int16)).mean()) for i in range(len(seq) - 1)]
    run = best = 0
    for v in d[2:-2]:                                   # 端の緩やかな出入り（smoothstep）は止まって当然なので除く
        run = run + 1 if v < 0.3 else 0; best = max(best, run)
    pats = [x for x in (eye_patches(P, a, (fr[0].shape[1], fr[0].shape[0])), eye_patches(P, b, (fr[0].shape[1], fr[0].shape[0]))) if x]
    bl = blink_frames(seq, pats, TOL)
    land = float(np.abs(fr[-1].astype(np.int16) - pb.astype(np.int16)).mean()); bg = abs(bg_level(fr[-1]) - bg_level(pb))
    ccs, pos = [], []
    for im in fr:
        c, p = ecc(pa, im); ccs.append(c); pos.append(p)
    jump = float(max(np.linalg.norm(pos[i + 1] - pos[i]) for i in range(len(pos) - 1)))
    r = {"motion_mean": round(float(np.mean(d)), 2), "still_run": best, "blink": bl, "land": round(land, 2), "bg": round(bg, 2),
         "cc_min": round(min(ccs), 3), "face_jump": round(jump, 2)}
    why = []
    if best >= 3: why.append(f"止まる続き {best} コマ")
    if bl: why.append(f"目を閉じたコマ {bl}")
    if land >= 3: why.append(f"着地の差 {land:.1f}")
    if bg >= 2: why.append(f"背景の明るさの差 {bg:.1f}")
    if min(ccs) < 0.85: why.append(f"顔の合い {min(ccs):.2f}")
    if jump > 3: why.append(f"顔の跳び {jump:.1f} px")
    r["ok"] = not why; r["why"] = "、".join(why); return r


out = {}
print(f"{'部品':14s} {'組':22s} {'動き':>5s} {'止':>2s} {'目':>3s} {'着地':>5s} {'背景':>5s} {'顔の合い':>7s} {'跳び':>5s}  判定")
for role, vs in U["roles"].items():
    for u in vs:
        res = {}
        if u.get("rife"):                                # 描いた 2 枚の間を RIFE で直に補間する組。Wan の列は無い
            print(f"{u['name']:14s} {base + '<>' + u['pose']:22s} RIFE の組（Wan の検査なし）")
            out[u["name"]] = {"role": role, "ok": True, "pairs": {}, "rife": True}; continue
        for a, b in ((base, u["pose"]), (u["pose"], base)):
            r = check_pair(a, b); res[f"{a}>{b}"] = r
            if "motion_mean" in r:
                print(f"{u['name']:14s} {a + '>' + b:22s} {r['motion_mean']:5.2f} {r['still_run']:2d} {len(r['blink']):3d} {r['land']:5.2f} {r['bg']:5.2f} {r['cc_min']:7.3f} {r['face_jump']:5.2f}  {'OK' if r['ok'] else 'NG ' + r['why']}")
            else: print(f"{u['name']:14s} {a + '>' + b:22s} NG {r['why']}")
        out[u["name"]] = {"role": role, "ok": all(r["ok"] for r in res.values()), "pairs": res}
json.dump(out, open(os.path.splitext(UF)[0] + ".checked.json", "w"), ensure_ascii=False, indent=1)
print("通った部品:", [k for k, v in out.items() if v["ok"]], " 落ちた部品:", [k for k, v in out.items() if not v["ok"]])
