"""say_lint.py — 合成に渡す文（say）の書き方を、字幕（text）と比べて検査する。声は作らない・聞かない。

  vm voice <作業フォルダ> lint [行番号 ...]    （voice.py から呼ぶ）

見つけるもの:
  - open   字幕で漢字の所を、say で仮名に開いた。仮名に開くとアクセントの手がかりが消え、
           同じ音の別の語（表→ひょう＝豹・雹、手元→てもと）や別の読み（色は→いろは）で読まれることがある
  - comma  字幕に無い読点・句点を say に足した。足した所で息つぎの間ができる（「開く、表だ」で 0.76 秒）
  - comma_space  字幕の空白を say で読点にした（「表は Claude の」→「表は、クロードの」）。間ができるのは同じだが、
           区切りとして自然な所が多いので分けて出す
英字・数字を仮名にした所（Claude→クロード）は検査しない（読ませるには開くしかない）。
用語辞書（video-scene の data/terms.yaml と config.voice.terms）にある語を、辞書の読みどおりに開いた所は open にしない。

読み手の見本（pyopenjtalk-plus、video-scene の ojt.py）があれば、開いた所ごとに say と「その語だけ漢字に戻した say」を比べ、
読みか句の中の高低が変わる所だけに「!」を付ける（変わらない所は数だけ出す）。読点は、修飾の途中（動詞・形容詞・助動詞と名詞の間）の
物だけに「!」を付ける。見本が無ければ、開いた所と足した読点の全部に「!」を付ける。
見本の読みが誤っていることもある（何人→なにニン、型締力→かたしめ）。say の読みが正しければ、その語を用語辞書に足すと次から出ない。
"""
import difflib, os, re, sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "video-scene", "scripts"))    # ojt・terms

PUNCT = set("、。，,．.")
SPACE = re.compile(r"\s")


def is_kanji(c):
    o = ord(c)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or c in "\u3005\u3006"      # 々 〆


def is_kana(c):
    o = ord(c)
    return 0x3041 <= o <= 0x3096 or 0x30A1 <= o <= 0x30FA or c in "\u30fc\u309d\u309e\u30fd\u30fe"   # ー ゝ ゞ ヽ ヾ


def to_hira(s):
    return "".join(chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s)


@dataclass
class Finding:
    kind: str          # open / comma / comma_space
    src: str           # 字幕の側（open は開いた漢字、comma は空）
    say: str           # say の側（open は開いた仮名、comma は足した記号）
    pos: int           # 字幕（空白を除いた文字列）の中の位置
    ctx: str           # 字幕の前後（【】で囲む）
    end: int = 0       # 字幕の側の終わり
    say_pos: tuple = (0, 0)   # say（空白を除いた文字列）の中の範囲
    extra: dict = field(default_factory=dict)   # 読み手の見本で比べた結果（change: 読み / 高さ / None、text・say の音と高低）

    def describe(self):
        if self.kind == "open":
            e = self.extra; ch = e.get("change", "?")
            why = {"読点": "。間に読点があるので見本で比べていない", "対応": "。見本の語と対応が取れず比べていない"}
            how = why.get(e.get("why"), "") if ch == "?" else (f"。読みが変わる（漢字のまま {e['t_word']} {e['t_sound']}、say {e['s_word']} {e['s_sound']}）" if ch == "読み" else
                                         f"。高さが変わる（漢字のまま {e['t_word']} {e['t_pitch']}、say {e['s_word']} {e['s_pitch']}）" if ch == "高さ" else "。読みも高さも同じ")
            return f"漢字を仮名に開いた: {self.src}→{self.say}（{self.ctx}）{how}"
        if self.kind == "comma":
            return f"字幕に無い「{self.say}」を足した（{self.ctx}）"
        if self.kind == "comma_soft":
            return f"字幕に無い「{self.say}」を足した（{self.ctx}）。句の切れ目なので間ができても崩れにくい"
        return f"字幕の空白を「{self.say}」にした（{self.ctx}）"

    @property
    def hard(self):
        """直す候補として「!」を付けて出すか。読み手の見本で比べられたときは、読みか高さが変わる開きと、修飾の途中の読点だけ。"""
        if self.kind == "open": return self.extra.get("change", "?") is not None
        return self.kind == "comma"


