"""vm voice lint（say の書き方の検査）。文字の比較は純関数で、読み手の見本（pyopenjtalk-plus）を使う所は入っているときだけ確かめる。"""
import json, os, subprocess, sys
from collections import namedtuple

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "skills", "video-mascot", "scripts")
sys.path.insert(0, SCRIPTS)
import say_lint as L  # noqa: E402

Term = namedtuple("Term", "word reading")


def kinds(fs):
    return [(f.kind, f.src, f.say) for f in fs]


# ---- 文字の比較（見本なし）

def test_same_or_missing_say_is_quiet():
    assert L.lint_line("表を作る。", None, use_reader=False) == []
    assert L.lint_line("表を作る。", "表を作る。", use_reader=False) == []


def test_opened_kanji_is_found():
    fs = L.lint_line("手元にファイルはできない。", "てもとにファイルはできない。", use_reader=False)
    assert kinds(fs) == [("open", "手元", "てもと")]
    assert "【手元】" in fs[0].ctx


def test_english_to_katakana_is_not_opening():
    assert L.lint_line("Claude が作る表だ。", "クロードが作る表だ。", use_reader=False) == []


def test_added_comma_and_space_comma_are_separated():
    fs = L.lint_line("ブラウザで開く表だ。", "ブラウザで開く、表だ。", use_reader=False)
    assert kinds(fs) == [("comma", "", "、")]
    assert "開く【、】表" in fs[0].ctx
    fs = L.lint_line("表は Claude のサーバーに置かれる。", "表は、クロードのサーバーに置かれる。", use_reader=False)
    assert kinds(fs) == [("comma_space", "", "、")]


def test_comma_and_opening_in_one_replace():
    fs = L.lint_line("ブラウザで開く表だ。", "ブラウザで開く、ひょうだ。", use_reader=False)
    assert sorted(kinds(fs)) == [("comma", "", "、"), ("open", "表", "ひょう")]


def test_term_reading_is_exempt():
    t = [Term("型締力", "かたじめりょく")]
    assert L.lint_line("これは型締力の目安だ。", "これはかたじめりょくの目安だ。", t, use_reader=False) == []
    # 辞書の読みと違う開き方は出す
    assert kinds(L.lint_line("これは型締力の目安だ。", "これはかたしめりょくの目安だ。", t, use_reader=False)) == [("open", "型締力", "かたしめりょく")]


def test_term_is_checked_per_occurrence():
    """同じ語が 2 回出て片方だけ読みが違えば、違う方は出す。辞書の読みを含むだけの開き方も出す。"""
    t = [Term("手元", "てもと")]
    fs = L.lint_line("手元と手元。", "てもととてまと。", t, use_reader=False)
    assert kinds(fs) == [("open", "手元", "てまと")] and fs[0].pos == 3
    assert kinds(L.lint_line("手元に置く。", "てもとんに置く。", t, use_reader=False)) == [("open", "手元", "てもとん")]
    assert L.lint_line("手元と手元。", "てもととてもと。", t, use_reader=False) == []


def test_kanji_run_is_shown_whole():
    fs = L.lint_line("次の手入れまで。", "次のていれまで。", use_reader=False)
    assert fs and all(f.kind == "open" for f in fs)
    assert "【手入】れ" in fs[0].ctx


def test_without_reader_everything_is_marked():
    fs = L.lint_line("表の横に置く。", "表のよこに置く。", use_reader=False)
    assert [f.hard for f in fs] == [True]


# ---- 読み手の見本あり

ojt_needed = pytest.mark.skipif(not __import__("ojt").available(), reason="pyopenjtalk-plus が無い")


@ojt_needed
@pytest.mark.parametrize("text,say,change", [
    ("表は Claude のサーバーに置かれる。", "ひょうは、クロードのサーバーに置かれる。", "高さ"),   # 表＝平板、ひょう＝豹の頭高
    ("手元にファイルはできない。", "てもとにファイルはできない。", "高さ"),
    ("行の色は赤になる。", "行のいろは、赤になる。", "読み"),                            # いろは
    ("表の横にグラフが置かれた。", "表のよこに、グラフが置かれた。", None),             # 横もよこも同じ
])
def test_reader_keeps_only_changes(text, say, change):
    fs = [f for f in L.lint_line(text, say) if f.kind == "open"]
    assert len(fs) == 1 and fs[0].extra["change"] == change
    assert fs[0].hard == (change is not None)


@ojt_needed
def test_split_word_is_compared_whole():
    """「一つ目」が「ひと」「め」に割れても、片方だけ漢字に戻した「一つめ」（いち と読まれる）で比べない。"""
    fs = [f for f in L.lint_line("注意は三つある。一つ目。", "注意は三つある。ひとつめ。") if f.kind == "open"]
    assert len(fs) == 2
    assert all(f.extra["t_word"] == "一つ目" and f.extra["t_sound"] == f.extra["s_sound"] for f in fs)


