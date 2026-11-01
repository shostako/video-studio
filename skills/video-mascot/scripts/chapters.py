"""章の見出しの JSON を読む純関数（numpy・OpenCV を使わない）。vm layout と screen-explainer の compose.py が使う。

章の JSON:
  {"chapters": [{"line": 1, "title": "cad-viewer の使い方"}, {"at": 24.0, "title": "視点を動かす"}, ...],
   "credits":  [{"from": 18, "to": 56, "text": ["サンプル: bearing.iges", "Open CASCADE 付属のデータ"]}, ...],
   "lead": 0.6}
  line は台詞の番号（voice/timing.json の n）で、その台詞の lead 秒前（既定 0.6）に見出しが替わる。at は秒で直に書く。
  credits は見出しの下に小さく出す、映したサンプルの出典・許諾。
"""
import json, os, sys


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr); sys.exit(2)


def chapter_plan(spec, line_starts):
    """章の JSON（dict）と台詞の開始秒 {n: 秒} から、[(替わる秒, 番号の文字, 見出し), ...]（時刻の順）と credits を返す。
    line の章は台詞の lead 秒前に替わる（0 秒より前にはしない）。知らない台詞の番号や、line も at も無い章は止める。"""
    lead = float(spec.get("lead", 0.6)); out = []
    for k, c in enumerate(spec.get("chapters", [])):
        if "title" not in c: fail(f"章 {k + 1} に title が無い")
        if "at" in c: t = float(c["at"])
        elif "line" in c:
            if c["line"] not in line_starts: fail(f"章 {k + 1} の line {c['line']} が timing.json に無い")
            t = max(0.0, line_starts[c["line"]] - lead)
        else: fail(f"章 {k + 1} に line も at も無い")
        out.append([t, c["title"]])
    out.sort(key=lambda x: x[0])
    plan = [(t, f"{k + 1:02d}", title) for k, (t, title) in enumerate(out)]
    credits = []
    for c in spec.get("credits", []):
        if not c.get("text"): fail("credits に text が無い")
        credits.append((float(c.get("from", 0)), float(c.get("to", 1e9)), list(c["text"]) if isinstance(c["text"], list) else [c["text"]]))
    return plan, credits


def load(path, timing_path):
    """章の JSON のファイルと timing.json から chapter_plan の結果を返す。timing.json が無ければ line の章は止まる。"""
    starts = {x["n"]: x["start"] for x in json.load(open(timing_path))["lines"]} if os.path.exists(timing_path) else {}
    return chapter_plan(json.load(open(path, encoding="utf-8")), starts)


def chapter_at(t, plan):
    """時刻 t に出す章の番号（plan の添字）。最初の章より前は最初の章。章が無ければ None。"""
    if not plan: return None
    k = 0
    for i, (t0, _, _) in enumerate(plan):
        if t0 <= t: k = i
    return k


def credit_alpha(t, c0, c1, fade=0.3):
    """サンプルの出どころの濃さ（0〜1）。c0 から fade 秒で出し、c1 で消す。"""
    if t < c0 or t >= c1: return 0.0
    return min(1.0, (t - c0) / fade) if fade > 0 else 1.0


def flash_alpha(t, t0, fade_in=0.3, hold=3.0, fade_out=1.0):
    """章が替わった所だけ見出しを出すときの濃さ（0〜1）。t0 から fade_in 秒で出し、hold 秒保って、fade_out 秒で消える。"""
    u = t - t0
    if u < 0 or u >= fade_in + hold + fade_out: return 0.0
    if u < fade_in: return u / fade_in if fade_in > 0 else 1.0
    if u < fade_in + hold: return 1.0
    return 1.0 - (u - fade_in - hold) / fade_out if fade_out > 0 else 0.0


BREAK_AFTER = "・、。）」』 　"


def fit_heading(title, width_of, maxw, big=34, small=26, two=30, two_min=22):
    """余白に出す見出しの (字の大きさ, [行])。big〜small px で 1 行に収まればそれ。収まらなければ two〜two_min px で 2 行に折る
    （区切りの字「・、）」などの後ろを優先し、無ければ字の間）。それでも収まらなければ two_min px で 2 行目の末尾を「…」で切る。
    width_of(文字, 大きさ) は描いたときの幅。"""
    for sz in range(big, small - 1, -2):
        if width_of(title, sz) <= maxw: return sz, [title]
    def split(sz):
        best = None
        for i in range(1, len(title)):
            a, b = title[:i], title[i:]
            if width_of(a, sz) > maxw: break
            score = (width_of(b, sz) <= maxw, title[i - 1] in BREAK_AFTER, -abs(len(a) - len(b)))
            if best is None or score > best[0]: best = (score, [a, b])
        return best
    for sz in range(two, two_min - 1, -2):
        b = split(sz)
        if b and b[0][0]: return sz, b[1]
    b = split(two_min); a, rest = (b[1] if b else [title[:1], title[1:]])
    while rest and width_of(rest + "…", two_min) > maxw: rest = rest[:-1]
    return two_min, [a, rest + "…"]


def heading_block(size, n_lines, title_y=76):
    """見出しの (各行の上端の y のリスト, 下線の y)。1 行・34px なら下線は 128（元の cad-viewer の解説と同じ位置）。"""
    lh = round(size * 1.4); ys = [title_y + i * lh for i in range(n_lines)]
    return ys, ys[-1] + size + 18
