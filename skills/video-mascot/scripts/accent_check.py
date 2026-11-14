"""accent_check.py — 声の高さを、字幕の読みの高低（東京式）と比べる（読み・アクセントの自動検査の 3 段目）。

  vm voice <作業フォルダ> accent [行番号 ...] [--all]    （voice.py から呼ぶ）

  1. 基準: reading と同じ文（say の開きを字幕の漢字に戻し、用語辞書の語は辞書の読み）を読み手の見本（ojt.py）に通し、
     モーラごとの高低（句の型から決めた L/H）を出す。用語辞書の accent があれば、その語はそれで上書きする
  2. 声の音素（voice/phones.json、無ければ書き起こす）を基準の音素に並べ、モーラの頭の時刻を取る（CTC の時刻は音の頭に出る）。
     モーラの区間は、その頭から次のモーラの頭まで。高さはその後ろ 5 割の F0 の中央値（半音、行の中央値が 0）
  3. 語（助詞・助動詞・記号を除く）ごとに、語のモーラと、同じ句の次のモーラ（後ろの助詞の頭）を見て、次のどれかなら警告する
     - 頭が高い / 頭が低い: 1 モーラ目から 2 モーラ目へ、低高のはずが head 半音より下がる / 高低のはずが head 半音ほど下がらない
     - k の後で下がらない: 下がり目（k モーラ目の後）で drop 半音より下がらない。1 モーラ遅れて下がるのは許す（高さの山は後ろへずれやすい）
     - i-j で下がる: 高いまま続くはずの所で big 半音より下がる
  読みが字幕と違う語（reading の「!」「?」の語）は、モーラの対応がずれるので見ない。

閾値の既定（head 0.5・drop 1.0・big 6.0 半音）は、2026-11-14〜15 にユーザーが聞いた 63 語（誤り 8）で決めた。そのデータでは
誤り 8 件のうち 6 件を拾い、誤った警告は 3 件。決めたデータで測った成績なので、ほかの台本では甘めに出ている。
"""
import os, re, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "video-scene", "scripts"))
import reading_check as R  # noqa: E402

HEAD, DROP, BIG, LATE = 0.5, 1.0, 6.0, 0.5
OCT = 99.0    # F0 の外れ値は捨てない（文末の +12〜16 を 10 半音で捨てると、正しい語の誤った警告が増えた）
SKIP_POS = ("助詞", "助動詞", "記号", "フィラー")


def mora_onsets(ra, heard):
    """基準のモーラごとの頭の時刻（秒）。声の音素と同じ音素の並んだ所の始まりの最小。取れないモーラは前後から等分で補い、
    端は行のモーラの長さの中央値（分からなければ 0.12 秒）で延ばす。"""
    rt = R.norm([(p, mi) for mi, m in enumerate(ra["moras"]) for p in m["phs"]])
    hh = R.norm([(p, j) for j, (p, _, _) in enumerate(heard)])
    got = {}
    for i, j in R.align([p for p, _ in rt], [p for p, _ in hh]):
        if i is None or j is None or rt[i][0] != hh[j][0]: continue
        got.setdefault(rt[i][1], []).append(heard[hh[j][1]][1])
    n = len(ra["moras"]); c = [min(got[i]) if i in got else None for i in range(n)]
    known = [i for i in range(n) if c[i] is not None]
    for i in range(n):
        if c[i] is None:
            lo = max((k for k in known if k < i), default=None); hi = min((k for k in known if k > i), default=None)
            if lo is not None and hi is not None: c[i] = c[lo] + (c[hi] - c[lo]) * (i - lo) / (hi - lo)
    # 端の取れないモーラ（行末の長音は norm で前の母音にまとまり、時刻が付かない）は、行のモーラの長さの中央値で延ばす
    if known:
        steps = [c[b] - c[a] for a, b in zip(known, known[1:]) if c[b] > c[a]]
        med = float(np.median([s / (b - a) for s, (a, b) in zip(steps, [(a, b) for a, b in zip(known, known[1:]) if c[b] > c[a]])])) if steps else 0.12
        first, last = known[0], known[-1]
        for i in range(last + 1, n): c[i] = c[last] + med * (i - last)
        for i in range(first): c[i] = max(0.0, c[first] - med * (first - i))
    return c


