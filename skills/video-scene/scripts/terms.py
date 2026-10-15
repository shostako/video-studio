"""terms.py — 用語辞書（data/terms.yaml）を読み、形を検査する。

使い方:
  vs terms [辞書.yaml]   既定は skills/video-scene/data/terms.yaml。正しければ語の数と一覧、崩れていれば理由を出して終了コード 1

辞書の形（書き方は references/terms.md）:
  terms:
    - word: 型締力            # 台本の表記（必須）
      reading: かたじめりょく  # 読み。ひらがな・カタカナ・ー だけ（必須）
      accent: LHHHHL          # 期待する高低の列。1モーラ1文字（references/accent.md）
      type: 5                 # accent の代わりにアクセント型の数字でもよい（両方書くなら一致させる）
      note: 任意のメモ

  - accent か type のどちらかは必須。accent の長さは読みのモーラ数と同じにする
  - 同じ word を2回書かない（読みが文脈で割れる語は、どちらを足すか人が決める）
  - 知らないキーと、同じ表に同じキーが2回あるのは書き間違いとして止める

読み込んだ結果は Term の並び。accent は "LHHHHL" の形にそろえ、type が無ければ列から計算する
（平板と尾高は語の中だけでは同じ列なので、列だけから書いた語の type は 0 にする）。
辞書の語を台本や vs accent に当てはめる処理はまだ無い（形だけ先に決める）。
"""
import argparse, sys
from dataclasses import dataclass
from pathlib import Path

from accent import accent_from_type, format_accent, parse_accent

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "terms.yaml"
KEYS = {"word", "reading", "accent", "type", "note"}
SMALL = set("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")  # 前のかなと合わせて1モーラ
KANA = set(chr(c) for c in range(0x3041, 0x3097)) | set(chr(c) for c in range(0x30A1, 0x30FB)) | {"ー"}


@dataclass(frozen=True)
class Term:
    word: str
    reading: str
    accent: str  # "LHHHL" の形
    type: int    # アクセント型の数字（0＝平板、1＝頭高、…）
    morae: int
    note: str = ""


class TermsError(ValueError):
    pass


def count_morae(reading):
    """かなの読みのモーラ数。小書きの ゃゅょ など は前と合わせて1、っ・ん・ー は1。"""
    if not reading:
        raise ValueError("読みが空")
    bad = sorted({c for c in reading if c not in KANA})
    if bad:
        raise ValueError(f"読みに かな・ー 以外の文字: {''.join(bad)!r}")
    if reading[0] in SMALL:
        raise ValueError(f"読みが小書きのかなで始まる: {reading!r}")
    return sum(1 for c in reading if c not in SMALL)


def type_from_accent(levels):
    """高低の列からアクセント型の数字を出す。最初の下がり目の位置、無ければ 0（平板。尾高と区別できない）。"""
    if len(levels) == 1:
        return 1 if levels[0] else 0
    return next((i + 1 for i in range(len(levels) - 1) if levels[i] > levels[i + 1]), 0)


def is_tokyo(levels):
    """東京式の型（accent_from_type で作れる列）か。LL・HH・LHLH のような列は書き間違いとして扱う。"""
    return accent_from_type(len(levels), type_from_accent(levels)) == format_accent(levels)