def _strip_spaces(text):
    """空白を除いた文字列と、各位置の直前に空白があったかの表（長さ len+1）を返す。"""
    out, sp, pending = [], [], False
    for c in text:
        if SPACE.match(c):
            pending = True; continue
        out.append(c); sp.append(pending); pending = False
    sp.append(pending)
    return "".join(out), sp


def _ctx(t, a, b, w=6):
    return ("…" if a > w else "") + t[max(0, a - w):a] + "【" + t[a:b] + "】" + t[b:b + w] + ("…" if b + w < len(t) else "")


def _align(t, s):
    """字幕と say の文字の対応（difflib の opcodes）。同じ文字が続く所では「同じ」の区間を say の右へ寄せる。
    「手元と」と「てもとと」なら、字幕の「と」を「てもと」の「と」ではなく後ろの「と」に合わせる（読みは後ろの助詞の手前まで続く）。"""
    ops = [list(o) for o in difflib.SequenceMatcher(None, t, s, autojunk=False).get_opcodes()]
    moved = True
    while moved:
        moved = False
        for k in range(1, len(ops) - 1):
            p_, e, n_ = ops[k - 1], ops[k], ops[k + 1]
            if e[0] != "equal" or p_[0] == "equal" or n_[0] == "equal" or n_[4] <= n_[3]: continue
            j1, j2 = e[3], e[4]
            if s[j1:j2] != s[j1 + 1:j2 + 1]: continue
            p_[4] += 1; e[3] += 1; e[4] += 1; n_[3] += 1; moved = True
        for o in ops:
            if o[0] != "equal": o[0] = "replace" if o[2] > o[1] and o[4] > o[3] else ("delete" if o[2] > o[1] else "insert")
        ops = [o for o in ops if o[2] > o[1] or o[4] > o[3]]
    return [tuple(o) for o in ops]


def _t2s(ops, x, end):
    """字幕の境目 x に当たる say の位置。同じ文字の続く所はそのまま、置き換えの途中なら置き換え全体に広げる（頭は始め、終わりは終わり）。"""
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal" and i1 <= x <= i2: return j1 + (x - i1)
        if i1 < x < i2 or (x == i1 and not end) or (x == i2 and end): return j2 if end else j1
    return None


def _term_spans(t, s, ops, terms):
    """辞書の語が字幕に出る所のうち、その出現に当たる say の区間が辞書の読みと同じ物。出現ごとに確かめる
    （同じ行に 2 回出て片方だけ読みが違うとき、違う方を見逃さない。読みを含むだけの「てもとん」も通さない）。"""
    spans = []
    for tm in terms:
        if not tm.word: continue
        want = to_hira(tm.reading)
        for m in re.finditer(re.escape(tm.word), t):
            sa, sb = _t2s(ops, m.start(), False), _t2s(ops, m.end(), True)
            if sa is None or sb is None: continue
            got = "".join(c for c in to_hira(s[sa:sb]) if c not in PUNCT)
            if got == want: spans.append((m.start(), m.end()))
    return spans


