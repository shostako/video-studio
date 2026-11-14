"""reading_check.py — 声の読みを、字幕の読みと音素で比べる（読み・アクセントの自動検査の 2 段目）。

  vm voice <作業フォルダ> reading [行番号 ...]    （voice.py から呼ぶ）

  1. 基準の文: say の中で仮名に開いた語を字幕の漢字に戻した文（英字を仮名にした所・用語辞書どおりの開きは say のまま）。
     say を書いた人の誤り（色は→いろは）も、基準の側には入らない
  2. 基準の文を読み手の見本（pyopenjtalk、ojt.py）で音素にする。声は音素の CTC モデル（phonemes.py）で書き起こす
  3. 音素の並びを編集距離で突き合わせ、食い違いのある語を出す
     - misread  基準とも say の読みとも違う（漢字のまま 表 を おもて と読んだ）
     - say      say の読みどおりだが、字幕の読み（見本）と違う（いろは と書いたので いろは と読んだ）。
                見本の読みが誤っている語（何人→なにニン）でも出るので、say が正しければその語を用語辞書に足す
用語辞書の語は、辞書の読みを基準にする（読みの割れる語は作業フォルダの辞書 config.voice.terms に、その動画での読みを書く）。
長音（えい・えー、おう・おー）、母音の長短、無声化、ゆう・いう は同じ音として扱う（norm）。
misread に「!」（聴いて確かめる）、say に「?」（say と見本のどちらの読みが正しいかを決める。耳は要らない）を付ける。
見本は読みの割れる漢字を取り違える（表→おもて、描く→えがく、札→さつ）。声が正しければ、その語を用語辞書に足すと次から出ない。
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "video-scene", "scripts"))
import say_lint as SL  # noqa: E402


def reference_text(text, say, terms=()):
    """読みの基準にする文。say が無ければ字幕（の空白を除いた物）。"""
    t, _ = SL._strip_spaces(text)
    if not say: return t
    s, _ = SL._strip_spaces(say)
    opens = [f for f in SL.lint_line(text, say, terms, use_reader=False) if f.kind == "open"]
    return SL._revert_opens(s, opens)[0] if opens else s


def apply_terms(an, ref, terms):
    """用語辞書の語は、辞書の読みを基準にする。見本の語（node）がまるごと辞書の語と同じ所だけを仮名に置き換えた文を返す
    （「行」を登録しても「行く」の 行 は置き換えない）。置き換えが無ければ None。"""
    if not terms: return None
    want = {t.word: t.reading for t in terms}
    reps = [(n["start"], n["end"], want[n["string"]]) for n in an["nodes"] if n["string"] in want and n["start"] is not None]
    if not reps: return None
    out, pos = [], 0
    for a, b, r in reps:
        out.append(ref[pos:a] + r); pos = b
    return "".join(out) + ref[pos:]


def tokens(an):
    """見本の音素の並び [(音素, 語の番号)]。"""
    return [(p, m["node"]) for m in an["moras"] for p in m["phs"]]


def norm(ps):
    """比べるための音素の並び。書き起こしと見本の書き方の揺れをそろえる。ps は (音素, 札) の並びで、札（語の番号や声の位置）は持ち回る。
    - えい→ええ、おう→おお（長音の書き方）。続く同じ母音は 1 つに（長短は見ない。モデルは語末の「ティ」を「ティー」と出す）
    - ゆう→いう（「という」「言う」）、い＋や行の y を落とす（内圧 naiatsu と naiyatsu）"""
    ps = list(ps); out = []
    k = 0
    while k < len(ps):
        if [p for p, _ in ps[k:k + 3]] == ["y", "u", "u"]: out += [("i", ps[k][1]), ("u", ps[k + 2][1])]; k += 3; continue
        p, tag = ps[k]
        if p == "y" and out and out[-1][0] == "i" and k + 1 < len(ps) and ps[k + 1][0] in ("a", "u", "o"): k += 1; continue
        if out and ((p == "i" and out[-1][0] == "e") or (p == "u" and out[-1][0] == "o")): p = out[-1][0]
        if out and p in ("a", "i", "u", "e", "o") and p == out[-1][0]: k += 1; continue
        out.append((p, tag)); k += 1
    return out


def align(a, b):
    """編集距離で並べる。返り値は (i か None, j か None) の並び。"""
    n, m = len(a), len(b)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): D[i][0] = i
    for j in range(m + 1): D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j] + 1, D[i][j - 1] + 1, D[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    i, j, out = n, m, []
    while i or j:
        if i and j and D[i][j] == D[i - 1][j - 1] + (a[i - 1] != b[j - 1]): out.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i and D[i][j] == D[i - 1][j] + 1: out.append((i - 1, None)); i -= 1
        else: out.append((None, j - 1)); j -= 1
    return out[::-1]


def _bad_tokens(pairs, a, b):
    """食い違いに関わる a の位置の集合と、挿入された b の位置をどの a に付けたか（{a の位置: [b の位置, ...]}）。
    挿入は次の a の位置（無ければ前）に付ける。"""
    bad, ins, pend, last = set(), {}, [], None
    for i, j in pairs:
        if i is None: pend.append(j); continue
        if j is None or a[i] != b[j] or pend: bad.add(i)
        if pend: ins.setdefault(i, []).extend(pend)
        pend = []; last = i
    if pend and last is not None: bad.add(last); ins.setdefault(last, []).extend(pend)
    return bad, ins


def check_line(text, say, heard, terms=()):
    """1 行の検査。heard は音素の並び（phonemes.hear の phones の 1 つ目の要素）。返り値は食い違いの並び。
    各要素: {kind, word, want（基準の音素）, got（声の音素）, h_span（声の音素の位置の範囲。heard の添字）}"""
    import ojt
    ref = reference_text(text, say, terms)
    ra = ojt.analyze(ref)
    ref2 = apply_terms(ra, ref, terms)
    if ref2: ref, ra = ref2, ojt.analyze(ref2)
    rt = norm(tokens(ra)); hh = norm([(p, j) for j, p in enumerate(heard)])
    rn, hn = [p for p, _ in rt], [p for p, _ in hh]
    pairs = align(rn, hn)
    bad, ins = _bad_tokens(pairs, rn, hn)
    if not bad: return []
    sa = ojt.analyze(SL._strip_spaces(say)[0]) if say else ra
    sn = [p for p, _ in norm(tokens(sa))]
    spairs = align(sn, hn)
    sbad, _ = _bad_tokens(spairs, sn, hn)
    h_ok_say = {j for i, j in spairs if i is not None and j is not None and i not in sbad}   # say の読みと合っている声の音素
    h_of = {i: j for i, j in pairs if i is not None}
    # 食い違いの語を、続く語ごとにまとめる
    nodes = sorted({rt[i][1] for i in bad})
    groups = []
    for k in nodes:
        if groups and k == groups[-1][-1] + 1: groups[-1].append(k)
        else: groups.append([k])
    out = []
    for g in groups:
        idx = [i for i, (_, k) in enumerate(rt) if k in g]
        hs = [h_of[i] for i in idx if h_of.get(i) is not None] + [j for i in idx for j in ins.get(i, [])]   # 語の前後に入った音も含める
        h_span = list(range(min(hs), max(hs) + 1)) if hs else []
        word = "".join(ra["nodes"][k]["string"] for k in g)
        want = " ".join(rn[i] for i in idx)
        got = " ".join(hn[j] for j in h_span)
        kind = "say" if (say and h_span and all(j in h_ok_say for j in h_span) and SL._strip_spaces(say)[0] != ref) else "misread"
        span = (hh[h_span[0]][1], hh[h_span[-1]][1]) if h_span else None
        out.append({"kind": kind, "word": word, "want": want, "got": got, "h_span": span})
    return out


def report(lines, phones, terms=()):
    """行番号 → 声の音素 [[音素, 始め, 終わり], ...] を受け取り、行ごとに検査して出す。「!」の数を返す。"""
    hard = soft = 0
    for n, ph in phones.items():
        l = lines[n - 1]
        for r in check_line(l.get("text", ""), l.get("say"), [p for p, _, _ in ph], terms):
            t = f"{ph[r['h_span'][0]][1]:.2f}〜{ph[r['h_span'][1]][2]:.2f} 秒" if r["h_span"] else "声に無い"
            if r["kind"] == "misread":
                hard += 1; print(f"! 行{n}: {r['word']} の読みが違う（{t}）。字幕の読み [{r['want']}]、声 [{r['got']}]", flush=True)
            else:
                soft += 1; print(f"? 行{n}: {r['word']} は say の読みで読んだ（{t}）。字幕の読み [{r['want']}]、声 [{r['got']}]。say が正しければ用語辞書に足す", flush=True)
    print(f"読みの検査（{len(phones)} 行）: 「!」{hard} 件、「?」{soft} 件", flush=True)
    if hard:
        print("  「!」は声を聴いて確かめる。見本が読みの割れる漢字を取り違えた所（表→おもて、描く→えがく）もある。"
              "誤読なら、その行を作り直すか、言い換える（仮名に開くと高さが崩れやすい。vm voice lint）", flush=True)
    return hard