def mora_pitch(t, st, c, i, late=LATE):
    """モーラ i の高さ（半音）。区間はモーラの頭から次の頭まで（無ければ 0.15 秒、長くても 0.3 秒）の後ろ late 割。声が無ければ None。"""
    if c[i] is None: return None
    lo = c[i]; nx = c[i + 1] if i + 1 < len(c) else None
    hi = nx if nx is not None and nx > lo else lo + 0.15
    hi = min(hi, lo + 0.3); lo = lo + (hi - lo) * (1 - late)
    sel = (t >= lo) & (t <= hi) & np.isfinite(st) & (np.abs(st) <= OCT)
    return float(np.median(st[sel])) if int(sel.sum()) >= 2 else None


def verdict(want, p, head=HEAD, drop=DROP, big=BIG):
    """want: 'LHHL' のような高低の列、p: モーラごとの半音（None は測れない）。違う所の理由の並びを返す（無ければ []）。"""
    v = [(i, x) for i, x in enumerate(p) if x is not None]
    why = []
    if len(v) >= 2 and v[0][0] == 0:
        (_, x0), (i1, x1) = v[0], v[1]
        if want[0] == "L" and want[i1] == "H" and x1 - x0 < -head: why.append("頭が高い")    # 比べる相手が高いはずのモーラのときだけ
        if want[0] == "H" and want[i1] == "L" and x0 - x1 < head: why.append("頭が低い")
    for k in range(len(want) - 1):
        if want[k] == "H" and want[k + 1] == "L":
            a = [x for i, x in v if i <= k and want[i] == "H"]; b = [x for i, x in v if i > k]
            ok = bool(a and b and a[-1] - b[0] >= drop)
            if not ok:
                a2 = [x for i, x in v if i <= k + 1]; b2 = [x for i, x in v if i > k + 1]
                ok = bool(a2 and b2 and a2[-1] - b2[0] >= drop)
            if a and b and not ok: why.append(f"{k + 1} モーラ目の後で下がらない")
            break
    for (i, x), (j, y) in zip(v, v[1:]):
        if all(want[m] == "H" for m in range(i, j + 1)) and x - y > big: why.append(f"{i + 1}〜{j + 1} モーラ目で下がる")
    return why


def _term_accent(terms):
    """用語辞書の語 → （語の中の高低の列、後ろの助詞の高低）。accent の無い辞書（テストの仮の物）は外す。"""
    out = {}
    for t in terms:
        acc = getattr(t, "accent", None)
        if not acc: continue
        k = getattr(t, "type", None)
        out[t.word] = (acc, "H" if k == 0 else "L")
    return out


def term_spans(text, ref, terms):
    """基準の文の中で、用語辞書の語に当たる文字の範囲 [(始め, 終わり, 辞書の語), ...]。字幕の中の辞書の語を、
    字幕と基準の文の文字の対応で基準の文へ写し、そこが辞書の読み（仮名）になっている所だけを取る。
    基準の文では辞書の語は仮名になっている（apply_terms で置き換えたか、say に初めから読みで書いてあった）。"""
    import say_lint as SL
    if not terms: return []
    t = SL._strip_spaces(text)[0]; ops = SL._align(t, ref); out = []
    for tm in terms:
        want = SL.to_hira(tm.reading)
        for m in re.finditer(re.escape(tm.word), t):
            x, y = SL._t2s(ops, m.start(), False), SL._t2s(ops, m.end(), True)
            if x is None or y is None: continue
            seg = ref[x:y]; core = seg.strip("".join(SL.PUNCT)); x += len(seg) - len(seg.lstrip("".join(SL.PUNCT)))
            if SL.to_hira(core) == want: out.append((x, x + len(core), tm.word))
    return out


