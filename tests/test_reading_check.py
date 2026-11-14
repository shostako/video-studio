"""vm voice reading（声の読みを字幕の読みと音素で比べる）。声の書き起こし（torch が要る）は CI では動かさず、音素の並びを渡して確かめる。"""
import os, sys
from collections import namedtuple

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "video-mascot", "scripts"))
import reading_check as R  # noqa: E402

Term = namedtuple("Term", "word reading")
ojt_needed = pytest.mark.skipif(not __import__("ojt").available(), reason="pyopenjtalk-plus が無い")


def P(s): return s.split()


def test_norm_absorbs_spelling_variants():
    n = lambda s: [p for p, _ in R.norm([(x, 0) for x in P(s)])]
    assert n("hy o u") == n("hy o o") == ["hy", "o"]        # ひょう・ひょー
    assert n("s e N s e i") == n("s e N s e e")
    assert n("t o y u u") == n("t o i u")                     # という
    assert n("n a i y a ts u") == n("n a i a ts u")
    assert n("ky a b i t i i") == n("ky a b i t i")
    assert n("i r o w a") != n("i r o h a")                   # 子音の違いは残す


def test_norm_keeps_tags():
    assert R.norm([("hy", 3), ("o", 3), ("u", 4), ("n", 5)]) == [("hy", 3), ("o", 3), ("n", 5)]


def test_align_is_minimal():
    pairs = R.align(P("a b c d"), P("a x c d e"))
    assert sum(1 for i, j in pairs if i is None or j is None or P("a b c d")[i] != P("a x c d e")[j]) == 2


@ojt_needed
def test_kanji_misread_is_found():
    """漢字のままの 表 を おもて と読んだ（実際にあった誤り）。"""
    heard = P("y o m o t e n o y o k o n i g u r a f u g a o k a r e t a")
    rs = R.check_line("表の横にグラフが置かれた。", "表のよこに、グラフが置かれた。", heard)
    assert [(r["kind"], r["word"]) for r in rs] == [("misread", "表の")]


@ojt_needed
def test_say_reading_is_marked_as_say():
    """say を いろは と書いて、声も いろは。字幕の読み（色は＝いろわ）とは違うので「?」。"""
    heard = P("b u r a N d o n o i r o h a f u k a i m i d o r i")
    rs = R.check_line("ブランドの色は深い緑。", "ブランドのいろは、深い緑。", heard)
    assert [r["kind"] for r in rs] == ["say"] and "h a" in rs[0]["got"]


@ojt_needed
def test_correct_voice_is_quiet():
    heard = P("t e m o t o n i f a i r u w a d e k i n a i")
    assert R.check_line("手元にファイルはできない。", "てもとにファイルはできない。", heard) == []


@ojt_needed
def test_terms_set_the_reference_reading():
    """見本が おもて と読む 表 も、辞書に ひょう と書けば、声の ひょう は正しい。語の単位なので 行く の 行 は置き換えない。"""
    heard = P("b u r a u z a d e h i r a k u hy o o d a")
    assert [r["word"] for r in R.check_line("ブラウザで開く表だ。", None, heard)] == ["表"]
    assert R.check_line("ブラウザで開く表だ。", None, heard, [Term("表", "ひょう")]) == []
    heard = P("a sh i t a i k u")
    assert R.check_line("明日行く。", None, heard, [Term("行", "ぎょう")]) == []


@ojt_needed
def test_reference_reverts_openings():
    assert R.reference_text("行の色は赤になる。", "行のいろは、赤になる。") == "行の色は、赤になる。"
    assert R.reference_text("Claude が作る。", "クロードが作る。") == "クロードが作る。"
