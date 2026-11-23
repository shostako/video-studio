"""動きの部品（opt-in）: 拠点の姿勢から出て拠点へ戻る短い動きを役ごとに登録し、台本の役から姿勢の切り替えを組む。
  vm units <作業フォルダ> list
      役と部品の一覧と、検査の結果を出す。
  vm units <作業フォルダ> check
      部品ごとに、作り置きの Wan の列（拠点→姿勢、姿勢→拠点）を検査し、units.checked.json に書く。
      動きの量（止まる続きが 3 コマ以上無い）、目の閉じ（Wan の勝手な瞬きと同じ照合）、着地（最後のコマと着く姿勢の絵の差）、
      顔の位置（顔の合わせの合いと 1 コマの跳び）。rife: true の部品（会釈など、描いた 2 枚の間を直に補間する組）は検査しない。
  vm units <作業フォルダ> build [--dry]
      config.cues（台本の役）から config.events・interp.durs（部品の組の分だけ）・head.events（units.idle があるとき）を
      組んで config.json に書く（最初の 1 回だけ元を config.json.bak_units に残す）。--dry は書かずに予定だけ出す。
      検査を通っていない部品、検査の後で列が変わった部品は使わない。
config の書き方は references/config-spec.md の「動きの部品」。"""
import json
import os
import shutil
import sys

import numpy as np

from lib import Proj, die, file_sig_mtime, interp_config, interp_on, pose_view

STILL_RUN, LAND_MAX, BG_MAX, CC_MIN, JUMP_MAX = 3, 3.0, 2.0, 0.85, 3.0   # 検査の境目（research/2026-11-23-motion-units）
UNIT_KEYS = {"name", "pose", "out", "hold", "back", "n", "rife"}
IDLE_DEFAULTS = {"min_gap": 1.8, "turn": 0.45, "hold": 0.5, "every": 6.0, "sides": None}


def units_config(cfg):
    """config.units を検める。{"base", "roles": {役: [部品, ...]}, "idle"（無ければ None）}。部品は name・pose・out・hold・back
    （秒）と、数える役の n、描いた 2 枚の間を直に補間する組の rife。"""
    u = cfg.get("units")
    if not isinstance(u, dict): raise ValueError("config.units が無い（references/config-spec.md の「動きの部品」）")
    poses = cfg.get("poses", {}); home = cfg.get("home", next(iter(poses), None)); base = u.get("base", home)
    if base not in poses: raise ValueError(f"units.base の姿勢が無い: {base}")
    if base != home: raise ValueError(f"units.base（{base}）は config.home（{home}）と同じにする（書き出しは home から始まる。PR #124 の Codex の指摘）")
    roles = u.get("roles")
    if not isinstance(roles, dict) or not roles: raise ValueError("units.roles は {役: [部品, ...]}")
    names, seen = set(), {}
    for r, vs in roles.items():
        if not isinstance(vs, list) or not vs: raise ValueError(f"units.roles.{r} は部品の並び")
        for x in vs:
            bad = set(x) - UNIT_KEYS
            if bad: raise ValueError(f"部品 {x.get('name')} に知らない項目: {sorted(bad)}")
            for k in ("name", "pose", "out", "hold", "back"):
                if k not in x: raise ValueError(f"役 {r} の部品に {k} が無い: {x}")
            if x["name"] in names: raise ValueError(f"部品の名前が重なる: {x['name']}")
            names.add(x["name"])
            if x["pose"] not in poses: raise ValueError(f"部品 {x['name']} の姿勢が無い: {x['pose']}")
            if x["pose"] == base: raise ValueError(f"部品 {x['name']} の姿勢が拠点と同じ")
            for k in ("out", "hold", "back"):
                if not isinstance(x[k], (int, float)) or x[k] <= 0: raise ValueError(f"部品 {x['name']} の {k} は正の秒: {x[k]!r}")
            # 書き出しの切り替えの秒（interp.durs）は姿勢の組ごとに 1 つ。同じ姿勢の部品で違うと、後の部品が前の部品の秒を上書きする
            k_ = (float(x["out"]), float(x["back"])); p_ = seen.setdefault(x["pose"], (k_, x["name"]))
            if p_[0] != k_: raise ValueError(f"同じ姿勢 {x['pose']} の部品 {p_[1]} と {x['name']} で out/back が違う（{p_[0]} と {k_}）。揃える")
    idle = u.get("idle")
    if idle is not None:
        if not isinstance(idle, dict): raise ValueError("units.idle は辞書")
        bad = set(idle) - set(IDLE_DEFAULTS)
        if bad: raise ValueError(f"units.idle に知らない項目: {sorted(bad)}")
        idle = {**IDLE_DEFAULTS, **idle}
        span = 2 * idle["turn"] + idle["hold"]
        if idle["every"] < span + 0.2: raise ValueError(f"units.idle.every（{idle['every']}）は往復 1 回の長さ（2×turn＋hold＝{span:.2f} 秒）より 0.2 秒以上長くする")
        chain = (cfg.get("head") or {}).get("chain") or []
        if not idle["sides"]: raise ValueError("units.idle.sides に頭の向き（head.chain の姿勢）を書く")
        miss = [s for s in idle["sides"] if s not in chain]
        if miss: raise ValueError(f"units.idle.sides が head.chain に無い: {miss}")
        if base not in chain: raise ValueError(f"units.idle を使うなら head.chain に拠点 {base} を入れる")
    return {"base": base, "roles": roles, "idle": idle}


