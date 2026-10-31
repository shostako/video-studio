"""マスコットが喋る動画を、1コマずつ組み立てて書き出す（パラパラ方式）。
  vm render <作業フォルダ> [--mode alpha|white] [--from 秒 --to 秒] [--out ファイル] [--mouth-scale 1.0]
    alpha（既定）: 背景を透明にした webm（out/mascot.webm、声は入れない）。どんな主動画にも重ねられる
    white       : 背景が白の mp4（声入り、out/mascot_white.mp4）。白っぽい主動画に「乗算」で重ねる用
  --mouth-scale  口の開きを全体に小さく(0.8)・大きく(1.2)する。--from/--to は一部だけ書き出して確かめる用
  切り替えの検査（毎回）: events の各切り替えが書き出したコマで実際に動いたか（頭の動きに隠れていないか、中割り・補間・Wan の列が出たか、
                 次の姿勢に着いたか）を最後に表で出し、<出力>.check.json に書く。書き出した動画の画素での確認は vm check
  --check-only   下見。絵を作らず（RIFE・Wan を呼ばず）時間割だけを回して同じ検査をし、Wan で新しく作る組を出す（<出力>.precheck.json）
  --strict       切り替えの検査で問題があれば終了コード 3（動画は書き出したまま残る）
  --lipsync amp|mora  口パクの母音の決め方（既定は config.lipsync、無ければ amp）。amp: 聞き取りの語を音の数で等分（今まで）。
                 mora: 行のかな台本を行の声の範囲にモーラの数で割り付け、両唇音・「っ」・句読点で口を閉じる
  --motion on|off  二次運動（既定は config.motion、無ければ off）。呼吸のゆらぎ、首の傾きとうなずき、まばたきの間隔のゆらぎ、
                 姿勢の切り替えの予備動作・オーバーシュート・イージング。off は今までどおりの息づかいとまばたき
  --interp rife|wan|off  中割りのコマ補間（既定は config.interp、無ければ off）。rife: 描いた中割りの間を RIFE で細かくし、
                 切り替えを interp.dur 秒（組ごとは interp.durs）とイージングで出す。作った列は ib_interp/ にためる。
                 wan: 姿勢の切り替えを Wan2.2 の First-Last-Frame で動かす（新PC の ComfyUI。interp.wan、作った列は ib_wan/ にためる）
config.transition（中割りの無い切り替えを溶かす・回って見せる）、events の via、config.gaze（視線の部品と、向きの切り替えの前に目が先に動く）、
poses.<名前>.yaw / head_yaw / face / anchor（向きの違う姿勢）は、書いた時だけ使う（references/config-spec.md の「向きと視線」）。
体は姿勢の絵1枚を固定し、口7形・目2段の部品を声の大きさと母音で毎コマ選んで貼る。姿勢の変わり目は中割り5枚（15fps）。
config の fps を 60、inbetween_div を 12、inbetween_fps を 30 にすると倍の細かさ（中割り11枚・まばたきは段の間を溶かす）。
姿勢の切り替え時刻は config.events（台詞のキーワードの声の時刻）で決める。軸足（向かって左の靴）の底を全部の絵でそろえる。"""
import json, math, os, random, re, subprocess, sys
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import Proj, MOUTHS, EYES, defloor, bake_shadow, boot_anchor, body_height, feet_anchor, fg_height, matte, die
from lib import vowel_frames, resolve_events, plan_at, choose_mouth as choose, smooth_mouth
from lib import mora_track, voiced_span, mora_frames, mora_mouth, PAUSE, frame_levels, word_hira, fill_vowel_gaps
from lib import occlude, motion_config, breath_wave, wobble, onset_env, head_rig, rig_affine, head_maps, head_move, switch_offset, blink_times
from lib import legs_config, lock_legs
from lib import transition_config, switch_kind, pose_view, gaze_config, resolve_gaze, gaze_track, gaze_part
from lib import interp_config, interp_on, interp_dur, dense_ks, via_home_config, home_route, head_config, head_pos, INTERP_DEFAULTS
from lib import frame_tag, switch_check, switch_report, head_spans, mouth_off_spans, mouth_report, mouth_shut_spans, mouth_shut_report, speech_loud
from parts import map_rois

a = [x for x in sys.argv[1:]]
if not a or a[0].startswith("-"): die("使い方: vm render <作業フォルダ> [--mode alpha|white] [--from 秒 --to 秒] [--out ファイル]")
P = Proj(a[0]); C = P.cfg
def opt(name, default=None, cast=str): return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default
MODE = opt("--mode", "alpha"); LIPSYNC = opt("--lipsync", C.get("lipsync", "amp"))
if LIPSYNC not in ("amp", "mora"): die(f"lipsync は amp か mora: {LIPSYNC}")
OCC = bool(C.get("face", {}).get("occlude", False))   # opt-in: 中割りに部品を移すとき、顔の前の手の上には貼らない
IDLE_OFF = C.get("idle", True) is False             # 既定（書かない・true）は今までどおりの息づかい（伸び縮み・上下・左右・声での持ち上がり）
try: MOT = motion_config(C.get("motion"), opt("--motion"))     # 二次運動（None は使わない＝今までどおり）
except ValueError as e_: die(str(e_))
try: TRANS = transition_config(C.get("transition")); GZ = gaze_config(C.get("gaze"))   # 向きの切り替えのつなぎ・視線（None は使わない）
except ValueError as e_: die(str(e_))
try: INTERP = interp_config(C.get("interp"), opt("--interp"))   # 中割りのコマ補間（None は使わない＝今までどおり）
except ValueError as e_: die(str(e_))
try: VH = via_home_config(C.get("via_home"))   # 中割りの無い組を home 経由でつなぐ（None は使わない＝今までどおり）
except ValueError as e_: die(str(e_))
try: HEADC = head_config(C.get("head"), C["poses"])   # 頭の向きの列（None は使わない＝今までどおり）
except ValueError as e_: die(str(e_))
PCFG = C["poses"]; VIEW = {p: pose_view(PCFG[p]) for p in PCFG}; FACE_ON = {p: PCFG[p].get("face", True) is not False for p in PCFG}
T0 = opt("--from", 0.0, float); MS = opt("--mouth-scale", float(C.get("mouth_scale", 1.0)), float)
FPS = P.fps; PAD = P.pad; OH = int(C.get("out_height", 1280)); random.seed(int(C.get("seed", 5)))
timing = json.load(open(P.p("voice", "timing.json"))); L = {x["n"]: x["start"] for x in timing["lines"]}; LDUR = {x["n"]: x["dur"] for x in timing["lines"]}; END = timing["end"]
T1 = opt("--to", END, float)
OUTF = opt("--out", P.p("out", "mascot.webm" if MODE == "alpha" else "mascot_white.mp4"))
VOICE = P.p("voice", "master.wav")