@ojt_needed
def test_halfwidth_kana_keeps_positions():
    """NFKC で長さが変わる半角カナの後ろでも、開いた語を見本で確かめる（位置がずれて「同じ」にしない）。"""
    import ojt
    an = ojt.analyze("ﾌﾟﾛｸﾞﾗﾑの色")
    iro = [n for n in an["nodes"] if n["string"] == "色"]
    assert iro and (iro[0]["start"], iro[0]["end"]) == (8, 9)
    fs = [f for f in L.lint_line("ﾌﾟﾛｸﾞﾗﾑの色は赤。", "ﾌﾟﾛｸﾞﾗﾑのいろは赤。") if f.kind == "open"]
    assert len(fs) == 1 and fs[0].extra["change"] == "読み"


@ojt_needed
def test_comma_inside_replacement_is_not_compared():
    """置き換えの途中の読点は、戻した文で落とすと読点の効き目を開いたせいにしてしまう。比べずに「!」で出す。"""
    fs = [f for f in L.lint_line("入力方法を説明。", "にゅうりょく、ほうほうをせつめい。") if f.kind == "open"]
    inner = [f for f in fs if f.src == "入力方法"]
    assert inner and inner[0].extra["change"] == "?" and inner[0].hard
    assert "読点" in inner[0].describe()


@ojt_needed
def test_tail_accent_is_seen_on_the_particle():
    """尾高（花が LH+L）と平板（はなが LH+H）は語の中では同じ。後ろの助詞まで比べて見分ける。"""
    fs = [f for f in L.lint_line("花が咲く。", "はなが咲く。") if f.kind == "open"]
    assert len(fs) == 1 and fs[0].extra["change"] == "高さ"
    assert fs[0].extra["t_pitch"] == "LHL" and fs[0].extra["s_pitch"] == "LHH"
    fs = [f for f in L.lint_line("男が来る。", "おとこが来る。") if f.kind == "open"]
    assert len(fs) == 1 and fs[0].extra["change"] is None


@ojt_needed
def test_comma_inside_modifier_is_hard():
    fs = L.lint_line("ブラウザで開く表だ。", "ブラウザで開く、表だ。")
    assert [(f.kind, f.hard) for f in fs] == [("comma", True)]
    fs = L.lint_line("表の横にグラフが置かれた。", "表の横に、グラフが置かれた。")
    assert [(f.kind, f.hard) for f in fs] == [("comma_soft", False)]


@ojt_needed
def test_ojt_long_vowel_and_numbers():
    import ojt
    a, b = ojt.analyze("表"), ojt.analyze("ひょう")
    assert ojt.sound(a["moras"]) == ojt.sound(b["moras"]) == "hyo R"
    an = ojt.analyze("紙が3枚並ぶ。")        # 「3」は「三」の語になる。前後の語の間の範囲を当てる
    three = [n for n in an["nodes"] if n["string"] == "三"]
    assert three and (three[0]["start"], three[0]["end"]) == (2, 3)
    an = ojt.analyze("母は赤が好き。")       # 「は」の a と「赤」の a は長音にしない
    assert "R" not in ojt.sound(an["moras"])


def test_tokyo_hl():
    import ojt
    assert "".join(ojt.tokyo_hl(0, m) for m in (1, 2, 3)) == "LHH"
    assert "".join(ojt.tokyo_hl(1, m) for m in (1, 2, 3)) == "HLL"
    assert "".join(ojt.tokyo_hl(2, m) for m in (1, 2, 3)) == "LHL"


# ---- vm voice lint

def test_voice_lint_command(tmp_path):
    cfg = {"name": "t", "poses": {"home": {}}, "voice": {"lines": [
        {"text": "手元にファイルはできない。", "say": "てもとにファイルはできない。"},
        {"text": "表を作る。"}]}}
    json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "voice.py"), str(tmp_path), "lint"], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert r.returncode == 0, r.stderr
    assert "! 行1: 漢字を仮名に開いた: 手元→てもと" in r.stdout
    assert "say の検査（2 行" in r.stdout
    assert "行2" not in r.stdout.replace("（2 行", "")


def test_voice_lint_reads_work_terms(tmp_path):
    (tmp_path / "terms.yaml").write_text("terms:\n  - word: 手元\n    reading: てもと\n    type: 0\n", encoding="utf-8")
    cfg = {"name": "t", "poses": {"home": {}}, "voice": {"terms": "terms.yaml", "lines": [
        {"text": "手元にファイルはできない。", "say": "てもとにファイルはできない。"}]}}
    json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "voice.py"), str(tmp_path), "lint"], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert r.returncode == 0, r.stderr
    assert "手元" not in r.stdout and "「!」0 件" in r.stdout