def pick(role_units, cue, turn, ok):
    """cue に合う部品。unit で名指し、n（数える役の何番目か）、どちらも無ければ役の部品を順に回す（turn は役ごとの回数）。"""
    r = cue["role"]; vs = [x for x in role_units.get(r, []) if ok(x)]
    if not vs: raise ValueError(f"役 {r} に検査を通った部品が無い")
    if "unit" in cue:
        vs = [x for x in vs if x["name"] == cue["unit"]]
        if not vs: raise ValueError(f"役 {r} に部品 {cue['unit']} が無いか、検査を通っていない")
        return vs[0]
    if "n" in cue:
        vs = [x for x in vs if x.get("n") == cue["n"]]
        if not vs: raise ValueError(f"役 {r} に {cue['n']} 番目の部品が無い")
        return vs[0]
    x = vs[turn.get(r, 0) % len(vs)]; turn[r] = turn.get(r, 0) + 1; return x


def plan(cues, U, ok, start, end, min_hold=0.3):
    """cues [{"role", "t"（着く秒）, ...}] を時刻の順に部品へ割り当て、[(出る秒, 着く秒, 戻り始める秒, 拠点に着く秒, 部品, cue), ...]、
    events、durs（部品の組の秒）、head の events（idle）を返す。次の部品の出だしに食い込むなら止まる秒を縮め、min_hold を割れば止める。"""
    base = U["base"]; turn = {}; rows = []
    for c in sorted(cues, key=lambda c: c["t"]):
        x = pick(U["roles"], c, turn, ok)
        rows.append([round(c["t"] - x["out"], 3), c["t"], c["t"] + x["hold"], None, x, c])
    for i, r in enumerate(rows):
        x = r[4]
        if r[0] < (rows[i - 1][3] if i else start): raise ValueError(f"{r[5].get('label', r[5]['role'])}（{r[1]:.2f} 秒）の出だしが前の部品の戻りか始まりと重なる")
        if i + 1 < len(rows):
            r[2] = min(r[2], rows[i + 1][0] - x["back"])
            if r[2] - r[1] < min_hold - 1e-6:
                raise ValueError(f"{r[5].get('label', r[5]['role'])}（{r[1]:.2f} 秒）と次の {rows[i + 1][5].get('label', rows[i + 1][5]['role'])}"
                                 f"（{rows[i + 1][1]:.2f} 秒）の間が詰まりすぎ（止まる秒 {r[2] - r[1]:.2f}）。どちらかを外すか時刻をずらす")
        r[2] = round(r[2], 3); r[3] = round(r[2] + x["back"], 3)
    if rows and rows[-1][3] > end + 1e-6: raise ValueError(f"最後の部品が声の終わり（{end:.2f} 秒）までに拠点に戻らない（{rows[-1][3]:.2f} 秒）")
    events, durs = [], {}
    for s, a, b, e, x, c in rows:
        events += [{"at": s, "pose": x["pose"]}, {"at": b, "pose": base}]
        durs[f"{base}>{x['pose']}"] = x["out"]; durs[f"{x['pose']}>{base}"] = x["back"]
    heads = []; idle = U["idle"]
    if idle:
        side = 0; need = 2 * idle["turn"] + idle["hold"]
        gaps = [(start, rows[0][0] if rows else end)] + [(rows[i][3], rows[i + 1][0]) for i in range(len(rows) - 1)] + ([(rows[-1][3], end)] if rows else [])
        for t0, t1 in gaps:                          # あいた所に、every 秒ごとに 1 回（少なくとも 1 回）。等しい間隔で真ん中に寄せる
            if t1 - t0 < max(idle["min_gap"], need + 0.2): continue
            k = max(1, min(int((t1 - t0) // idle["every"]), int((t1 - t0) // (need + 0.2))))   # 1 回ずつ枠に収まる回数まで
            for j in range(k):
                a = round(t0 + (t1 - t0) * (j + 0.5) / k - need / 2, 3); v = idle["sides"][side % len(idle["sides"])]; side += 1
                heads += [{"at": a, "pose": base}, {"at": round(a + idle["turn"], 3), "pose": v},
                          {"at": round(a + idle["turn"] + idle["hold"], 3), "pose": v}, {"at": round(a + need, 3), "pose": base}]
    return rows, events, durs, heads


# ---------- 検査 ----------
def wan_n(cfg):
    """今の設定で書き出しが使う Wan の列のコマ数（render.py の DIV * interp.mult - 1）。"""
    icfg = interp_config(cfg.get("interp"), None) or {}
    return int(cfg.get("inbetween_div", 6)) * int(icfg.get("mult", 8)) - 1


def interp_used(cfg, a, b):
    """書き出しが a→b を補間（Wan か描いた 2 枚の間の直の補間）で動かすか。render.py の wan_ok と同じ条件: engine が wan、
    interp.pairs に入っている（無ければ全部）、体と顔の向きが同じ。外れる組は検査した列も部品の秒も使われない（PR #124 の Codex の指摘）。"""
    icfg = interp_config(cfg.get("interp"), None); P_ = cfg.get("poses", {})
    return bool(icfg) and icfg.get("engine") == "wan" and a != b and a in P_ and b in P_ \
        and pose_view(P_[a]) == pose_view(P_[b]) and interp_on(icfg, a, b)


def rife_pair(cfg, a, b):
    """a↔b を描いた 2 枚の間の補間で書き出すか（render.py と同じく interp.wan.rife_pairs のどちら向きかにあるか）。"""
    icfg = interp_config(cfg.get("interp"), None) or {}
    rp = (icfg.get("wan") or {}).get("rife_pairs") or []
    return f"{a}>{b}" in rp or f"{b}>{a}" in rp


def wan_ready(P, cfg, a, b):
    """a→b の Wan の列が、書き出しと同じ判定（wanflf.ready: 元の絵・seed・指示文・後処理の印）で今の設定に合うか。
    合わなければ書き出しは列を作り直すので、検査した列とは別物になる（PR #124 の Codex の指摘）。"""
    from wanflf import ready
    icfg = interp_config(cfg.get("interp"), None)
    return interp_used(cfg, a, b) and ready(P, a, b, wan_n(cfg), icfg)


def wan_dir(P, a, b, n):
    return P.p("ib_wan", f"{a}__{b}", f"n{n}")


def wan_files(d):
    if not os.path.isdir(d): return []
    fs = [f for f in os.listdir(d) if f[:1] == "f" and f[1:].split(".")[0].isdigit()]
    return [os.path.join(d, f) for f in sorted(fs, key=lambda f: int(f[1:].split(".")[0]))]


def judge(seq, end_img, pats, tol, face_track):
    """1 本の列の検査。seq は [始点の絵, Wan のコマ..., 終点の絵]、face_track(コマ) は (合い, 顔の点)。"""
    import cv2
    from wanflf import blink_frames, bg_level
    d = [float(np.abs(seq[i + 1].astype(np.int16) - seq[i].astype(np.int16)).mean()) for i in range(len(seq) - 1)]
    run = best = 0
    for v in d[2:-2]:                                   # 端の緩やかな出入りは止まって当然なので除く
        run = run + 1 if v < 0.3 else 0; best = max(best, run)
    fr = seq[1:-1]
    bl = blink_frames(seq, pats, tol)
    land = float(np.abs(fr[-1].astype(np.int16) - end_img.astype(np.int16)).mean()); bg = abs(bg_level(fr[-1]) - bg_level(end_img))
    tr = [face_track(im) for im in fr]; ccs = [t[0] for t in tr]; pos = [t[1] for t in tr]
    jump = float(max(np.linalg.norm(pos[i + 1] - pos[i]) for i in range(len(pos) - 1))) if len(pos) > 1 else 0.0
    why = []
    if best >= STILL_RUN: why.append(f"止まる続き {best} コマ")
    if bl: why.append(f"目を閉じたコマ {bl}")
    if land >= LAND_MAX: why.append(f"着地の差 {land:.1f}")
    if bg >= BG_MAX: why.append(f"背景の明るさの差 {bg:.1f}")
    if min(ccs) < CC_MIN: why.append(f"顔の合い {min(ccs):.2f}")
    if jump > JUMP_MAX: why.append(f"顔の跳び {jump:.1f} px")
    return {"motion": round(float(np.mean(d)), 2), "still_run": best, "blink": bl, "land": round(land, 2), "bg": round(bg, 2),
            "cc_min": round(min(ccs), 3), "face_jump": round(jump, 2), "ok": not why, "why": "、".join(why)}


def check(P, cfg, U):
    import cv2
    from wanflf import eye_patches
    icfg = interp_config(cfg.get("interp"), None) or {}
    if icfg.get("engine") != "wan": die("動きの部品の検査は Wan の切り替え（interp.engine: \"wan\"）の作り置きを見る。config.interp を確かめる")
    n = wan_n(cfg)
    tol = (icfg.get("wan") or {}).get("blink_tol", 0.05); tol = 0.05 if tol is None else tol
    base = U["base"]; home = P.read_pose(base)
    pj = json.load(open(P.p(f"parts_{base}", "parts.json"))); m1 = cv2.imread(P.p(f"parts_{base}", "m1.png"), cv2.IMREAD_UNCHANGED)
    mx, my = pj["m1"][0] + m1.shape[1] / 2, pj["m1"][1] + m1.shape[0] / 2
    roi = (int(mx - 150), int(my - 200), int(mx + 150), int(my + 120))
    g1 = cv2.cvtColor(home, cv2.COLOR_BGR2GRAY).astype(np.float32)
    def face_track(im):
        x0, y0, x1, y1 = roi; g0 = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
        m = np.zeros(g0.shape, np.uint8); m[max(0, y0):y1, max(0, x0):x1] = 1; M = np.eye(2, 3, dtype=np.float32); cc = -1.0
        try: cc, M = cv2.findTransformECC(g0, g1, M, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5), m, 5)
        except cv2.error: pass
        A = cv2.invertAffineTransform(M); return float(cc), A @ np.array([mx, my, 1.0])
    out = {}
    for r, vs in U["roles"].items():
        for x in vs:
            if x.get("rife"):                            # 書き出しが補間で動かす組か（rife_pairs に無ければ Wan で動き、検査していない列になる）
                why = ("" if interp_used(cfg, base, x["pose"]) and interp_used(cfg, x["pose"], base) else
                       f"書き出しが {base}↔{x['pose']} を補間で動かさない（interp.pairs・向きを確かめる）")
                if not why and not rife_pair(cfg, base, x["pose"]): why = f"rife: true だが interp.wan.rife_pairs に {base}>{x['pose']} が無い（書き出しは Wan で動く）"
                out[x["name"]] = {"role": r, "ok": not why, "rife": True, "pairs": {}, **({"why": why} if why else {})}
                print(f"{x['name']:14s} {base + '<>' + x['pose']:22s} " + ("描いた 2 枚の間の補間（Wan の検査なし）" if not why else "NG " + why)); continue
            res = {}
            for a, b in ((base, x["pose"]), (x["pose"], base)):
                d = wan_dir(P, a, b, n); fs = wan_files(d)
                if not interp_used(cfg, a, b):
                    res[f"{a}>{b}"] = {"ok": False, "why": f"書き出しがこの組を補間で動かさない（interp.pairs・向きを確かめる）"}
                    print(f"{x['name']:14s} {a + '>' + b:22s} NG {res[f'{a}>{b}']['why']}"); continue
                if not fs or not wan_ready(P, cfg, a, b):
                    res[f"{a}>{b}"] = {"ok": False, "why": (f"作り置きが今の絵・設定に合わない: {os.path.relpath(d, P.root)}" if fs else
                                                           f"作り置きが無い: {os.path.relpath(d, P.root)}") + "（vm render で作る）"}
                    print(f"{x['name']:14s} {a + '>' + b:22s} NG {res[f'{a}>{b}']['why']}"); continue
                fr = [cv2.imread(f) for f in fs]; pa, pb = P.read_pose(a), P.read_pose(b)
                if fr[0].shape != pa.shape: fr = [cv2.resize(im, (pa.shape[1], pa.shape[0]), interpolation=cv2.INTER_AREA) for im in fr]
                size = (fr[0].shape[1], fr[0].shape[0])
                pats = [p for p in (eye_patches(P, a, size), eye_patches(P, b, size)) if p]
                j = judge([pa] + fr + [pb], pb, pats, tol, face_track); j["sig"] = file_sig_mtime(fs); res[f"{a}>{b}"] = j
                print(f"{x['name']:14s} {a + '>' + b:22s} 動き {j['motion']:5.2f} 止 {j['still_run']} 目 {len(j['blink'])} 着地 {j['land']:5.2f} "
                      f"背景 {j['bg']:5.2f} 顔の合い {j['cc_min']:.3f} 跳び {j['face_jump']:4.2f}  {'OK' if j['ok'] else 'NG ' + j['why']}")
            out[x["name"]] = {"role": r, "ok": all(v["ok"] for v in res.values()), "pairs": res, "n": n}
    json.dump(out, open(P.p("units.checked.json"), "w"), ensure_ascii=False, indent=1)
    good = [k for k, v in out.items() if v["ok"]]; bad = [k for k, v in out.items() if not v["ok"]]
    print(f"通った部品 {len(good)}: {good}" + (f"\n落ちた部品 {len(bad)}: {bad}" if bad else ""))
    return 0 if not bad else 1


def checked_ok(P, cfg, U):
    """検査を通っていて、検査の後で列が変わっていない部品か、を返す関数。"""
    f = P.p("units.checked.json")
    if not os.path.exists(f): die(f"検査の結果が無い: vm units {P.root} check")
    ch = json.load(open(f)); base = U["base"]; n = wan_n(cfg)
    def ok(x):
        r = ch.get(x["name"])
        if not r or not r.get("ok"): return False
        if r.get("rife") or x.get("rife"):
            return bool(x.get("rife")) and rife_pair(cfg, base, x["pose"]) and interp_used(cfg, base, x["pose"]) and interp_used(cfg, x["pose"], base)
        if r.get("n") != n: return False                    # 検査の後で interp.mult・inbetween_div を変えた（書き出しは別の長さの列を使う）
        for a, b in ((base, x["pose"]), (x["pose"], base)):
            j = r["pairs"].get(f"{a}>{b}")
            fs = wan_files(wan_dir(P, a, b, n))
            if not j or not fs or j.get("sig") != file_sig_mtime(fs) or not wan_ready(P, cfg, a, b): return False
        return True
    return ok


# ---------- 台本の役の時刻 ----------
def cue_times(P, cfg, cues):
    """config.cues の各役の着く秒。at（秒）、kw（ひらがなの並び）/ word（語の候補）＋ line（行番号）で声の時刻を引く（events と同じ）。"""
    from lib import find_time, find_word, vowel_frames, words_hira
    timing = json.load(open(P.p("voice", "timing.json")))
    starts = {x["n"]: x["start"] for x in timing["lines"]}; durs = {x["n"]: x["dur"] for x in timing["lines"]}
    need_words = any("kw" in c or "word" in c for c in cues)
    WH = hs = None
    if need_words:
        wf = P.p("voice", "master.words.json")
        if not os.path.exists(wf): die(f"語の時刻が無い: {wf}（vm voice で作る）")
        words = json.load(open(wf))
        import pykakasi; KK = pykakasi.kakasi()
        WH = [(h, s, e) for h, (w, s, e) in zip(words_hira([w for w, _, _ in words], KK.convert), words)]
        _, hs = vowel_frames(WH, 60, int(np.ceil(timing["end"] * 60)) + 1)
    out = []
    for i, c in enumerate(cues):
        if "role" not in c: die(f"cues[{i}] に role が無い: {c}")
        c = dict(c)
        if "at" in c: t, how = float(c["at"]), "秒"
        elif "kw" in c or "word" in c:
            if c.get("line") not in starts: die(f"cues[{i}] の line が台本の行に無い: {c.get('line')}")
            n = c["line"]
            t, how = (find_word(WH, starts[n], durs[n], tuple(c["word"]) if isinstance(c["word"], list) else (c["word"],), c.get("fallback", 0.5))
                      if "word" in c else find_time(hs, starts[n], durs[n], c["kw"], c.get("fallback", 0.5)))
        else: die(f"cues[{i}] に at か kw / word が無い: {c}")
        c["t"] = round(t + float(c.get("offset", 0)), 3); c["how"] = how
        c.setdefault("label", c.get("kw") or (c["word"] if isinstance(c.get("word"), str) else None) or c["role"])
        out.append(c)
    return out, float(timing["end"])


def build(P, cfg, U, dry):
    cues = cfg.get("cues")
    if not isinstance(cues, list) or not cues: die("config.cues（台本の役）が無い")
    ok = checked_ok(P, cfg, U)
    ct, end = cue_times(P, cfg, cues)
    est = [f"{c['label']}（{c['t']:.2f} 秒）" for c in ct if c["how"] == "推定"]
    if est: print(f"注意: 声の中に語が見つからず行の割合で見積もった役: {est}（kw は小さい「ゃゅょ」を含めない。含む語は word で書くか at で書く）", flush=True)
    try: rows, events, durs, heads = plan(ct, U, ok, 0.0, end)
    except ValueError as e: die(str(e))
    for (s, a, b, e, x, c) in rows:
        print(f"{s:8.2f}→{a:8.2f} {x['name']:14s}（{c['role']}・{c['label']}・{c['how']}）止まる {b - a:.2f} 秒、{e:8.2f} に拠点")
    if heads: print("頭の往復:", [(h["at"], h["pose"]) for h in heads[1::4]])
    if dry: return 0
    path = P.p("config.json")
    if not os.path.exists(path + ".bak_units"): shutil.copy(path, path + ".bak_units")
    raw = json.load(open(path))
    raw["events"] = events
    raw.setdefault("interp", {}).setdefault("durs", {}).update(durs)   # 部品の組の秒だけ書き替える（数える所の短い切り替えなどは残す）
    if U["idle"]: raw.setdefault("head", {})["events"] = heads
    json.dump(raw, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"書いた: {path}（events {len(events)}、頭の往復 {len(heads) // 4}）。次は vm render {P.root} --check-only")
    return 0


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in ("list", "check", "build"):
        print(__doc__.split("config の書き方")[0]); sys.exit(2)
    P = Proj(sys.argv[1]); cfg = P.cfg
    try: U = units_config(cfg)
    except ValueError as e: die(str(e))
    cmd = sys.argv[2]
    if cmd == "list":
        f = P.p("units.checked.json"); ch = json.load(open(f)) if os.path.exists(f) else {}
        ok = checked_ok(P, cfg, U) if ch else (lambda x: None)
        for r, vs in U["roles"].items():
            for x in vs:
                st = {True: "検査済み", False: "未検査か NG か列が変わった", None: "未検査"}[ok(x)]
                print(f"{r:10s} {x['name']:14s} {U['base']}→{x['pose']:13s} 出 {x['out']} 止 {x['hold']} 戻 {x['back']}"
                      f"{' n=' + str(x['n']) if 'n' in x else ''}{' rife' if x.get('rife') else ''}  {st}")
        if U["idle"]: print(f"拠点での頭の往復: {U['idle']}")
        return 0
    if cmd == "check": return check(P, cfg, U)
    return build(P, cfg, U, "--dry" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