# ---------- 声: 大きさ・語・母音 ----------
def load_audio(p, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768, sr
x, SR = load_audio(VOICE); NALL = int(math.ceil(END * FPS)); WIN = SR * 2 // 30; R = max(1, round(FPS / 30))   # 窓は時間で固定（30fps の2コマ分）。R = 30fps に対する倍率
rms = frame_levels(x, SR, FPS, NALL, WIN)
lvl = np.clip(rms / (np.percentile(rms[rms > 0], 95) + 1e-6), 0, 1.5) * MS
WORDS = P.p("voice", "master.words.json")
if not os.path.exists(WORDS) or os.path.getmtime(WORDS) < os.path.getmtime(VOICE):
    from faster_whisper import WhisperModel
    sys.path.insert(0, os.path.expanduser("~/.claude/skills/video-scene/scripts")); from ear import read_audio
    segs, _ = WhisperModel("medium", device="cpu", compute_type="int8").transcribe(read_audio(VOICE), language="ja", word_timestamps=True, condition_on_previous_text=False)
    json.dump([[w.word, w.start, w.end] for s in segs for w in s.words], open(WORDS, "w"), ensure_ascii=False)
words = json.load(open(WORDS))
import pykakasi; KK = pykakasi.kakasi()
def to_hira(s): return "".join(ch for ch in "".join(t["hira"] for t in KK.convert(s)) if "ぁ" <= ch <= "ゖ" or ch == "ー")
WH = [(to_hira(w), s, e) for w, s, e in words]     # 語のひらがなと時刻
vowel_at, hira_stream = vowel_frames(WH, FPS, NALL)   # 音の並び（events の語の位置探し）はかなの語だけで作る（今までどおり）
vowel_at, _ = vowel_frames([(word_hira(h, w[0]), s, e) for (h, s, e), w in zip(WH, words)], FPS, NALL)   # 口の母音: 英字・数字・記号の語は「あ」

# ---------- 口 ----------
lvl_s = np.array([np.median(lvl[max(0, f - R):f + R + 1]) for f in range(NALL)])
if LIPSYNC == "mora":                             # 行のかな台本（voice.lines[].kana、無ければ say か text をかなにしたもの）をモーラで割り付ける
    VL = C.get("voice", {}).get("lines", []); MO = C.get("mora", {}); segs = []
    lvl_t = lvl_s / MS if MS > 0 else lvl_s        # 無音を削る判定は口の倍率に左右されない大きさで
    def to_kana(s): return "".join(ch for ch in "".join(t["hira"] for t in KK.convert(s)) if "ぁ" <= ch <= "ゖ" or ch == "ー" or ch in PAUSE)
    for n in sorted(L):
        if n > len(VL): die(f"lipsync=mora: 行{n} の台本が config.voice.lines に無い")
        kana = VL[n - 1].get("kana") or to_kana(VL[n - 1].get("say", VL[n - 1]["text"]))
        s_, e_ = voiced_span(lvl_t, FPS, L[n], L[n] + LDUR[n]) if MO.get("trim", True) else (L[n], L[n] + LDUR[n])
        segs += mora_track(kana, s_, e_, float(MO.get("pause_weight", 2.0)), float(MO.get("close_frac", 0.3)), float(MO.get("min_close", 0.067)))
    shape_at = mora_frames(segs, FPS, NALL)
    mouth = [mora_mouth(lvl_s[f], shape_at[f]) for f in range(NALL)]
else:
    vowel_at = fill_vowel_gaps(vowel_at, lvl_s >= 0.15, FPS)   # 語の間の短い隙間で声が出ているコマにも母音（0.15 は choose_mouth の閉じの境）
    mouth = [choose(lvl_s[f], vowel_at[f]) for f in range(NALL)]
mouth = smooth_mouth(mouth, R)                    # すぐ消える形は直前の形にする
print("口の形のコマ数:", {str(m): mouth.count(m) for m in sorted(set(mouth), key=str)}, file=sys.stderr)
sm = np.convolve(lvl, np.ones(5 * R) / (5 * R), mode="same")
SEED = int(C.get("seed", 5)); NOD = onset_env(sm, FPS) if MOT and MOT["head"] else None    # 二次運動のゆらぎの種と、うなずきの包絡

# ---------- 姿勢・部品・軸足 ----------
FL = C.get("floor", {"clean": True}); H0, W0 = P.read_pose(P.home).shape[:2]; Y0 = int(FL.get("y0", round(H0 * 0.705)))
PB, SH = {}, {}
try: LEGS = legs_config(C.get("legs_lock"), PCFG, P.home)   # 下半身の差し替え（opt-in）。正面の姿勢と中割りの腰から下を、1つの姿勢の下半身に揃える
except ValueError as e_: die(str(e_))
LEGS_SRC = P.read_pose(LEGS["from"]) if LEGS else None
LEGS_ON = set(LEGS["poses"]) | {LEGS["from"]} if LEGS else set()
def legs_on(*poses_): return bool(LEGS) and all(q in LEGS_ON for q in poses_) and not all(q == LEGS["from"] for q in poses_)
def legs(img, sc):
    """下半身を差し替えた絵と、その絵の足元の点（元の姿勢の足元を写した点）。sc はこの絵を書き出す時の倍率（脚の大きさを元の姿勢に揃える）。"""
    out, info = lock_legs(img, LEGS_SRC, LEGS["cut"], LEGS["feather"], LEGS["hand_zone"], SCALE[LEGS["from"]] / sc, dx=0 if LEGS["fix_x"] else None)
    if info is None: return img, None
    a_ = ANCH[LEGS["from"]]; M = info["M"]
    return out, (float(M[0, 0] * a_[0] + M[0, 2]), float(M[1, 1] * a_[1] + M[1, 2]))
if LEGS: print("下半身の差し替え:", LEGS["from"], "→", LEGS["poses"], file=sys.stderr)
RAW = {}
for p in P.poses:
    img = RAW[p] = P.read_pose(p)
    if any(k in PCFG[p] for k in ("yaw", "head_yaw", "face", "anchor", "scale")) and img.shape != (H0, W0, 3):   # 向きの違う姿勢は home と同じ大きさで描く決まり
        die(f"姿勢 {p} の絵の大きさ {img.shape[1]}x{img.shape[0]} が home の {W0}x{H0} と違う（同じ大きさにしてから。docs/mascot-views-spec.md）")
    if FL.get("clean", False): PB[p], SH[p] = defloor(img, Y0)
    else: PB[p], SH[p] = img, np.zeros(img.shape[:2], np.float32)
AN = C.get("anchor", {"mode": "boot"}); AMODE = AN.get("mode", "boot")
DETECT, HEIGHT = {"boot": (boot_anchor, body_height), "feet": (feet_anchor, fg_height)}.get(AMODE, (None, None))   # feet: 色に依らない足元（opt-in）
if DETECT:
    ANCH = {p: tuple(map(float, PCFG[p]["anchor"])) if "anchor" in PCFG[p] else DETECT(PB[p]) for p in P.poses}
    miss = [p for p, v in ANCH.items() if v is None]
    if miss: die(f"軸足{'の靴' if AMODE == 'boot' else '（足元）'}が見つからない姿勢: {miss}（config.anchor を {'feet か ' if AMODE == 'boot' else ''}manual にするか none に）")
    HT = {p: HEIGHT(PB[p], ANCH[p]) for p in P.poses}; SCALE = {p: HT[P.home] / HT[p] for p in P.poses}
    for p in P.poses:                             # poses.<名前>.scale: 背の高さで揃えず、この倍率に固定（伸び・お辞儀・屈むなど背が変わるポーズ。opt-in）
        if "scale" in PCFG[p]: SCALE[p] = float(PCFG[p]["scale"])
    if AMODE == "boot":                           # 靴で拾った軸足が足元の線に乗っているか（紺のズボンの裾などを拾うと、大きさの補正も狂う）。知らせるだけ
        off = [p for p in P.poses if "anchor" not in PCFG[p] and (lambda f_: f_ is not None and abs(ANCH[p][1] - f_[1]) > 0.01 * H0)(feet_anchor(PB[p]))]
        if off: print(f"注意: 靴で拾った軸足が足元に無い姿勢: {off}（服の裾などを拾っている。config の anchor を {{\"mode\": \"feet\"}} に。vm views で確かめる）", file=sys.stderr)
elif AMODE == "manual":
    ANCH = {p: tuple(v) for p, v in AN["points"].items()}
    for p in P.poses:
        if p not in ANCH and "anchor" in PCFG[p]: ANCH[p] = tuple(map(float, PCFG[p]["anchor"]))
    SCALE = {p: float(AN.get("scales", {}).get(p, PCFG[p].get("scale", 1.0))) for p in P.poses}
else:
    ANCH = {p: (W0 / 2, H0 * 0.9) for p in P.poses}; SCALE = {p: float(PCFG[p].get("scale", 1.0)) for p in P.poses}
if LEGS:                                          # 差し替える姿勢は基準と同じ大きさの絵（中割りは端の姿勢の大きさに直してから差し替える）
    bad = [p for p in P.poses if legs_on(p) and RAW[p].shape != LEGS_SRC.shape]
    if bad: die(f"legs_lock: 絵の大きさが {LEGS['from']} と違う姿勢: {bad}（同じ大きさにするか legs_lock.poses から外す）")
if LEGS and LEGS["from"] not in ANCH: die(f"legs_lock.from の姿勢 {LEGS['from']} の足元が無い（anchor.points に書く）")
if LEGS:                                          # 足元と大きさを元の絵で決めてから差し替え、足元の点は元の姿勢の足元を写した点にする（手で書いた anchor も）
    for p in P.poses:
        if not legs_on(p): continue
        img, a_ = legs(RAW[p], SCALE[p])
        if a_ is None: continue
        ANCH[p] = a_
        if FL.get("clean", False): PB[p], SH[p] = defloor(img, Y0)
        else: PB[p] = img
REF = ANCH[P.home]
print("軸足:", {p: tuple(round(float(v), 1) for v in a_) for p, a_ in ANCH.items()}, "大きさ:", {p: round(float(v), 3) for p, v in SCALE.items()}, file=sys.stderr)
PARTS = {}
for p in P.poses:
    PARTS[p] = {}; mp = P.p(f"parts_{p}", "parts.json")
    if not FACE_ON[p]: continue                   # 顔の見えない姿勢（後ろ向き）は口・目の部品なし
    if not os.path.exists(mp): die(f"部品が無い: parts_{p}（先に vm parts）")
    for k, (px, py) in json.load(open(mp)).items(): PARTS[p][k] = (cv2.imread(P.p(f"parts_{p}", f"{k}.png"), cv2.IMREAD_UNCHANGED), px, py)
FB = {"m7": "m1", "m3": "m2", "m6": "m1"}      # 無い形は近い形で代用
def part_of(parts, k):
    while k and k not in parts: k = FB.get(k)
    return parts.get(k) if k else None

def shift_m(a_, sc): return np.float32([[sc, 0, REF[0] - sc * a_[0] + PAD], [0, sc, REF[1] - sc * a_[1]]])
def shift(img, a_, sc, interp=cv2.INTER_LINEAR, val=(253, 253, 253)):
    """軸足の靴の底の中心 a_ を REF に重ね、その点を中心に sc 倍する。左右に PAD の余白を足した画面に置く。"""
    return cv2.warpAffine(img, shift_m(a_, sc), (img.shape[1] + 2 * PAD, img.shape[0]), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=val)
KEEP = {}; HEAD = {}
for p_ in P.poses:                       # 顔（目と口）の矩形。この中の白（白目・歯）は背景にしない
    if not FACE_ON[p_]: KEEP[p_] = []; HEAD[p_] = None; continue
    mr, er, _ = map_rois(P, p_); HEAD[p_] = head_rig(mr, er, MOT["head"]["neck"], MOT["head"]["radius"]) if MOT and MOT["head"] else None
    KEEP[p_] = [(er[0] - 10, er[1] - 10, er[2] + 10, er[3] + 10), (mr[0] - 10, mr[1] - 10, mr[2] + 10, mr[3] - 24)]   # 目と口を別々の箱に（口はあごの下へ広げない）

def face_affine(src, dst, roi):
    x0, y0, x1, y1 = roi
    g0 = cv2.cvtColor(dst, cv2.COLOR_BGR2GRAY).astype(np.float32); g1 = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mask = np.zeros(g0.shape, np.uint8); mask[y0:y1, x0:x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1
    try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6), mask, 5)
    except cv2.error: pass
    return cv2.invertAffineTransform(M), cc
