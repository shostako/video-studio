"""手の部品（opt-in）: 指の形のような細かい所を、全身の絵ではなく手のアップで一度だけ描き、元の姿勢の絵にはめ込んで姿勢の絵を作る。
  vm hands <作業フォルダ> draw [名前 ...] [--img codex|chat|chat+codex] [--dry-run]
      config.hands.<名前> の base の姿勢から box を切り出して参照にし、手だけを描かせる → hands/<名前>.png（描けたものは飛ばす）
  vm hands <作業フォルダ> check [名前 ...]   描いた手を拡大して並べる → hands/check.png（指の本数は、曲げた指まで数えて人か Claude が確かめる）
  vm hands <作業フォルダ> place [名前 ...] [--force]
      hands/<名前>.png を base の絵の box にはめ込む → poses/pose_<名前>.png。体は base の絵のまま（切り替えで手以外が動かない）
      前に place で作った絵は置き換える。それ以外（全身で描いた絵など）がある姿勢は置き換えずに終了コード 3。
      --force でその古い絵と、それから作った差分・部品・中割りを reject/hands_replaced/ へ移してから書く
config:
  "hands": {"count_3": {"base": "raise_r", "box": [x0, y0, x1, y1],
                        "desc": "the hand shows the number three: ... Count check: 3 raised + 1 curled + thumb = 5 digits."}}
  - 名前は config.poses にも書いておく（口・目の部品や中割りの組は今までどおり。口・目は vm parts --borrow で写せる）
  - box は base の絵の座標。手首と手が全部入り、顔にかからない範囲にする（vm grid で読む）
書かなければ何も変わらない。全身の絵で指の本数を描き分けさせると、曲げた指が残って指が多くなりやすい（手のアップだと本数が合った）。"""
import json, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, die

PROMPT = ("Close-up of the same hand as in the reference image: the same rendering style, skin color, sleeve and cuff, the same framing, "
          "and the wrist and forearm in exactly the same position; plain white background. Only the hand shape changes: {desc} "
          "A human hand has exactly five digits (thumb, index, middle, ring, little); do NOT draw any extra finger.")
SCALE = 2          # 参照に渡す切り抜きの拡大率（小さい切り抜きのままだと手が潰れる）


def spec(P, name):
    h = (P.cfg.get("hands") or {}).get(name)
    if not h: die(f"config.hands に無い: {name}")
    for k in ("base", "box", "desc"):
        if k not in h: die(f"config.hands.{name} に {k} が無い")
    x0, y0, x1, y1 = h["box"]
    if not (x0 < x1 and y0 < y1): die(f"config.hands.{name}.box がおかしい: {h['box']}")
    return h


def names(P, args):
    return args or list((P.cfg.get("hands") or {}).keys())


def ref_crop(P, name):
    h = spec(P, name); base = P.read_pose(h["base"]); x0, y0, x1, y1 = h["box"]
    H, W = base.shape[:2]
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H: die(f"config.hands.{name}.box が絵（{W}x{H}）の外に出る")
    crop = cv2.resize(base[y0:y1, x0:x1], ((x1 - x0) * SCALE, (y1 - y0) * SCALE), interpolation=cv2.INTER_LANCZOS4)
    os.makedirs(P.p("hands"), exist_ok=True); p = P.p("hands", f"_ref_{name}.png"); cv2.imwrite(p, crop)
    return p


def jobs_draw(P, ns):
    return [(P.p("hands", f"{n}.png"), PROMPT.format(desc=spec(P, n)["desc"].strip()), [ref_crop(P, n)]) for n in ns]


