"""台本の役（cues.json）と動きの部品（units.json、検査済みの units.checked.json）から、作業フォルダの config に
姿勢の切り替え（events・interp.durs）と、home にいる間の頭の小さな往復（head.events）を書く（2026-11-23）。
  - 同じ役が続けて来たら、その役の部品を順に替える（同じ役に 2〜3 種類）。cue に unit を書けばその部品、
    数える役は n（何番目か）でその部品
  - 部品は着く時刻（語の頭）から逆に out 秒前に動き出し、hold 秒止まって、back 秒で home に戻る。次の部品の出だしに
    食い込むなら、止まる秒を縮める（0.3 秒は残す）
  - home にいる間が idle.min_gap 秒以上あけば、頭を half_l / half_r へ回して戻す（左右を交互に）
使い方: python assemble.py <作業フォルダ> units.json cues.json   （元の config は config.json.bak_units に残す）"""
import sys, os, json, shutil

W, UF, CF = sys.argv[1:4]
U = json.load(open(UF)); C = json.load(open(CF)); base = U["base"]
chk = os.path.splitext(UF)[0] + ".checked.json"
ok = json.load(open(chk)) if os.path.exists(chk) else {}
if not ok: sys.exit(f"検査の結果が無い: {chk}（先に check_units.py）")
pool = {r: [u for u in vs if ok.get(u["name"], {}).get("ok")] for r, vs in U["roles"].items()}
# 書き出しの切り替えの秒（interp.durs）は姿勢の組ごとに 1 つ。同じ姿勢を使う部品で out/back が違うと、後の部品が
# 前の部品の秒を黙って上書きし、組んだ時刻と書き出しが食い違う（PR #122 の Codex の指摘）。揃っていなければ止める
seen = {}
for vs in U["roles"].values():
    for u in vs:
        k = (u["out"], u["back"]); p = seen.setdefault(u["pose"], (k, u["name"]))
        if p[0] != k: sys.exit(f"同じ姿勢 {u['pose']} の部品 {p[1]} と {u['name']} で out/back が違う（{p[0]} と {k}）。揃える")
turn = {r: 0 for r in pool}

plan = []                                   # (動き出す秒, 着く秒, 戻り始める秒, 戻り着く秒, 部品)
for c in C["cues"]:
    vs = pool.get(c["role"])
    if not vs: sys.exit(f"役 {c['role']} に検査を通った部品が無い")
    if "unit" in c:                         # 台本の側で部品を名指し（意味を固定したい所）
        vs = [u for u in vs if u["name"] == c["unit"]]
        if not vs: sys.exit(f"役 {c['role']} に部品 {c['unit']} が無いか、検査を通っていない")
        u = vs[0]
    elif "n" in c:                          # 数える役: 何番目か（n）で部品を選ぶ
        vs = [u for u in vs if u.get("n") == c["n"]]
        if not vs: sys.exit(f"役 {c['role']} に {c['n']} 番目の部品が無い")
        u = vs[0]
    else:
        u = vs[turn[c["role"]] % len(vs)]; turn[c["role"]] += 1
    s = round(c["arrive"] - u["out"], 2); plan.append([s, c["arrive"], c["arrive"] + u["hold"], None, u, c])
for i, p in enumerate(plan):
    u = p[4]
    if i + 1 < len(plan):                   # 次の出だしの前に home に着く
        latest = plan[i + 1][0] - u["back"]
        p[2] = min(p[2], latest)
        if p[2] - p[1] < 0.3: sys.exit(f"{p[5]['word']} と {plan[i + 1][5]['word']} の間が詰まりすぎ（止まる秒 {p[2] - p[1]:.2f}）")
    p[2] = round(p[2], 2); p[3] = round(p[2] + u["back"], 2)
    if plan[i][0] < (plan[i - 1][3] if i else 0): sys.exit(f"{p[5]['word']} の出だしが前の部品の戻りと重なる")

events, durs = [], {}
for s, a, r, e, u, c in plan:
    events += [{"at": s, "pose": u["pose"]}, {"at": r, "pose": base}]
    durs[f"{base}>{u['pose']}"] = u["out"]; durs[f"{u['pose']}>{base}"] = u["back"]

idle = U["idle"]; heads = []; side = 0
spans = [(C.get("start", 0.0), plan[0][0])] + [(plan[i][3], plan[i + 1][0]) for i in range(len(plan) - 1)] + [(plan[-1][3], C["end"])]
for t0, t1 in spans:
    if t1 - t0 < idle["min_gap"]: continue
    mid = (t0 + t1) / 2; need = 2 * idle["turn"] + idle["hold"]; a = round(mid - need / 2, 2); v = idle["sides"][side % len(idle["sides"])]; side += 1
    heads += [{"at": a, "pose": base}, {"at": round(a + idle["turn"], 2), "pose": v},
              {"at": round(a + idle["turn"] + idle["hold"], 2), "pose": v}, {"at": round(a + need, 2), "pose": base}]

cp = os.path.join(W, "config.json"); cfg = json.load(open(cp))
if not os.path.exists(cp + ".bak_units"): shutil.copy(cp, cp + ".bak_units")
cfg["events"] = events
cfg.setdefault("interp", {})["durs"] = durs
cfg.setdefault("head", {})["events"] = heads
json.dump(cfg, open(cp, "w"), ensure_ascii=False, indent=1)
for s, a, r, e, u, c in plan: print(f"{s:7.2f}→{a:7.2f} {u['name']:13s}（{c['role']}・{c['word']}）止まる {r - a:.2f} 秒、{e:7.2f} に home")
print("頭の往復:", [(h["at"], h["pose"]) for h in heads[1::4]])
