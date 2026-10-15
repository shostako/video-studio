"""accent.py — 声の高さ（F0）を測り、語ごとに期待するアクセント（高低の列）と合っているかを点数にする。

使い方:
  vs accent 声.wav 語.json [--floor 75] [--ceiling 500] [--thresh 1.5] [--json 出力.json]

  語.json は語の並び。1語ずつ、声の中の時刻と期待する高低の列を書く:
    [{"word": "薄い板", "start": 0.10, "end": 0.62, "accent": "LHHHL"}, ...]
  "accent" の代わりに "type"（アクセント型の数字）と "morae"（モーラ数）でもよい。
  時刻は Whisper の語の時刻（research/2026-10-15-tts/acc_words.py の words.json）などから取る。

期待する高低の列（用語辞書もこの書き方に揃える）:
  - 語の1モーラに1文字。L＝低、H＝高（「低」「高」でも書ける）。例: 薄い板（うすいいた）＝ "LHHHL"
  - 長さはモーラ数（「きゃ」で1、「っ」「ん」「ー」も1）。語の中だけを書き、後ろの助詞は含めない
  - アクセント型の数字 k からは accent_from_type(モーラ数, k) で作る（0＝平板、1＝頭高、k＝k モーラ目の後で下がる）
    尾高（k＝モーラ数）は語の中だけでは平板と同じ列になる（違いは助詞の高さ）

点数の出し方:
  - 語の時刻をモーラ数で等分し（"bounds" で境目を直接渡してもよい）、各モーラの真ん中 6 割の F0 の中央値を取る
  - F0 は声全体の中央値を 0 とした半音（semitone）。高い声・低い声で同じ物差しになる
  - 声の出ているモーラだけを順に並べ、隣どうしの差を「上がる（+thresh 以上）・下がる（-thresh 以下）・平ら」に分け、
    期待（L→H は上がる、H→L は下がる、同じ高さは平ら）と合う組の割合を score とする
  - 別に、下がり目（何モーラ目の後で下がるか。平板・尾高は無し）が期待と同じかを drop_ok に出す。
    平らな組が多い語では、頭高と平板の取り違えでも score は 0.67 ほど残るので、型の取り違えは drop_ok で見る
  - 無声化した母音（「うすい」の「す」など）は F0 が取れないので飛ばし、前後の声の出ているモーラどうしで比べる

本物の声でこの点数が耳の判定と合うかは、まだ確かめていない（手元待ち）。thresh の既定 1.5 半音も仮の値。
"""
import argparse, json, os, sys

import numpy as np

LEVEL = {"L": 0, "H": 1, "低": 0, "高": 1}


def parse_accent(s):
    """'LHHHL'・'低高高高低'・'L-H-H' などを (0, 1, 1, 1, 0) にする。空白・'-'・'・' は無視、小文字も可。"""
    out = []
    for c in str(s):
        if c in " -・_":
            continue
        v = LEVEL.get(c.upper() if c.isascii() else c)
        if v is None:
            raise ValueError(f"アクセントの列に使えない文字: {c!r}（L/H か 低/高）: {s!r}")
        out.append(v)
    if not out:
        raise ValueError(f"アクセントの列が空: {s!r}")
    return tuple(out)


def format_accent(levels):
    return "".join("H" if v else "L" for v in levels)


def accent_from_type(morae, k):
    """アクセント型の数字から語の中の高低の列を作る。0＝平板、1＝頭高、2..n-1＝中高、n＝尾高。"""
    if morae < 1 or not 0 <= k <= morae:
        raise ValueError(f"モーラ数 {morae} にアクセント型 {k} は無い")
    if k == 1:
        return "H" + "L" * (morae - 1)
    hi_end = morae if k == 0 else k  # この位置（1始まり）まで高い
    return "".join("L" if i == 1 else ("H" if i <= hi_end else "L") for i in range(1, morae + 1))


def f0_track(src, floor=75.0, ceiling=500.0, step=0.005):
    """wav（パス）か (標本の配列, 標本化周波数) から F0 を取る。返り値は (時刻[秒], F0[Hz]、声が無い所は nan)。"""
    import parselmouth
    if isinstance(src, (str, os.PathLike)):
        snd = parselmouth.Sound(str(src))
    else:
        x, sr = src
        snd = parselmouth.Sound(np.asarray(x, dtype=np.float64), sampling_frequency=float(sr))
    if snd.n_channels > 1:
        snd = snd.convert_to_mono()
    p = snd.to_pitch_ac(time_step=step, pitch_floor=floor, pitch_ceiling=ceiling)
    f0 = p.selected_array["frequency"].astype(float)
    f0[f0 <= 0] = np.nan
    return np.asarray(p.xs(), dtype=float), f0


def to_semitones(f0, ref=None):
    """Hz を半音にする。ref（既定は声の出ている所の中央値）を 0 とする。"""
    f0 = np.asarray(f0, dtype=float)
    if ref is None:
        v = f0[np.isfinite(f0)]
        if v.size == 0:
            return np.full_like(f0, np.nan)
        ref = float(np.median(v))
    return 12.0 * np.log2(f0 / ref)


def mora_bounds(start, end, n):
    return [start + (end - start) * i / n for i in range(n + 1)]


def mora_pitches(t, st, bounds, core=0.6, min_frames=2):
    """各モーラの真ん中 core の幅の F0（半音）の中央値。声の出ているコマが min_frames 未満なら None。"""
    t = np.asarray(t, dtype=float); st = np.asarray(st, dtype=float)
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        pad = (b - a) * (1.0 - core) / 2.0
        m = (t >= a + pad) & (t <= b - pad) & np.isfinite(st)
        out.append(float(np.median(st[m])) if int(m.sum()) >= min_frames else None)
    return out