def archive_old(P, name):
    """--force で置き換える前に、古い姿勢の絵と、それから作った口・目の差分（parts/<名前>_*.png）・部品（parts_<名前>/）・
    その姿勢を端に持つ中割り（ib/ib_<前>_<次>_*.png）を reject/hands_replaced/<名前>_<時刻>/ へ移す（新しい手の絵に古い差分が残らないように）。"""
    import glob, time
    rd = P.p("reject", "hands_replaced", f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"); os.makedirs(rd, exist_ok=True); moved = []
    src = [P.pose_path(name)] + glob.glob(P.p("parts", f"{name}_*.png")) + [P.p(f"parts_{name}")]
    for a, b in P.cfg.get("pairs", []):
        if name in (a, b): src += glob.glob(P.p("ib", f"ib_{a}_{b}_*.png"))
    for f in src:
        if os.path.exists(f):
            rel = os.path.relpath(f, P.p("")); dst = os.path.join(rd, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(f, dst); moved.append(rel)
    print(f"  {name}: 古い絵と、それから作った差分・部品・中割り {len(moved)} 件を {os.path.relpath(rd, P.p(''))}/ へ移した")


def place(P, name, force=False):
    """描いた手を base の絵の box に重ね、違う所だけを縁をぼかして貼る。書いたら True。"""
    h = spec(P, name); out = P.pose_path(name); mark = P.p("hands", f"{name}.placed.json")
    hp = P.p("hands", f"{name}.png")
    if not os.path.exists(hp): die(f"手の絵が無い: hands/{name}.png（先に vm hands ... draw）")
    if os.path.exists(out) and not os.path.exists(mark):    # 前に place で作った絵ではない（全身で描いた絵など）
        if not force:
            print(f"{name}: poses/pose_{name}.png は place で作った絵ではない（全身で描いた絵など）。置き換えるなら --force（古い絵と、それから作った差分・部品・中割りは reject/hands_replaced/ へ移す）")
            return False
        archive_old(P, name)
    base = P.read_pose(h["base"]); x0, y0, x1, y1 = h["box"]; ref = base[y0:y1, x0:x1]
    hand = cv2.resize(cv2.imread(hp), (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    g0 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(hand, cv2.COLOR_BGR2GRAY).astype(np.float32)
    M = np.eye(2, 3, dtype=np.float32); cc = -1.0
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), None, 5)
    except cv2.error: pass
    hand = cv2.warpAffine(hand, M, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    d = np.linalg.norm(hand.astype(np.float32) - ref.astype(np.float32), axis=2)
    m = (cv2.GaussianBlur(d, (0, 0), 2) > 18).astype(np.uint8); m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    m = cv2.dilate(m, np.ones((15, 15), np.uint8))
    a = np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), 5) * 1.5, 0, 1)
    e = max(2, min(x1 - x0, y1 - y0) // 20)             # box の縁は元の絵に戻す（四角い継ぎ目を出さない）
    ramp = np.ones_like(a); ramp[:e, :] *= np.linspace(0, 1, e)[:, None]; ramp[-e:, :] *= np.linspace(1, 0, e)[:, None]
    ramp[:, :e] *= np.linspace(0, 1, e)[None, :]; ramp[:, -e:] *= np.linspace(1, 0, e)[None, :]
    a = (a * ramp)[..., None]
    img = base.copy(); img[y0:y1, x0:x1] = (hand * a + ref * (1 - a)).astype(np.uint8)
    os.makedirs(os.path.dirname(out), exist_ok=True); cv2.imwrite(out, img)
    json.dump({"base": h["base"], "box": h["box"], "cc": round(float(cc), 4)}, open(mark, "w"))   # place で作った印（次は --force なしで置き換える）
    print(f"{name}: hands/{name}.png を {h['base']} の {h['box']} にはめた（合わせ cc {cc:.3f}、ずれ {np.round(M[:, 2], 1).tolist()}）")
    return True


def check(P, ns):
    tiles = []
    for n in ns:
        hp = P.p("hands", f"{n}.png")
        if not os.path.exists(hp): print(f"{n}: まだ描いていない"); continue
        t = cv2.resize(cv2.imread(hp), (420, int(420 * 1.3))); cv2.putText(t, n, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2); tiles.append(t)
    if not tiles: return
    hh = max(t.shape[0] for t in tiles); row = np.hstack([cv2.copyMakeBorder(t, 0, hh - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles])
    out = P.p("hands", "check.png"); cv2.imwrite(out, row); print("確かめる絵:", out, "（曲げた指まで数える。親指を除いて合計4本）")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if len(argv) < 2 or argv[1] not in ("draw", "check", "place"): die("使い方: vm hands <作業フォルダ> draw|check|place [名前 ...] [--img ...] [--dry-run] [--force]")
    import poses
    backend = poses.img_backend(argv, {}) if "--img" in argv else None
    if "--img" in argv: i = argv.index("--img"); del argv[i:i + 2]
    P = Proj(argv[0]); what = argv[1]; rest = [a for a in argv[2:] if not a.startswith("--")]; ns = names(P, rest)
    if not ns: die("config.hands が空")
    if what == "draw":
        ok = poses.run_jobs(jobs_draw(P, ns), 2, "--dry-run" in argv, backend=backend or poses.img_backend([], P.cfg))
        if poses.LIMIT.is_set(): sys.exit(4)
        sys.exit(0 if ok else 1)
    if what == "check": check(P, ns); sys.exit(0)
    n = sum(place(P, x, "--force" in argv) for x in ns); print(f"はめた {n} / {len(ns)}")
    sys.exit(0 if n == len(ns) else 3)                       # 置き換えなかった姿勢があれば黙って成功にしない
