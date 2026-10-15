"""terms.py（用語辞書の読み込み・検査）のテスト。語はテスト用に作ったもので、辞書の中身ではない。"""
import subprocess, sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")
import terms as tm

SCRIPT = Path(__file__).resolve().parent.parent / "skills/video-scene/scripts/terms.py"


def load(tmp_path, text):
    p = tmp_path / "terms.yaml"
    p.write_text(text, encoding="utf-8")
    return tm.load_terms(p)


def test_shipped_dictionary_is_valid_and_empty():
    # 中身は人が足す。リポに入っている辞書は形が正しく、空で始まる
    assert tm.DEFAULT_PATH.is_file()
    assert tm.load_terms() == []


@pytest.mark.parametrize("text", ["", "terms:\n", "terms: []\n", "# コメントだけ\n"])
def test_empty_forms(tmp_path, text):
    assert load(tmp_path, text) == []


def test_load_accent_and_type(tmp_path):
    ts = load(tmp_path, """
terms:
  - word: 薄い板
    reading: うすいいた
    accent: LHHHL
    note: テスト用
  - word: キャビティ
    reading: きゃびてぃ
    type: 1
  - word: 金型
    reading: かながた
    accent: 低高高高
    type: 0
""")
    assert [t.word for t in ts] == ["薄い板", "キャビティ", "金型"]
    a, b, c = ts
    assert (a.accent, a.type, a.morae, a.note) == ("LHHHL", 4, 5, "テスト用")
    assert (b.accent, b.type, b.morae, b.note) == ("HLL", 1, 3, "")
    assert (c.accent, c.type, c.morae) == ("LHHH", 0, 4)
    assert tm.as_dict(ts)["金型"] is c


def test_odaka_type_is_kept(tmp_path):
    # 尾高は語の中では平板と同じ列。type で書けば型の数字は残る
    (t,) = load(tmp_path, "terms:\n  - {word: 男, reading: おとこ, type: 3}\n")
    assert (t.accent, t.type) == ("LHH", 3)


@pytest.mark.parametrize("reading,n", [
    ("うすいいた", 5), ("きゃく", 2), ("きって", 3), ("ほんだ", 3), ("ゲート", 3),
    ("ジョーカー", 4), ("てぃっしゅ", 3), ("ヴァイオリン", 5),
])
def test_count_morae(reading, n):
    assert tm.count_morae(reading) == n


@pytest.mark.parametrize("reading", ["", "型", "kata", "かた ", "ゃく", "かた1"])
def test_count_morae_rejects(reading):
    with pytest.raises(ValueError):
        tm.count_morae(reading)


@pytest.mark.parametrize("acc,ok", [
    ("L", True), ("H", True), ("LH", True), ("HL", True), ("LHHHL", True), ("HLLL", True),
    ("LL", False), ("HH", False), ("LHLH", False), ("HHL", False), ("LLH", False),
])
def test_is_tokyo(acc, ok):
    assert tm.is_tokyo(tuple(1 if c == "H" else 0 for c in acc)) is ok


BAD = [
    ("- just a string", "一番上は terms:"),
    ("terms: {word: a}", "語の並び"),
    ("version: 1\nterms: []", "知らないキー: version"),
    ("terms:\n  - 型締力", "表にする"),
    ("terms:\n  - {reading: かた, accent: HL}", "word が無い"),
    ("terms:\n  - {word: 型, accent: HL}", "reading が無い"),
    ("terms:\n  - {word: on, reading: おん, accent: HL}", "引用符"),
    ("terms:\n  - {word: 型, reading: カタ型, accent: HL}", "かな・ー 以外"),
    ("terms:\n  - {word: 型, reading: かた}", "accent（LHHHL の列）か type"),
    ("terms:\n  - {word: 型, reading: かた, accent: LHH}", "3 モーラ、読み かた は 2 モーラ"),
    ("terms:\n  - {word: 型, reading: かた, accent: LX}", "使えない文字"),
    ("terms:\n  - {word: 型, reading: かたち, accent: LHL, type: 0}", "合わない"),
    ("terms:\n  - {word: 型, reading: かた, type: 3}", "モーラ数 2 にアクセント型 3 は無い"),
    ("terms:\n  - {word: 型, reading: かた, type: '1'}", "type は 0 以上の整数"),
    ("terms:\n  - {word: 型, reading: かた, type: true}", "type は 0 以上の整数"),
    ("terms:\n  - {word: 型, reading: かた, accent: 10}", "type: に書く"),
    ("terms:\n  - {word: 型, reading: かたがみ, accent: LHLH}", "東京式"),
    ("terms:\n  - {word: 型, reading: かた, accent: HH}", "東京式"),
    ("terms:\n  - {word: 型, reading: かた, accent: HL, nota: x}", "知らないキー: nota"),
    ("terms:\n  - {word: 型, reading: かた, accent: HL, note: 3}", "note は文字列"),
    ("terms:\n  - {word: 市場, reading: いちば, accent: HLL}\n  - {word: 市場, reading: しじょう, type: 0}",
     "2 語目: 市場 は 1 語目と同じ word"),
    ("terms: [\n", "YAML として読めない"),
    ("terms:\n  - word: 型\n    reading: かた\n    accent: HL\n    accent: LH\n", "5 行目: キー accent が同じ表に2回ある"),
    ("terms:\n  - {word: 板, reading: いた, accent: HL}\nterms: []\n", "キー terms が同じ表に2回ある"),
]


@pytest.mark.parametrize("text,msg", BAD)
def test_rejects(tmp_path, text, msg):
    with pytest.raises(tm.TermsError) as e:
        load(tmp_path, text)
    assert msg in str(e.value)


def test_error_names_the_entry(tmp_path):
    with pytest.raises(tm.TermsError) as e:
        load(tmp_path, "terms:\n  - {word: 板, reading: いた, accent: HL}\n  - {word: 型, reading: かた, accent: LLL}\n")
    assert "2 語目" in str(e.value) and "型" in str(e.value)


def test_cli_ok_and_ng(tmp_path):
    ok = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert ok.returncode == 0 and "ok   0 語" in ok.stdout
    p = tmp_path / "t.yaml"
    p.write_text("terms:\n  - {word: 板, reading: いた, accent: HL}\n", encoding="utf-8")
    ok = subprocess.run([sys.executable, str(SCRIPT), str(p)], capture_output=True, text=True)
    assert ok.returncode == 0 and "板  いた  HL（1 型、2 モーラ）" in ok.stdout
    p.write_text("terms:\n  - {word: 板, reading: いた}\n", encoding="utf-8")
    ng = subprocess.run([sys.executable, str(SCRIPT), str(p)], capture_output=True, text=True)
    assert ng.returncode == 1 and "NG" in ng.stderr