IBCACHE = {}; IBCACHE_MAX = 48   # 中割りの絵の控え。補間で枚数が増えるとメモリを食い潰すので、古いものから捨てる
def ib_item(item, src_pose, lerp_parts=False):
    """中割りの絵と、その上に移植した部品（顔に合わせられなければ部品なし）、軸足の位置、大きさの補正。"""
    path, a_, b_, k_ = item; key = (path, src_pose, lerp_parts)
    if key in IBCACHE: IBCACHE[key] = IBCACHE.pop(key); return IBCACHE[key]   # 使った順に並べ直す
    while len(IBCACHE) >= IBCACHE_MAX: IBCACHE.pop(next(iter(IBCACHE)))
    img = cv2.imread(path)
    if img is None: die(f"中割りの絵が無い: {path}")
    ref = PB[src_pose]
    if img.shape != ref.shape: img = cv2.resize(img, (ref.shape[1], ref.shape[0]))
    sc = SCALE[a_] + (SCALE[b_] - SCALE[a_]) * k_ / DIV
    lanc = None
    if legs_on(a_, b_): img, lanc = legs(img, sc)  # 両端とも差し替える姿勢なら、中割りも同じ下半身に（足元の点も差し替えた脚から）
    clean, shadow = defloor(img, Y0) if FL.get("clean", False) else (img, np.zeros(img.shape[:2], np.float32))
    own = "anchor" in PCFG[a_] or "anchor" in PCFG[b_]          # 端の姿勢に anchor を書いたら、中割りも測らずに両端の間で補う
    anc = lanc if lanc is not None else (DETECT(clean) if DETECT and not own else None)
    if anc is None: anc = tuple(np.array(ANCH[a_]) + (np.array(ANCH[b_]) - np.array(ANCH[a_])) * k_ / DIV)
    if lerp_parts:                                # 頭の向きの列: 部品は一番近い向きの絵の物を、隣どうしの向きの置き場所の間に置く
        w_ = k_ / DIV if a_ != b_ else 0.0          #（顔の合わせで写すと、首が回る途中で合わせがずれて口が顔に遅れた）
        parts = {}
        for k, (im, px, py) in PARTS[src_pose].items():
            if k not in PARTS[a_] or k not in PARTS[b_]: continue
            (_, ax, ay), (_, bx, by) = PARTS[a_][k], PARTS[b_][k]
            parts[k] = (im, int(round(ax + (bx - ax) * w_)), int(round(ay + (by - ay) * w_)))
        IBCACHE[key] = (clean, shadow, parts, anc, sc, HEAD[src_pose]); return IBCACHE[key]
    allp = list(PARTS[src_pose].values())
    if not allp: IBCACHE[key] = (clean, shadow, {}, anc, sc, None); return IBCACHE[key]
    xs = [p_[1] for p_ in allp] + [p_[1] + p_[0].shape[1] for p_ in allp]; ys = [p_[2] for p_ in allp] + [p_[2] + p_[0].shape[0] for p_ in allp]
    roi = (max(0, min(xs) - 80), max(0, min(ys) - 100), min(img.shape[1], max(xs) + 80), min(img.shape[0], max(ys) + 60))
    A, cc = face_affine(PB[src_pose], clean, roi); parts = {}; rig = HEAD[src_pose]
    if cc >= 0.80:
        rig = rig_affine(rig, A)                  # 二次運動の首も、部品と同じく中割りの顔の位置へ写す
        H, W = clean.shape[:2]
        ref = cv2.warpAffine(PB[src_pose], A, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) if OCC else None
        for k, (im, px, py) in PARTS[src_pose].items():
            T = A.copy(); T[:, 2] += A[:, 0] * px + A[:, 1] * py
            full = cv2.warpAffine(im, T, (W, H), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
            if OCC: full = occlude(full, clean, ref)   # 中割りで顔の前に来た手には貼らない（config.face.occlude）
            yy, xx = np.where(full[:, :, 3] > 0)
            if len(xx): parts[k] = (full[yy.min():yy.max() + 1, xx.min():xx.max() + 1], int(xx.min()), int(yy.min()))
    IBCACHE[key] = (clean, shadow, parts, anc, sc, rig); return IBCACHE[key]

DRY = "--check-only" in sys.argv                  # 下見: 絵を作らず時間割だけを回して、切り替えの検査をする（RIFE・Wan を呼ばない）
class LazySeq:
    """補間した列。長さは先に分かり、絵（RIFE）は最初に中身を引いた時に作る（--from/--to の範囲外の切り替えでは作らない）。
    dry(i) は下見（--check-only）のときに作らずに返す項目（パスは置き場の名前だけ。検査は置き場の名前で出どころを見る）。"""
    def __init__(self, n, make, rev, dry=None): self.n, self.make, self.rev, self.items, self.dry = n, make, rev, None, dry
    def __len__(self): return self.n
    def __bool__(self): return self.n > 0
    def __getitem__(self, i):
        if DRY and self.dry: return self.dry()
        if self.items is None: self.items = self.make()
        return self.items[self.n - 1 - i] if self.rev else self.items[i]
def dense_seq(pa, pb, rev, direct):
    def make():
        from interp import dense_paths
        paths = dense_paths(P, pa, pb, DIV, INTERP, log=lambda m: print(m, file=sys.stderr), direct=direct)
        return [(pth, pa, pb, k) for pth, k in zip(paths, dense_ks(DIV, INTERP["mult"]))]
    return LazySeq(DIV * INTERP["mult"] - 1, make, rev, dry=lambda: (P.p("ib_interp", "_dry"), pa, pb, 0))
def wan_seq(a_, b_):
    """Wan の First-Last-Frame で a→b を動かした列（engine: wan）。長さと k の位置は RIFE の直の補間と同じ（端の姿勢の間を div 等分した単位）。"""
    n = DIV * INTERP["mult"] - 1
    def make():
        from wanflf import dense_paths as wan_paths
        paths = wan_paths(P, a_, b_, n, INTERP, log=lambda m: print(m, file=sys.stderr))
        return [(pth, a_, b_, k) for pth, k in zip(paths, dense_ks(DIV, INTERP["mult"]))]
    return LazySeq(n, make, False, dry=lambda: (P.p("ib_wan", f"{a_}__{b_}", "_dry"), a_, b_, 0))
def wan_ok(a_, b_):                               # Wan で動かす組か（engine: wan、向きの同じ組、interp.pairs で絞れる）
    return bool(INTERP) and INTERP["engine"] == "wan" and a_ != b_ and VIEW[a_] == VIEW[b_] and interp_on(INTERP, a_, b_)
IBSEQ = {}
def ib_seq(a_, b_):
    if (a_, b_) in IBSEQ: return IBSEQ[(a_, b_)]
    if wan_ok(a_, b_):                            # engine: wan。rife_pairs の組（頭が少し動くだけ）は描いた 2 枚の間を RIFE で直に
        rp = INTERP["wan"]["rife_pairs"]
        if f"{a_}>{b_}" in rp or f"{b_}>{a_}" in rp:
            pa, pb = sorted((a_, b_)); IBSEQ[(a_, b_)] = dense_seq(pa, pb, pa != a_, True)
        else:
            IBSEQ[(a_, b_)] = wan_seq(a_, b_)
        return IBSEQ[(a_, b_)]
    d = P.pair_dir(a_, b_)
    if d is None and direct_ok(a_, b_):           # 中割りの無い組を、端の姿勢2枚の間で直に補間する（interp.direct）
        pa, pb = sorted((a_, b_)); IBSEQ[(a_, b_)] = dense_seq(pa, pb, pa != a_, True); return IBSEQ[(a_, b_)]
    if d is None: IBSEQ[(a_, b_)] = None; return None
    pa, pb, rev = d
    if INTERP and interp_on(INTERP, pa, pb):      # コマ補間: 描いた絵の間を RIFE で細かくした列（k は小数）
        IBSEQ[(a_, b_)] = dense_seq(pa, pb, rev, False); return IBSEQ[(a_, b_)]
    seq = [(P.ib_path(pa, pb, k), pa, pb, k) for k in range(1, DIV)]
    IBSEQ[(a_, b_)] = seq[::-1] if rev else seq; return IBSEQ[(a_, b_)]
def direct_ok(a_, b_):                            # 中割りの無い組を直に補間するか（interp.direct、向きの同じ組だけ）
    return bool(INTERP) and INTERP["direct"] and a_ != b_ and P.pair_dir(a_, b_) is None and VIEW[a_] == VIEW[b_] and interp_on(INTERP, a_, b_)
def interp_pair(a_, b_):                          # コマ補間する組か（中割りのある組と、直に補間する組と、Wan で動かす組）
    d = P.pair_dir(a_, b_); return bool(INTERP) and ((d is not None and interp_on(INTERP, d[0], d[1])) or direct_ok(a_, b_) or wan_ok(a_, b_))

# ---------- 時間割 ----------
DIV = P.ib_div; NIB = DIV - 1; IBFPS = int(C.get("inbetween_fps", 15)); IBDUR = NIB / IBFPS
EVS = C.get("events", []); USE_VIA = TRANS is not None or any("via" in e for e in EVS)   # 向きの切り替えのつなぎ（書いた時だけ）
def ib_d(a_, b_): return interp_dur(INTERP, a_, b_) if interp_pair(a_, b_) else IBDUR   # 中割りのある切り替えの秒
def trans_of(a_, b_, via): return switch_kind(P.pair_dir(a_, b_) is not None or direct_ok(a_, b_) or wan_ok(a_, b_), via, TRANS, ib_d(a_, b_))   # Wan で動かす組も「中割りあり」（events の via は優先）
def sw_dur(a_, b_, via):
    k_ = trans_of(a_, b_, via); return ib_d(a_, b_) if k_ is None else k_[1]
def route(a_, b_, via):                           # home 経由でつなぐ切り替えの (前→home の秒, hold, home→次 の秒)（via_home。via を書いた切り替えは via が優先）
    if not (VH and via is None and home_route(a_, b_, P.home, lambda x_, y_: P.pair_dir(x_, y_) is not None)): return None
    return sw_dur(a_, P.home, None), VH["hold"], sw_dur(P.home, b_, None)
ev = resolve_events(EVS, P.home, L, LDUR, IBDUR, hira_stream, WH, log=lambda m: print(m, file=sys.stderr),
                    dur_of=sw_dur if (USE_VIA or INTERP) else None, with_via=USE_VIA, route=route if VH else None)
EASE = MOT["switch"]["ease"] if MOT and MOT["switch"] else None
IB_DUR = (lambda a_, b_: (interp_dur(INTERP, a_, b_), INTERP["ease"]) if interp_pair(a_, b_) else None) if INTERP else None
def plan(f): return plan_at(f / FPS, ev, P.home, ib_seq, IBFPS, NIB, EASE, trans_of if USE_VIA else None, IB_DUR)
SW = [(e_[0], sw_dur(e_[1], e_[2], e_[3] if USE_VIA else None) if (USE_VIA or INTERP) else IBDUR, e_[1], e_[2]) for e_ in ev]   # 切り替え（開始, 長さ, 前, 次）

# ---------- 視線 ----------
GAZE = [None] * NALL
if GZ:                                            # 台本の指定（gaze.events）と、顔の向きが変わる切り替えの前に目が先に動く分
    spans = resolve_gaze(GZ["events"], L, LDUR, hira_stream, WH, GZ["hold"], log=lambda m: print(m, file=sys.stderr))
    def instant(e_):                              # 中割りもつなぎも無い切り替えは一瞬（目の先回りは切り替えの時刻で終える）
        k_ = trans_of(e_[1], e_[2], e_[3]) if USE_VIA else None
        return (k_ is None and ib_seq(e_[1], e_[2]) is None) or (k_ is not None and k_[0] == "cut")
    GSW = [(sw[0], 0.0 if instant(e_) else sw[1], sw[2], sw[3]) for sw, e_ in zip(SW, ev)]
    GAZE = gaze_track(NALL, FPS, spans, GSW, lambda p_: VIEW[p_][1], GZ["lead"])

# ---------- まばたき ----------
BLINK_AT = []
if MOT and MOT["blink"]:                          # 二次運動: 間隔をゆらがせ、ときどき2回続け、姿勢の切り替えでもまばたく
    B_ = MOT["blink"]
    BLINK_AT = blink_times(END, random.Random(SEED + 101), B_["mean"], B_["spread"], B_["min"], B_["max"], B_["double"],
                           extra=[e_[0] for e_ in ev] if B_["on_switch"] else ())
elif MOT is None:                                 # 今までどおり（motion.blink: false はまばたきしない）
    t = 1.2
    while t < END: BLINK_AT.append(t); t += random.uniform(2.6, 4.6)
blink = [None] * NALL                  # まばたき: None か "e1"/"e2"、細かい時は (下の段, 上の段, 上の段の割合)
BL = [0, 1, 1, 2, 2, 1, 1, 0]; BK = {0: None, 1: "e1", 2: "e2"}   # 30fps の6コマ（e1 e1 e2 e2 e1 e1）を、前後の「開き」込みの閉じ具合で表す
for t in BLINK_AT:
    f0 = int(t * FPS)
    if R == 1:
        for k, e in enumerate(["e1", "e1", "e2", "e2", "e1", "e1"]):
            if f0 + k < NALL: blink[f0 + k] = e
    else:                                         # 30fps の各コマの中心を結んだ閉じ具合を R 倍の細かさで取り、段の間は溶かす
        for k in range(6 * R + 1):
            u = (k + 0.5) / R - 0.5 + 1           # BL 上の位置（BL[1] が 30fps の1コマ目）
            i0 = int(math.floor(u)); fr = u - i0; lv = BL[min(i0, 7)] * (1 - fr) + BL[min(i0 + 1, 7)] * fr
            lo = int(math.floor(lv)); hi = min(2, lo + 1); a_ = lv - lo
            if f0 + k < NALL and lv > 0.01: blink[f0 + k] = BK[lo] if a_ < 0.02 else (BK[lo], BK[hi], a_)

# ---------- 描画 ----------
def paste(img, part):
    if part is None: return
    im, px, py = part; h, w = im.shape[:2]
    if py < 0 or px < 0 or py + h > img.shape[0] or px + w > img.shape[1]: return
    al = im[:, :, 3:4].astype(np.float32) / 255; roi = img[py:py + h, px:px + w].astype(np.float32); img[py:py + h, px:px + w] = (roi * (1 - al) + im[:, :, :3] * al).astype(np.uint8)
def compose(pl, mth, blk, look=None):
    if pl[0] == "ib":
        clean, shadow, parts, anc, sc, rig = ib_item(pl[1], pl[2], len(pl) > 3 and pl[3] == "head"); img = clean.copy()
    else:
        img = PB[pl[1]].copy(); shadow = SH[pl[1]]; parts = PARTS[pl[1]]; anc = ANCH[pl[1]]; sc = SCALE[pl[1]]; rig = HEAD[pl[1]]
    paste(img, part_of(parts, mth))
    if blk is None and look is not None:          # 視線: まばたきの間は貼らない。その姿勢に無い部品は元の目のまま
        g_ = gaze_part(look, VIEW[pl[2] if pl[0] == "ib" else pl[1]][1], parts)
        if g_: paste(img, parts[g_])
    if isinstance(blk, tuple):                    # 細かいまばたき: 2つの段を割合で溶かす
        lo_, hi_, al_ = blk; i_lo = img.copy(); paste(i_lo, part_of(parts, lo_)); paste(img, part_of(parts, hi_)); img = cv2.addWeighted(img, al_, i_lo, 1 - al_, 0)
    else: paste(img, part_of(parts, blk))
    k = KEEP[pl[2] if pl[0] == "ib" else pl[1]]; m1 = shift_m(anc, sc); pad_ = 30 if pl[0] == "ib" else 0     # 中割りは顔が少し動くので広めに
    return shift(img, anc, sc), shift(shadow, anc, sc, val=0), (m1, [(b[0] - pad_, b[1] - pad_, b[2] + pad_, b[3] + pad_) for b in k], rig)

# ---------- 頭の向きの列（config.head、opt-in）----------
# 描いた向きの絵（head.chain）の隣どうしの間を RIFE で直に細かくして 1 本の列にし、頭の動きはその列の上を行き来させる。
# 列の各コマは中割りと同じ形で書き出す（口・目・視線の部品は一番近い向きの絵から顔に合わせて写す）。Wan は使わない
HEAD_KEYS, HEAD_IDX, HEAD_ITEMS = [], {}, None
if HEADC and HEADC["events"]:
    for p_ in HEADC["chain"]:
        if RAW[p_].shape != RAW[HEADC["chain"][0]].shape: die(f"head.chain の姿勢の絵の大きさがそろっていない: {p_}")
    _hk = resolve_events(HEADC["events"], HEADC["chain"][0], L, LDUR, 0.0, hira_stream, WH, log=lambda m: print("頭: " + m, file=sys.stderr), dur_of=lambda a_, b_, v_: 0.0)
    HEAD_KEYS = [(e_[0], e_[2]) for e_ in _hk]
    _hm = HEADC["mult"] * DIV
    for i_, p_ in enumerate(HEADC["chain"]): HEAD_IDX[p_] = i_ * _hm
    print("頭の動きの要所:", [(round(t_, 2), p_) for t_, p_ in HEAD_KEYS], file=sys.stderr)
def head_items():
    """列の各コマ [(絵のパス, 前の向き, 次の向き, k), ...]（向きの絵そのものも含む）。最初に使う時に RIFE で作る。"""
    global HEAD_ITEMS
    if HEAD_ITEMS is None:
        from interp import dense_paths
        cfg = dict(INTERP or INTERP_DEFAULTS); cfg["mult"] = HEADC["mult"]
        ch = HEADC["chain"]; items = [(P.pose_path(ch[0]), ch[0], ch[0], 0)]
        for pa_, pb_ in zip(ch, ch[1:]):
            paths = dense_paths(P, pa_, pb_, DIV, cfg, log=lambda m: print(m, file=sys.stderr), direct=True)
            items += [(pth, pa_, pb_, k_) for pth, k_ in zip(paths, dense_ks(DIV, HEADC["mult"]))] + [(P.pose_path(pb_), pb_, pb_, 0)]
        HEAD_ITEMS = items
    return HEAD_ITEMS
def head_plan(f):
    """f が頭の動きの中なら、列のコマを中割りと同じ形で ("ib", item, 部品を写す向き)。外なら None"""
    pos = head_pos(f / FPS, HEAD_KEYS, HEAD_IDX, rest=P.home if P.home in HEAD_IDX else None) if HEAD_KEYS else None
    if pos is None: return None
    src = min(HEADC["chain"], key=lambda p_: abs(HEAD_IDX[p_] - pos))
    if DRY: return ("ib", (P.p("ib_interp", "_dry"), src, src, 0), src, "head")
    items = head_items(); j = min(len(items) - 1, max(0, int(round(pos))))
    return ("ib", items[j], src, "head")

SWITCHES = [(s_, d_) for s_, d_, _, _ in SW]      # 二次運動: 予備動作とオーバーシュートを足す切り替え（開始, 長さ）

def body(pl, f):
    """1つの絵（姿勢か中割り）に口・目・視線を貼り、二次運動の首を傾ける。戻り値 (絵, 影, 顔の箱（首の傾き込み、息づかいの前の座標）)。"""
    img, sh, kinfo = compose(pl, mouth[f], blink[f], GAZE[f])
    if f > 0 and mouth[f] != mouth[f - 1]:         # 口の形が変わるコマは前後を半々に溶かす
        i2, s2, _ = compose(pl, mouth[f - 1], blink[f], GAZE[f]); img = cv2.addWeighted(img, 0.5, i2, 0.5, 0); sh = (sh + s2) / 2
    H, W = img.shape[:2]; tt = f / FPS; hb = None
    if MOT is not None:
        rig = kinfo[2]                            # 首（絵の座標。中割りは顔の動きに合わせて写したもの）
        if rig:                                   # 首: 首から上だけを傾け、声の出だしで少し下げる（首より下は動かさない）
            m1_ = kinfo[0]; sc_ = float(m1_[0, 0]); pv = (m1_[0, 0] * rig[0][0] + m1_[0, 2], m1_[1, 1] * rig[0][1] + m1_[1, 2])
            hb = (pv, MOT["head"]["roll"] * wobble(tt, MOT["head"]["period"], SEED + 2), MOT["head"]["nod"] * NOD[f], rig[1] * sc_, rig[2] * sc_)
            x0_, x1_ = max(0, int(pv[0] - 1.6 * hb[3]) - 2), min(W, int(pv[0] + 1.6 * hb[3]) + 3); y1_ = min(H, int(pv[1]) + 3)
            if x1_ > x0_ and y1_ > 0:
                mx, my = head_maps(x0_, 0, x1_, y1_, *hb)
                img[:y1_, x0_:x1_] = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    m1, kbs = kinfo[0], kinfo[1]; boxes = []
    for kb in kbs:                                # 顔の箱を、移動と首の傾きで写す（息づかい・縮小はあとで）
        pts = np.array([[kb[0], kb[1]], [kb[2], kb[3]]], np.float32); p1 = pts @ m1[:, :2].T + m1[:, 2]
        if hb:                                    # 首の傾きで顔の箱も動かす（箱の中心の動きだけずらす）
            c_ = p1.mean(0); mx_, my_ = head_move(c_[0], c_[1], *hb); p1 = p1 + np.array([float(mx_) - c_[0], float(my_) - c_[1]], np.float32)
        boxes.append(p1)
    return img, sh, boxes
W1 = W0 + 2 * PAD; OW = 2 * round(OH * W1 / H0 / 2)
f0, f1 = int(T0 * FPS), int(math.ceil(T1 * FPS))
if min(f1, NALL) <= f0: die(f"書き出すコマが無い（{T0}〜{T1} 秒、声は {NALL / FPS:.2f} 秒まで。--from / --to を見直す）")
if DRY: enc = None
elif MODE == "alpha":
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-auto-alt-ref", "0", OUTF], stdin=subprocess.PIPE)
else:
    tmp = OUTF + ".noaudio.mp4"
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
def squash(img, sh, boxes, sq_):
    """turn の途中: 体の真ん中（home の軸足の x）を軸に横へ (1 - sq_) 倍に縮める。"""
    cx_ = REF[0] + PAD; S_ = np.array([[1 - sq_, 0, sq_ * cx_], [0, 1, 0]], np.float32); H, W = img.shape[:2]
    img = cv2.warpAffine(img, S_, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(253, 253, 253))
    sh = cv2.warpAffine(sh, S_, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return img, sh, [b_ @ S_[:, :2].T + S_[:, 2] for b_ in boxes]

def finish(img, sh, boxes, sdd):
    """息づかい sdd=(伸び縮み, 横, 縦) の変換と縮小をかけ、alpha なら背景を透明にした BGRA、white なら影を焼き込んだ BGR にする。"""
    H, W = img.shape[:2]; s, dx, dy = sdd
    M = np.array([[s, 0, (1 - s) * W / 2 + dx], [0, s, (1 - s) * H + dy]], np.float32)     # 息づかい: 足元を中心にわずかに伸び縮み
    img = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(253, 253, 253))
    sh = cv2.warpAffine(sh, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    img = cv2.resize(img, (OW, OH), interpolation=cv2.INTER_AREA); sh = cv2.resize(sh, (OW, OH), interpolation=cv2.INTER_AREA)
    if MODE != "alpha": return bake_shadow(img, sh)
    fxs, fys = OW / W, OH / H; keep = []
    for p1 in boxes:                                                                      # 顔の箱を、息づかい・縮小の変換で最終の画素に写す
        p2 = p1 @ M[:, :2].T + M[:, 2]
        keep.append((int(p2[0, 0] * fxs), int(p2[0, 1] * fys), int(p2[1, 0] * fxs), int(p2[1, 1] * fys)))
    return matte(img, sh, keep)

TAGS, SPEAK, FACEP, LOUD = [], [], [], []         # 検査: 各コマで何を出したか（frame_tag）、口を開けているか、口の部品を貼る姿勢に部品があるか、声が出ているか
def face_of(pl):
    if pl[0] == "mix": return (FACE_ON[pl[1]] and FACE_ON[pl[2]], pl[1] if not FACE_ON[pl[1]] else pl[2])
    p_ = pl[2] if pl[0] == "ib" else pl[1]; return (FACE_ON[p_], p_)
for f in range(f0, min(f1, NALL)):
    hp = head_plan(f); pl = hp or plan(f); tt = f / FPS   # 頭の動きの中は、頭の向きの列が姿勢の時間割より優先
    TAGS.append(frame_tag(pl, hp is not None)); SPEAK.append(mouth[f] is not None); FACEP.append(face_of(pl)); LOUD.append(speech_loud(lvl_s[f], vowel_at[f] if LIPSYNC == "amp" else None))   # 「っ」の閉じは数えない
    if DRY: continue
    if MOT is None and IDLE_OFF:                   # config.idle: false（opt-in）で、止まっている間の息づかいを全部止める
        s, dx, dy = 1.0, 0.0, 0.0
    elif MOT is None:
        s = 1 + 0.004 * math.sin(2 * math.pi * tt / 3.6); dx = 1.5 * math.sin(2 * math.pi * tt / 5.3); dy = -2.0 * math.sin(2 * math.pi * tt / 3.6) - 2.5 * sm[f]
    else:
        s, dx, dy = 1.0, 0.0, -2.5 * sm[f]
        if MOT["breath"]:
            b_ = MOT["breath"]; v_ = 2 * breath_wave(tt, b_["period"], b_["jitter"], b_["inhale"], SEED) - 1; s += b_["scale"] * v_; dy -= b_["lift"] * v_
        if MOT["body"]: dx = MOT["body"]["sway"] * wobble(tt, MOT["body"]["period"], SEED + 1)
        if MOT["switch"]: dy += switch_offset(tt, SWITCHES, MOT["switch"]["anticipate"], MOT["switch"]["anticipate_px"], MOT["switch"]["overshoot_px"], MOT["switch"]["settle"])
    M = (s, dx, dy)
    if pl[0] == "mix":                             # 向きの切り替え: 前と次の姿勢を溶かす（turn は横に少し縮めて回って見せる）
        A_ = body(("pose", pl[1]), f); B_ = body(("pose", pl[2]), f); u_, sq_ = pl[3], pl[4]
        if sq_ > 0: A_ = squash(*A_, sq_); B_ = squash(*B_, sq_)
        if MODE == "alpha":                        # 透明は姿勢ごとに切り抜いてから、色と透明度を重みで混ぜる（白い背景ごと混ぜると灰色の縁が残る）
            ra = finish(*A_, M).astype(np.float32); rb = finish(*B_, M).astype(np.float32)
            aa, ab = ra[:, :, 3:4] / 255 * (1 - u_), rb[:, :, 3:4] / 255 * u_; at = aa + ab
            col = (ra[:, :, :3] * aa + rb[:, :, :3] * ab) / np.maximum(at, 1e-6)
            out = np.dstack([np.clip(col, 0, 255), np.clip(at * 255, 0, 255)]).round().astype(np.uint8)
        else:
            out = finish(cv2.addWeighted(B_[0], u_, A_[0], 1 - u_, 0), B_[1] * u_ + A_[1] * (1 - u_), A_[2] + B_[2], M)
    else:
        out = finish(*body(pl, f), M)
    enc.stdin.write(out.tobytes())
    if f % 300 == 0: print(f"  {f}/{NALL}", file=sys.stderr, flush=True)
if not DRY:
    enc.stdin.close(); rc_enc = enc.wait()
    if rc_enc != 0: die(f"ffmpeg の書き出しに失敗（終了コード {rc_enc}）")
    if MODE != "alpha":
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-ss", f"{T0}", "-t", f"{T1 - T0}", "-i", VOICE, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", OUTF], check=True)
        os.remove(tmp)