def _cls(d, thresh):
    return 1 if d >= thresh else (-1 if d <= -thresh else 0)


ARROW = {1: "↑", -1: "↓", 0: "→"}


def score_pitches(pitches, accent, thresh=1.5):
    """モーラごとの高さ（半音、None は声なし）と期待する列から点数を出す。"""
    lv = parse_accent(accent)
    if len(pitches) != len(lv):
        raise ValueError(f"モーラ数が合わない: 高さ {len(pitches)}、列 {len(lv)}")
    idx = [i for i, p in enumerate(pitches) if p is not None]
    pairs = []
    for i, j in zip(idx[:-1], idx[1:]):
        want = (lv[j] > lv[i]) - (lv[j] < lv[i])
        d = pitches[j] - pitches[i]
        got = _cls(d, thresh)
        pairs.append({"from": i, "to": j, "delta": round(d, 2), "want": ARROW[want], "got": ARROW[got], "ok": got == want})
    ok = sum(p["ok"] for p in pairs)
    # 下がり目（アクセント核）: 何モーラ目の後で下がるか。期待は列から、測定は最初の「下がる」組の前の側
    drop_want = next((i + 1 for i in range(len(lv) - 1) if lv[i] > lv[i + 1]), None)
    drop_got = next((p["from"] + 1 for p in pairs if p["got"] == "↓"), None)
    return {
        "accent": format_accent(lv),
        "pitches": [None if p is None else round(p, 2) for p in pitches],
        "unvoiced": [i for i, p in enumerate(pitches) if p is None],
        "pairs": pairs,
        "want": "".join(p["want"] for p in pairs),
        "got": "".join(p["got"] for p in pairs),
        "score": (ok / len(pairs)) if pairs else None,
        "drop_want": drop_want,
        "drop_got": drop_got,
        "drop_ok": (drop_got == drop_want) if pairs else None,
    }


def word_accent(w):
    """語の指定から高低の列を取る（"accent"、または "type" と "morae"）。"""
    if w.get("accent") is not None:
        return format_accent(parse_accent(w["accent"]))
    if w.get("type") is not None and w.get("morae") is not None:
        return accent_from_type(int(w["morae"]), int(w["type"]))
    raise ValueError(f"語 {w.get('word')!r} に accent（か type と morae）が無い")


def score_word(t, st, w, thresh=1.5, core=0.6):
    """1語の点数。w は {"word", "start", "end", "accent" か "type"+"morae", 任意で "bounds"}。"""
    acc = word_accent(w)
    n = len(acc)
    bounds = w.get("bounds") or mora_bounds(float(w["start"]), float(w["end"]), n)
    if len(bounds) != n + 1:
        raise ValueError(f"語 {w.get('word')!r} の bounds は {n + 1} 個要る（{len(bounds)} 個）")
    r = score_pitches(mora_pitches(t, st, bounds, core=core), acc, thresh=thresh)
    return {"word": w.get("word", ""), "start": float(bounds[0]), "end": float(bounds[-1]), **r}


def score_words(src, words, floor=75.0, ceiling=500.0, thresh=1.5, core=0.6):
    """声（wav のパスか (配列, 標本化周波数)）の F0 を1回取り、語ごとに点数を出す。"""
    t, f0 = f0_track(src, floor=floor, ceiling=ceiling)
    st = to_semitones(f0)
    return [score_word(t, st, w, thresh=thresh, core=core) for w in words]


def main():
    ap = argparse.ArgumentParser(description="語ごとのアクセント（F0 の高低）の点数")
    ap.add_argument("wav"); ap.add_argument("words", help="語の並びの JSON（使い方は先頭の説明）")
    ap.add_argument("--floor", type=float, default=75.0, help="F0 の下限 Hz（既定 75）")
    ap.add_argument("--ceiling", type=float, default=500.0, help="F0 の上限 Hz（既定 500）")
    ap.add_argument("--thresh", type=float, default=1.5, help="上がる・下がると見なす差（半音、既定 1.5）")
    ap.add_argument("--json", help="結果を JSON でも書き出す")
    a = ap.parse_args()
    try:
        import parselmouth  # noqa: F401
    except ImportError:
        sys.exit("ERROR: parselmouth が無い。video-scene の setup.sh を流す（praat-parselmouth を入れる）")
    words = json.load(open(a.words, encoding="utf-8"))
    res = score_words(a.wav, words, floor=a.floor, ceiling=a.ceiling, thresh=a.thresh)
    for r in res:
        s = "  -  " if r["score"] is None else f"{r['score']:.2f}"
        hi = " ".join("·" if p is None else f"{p:+.1f}" for p in r["pitches"])
        dr = "  -  " if r["drop_ok"] is None else ("下がり目 ok" if r["drop_ok"] else f"下がり目 NG（期待 {r['drop_want']}、測定 {r['drop_got']}）")
        print(f"{s}  {r['word']}  {r['start']:.2f}-{r['end']:.2f}  期待 {r['accent']} {r['want']}  測定 {r['got']}  {dr}  [{hi}]")
    sc = [r["score"] for r in res if r["score"] is not None]
    print(f"平均 {sum(sc) / len(sc):.2f}（{len(sc)} 語）" if sc else "点数の付いた語が無い")
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
