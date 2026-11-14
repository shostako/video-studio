"""vm voice accent（声の高さを字幕の読みの高低と比べる）。判定（verdict）は純関数で、声は合成した F0 の並びで確かめる。"""
import os, sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "video-mascot", "scripts"))
import accent_check as AC  # noqa: E402

ojt_needed = pytest.mark.skipif(not __import__("ojt").available(), reason="pyopenjtalk-plus が無い")


def test_flat_word_read_as_head_high():
    """表に（低高高）を 高低低 で読んだ（実際にあった誤り: +0.9 → -5.9 → -7.4）。"""
    assert "頭が高い" in AC.verdict("LHH", [0.9, -5.9, -7.4])
    assert AC.verdict("LHH", [-3.0, 2.0, 2.5]) == []


def test_missing_drop_and_one_mora_delay():
    """色も（低高低）の も が下がらない（-4.7 → +2.1 → +1.3）。下がり目が 1 モーラ遅れるのは許す。"""
    assert any("下がらない" in w for w in AC.verdict("LHL", [-4.7, 2.1, 1.3]))
    assert AC.verdict("LHLL", [-3.0, 4.0, 5.0, -2.0]) == []          # 山が 3 モーラ目へずれた
    assert any("下がらない" in w for w in AC.verdict("LHLL", [-3.0, 4.0, 5.0, 4.5]))


def test_big_fall_inside_high_plateau():
    """見直し先も（低高高高高高高）の さき で大きく下がった。"""
    assert any("下がる" in w for w in AC.verdict("LHHHHHH", [-0.2, 6.9, 5.3, None, -2.7, -3.0, -3.5]))
    assert AC.verdict("LHHHH", [-2.0, 4.0, 3.0, 2.5, 2.0]) == []    # 自然な下がり（数半音）は許す


def test_unvoiced_moras_are_skipped():
    assert AC.verdict("LHH", [None, None, 3.0]) == []
    assert AC.verdict("LHLL", [0, 4, -3, -4]) == []
    assert AC.verdict("LHLL", [0, None, -3, -4]) == []   # 高いはずの 2 モーラ目が測れないとき、下がり目の後の低い所と比べない
    assert "頭が高い" in AC.verdict("LHHH", [5.0, None, -4.0, -5.0])


def test_mora_pitch_uses_late_part():
    """モーラの区間は頭から次の頭まで、高さは後ろ 5 割。前半の上り坂は見ない。"""
    t = np.arange(0, 1, 0.01)
    st = np.where(t < 0.25, -5.0, 5.0)        # 0.2〜0.4 のモーラの前半は低く、後半は高い
    c = [0.0, 0.2, 0.4]
    assert AC.mora_pitch(t, st, c, 1) == pytest.approx(5.0)
    assert AC.mora_pitch(t, np.full_like(t, np.nan), c, 1) is None


def test_mora_onsets_fill_gaps():
    ra = {"moras": [{"phs": ["k", "a"]}, {"phs": ["t", "a"]}, {"phs": ["n", "a"]}]}
    heard = [["k", 0.10, 0.12], ["a", 0.13, 0.15], ["x", 0.30, 0.31], ["n", 0.50, 0.52], ["a", 0.53, 0.55]]
    c = AC.mora_onsets(ra, heard)
    assert c[0] == pytest.approx(0.10) and c[2] == pytest.approx(0.50)
    assert c[1] == pytest.approx(0.30)       # t a が合わない（x と聞こえた）→ 前後のモーラの頭から等分で補う


@ojt_needed
def test_term_accent_survives_reading_substitution(monkeypatch):
    """辞書の語を読みの仮名に置き換えても、辞書の accent を基準にする。見本では 猫 は頭高。辞書に平板（LH）と書けば、
    頭高に読んだ声に警告が出る。"""
    from collections import namedtuple
    T = namedtuple("T", "word reading accent type")
    heard = [["n", 0.10, 0.12], ["e", 0.13, 0.15], ["k", 0.30, 0.32], ["o", 0.33, 0.35], ["g", 0.50, 0.52], ["a", 0.53, 0.55]]
    t = np.arange(0, 0.8, 0.005)
    st = np.where(t < 0.30, 5.0, -5.0)            # ね が高く、こ・が が低い（頭高）
    monkeypatch.setattr(AC.R, "check_line", lambda *a, **k: [])
    assert not [r for r in AC.check_line("猫が", None, heard, None, (), f0=(t, st)) if r["word"].startswith("猫")]
    flat = AC.check_line("猫が", None, heard, None, [T("猫", "ねこ", "LH", 0)], f0=(t, st))
    assert [r["word"] for r in flat] == ["猫+が"] and "頭が高い" in flat[0]["why"]