# ---------- 切り替えの検査 ----------
# events の各切り替えが、書き出したコマで実際に動いたか（頭の動きに隠れていないか、中割り・補間・Wan の列が出たか、次の姿勢に着いたか）。
# 結果は <出力>.check.json（下見は .precheck.json）に書き、vm check（書き出した動画の画素で確かめる）が読む。--strict なら問題があれば終了コード 3
def sw_kind(e_):
    k_ = trans_of(e_[1], e_[2], e_[3] if len(e_) > 3 else None) if USE_VIA else None
    if k_ is not None: return "instant" if k_[0] == "cut" else "mix"
    return "ib" if ib_seq(e_[1], e_[2]) else "instant"
def sw_engine(a_, b_, kind):
    if kind != "ib": return kind
    if wan_ok(a_, b_):
        rp = INTERP["wan"]["rife_pairs"]; return "rife" if (f"{a_}>{b_}" in rp or f"{b_}>{a_}" in rp) else "wan"
    return "rife" if interp_pair(a_, b_) else "drawn"
SWL = []
for sw, e_ in zip(SW, ev):
    k_ = sw_kind(e_); item = {"at": round(sw[0], 4), "dur": round(sw[1], 4), "from": e_[1], "to": e_[2], "kind": k_, "engine": sw_engine(e_[1], e_[2], k_)}
    if item["engine"] == "wan":
        wd = P.p("ib_wan", f"{e_[1]}__{e_[2]}", f"n{DIV * INTERP['mult'] - 1}")
        item["wan_dir"] = wd; item["wan_ready"] = os.path.exists(os.path.join(wd, "stamp.json"))
    SWL.append(item)
