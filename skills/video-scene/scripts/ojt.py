"""ojt.py — 文を pyopenjtalk（pyopenjtalk-plus）に通し、語ごとの読み（モーラ）と、句の中の高低（L/H）を出す。

声は使わない。「標準的な東京式の読み手なら、この文をどう読むか」の見本を作る。
  - 語（node）: 文の中の文字の範囲、品詞、活用形、読み
  - モーラ: 音（hyo・R など。長音は R、無声化も有声と同じに扱う）、高低（句の型から決めた L/H）、属する語・句

pyopenjtalk が無ければ available() が False を返す（呼ぶ側は文字の比較だけに落とす）。
入れ方: <スキルの venv>/bin/python -m pip install pyopenjtalk-plus
"""
import contextlib, io, re, unicodedata

_P = None


def available():
    global _P
    if _P is None:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                import pyopenjtalk  # noqa: F401  （onnxruntime が無いという注意を黙らせる）
            _P = pyopenjtalk
        except ImportError:
            _P = False
    return bool(_P)


def tokyo_hl(k, m):
    """句の型 k（0＝平板、1＝頭高…）で、m モーラ目（1 始まり）が高いか低いか。"""
    if k == 1: return "H" if m == 1 else "L"
    if m == 1: return "L"
    return "H" if (k == 0 or m <= k) else "L"


_LAB = re.compile(r"\^(.+?)-(.+?)\+.*?/A:(-?\w+)\+(\w+)\+(\w+)/.*?/F:(\w+)_(\w+)#\w+_\w+@(\w+)_\w+\|")


def _moras_from_labels(labels):
    """フルコンテキストラベルを、モーラの並び [{ph, hl, ap}] にする。ap は句の通し番号。"""
    out, key, bg = [], None, 0
    for lab in labels:
        m = _LAB.search(lab)
        if not m: continue
        ph = m.group(2)
        if ph in ("sil", "pau"):
            bg += 1; key = None; continue
        a2, f1, f2, f5 = m.group(4), m.group(6), m.group(7), m.group(8)
        if "xx" in (a2, f2, f5): continue
        k = (bg, int(f5), int(a2))
        if k != key:
            out.append({"ph": "", "phs": [], "hl": tokyo_hl(int(f2), int(a2)), "ap": (bg, int(f5))}); key = k
        p_ = ph.lower() if ph not in ("N", "cl") else ph      # 無声化（I・U）は有声と同じに
        out[-1]["ph"] += p_; out[-1]["phs"].append(p_)
    return out


def _norm(s):
    return unicodedata.normalize("NFKC", s)


def analyze(text):
    """文を語とモーラに分ける。返り値 {"nodes": [...], "moras": [...]}。pyopenjtalk が無ければ None。
    node: {string, start, end（text の中の文字の範囲。見つからなければ None）, pos, cform, pron, mora: [モーラの番号...]}
    mora: {ph（音。長音は R）, phs（音素の並び。OpenJTalk の音素、無声化は小文字に、長音は前の母音）, hl, ap, node}"""
    if not available(): return None
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        nj = _P.run_frontend(text)
        labels = _P.make_label(nj)
    moras = _moras_from_labels(labels)
    nt = _norm(text)
    nodes, pos, mi = [], 0, 0
    for n in nj:
        s = _norm(n["string"])
        st = nt.find(s, pos) if s else -1
        if st < 0 or st - pos > 8: st = None
        k = int(n.get("mora_size", 0) or 0)
        idx = list(range(mi, min(mi + k, len(moras)))); mi += k
        node = {"string": n["string"], "start": st, "end": None if st is None else st + len(s), "pos": n.get("pos", ""),
                "cform": n.get("cform", ""), "pron": n.get("pron", ""), "mora": idx}
        if st is not None: pos = st + len(s)
        for i in idx: moras[i]["node"] = len(nodes)
        nodes.append(node)
    _fill_gaps(nodes, len(nt))
    _to_original(nodes, text)
    _long_vowels(moras)
    return {"nodes": nodes, "moras": moras}


def _to_original(nodes, text):
    """語の範囲（NFKC にした文の中の位置）を、元の text の中の位置に直す。
    半角カナ（ﾌﾟ → プ）のように NFKC で長さが変わる文字があると、そのままでは後ろの位置がずれる。
    L[i] = text の先頭 i 文字を NFKC にした長さ。正規化後の位置 k の文字は L[i] <= k < L[i+1] の元の i から来ている。"""
    L = [len(_norm(text[:i])) for i in range(len(text) + 1)]
    if L[-1] == len(text) and all(L[i] == i for i in range(len(L))): return
    def start(k): return next((i for i in range(len(text)) if L[i] <= k < L[i + 1]), len(text))
    def end(k): return next((i for i in range(len(text) + 1) if L[i] >= k), len(text))
    for x in nodes:
        if x["start"] is not None: x["start"], x["end"] = start(x["start"]), end(x["end"])


def _fill_gaps(nodes, n):
    """文字の範囲が見つからない語（数字を漢数字に直した「3」→「三」など）に、前後の語の間の範囲を当てる。"""
    found = [x["start"] is not None for x in nodes]
    for i, x in enumerate(nodes):
        if found[i]: continue
        a = next((nodes[k]["end"] for k in range(i - 1, -1, -1) if found[k]), 0)
        b = next((nodes[k]["start"] for k in range(i + 1, len(nodes)) if found[k]), n)
        if b > a: x["start"], x["end"] = a, b


def _long_vowels(moras):
    """語の中の長音を R にそろえる（表＝ヒョー と ひょう＝ヒョウ を同じ音にする）。語の境目はまたがない（「は」の a と「赤」の a）。"""
    prev, pn = "", None
    for x in moras:
        same = x.get("node") == pn and pn is not None
        if same and x["ph"] in ("a", "i", "u", "e", "o") and (x["ph"] == prev or (x["ph"] == "u" and prev == "o") or (x["ph"] == "i" and prev == "e")):
            x["ph"] = "R"
        else:
            prev = x["ph"][-1:] if x["ph"] not in ("N", "cl") else ""
        pn = x.get("node")


def region(an, a, b):
    """text の文字の範囲 [a, b) にかかる語を全部含むように広げた範囲と、その語の番号。"""
    ks = [i for i, n in enumerate(an["nodes"]) if n["start"] is not None and n["start"] < b and n["end"] > a]
    if not ks: return a, b, []
    return min(a, an["nodes"][ks[0]]["start"]), max(b, an["nodes"][ks[-1]]["end"]), ks


def region_moras(an, ks):
    return [an["moras"][i] for k in ks for i in an["nodes"][k]["mora"]]


def next_in_phrase(an, ks):
    """語の並び ks の最後のモーラの次のモーラが同じ句にあれば、その 1 つを並びで返す（無ければ []）。
    尾高（花が LHL）と平板（はなが LHH）は語の中では同じ列で、違いは後ろの助詞の高さに出る。"""
    ms = region_moras(an, ks)
    if not ms: return []
    i = an["moras"].index(ms[-1]) + 1
    return [an["moras"][i]] if i < len(an["moras"]) and an["moras"][i]["ap"] == ms[-1]["ap"] else []


def sound(ms): return " ".join(m["ph"] for m in ms)
def pitch(ms): return "".join(m["hl"] for m in ms)
