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


def job_key(job):
    """候補の作り置きの鍵。合成に渡す物（文・説明文・seed・速さ）と手本の声の中身。どれかが変われば別の候補として作り直す。"""
    import json
    ref = job.get("ref")
    d = {k: job.get(k) for k in ("text", "caption", "seed", "duration_scale")} | {"ref": md5(ref) if ref and os.path.exists(ref) else ref}
    return hashlib.md5(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:8]


def kanji_say(text, say, warns, terms=()):
    """say で仮名に開いた所のうち、高さの警告の出た語（warns、warnings の accent の項目。開いた所の位置 opens を持つ）に掛かる所だけを
    字幕の漢字に戻した say。戻す所が無ければ None。位置で決める（同じ字を含む別の語は戻さない）。用語辞書の読みどおりに開いた所は戻さない。
    say の空白は残す。理由: 仮名に開いた語は高さが外れやすく、漢字に戻すと直る（2026-11-15、ユーザーが聞いた 21 本で、漢字 14 本のうち
    OK 13・△ 1、仮名 7 本のうち OK 1）。"""
    import say_lint as SL
    if not say: return None
    want = {tuple(sp) for w in warns if w.get("kind") == "accent" for sp in w.get("opens", ())}
    s, sp = SL._strip_spaces(say)
    def inner_punct(f):    # 開いた所の中に読点などがある（戻すと間まで消える）。_compare_reader と同じく戻さない
        ss = s[f.say_pos[0]:f.say_pos[1]].strip("".join(SL.PUNCT))
        return any(c in SL.PUNCT for c in ss)
    opens = [f for f in SL.lint_line(text, say, terms, use_reader=False) if f.kind == "open" and tuple(f.say_pos) in want and not inner_punct(f)]
    if not opens: return None
    new, lo, _, _ = SL._revert_opens(s, opens)
    cut = sorted({lo[i] for i in range(len(s)) if sp[i]})    # 空白のあった所に戻す
    out = "".join(" " * (i in cut) + c for i, c in enumerate(new))
    return out if out != say else None


def warnings(line, phones, wav, terms=(), also=()):
    """1 行の声の警告。phones は [[音素, 始め, 終わり], ...]。返り値は [{kind: reading|accent, word, t, end, why}]。
    also は、仮名に開いていなくても数える高さの語の名前（漢字に戻した候補で、戻した語の警告を数えるため）。"""
    import reading_check as R, accent_check as A
    text, say = line.get("text", ""), line.get("say")
    out = []
    for r in R.check_line(text, say, [p for p, _, _ in phones], terms):
        if r["kind"] != "misread": continue
        hs = r["h_span"]
        out.append({"kind": "reading", "word": r["word"], "t": phones[hs[0]][1] if hs else None, "end": phones[hs[1]][2] if hs else None,
                    "why": f"読み [{r['want']}] が声では [{r['got']}]"})
    for r in A.check_line(text, say, phones, wav, terms):
        if r["opened"] or r["word"] in also:
            out.append({"kind": "accent", "word": r["word"], "t": r["t"], "end": r.get("end"), "why": "・".join(r["why"]), "opens": r.get("opens", [])})
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
    """orig は元の声の警告の数、cands は [(候補, 警告の数), ...]（試す順）。元より少ない候補のうち、いちばん少なく、
    同じ数なら先の候補を返す。元より少ない候補が無ければ None（元の声を残す）。"""
    best = None
    for s, k in cands:
        if k < orig and (best is None or k < best[1]): best = (s, k)
    return best[0] if best else None