CHK = switch_check(TAGS, f0, FPS, SWL)
for ln in switch_report(CHK): print(ln, file=sys.stderr)
if DRY:                                           # 下見: これから Wan で作る組（置き場にまだ無い組）
    todo = sorted({f"{r['from']}→{r['to']}" for r in CHK if r["status"] != "skip" and r.get("engine") == "wan" and not r.get("wan_ready")})
    print(f"Wan で新しく作る組: {len(todo)}{'（' + '、'.join(todo) + '）' if todo else ''}", file=sys.stderr)
MOFF = mouth_off_spans(SPEAK, FACEP, FPS, f0)    # 口の検査: 口の部品の無い姿勢（face: false）で話している所（口が止まって見える）
for ln in mouth_report(MOFF): print(ln, file=sys.stderr)
MSHUT = [s_ for s_ in mouth_shut_spans(LOUD, SPEAK, FPS, f0)            # 声が出ているのに口が閉じている所。口の部品の無い姿勢の所は上で数えた
         if not any(m_["from"] <= s_["from"] and s_["to"] <= m_["to"] for m_ in MOFF)]
for ln in mouth_shut_report(MSHUT, LIPSYNC == "amp"): print(ln, file=sys.stderr)
NBAD = sum(r["status"] not in ("ok", "skip") for r in CHK) + sum(s["long"] for s in MOFF) + (len(MSHUT) if LIPSYNC == "amp" else 0)   # モーラ式は知らせるだけ
HSP = head_spans(HEAD_KEYS, P.home if P.home in HEAD_IDX else None) if HEAD_KEYS else []
CHKF = os.path.splitext(OUTF)[0] + (".precheck.json" if DRY else ".check.json")
json.dump({"video": None if DRY else os.path.abspath(OUTF), "fps": FPS, "from": T0, "to": T1, "problems": NBAD, "switches": CHK, "head_spans": HSP, "mouth_off": MOFF, "mouth_shut": MSHUT},
          open(CHKF, "w"), ensure_ascii=False, indent=1)
print(CHKF if DRY else OUTF)
if NBAD and "--strict" in sys.argv: die(f"切り替えの検査・口の検査で問題が {NBAD} 件（{CHKF}）", 3)