def check_line(text, say, heard, wav, terms=(), f0=None):
    """1 行の検査。heard は [[音素, 始め, 終わり], ...]。返り値は [{word, want, pitches, why, t}]（違う所だけ）。"""
    import ojt, accent as A
    ref = R.reference_text(text, say, terms)
    ra = ojt.analyze(ref)
    ref2 = R.apply_terms(ra, ref, terms)
    if ref2: ref, ra = ref2, ojt.analyze(ref2)
    tspans = term_spans(text, ref, terms)
    skip = [r["ref_span"] for r in R.check_line(text, say, [p for p, _, _ in heard], terms) if r.get("ref_span")]   # 読みが違う所（文字の範囲）
    c = mora_onsets(ra, heard)
    if f0 is None:
        t, hz = A.f0_track(wav); f0 = (t, A.to_semitones(hz))
    t, st = f0
    tacc = _term_accent(terms)
    import say_lint as SL
    # 仮名に開いたかどうかは、辞書の除外を使わずに見る（辞書の読みで開いた語も、開いた語として先に出す）
    opened = [f.src for f in SL.lint_line(text, say, (), use_reader=False) if f.kind == "open"]
    # 見る単位: 辞書の語（仮名に置き換えた範囲にかかる見本の語をまとめた物）と、それ以外の語 1 つずつ
    units, used = [], set()
    for a_, b_, w in tspans:
        ks = [k for k, n in enumerate(ra["nodes"]) if n["start"] is not None and n["start"] < b_ and n["end"] > a_]
        if ks: units.append((w, ks)); used.update(ks)
    for k, n in enumerate(ra["nodes"]):
        if k not in used: units.append((n["string"], [k]))
    units.sort(key=lambda u: u[1][0])
    out = []
    for word, ks in units:
        n = ra["nodes"][ks[0]]; k = ks[-1]
        if word not in tacc and (n["pos"] in SKIP_POS or not n["mora"]): continue
        a_ = min(ra["nodes"][kk]["start"] for kk in ks if ra["nodes"][kk]["start"] is not None) if any(ra["nodes"][kk]["start"] is not None for kk in ks) else None
        b_ = max(ra["nodes"][kk]["end"] for kk in ks if ra["nodes"][kk]["end"] is not None) if a_ is not None else None
        if a_ is not None and any(x < b_ and y > a_ for x, y in skip): continue
        ms = [i for kk in ks for i in ra["nodes"][kk]["mora"]]
        if not ms: continue
        nx = ojt.next_in_phrase(ra, ks)
        want = "".join(ra["moras"][i]["hl"] for i in ms)
        if word in tacc:
            acc, after = tacc[word]
            if len(acc) == len(ms): want = acc
            if nx: nx = [dict(nx[0], hl=after)]
        if nx: ms.append(ra["moras"].index(ojt.next_in_phrase(ra, ks)[0])); want += nx[0]["hl"]
        if len(ms) < 2: continue
        p = [mora_pitch(t, st, c, i) for i in ms]
        why = verdict(want, p)
        if why:
            end = c[ms[-1] + 1] if ms[-1] + 1 < len(c) and c[ms[-1] + 1] is not None else (c[ms[-1]] + 0.2 if c[ms[-1]] is not None else None)
            after = next((m["string"] for m in ra["nodes"][k + 1:] if m["mora"]), "") if nx else ""
            out.append({"word": word + ("+" + after if after else ""),
                        "want": want, "pitches": [None if x is None else round(x, 1) for x in p], "why": why, "t": c[ms[0]], "end": end,
                        "opened": any(o in word or word in o for o in opened)})
    return out


