"""vm voice retry の中身。読み・高さの警告が出た行だけ、seed を替えた候補を作り、警告のいちばん少ない声を選ぶ。

数える警告は 2 つ。読みの「!」（reading_check の misread）と、say で仮名に開いた語の高さの「!」（accent_check の opened）。
数えない物と理由:
- lint の警告: say の文で決まり、seed を替えても変わらない。
- 読みの「?」（say の読みで読んだ）: say の文の誤りで、seed では直らない。
- 1 音だけの違い・仮名に開いていない語の高さ: ユーザーが聞いた答え合わせで当たりが少なかった（2026-11-14〜15）。
"""
import hashlib, os


def md5(path):
    with open(path, "rb") as f: return hashlib.md5(f.read()).hexdigest()


def seeds(base, n):
    """候補の seed。元の seed の次から n 個。同じ行を同じ n でもう一度流すと同じ候補になる（作り置きを使い回せる）。"""
    return [base + k for k in range(1, n + 1)]


def warnings(line, phones, wav, terms=()):
    """1 行の声の警告。phones は [[音素, 始め, 終わり], ...]。返り値は [{kind: reading|accent, word, t, end, why}]。"""
    import reading_check as R, accent_check as A
    text, say = line.get("text", ""), line.get("say")
    out = []
    for r in R.check_line(text, say, [p for p, _, _ in phones], terms):
        if r["kind"] != "misread": continue
        hs = r["h_span"]
        out.append({"kind": "reading", "word": r["word"], "t": phones[hs[0]][1] if hs else None, "end": phones[hs[1]][2] if hs else None,
                    "why": f"読み [{r['want']}] が声では [{r['got']}]"})
    for r in A.check_line(text, say, phones, wav, terms):
        if r["opened"]: out.append({"kind": "accent", "word": r["word"], "t": r["t"], "end": r.get("end"), "why": "・".join(r["why"])})
    return out


def key(w):
    """警告を候補どうしで突き合わせる鍵。語と種類（時刻は声ごとに違う）。"""
    return (w["kind"], w["word"])


def stuck(orig, cands):
    """元の声にもどの候補にも出た警告の鍵。seed では直らない物（見本の読み違い、say の書き方、Irodori の癖）。"""
    if not cands: return set()
    out = {key(w) for w in orig}
    for ws in cands: out &= {key(w) for w in ws}
    return out


def choose(orig, cands):
    """orig は元の声の警告の数、cands は [(seed, 警告の数), ...]（seed の順）。元より少ない候補のうち、いちばん少なく、
    同じ数なら先の seed を返す。元より少ない候補が無ければ None（元の声を残す）。"""
    best = None
    for s, k in cands:
        if k < orig and (best is None or k < best[1]): best = (s, k)
    return best[0] if best else None