def lint_line(text, say, terms=(), use_reader=True):
    """1 行の字幕と say を比べて Finding の並びを返す。say が無い・字幕と同じなら []。
    terms は .word と .reading を持つ物の並び（terms.Term）。"""
    if not say or say == text: return []
    t, sp = _strip_spaces(text)
    s, _ = _strip_spaces(say)
    ops = _align(t, s)
    spans = _term_spans(t, s, ops, terms)
    out = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal": continue
        ts, ss = t[i1:i2], s[j1:j2]
        added = [c for c in ss if c in PUNCT]
        removed = [c for c in ts if c in PUNCT]
        for c in added[len(removed):]:
            # 空白があったのは、置き換えの範囲の頭か、その中のどこか
            space = any(sp[k] for k in range(i1, i2 + 1))
            ctx = ("…" if i1 > 6 else "") + t[max(0, i1 - 6):i1] + "【" + c + "】" + t[i1:i1 + 6] + ("…" if i1 + 6 < len(t) else "")
            out.append(Finding("comma_space" if space else "comma", "", c, i1, ctx, end=i2, say_pos=(j1, j2)))
        tk = "".join(c for c in ts if c not in PUNCT)
        sk = "".join(c for c in ss if c not in PUNCT)
        if op == "replace" and tk and sk and any(is_kanji(c) for c in tk) and all(is_kana(c) for c in sk):
            if any(a <= i1 and i2 <= b for a, b in spans): continue
            # 表示は漢字のまとまり全体（「手入れ」の「手入」が 1 字ずつに割れても、前後の漢字をつけて出す）
            a, b = i1, i2
            while a > 0 and is_kanji(t[a - 1]): a -= 1
            while b < len(t) and is_kanji(t[b]): b += 1
            out.append(Finding("open", tk, sk, i1, _ctx(t, a, b), end=i2, say_pos=(j1, j2)))
    if use_reader: _compare_reader(t, s, None, out)
    return out


def _revert_opens(s, opens):
    """say の開いた仮名を全部、字幕の漢字に戻した文と、say の位置 → 戻した文の位置の対応（頭用・終わり用）を返す。
    足した読点はそのまま残す（読点の効き目は別に出す）。"""
    spans = []
    for f in opens:
        j1, j2 = f.say_pos; ss = s[j1:j2]
        lead = len(ss) - len(ss.lstrip("".join(PUNCT))); trail = len(ss) - len(ss.rstrip("".join(PUNCT)))
        spans.append((j1 + lead, j2 - trail, f.src))
    spans.sort()
    out, lo, hi, k = [], [0] * (len(s) + 1), [0] * (len(s) + 1), 0
    pos = 0
    for c1, c2, src in spans + [(len(s), len(s), "")]:
        for x in range(pos, c1 + 1): lo[x] = hi[x] = k + (x - pos)
        out.append(s[pos:c1]); k += c1 - pos
        if c2 > c1 or src:
            for x in range(c1 + 1, c2 + 1): lo[x] = k; hi[x] = k + len(src)
            lo[c1] = k; hi[c2] = k + len(src)
            out.append(src); k += len(src)
        pos = c2
    return "".join(out), lo, hi, spans