@ojt_needed
def test_phone_cache_uses_content_hash(tmp_path, monkeypatch):
    """大きさが同じでも中身の違う声は、書き起こしを使い回さない。中身が同じなら使い回す。"""
    import json
    sys.path.insert(0, os.path.join(HERE, "..", "skills", "video-mascot", "scripts"))
    import voice, phonemes
    os.makedirs(tmp_path / "voice")
    w = str(tmp_path / "voice" / "l1.wav")
    def sine(f):        # CI に ffmpeg が無いので wave で書く（どちらも 0.5 秒・同じ大きさ）
        import wave
        x = (np.sin(2 * np.pi * f * np.arange(8000) / 16000) * 8000).astype("<i2")
        with wave.open(w, "wb") as o: o.setnchannels(1); o.setsampwidth(2); o.setframerate(16000); o.writeframes(x.tobytes())
    sine(200)
    json.dump({"name": "t", "poses": {"home": {}}, "voice": {"lines": [{"text": "猫が"}]}}, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    calls = []
    monkeypatch.setattr(phonemes, "hear", lambda paths: calls.append(list(paths)) or [{"path": p, "phones": [["n", 0.1, 0.12]]} for p in paths])
    run = lambda: (monkeypatch.setattr(sys, "argv", ["voice.py", str(tmp_path), "accent"]), voice.main())
    run(); run()
    assert len(calls) == 1                         # 2 回目は控えを使う
    sine(300)                                      # 同じ長さ・違う中身
    run()
    assert len(calls) == 2


def test_report_shows_only_opened_words_by_default(monkeypatch, capsys):
    """既定は仮名に開いた語だけ。開いていない語は数だけで、show_all で出す。"""
    items = [{"word": "棒+が", "want": "LHH", "pitches": [5.0, -3.0, None], "why": ["頭が高い"], "t": 1.0, "end": 1.3, "opened": True},
             {"word": "並ぶ", "want": "LHH", "pitches": [-2.9, -5.4, 1.0], "why": ["頭が高い"], "t": 2.0, "end": 2.3, "opened": False}]
    monkeypatch.setattr(AC, "check_line", lambda *a, **k: items)
    found = AC.report([{"text": "x"}], {1: []}, lambda n: None)
    out = capsys.readouterr().out
    assert [r["word"] for r in found] == ["棒+が"] and "並ぶ" not in out and "疑い 1 件は出していない" in out
    found = AC.report([{"text": "x"}], {1: []}, lambda n: None, show_all=True)
    assert [r["word"] for r in found] == ["棒+が", "並ぶ"]



@ojt_needed
def test_term_already_in_say_keeps_dictionary_accent(monkeypatch):
    """say に辞書の読み（ねこ）を初めから書いた語も、辞書の accent を使う。"""
    from collections import namedtuple
    T = namedtuple("T", "word reading accent type")
    heard = [["n", 0.10, 0.12], ["e", 0.13, 0.15], ["k", 0.30, 0.32], ["o", 0.33, 0.35], ["g", 0.50, 0.52], ["a", 0.53, 0.55]]
    t = np.arange(0, 0.8, 0.005); st = np.where(t < 0.30, 5.0, -5.0)
    monkeypatch.setattr(AC.R, "check_line", lambda *a, **k: [])
    flat = AC.check_line("猫が", "ねこが", heard, None, [T("猫", "ねこ", "LH", 0)], f0=(t, st))
    assert [r["word"] for r in flat] == ["猫+が"] and "頭が高い" in flat[0]["why"]
    assert flat[0]["opened"]                          # 辞書の読みで開いた語も、開いた語（既定で出す側）


@ojt_needed
def test_misread_term_is_not_accent_checked(monkeypatch):
    """読みを誤った辞書の語（読みの検査の結果は仮名の ねこ）は、高さを見ない（文字の範囲で突き合わせる）。"""
    from collections import namedtuple
    T = namedtuple("T", "word reading accent type")
    heard = [["n", 0.10, 0.12], ["e", 0.13, 0.15], ["k", 0.30, 0.32], ["o", 0.33, 0.35], ["g", 0.50, 0.52], ["a", 0.53, 0.55]]
    t = np.arange(0, 0.8, 0.005); st = np.where(t < 0.30, 5.0, -5.0)
    monkeypatch.setattr(AC.R, "check_line", lambda *a, **k: [{"word": "ねこ", "ref_span": (0, 2), "kind": "misread"}])
    assert AC.check_line("猫が", None, heard, None, [T("猫", "ねこ", "LH", 0)], f0=(t, st)) == []



def test_phrase_final_long_vowel_gets_timing():
    """行末の長音（棒 b o / o）は norm でまとまって時刻が付かない。モーラの長さで延ばして高さを測れるようにする。"""
    ra = {"moras": [{"phs": ["b", "o"]}, {"phs": ["o"]}]}
    c = AC.mora_onsets(ra, [["b", 0.10, 0.11], ["o", 0.12, 0.50]])
    assert c[0] == pytest.approx(0.10) and c[1] is not None and c[1] > c[0]
    t = np.arange(0, 0.6, 0.005); st = np.where(t < c[1], 5.0, -5.0)       # 頭高に読んだ（低高のはず）
    p = [AC.mora_pitch(t, st, c, i) for i in range(2)]
    assert None not in p and "頭が高い" in AC.verdict("LH", p)



@ojt_needed
def test_adjacent_terms_keep_their_spans():
    """辞書の語が並んでも（東京大学）、それぞれの範囲を取る。置き換えた場合も、say に初めから読みで書いた場合も。"""
    from collections import namedtuple
    T = namedtuple("T", "word reading accent type")
    terms = [T("東京", "とうきょう", "LHHH", 0), T("大学", "だいがく", "LHHH", 0)]
    got = sorted(w for _, _, w in AC.term_spans("東京大学へ", "とうきょうだいがくへ", terms))
    assert got == ["大学", "東京"]
    ref = "とうきょうだいがくへ"
    spans = {w: ref[a:b] for a, b, w in AC.term_spans("東京大学へ", ref, terms)}
    assert spans == {"東京": "とうきょう", "大学": "だいがく"}
    import ojt
    ref2, done = AC.R.apply_terms(ojt.analyze("東京大学へ"), "東京大学へ", terms, spans=True)
    if ref2:                                  # 見本が 東京・大学 に分けたとき、置き換えの記録はそれぞれの範囲を持つ
        assert sorted(w for _, _, w in done) == sorted(n["string"] for n in ojt.analyze("東京大学へ")["nodes"] if n["string"] in ("東京", "大学"))