def check_term(e, where=""):
    """1語の dict を検査して Term を返す。崩れていれば理由を書いた TermsError。"""
    def err(msg):
        raise TermsError(f"{where}: {msg}" if where else msg)

    if not isinstance(e, dict):
        err(f"語は word・reading などを持つ表にする（{type(e).__name__} になっている）")
    extra = sorted(set(map(str, e)) - KEYS)
    if extra:
        err(f"知らないキー: {', '.join(extra)}（使えるのは {', '.join(sorted(KEYS))}）")
    for k in ("word", "reading"):
        if k not in e:
            err(f"{k} が無い")
        if not isinstance(e[k], str) or not e[k].strip():
            # YAML は引用符なしの on / no / 123 などを文字列にしない
            err(f"{k} は文字列で書く（{e[k]!r} と読めた。英字や数字だけの語は引用符で囲む）")
    word, reading = e["word"].strip(), e["reading"].strip()
    try:
        morae = count_morae(reading)
    except ValueError as x:
        err(f"{word}: {x}")
    if "accent" not in e and "type" not in e:
        err(f"{word}: accent（LHHHL の列）か type（型の数字）が要る")
    lv = None
    if "accent" in e:
        if not isinstance(e["accent"], str):
            err(f"{word}: accent は L/H の文字列で書く（{e['accent']!r} と読めた。型の数字なら type: に書く）")
        try:
            lv = parse_accent(e["accent"])
        except ValueError as x:
            err(f"{word}: {x}")
        if len(lv) != morae:
            err(f"{word}: accent {format_accent(lv)} は {len(lv)} モーラ、読み {reading} は {morae} モーラ")
        if not is_tokyo(lv):
            err(f"{word}: accent {format_accent(lv)} は東京式の型にならない（1モーラ目と2モーラ目は高さが違い、高いのは1か所のまとまり）")
    k = None
    if "type" in e:
        k = e["type"]
        if isinstance(k, bool) or not isinstance(k, int):
            err(f"{word}: type は 0 以上の整数（{k!r}）")
        try:
            want = accent_from_type(morae, k)
        except ValueError as x:
            err(f"{word}: {x}（読み {reading}）")
        if lv is not None and format_accent(lv) != want:
            err(f"{word}: accent {format_accent(lv)} と type {k}（{want}）が合わない")
        lv = parse_accent(want)
    note = e.get("note", "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        err(f"{word}: note は文字列で書く")
    if k is None:
        k = type_from_accent(lv)
    return Term(word=word, reading=reading, accent=format_accent(lv), type=k, morae=morae, note=note)


def parse_terms(data, src="terms"):
    """YAML を読んだ後の値（dict）を検査して Term の並びにする。空の辞書は []。"""
    if data is None:
        return []
    if not isinstance(data, dict):
        raise TermsError(f"{src}: 一番上は terms: の表にする")
    extra = sorted(set(map(str, data)) - {"terms"})
    if extra:
        raise TermsError(f"{src}: 知らないキー: {', '.join(extra)}（一番上は terms: だけ）")
    items = data.get("terms")
    if items is None:
        return []
    if not isinstance(items, list):
        raise TermsError(f"{src}: terms は語の並び（- word: ... を並べる）にする")
    out, seen = [], {}
    for i, e in enumerate(items, 1):
        t = check_term(e, where=f"{src}: {i} 語目")
        if t.word in seen:
            raise TermsError(f"{src}: {i} 語目: {t.word} は {seen[t.word]} 語目と同じ word（1語1回）")
        seen[t.word] = i
        out.append(t)
    return out


def load_terms(path=None):
    """辞書のファイルを読んで Term の並びを返す。崩れていれば TermsError。"""
    try:
        import yaml
    except ImportError:
        raise TermsError("PyYAML が無い。video-scene の setup.sh を流す（pyyaml を入れる）")
    class Loader(yaml.SafeLoader):
        pass

    def no_dup(loader, node, deep=False):
        # PyYAML は同じキーが2回あると黙って後ろを採る。書き間違いを見逃さないよう止める
        seen = set()
        for k, _ in node.value:
            key = loader.construct_object(k, deep=deep)
            if key in seen:
                raise TermsError(f"{p}: {k.start_mark.line + 1} 行目: キー {key} が同じ表に2回ある")
            seen.add(key)
        return loader.construct_mapping(node, deep=deep)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, no_dup)
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = yaml.load(p.read_text(encoding="utf-8"), Loader=Loader)
    except yaml.YAMLError as x:
        raise TermsError(f"{p}: YAML として読めない: {x}")
    return parse_terms(data, src=str(p))


def as_dict(terms):
    """word → Term の表。"""
    return {t.word: t for t in terms}


def main():
    ap = argparse.ArgumentParser(description="用語辞書（terms.yaml）の検査")
    ap.add_argument("path", nargs="?", help=f"辞書のファイル（既定 {DEFAULT_PATH}）")
    a = ap.parse_args()
    try:
        terms = load_terms(a.path)
    except (TermsError, OSError) as x:
        sys.exit(f"NG   {x}")
    print(f"ok   {len(terms)} 語（{a.path or DEFAULT_PATH}）")
    for t in terms:
        print(f"     {t.word}  {t.reading}  {t.accent}（{t.type} 型、{t.morae} モーラ）" + (f"  {t.note}" if t.note else ""))


if __name__ == "__main__":
    main()