def _compare_reader(t, s, ops, found):
    """読み手の見本（pyopenjtalk）で、開いた所を確かめて Finding.extra に書く。
    比べるのは say と、say の開いた語を全部字幕の漢字に戻した文（足した読点はそのまま）。開いたことの効き目だけが出る。
    「一つ目」が「ひと」「め」に割れても、両方を戻した「一つ目」で比べる。
    読点は、前が動詞・形容詞・助動詞で後ろが名詞（修飾の途中）のものだけ comma に残し、他は comma_soft にする。"""
    import ojt
    if not ojt.available(): return
    at, as_ = ojt.analyze(t), ojt.analyze(s)
    opens = []
    for f in found:
        if f.kind != "open": continue
        inner = s[f.say_pos[0]:f.say_pos[1]].strip("".join(PUNCT))
        if any(c in PUNCT for c in inner):
            # 置き換えの途中に読点がある（入力方法 → にゅうりょく、ほうほう）。読点が漢字のどこに入るか分からないので、
            # 戻した文を作ると読点の有無まで変わる。比べずに「!」のまま出す
            f.extra = {"change": "?", "why": "読点"}
        else: opens.append(f)
    if opens:
        s2, lo, hi, spans = _revert_opens(s, opens)
        a2n = ojt.analyze(s2)
        back_lo = {}; back_hi = {}
        for x in range(len(s) + 1):
            back_lo.setdefault(lo[x], x); back_hi[hi[x]] = x
        for f, (c1, c2, _) in zip(sorted(opens, key=lambda f: f.say_pos), spans):
            a, b = c1, c2
            for _ in range(6):
                a, b, ks = ojt.region(as_, a, b)
                x, y, k2 = ojt.region(a2n, lo[a], hi[b])
                na = min(a, min((v for u, v in back_lo.items() if u >= x), default=a))
                nb = max(b, max((v for u, v in back_hi.items() if u <= y), default=b))
                if (na, nb) == (a, b): break
                a, b = na, nb
            mo, mk = ojt.region_moras(as_, ks), ojt.region_moras(a2n, k2)
            # 高さは同じ句の次のモーラ（後ろの助詞の頭）まで比べる。尾高と平板の違いはそこに出る
            no, nk = ojt.next_in_phrase(as_, ks), ojt.next_in_phrase(a2n, k2)
            e = {"t_word": s2[x:y] + ("+" + "".join(m["ph"] for m in nk) if nk else ""), "s_word": s[a:b] + ("+" + "".join(m["ph"] for m in no) if no else ""),
                 "t_sound": ojt.sound(mk), "s_sound": ojt.sound(mo), "t_pitch": ojt.pitch(mk + nk), "s_pitch": ojt.pitch(mo + no)}
            if not mo or not mk: e["change"] = "?"; e["why"] = "対応"   # 語が見つからない。比べていないのに「同じ」にしない
            else: e["change"] = "読み" if e["t_sound"] != e["s_sound"] else ("高さ" if e["t_pitch"] != e["s_pitch"] else None)
            f.extra = e
    for f in found:
        if f.kind == "comma":
            prev = [n for n in at["nodes"] if n["end"] is not None and n["end"] <= f.pos]
            nxt = [n for n in at["nodes"] if n["start"] is not None and n["start"] >= f.pos]
            if not (prev and nxt and prev[-1]["pos"] in ("動詞", "形容詞", "助動詞") and nxt[0]["pos"] == "名詞"):
                f.kind = "comma_soft"


def load_all_terms(cfg_terms=None, base=None):
    """video-scene の辞書と、作業フォルダの辞書（config.voice.terms、相対なら作業フォルダから）を合わせて読む。"""
    import terms as T
    out = list(T.load_terms())
    for p in ([cfg_terms] if isinstance(cfg_terms, str) else (cfg_terms or [])):
        if base and not os.path.isabs(p): p = os.path.join(base, p)
        out += T.load_terms(p)
    return out


def lint_lines(lines, only=None, terms=()):
    """行番号（1 始まり）→ Finding の並び。only で行を絞る。"""
    res = {}
    for n, l in enumerate(lines, 1):
        if only and n not in only: continue
        res[n] = lint_line(l.get("text", ""), l.get("say"), terms)
    return res


def report(res, show_all=False):
    """結果を出して、「!」の付いた数を返す。"""
    import ojt
    hard = 0; quiet = 0
    for n, fs in res.items():
        for f in fs:
            if f.hard: print(f"! 行{n}: {f.describe()}", flush=True); hard += 1
            elif show_all or f.kind != "open": print(f"  行{n}: {f.describe()}", flush=True)
            if f.kind == "open" and not f.hard: quiet += 1
    reader = "あり" if ojt.available() else "無し（pyopenjtalk-plus を入れると、読みと高さが変わる所だけに絞れる。入れ方は video-scene の setup.sh を VS_ACCENT_CHECK=1 で）"
    print(f"say の検査（{len(res)} 行、読み手の見本 {reader}）: 「!」{hard} 件" + (f"、開いても読みと高さが変わらない所 {quiet} 件（--all で出す）" if quiet and not show_all else ""), flush=True)
    if hard:
        print("  開いた語は、漢字に戻して読み違えないかを聴いて確かめる。仮名に開くと、同じ音の別の語の高さや別の読みで読まれやすい（表→ひょう＝豹、色は→いろは）。"
              "say の読みが正しく、漢字のままだと読み違える語は、用語辞書（video-scene の data/terms.yaml か config.voice.terms）に読みとアクセントを書くと次から出ない。"
              "足した読点は、そこで間を空けたいのでなければ外す", flush=True)
    return hard
