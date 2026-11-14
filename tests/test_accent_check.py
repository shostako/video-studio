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