def report(lines, phones, wav_of, terms=(), show_all=False):
    """行番号 → 声の音素、行番号 → 声の wav を受け取って出す。出した警告の並びを返す。
    既定では say で仮名に開いた語だけを出し、ほかの語は数だけ（show_all で出す）。理由: ユーザーが聞いた語（2026-11-14〜15）で、
    仮名に開いた語の警告は 9 件のうち 6 件が本当の誤り、開いていない語の警告は 15 件のうち 1 件だった。"""
    found = []
    for n, ph in phones.items():
        l = lines[n - 1]
        for r in check_line(l.get("text", ""), l.get("say"), ph, wav_of(n), terms): found.append(dict(r, line=n))
    found.sort(key=lambda r: (not r["opened"], r["line"]))
    hidden = 0 if show_all else sum(not r["opened"] for r in found)
    if not show_all: found = [r for r in found if r["opened"]]
    for r in found:
        hi = " ".join("·" if x is None else f"{x:+.1f}" for x in r["pitches"])
        t = "" if r["t"] is None else f"{r['t']:.2f} 秒、"
        tag = "（仮名に開いた語）" if r["opened"] else ""
        print(f"! 行{r['line']}: {r['word']} の高さが違う{tag}（{t}{'・'.join(r['why'])}）。期待 {r['want']}、測った高さ [{hi}]", flush=True)
    no = sum(r["opened"] for r in found)
    print(f"高さの検査（{len(phones)} 行）: 「!」{len(found)} 件（仮名に開いた語 {no}、ほかの語 {len(found) - no}）"
          + (f"。仮名に開いていない語の疑い {hidden} 件は出していない（当たりが少ない。--all で出す）" if hidden else ""), flush=True)
    if found:
        print("  「!」は聴いて確かめる（--clips で語の前後を切り出した聞き取り用の音声を作れる）。仮名に開いた語は当たりが多い（聞いた 9 件のうち 6 件）。"
              "開いていない語は、句の頭が低く入らないだけの所も拾い、当たりが少ない（聞いた 15 件のうち 1 件）。"
              "違っていれば、その行を作り直すか、漢字・仮名の書き方を変える。語の正しい高さは用語辞書の accent に書くと、それを基準にする", flush=True)
    return found


def make_clips(items, wav_of, out, text_of=None):
    """警告の語の前後を切り出し、番号の数だけ「ピッ」（低く長いのが 10、高く短いのが 1）を鳴らしてから 2 回ずつ流す 1 本の音声と、番号の一覧を作る。
    items は report の返り値（line・t・end の付いた物）。out は .mp3 のパス。一覧は同じ名前の .md。"""
    import subprocess, tempfile
    ff = lambda *a: subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)
    with tempfile.TemporaryDirectory() as td:
        ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "1.0", f"{td}/sil.wav")
        ff("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.12", f"{td}/gap.wav")
        ff("-f", "lavfi", "-i", "sine=frequency=700:sample_rate=48000:duration=0.35", "-af", "volume=0.25", f"{td}/b10.wav")
        ff("-f", "lavfi", "-i", "sine=frequency=1200:sample_rate=48000:duration=0.10", "-af", "volume=0.25", f"{td}/b1.wav")
        parts, md = [], ["# 聞き取り", "", "番号の数だけ「ピッ」（低く長いのが 10、高く短いのが 1）のあと、その語の前後の声が 2 回流れる。",
                         "【】の語（後ろの助詞まで）が正しい高さ・読みに聞こえるかを OK / NG で。NG なら「低高高」の形で、聞こえた高さと正しい高さを。", ""]
        for i, r in enumerate(items, 1):
            if r.get("t") is None: continue
            tens, ones = divmod(i, 10)
            parts += [f"{td}/b10.wav", f"{td}/gap.wav"] * tens + [f"{td}/b1.wav", f"{td}/gap.wav"] * ones
            t0 = max(0.0, r["t"] - 0.9); d = (r["end"] or r["t"] + 0.3) + 1.1 - t0
            c = f"{td}/c{i}.wav"
            ff("-ss", f"{t0:.3f}", "-t", f"{d:.3f}", "-i", wav_of(r["line"]), "-af",
               "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:d=0.05,areverse,afade=t=in:d=0.05,areverse", "-ar", "48000", "-ac", "1", c)
            parts += [f"{td}/sil.wav", c, f"{td}/sil.wav", c, f"{td}/sil.wav", f"{td}/sil.wav"]
            md.append(f"{i}. 行{r['line']}　【{r['word'].replace('+', '')}】" + (f"　全文: {text_of(r['line'])}" if text_of else ""))
        open(f"{td}/l.txt", "w", encoding="utf-8").write("".join(f"file '{p}'\n" for p in parts))
        ff("-f", "concat", "-safe", "0", "-i", f"{td}/l.txt", "-ar", "48000", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "3", out)
    open(os.path.splitext(out)[0] + ".md", "w", encoding="utf-8").write("\n".join(md) + "\n")
    return out
