"""video-mascot の口パク（lipsync: "mora"）の純関数のテスト。入力はすべて合成。"""
import pytest

import lib


def r(seg, nd=4):
    return [(round(s, nd), round(e, nd), k) for s, e, k in seg]


# ---------- kata_to_hira ----------
def test_kata_to_hira():
    assert lib.kata_to_hira("カタカナ・ヴァー") == "かたかな・ゔぁー"
    assert lib.kata_to_hira("ヵヶ漢字abc") == "ヵヶ漢字abc"


# ---------- kana_morae ----------
@pytest.mark.parametrize("kana, want", [
    ("あいうえお", [("あ", "a", False), ("い", "i", False), ("う", "u", False), ("え", "e", False), ("お", "o", False)]),
    ("きゃく", [("きゃ", "a", False), ("く", "u", False)]),
    ("みゃく", [("みゃ", "a", True), ("く", "u", False)]),           # 両唇音＋小書きは唇を閉じて a
    ("きって", [("き", "i", False), ("っ", "q", False), ("て", "e", False)]),
    ("こーひー", [("こ", "o", False), ("ー", "o", False), ("ひ", "i", False), ("ー", "i", False)]),
    ("ぱん", [("ぱ", "a", True), ("ん", "n", False)]),
    ("ゔぁ", [("ゔぁ", "a", False)]),
    ("カメラ", [("か", "a", False), ("め", "e", True), ("ら", "a", False)]),
])
def test_kana_morae(kana, want):
    assert lib.kana_morae(kana) == want


def test_kana_morae_pauses_collapse_and_unknown_dropped():
    # 続く句読点は1つの息つぎ。漢字・英字は捨てる。「っ」の後の「ー」は捨て、前に母音の無い小書きはその母音の1モーラ
    assert [k for _, k, _ in lib.kana_morae("あ、。 い漢ab")] == ["a", "pause", "i"]
    assert [k for _, k, _ in lib.kana_morae("っーゃあ")] == ["q", "a", "a"]
    assert [k for _, k, _ in lib.kana_morae("、ぃ")] == ["i"]                  # 先頭の句読点は付かない


# ---------- mora_track ----------
def test_mora_track_even_split():
    assert r(lib.mora_track("かいと", 1.0, 1.3)) == [(1.0, 1.1, "a"), (1.1, 1.2, "i"), (1.2, 1.3, "o")]


def test_mora_track_pause_weight_and_edges_trimmed():
    # 行頭・行末の句読点は捨てる。中の息つぎは 2 モーラ分の closed。全4単位で 0.4 秒
    assert r(lib.mora_track("、あ、い。", 0.0, 0.4)) == [(0.0, 0.1, "a"), (0.1, 0.3, "closed"), (0.3, 0.4, "i")]
    assert r(lib.mora_track("あ、い", 0.0, 0.3, pause_weight=1.0)) == [(0.0, 0.1, "a"), (0.1, 0.2, "closed"), (0.2, 0.3, "i")]


def test_mora_track_bilabial_closes_head():
    # 1モーラ 0.2 秒、閉じるのは頭の 0.3 → 0.06 秒、ただし min_close 0.067 秒以上
    assert r(lib.mora_track("あま", 0.0, 0.4)) == [(0.0, 0.2, "a"), (0.2, 0.267, "closed"), (0.267, 0.4, "a")]
    # 長いモーラは割合どおり。短いモーラはモーラの半分まで
    assert r(lib.mora_track("ま", 0.0, 1.0)) == [(0.0, 0.3, "closed"), (0.3, 1.0, "a")]
    assert r(lib.mora_track("ま", 0.0, 0.1)) == [(0.0, 0.05, "closed"), (0.05, 0.1, "a")]


def test_mora_track_n_before_bilabial_closes_and_merges():
    # 「さんぽ」: 「ん」は唇を閉じ、次の「ぽ」の頭の閉じとまとまる
    assert r(lib.mora_track("さんぽ", 0.0, 0.3, min_close=0.0)) == [(0.0, 0.1, "a"), (0.1, 0.23, "closed"), (0.23, 0.3, "o")]
    # 両唇音の前でなければ「ん」は n
    assert [k for _, _, k in lib.mora_track("さんか", 0.0, 0.3)] == ["a", "n", "a"]


def test_mora_track_sokuon_and_merge_same_shape():
    assert r(lib.mora_track("きって", 0.0, 0.3)) == [(0.0, 0.1, "i"), (0.1, 0.2, "closed"), (0.2, 0.3, "e")]
    assert r(lib.mora_track("かあ", 0.0, 0.2)) == [(0.0, 0.2, "a")]          # 続く同じ形は1区間


def test_mora_track_last_segment_ends_exactly_and_covers_line():
    seg = lib.mora_track("しゃしゅつあっしゅく、せいけい", 2.0, 5.0)
    assert seg[0][0] == 2.0 and seg[-1][1] == 5.0
    assert all(abs(a[1] - b[0]) < 1e-9 for a, b in zip(seg, seg[1:]))      # すき間なくつながる


@pytest.mark.parametrize("kana, s, e", [("", 0.0, 1.0), ("、。", 0.0, 1.0), ("漢字", 0.0, 1.0), ("あ", 1.0, 1.0), ("あ", 2.0, 1.0)])
def test_mora_track_empty(kana, s, e):
    assert lib.mora_track(kana, s, e) == []


# ---------- voiced_span ----------
def test_voiced_span_trims_silence():
    lv = [0, 0, 0.5, 0.2, 0, 0.3, 0, 0, 0, 0]
    assert lib.voiced_span(lv, 10, 0.0, 1.0) == (0.2, 0.6)
    assert lib.voiced_span(lv, 10, 0.0, 1.0, thr=0.4) == (0.2, 0.3)
    assert lib.voiced_span(lv, 10, 0.25, 1.0) == (0.25, 0.6)               # 行の範囲より外へは広げない


def test_voiced_span_no_voice_keeps_line_and_clips_to_levels():
    assert lib.voiced_span([0] * 10, 10, 0.1, 0.8) == (0.1, 0.8)
    assert lib.voiced_span([1.0] * 5, 10, 0.0, 2.0) == (0.0, 0.5)


# ---------- mora_frames ----------
def test_mora_frames_samples_frame_start():
    seg = [(0.0, 0.1, "a"), (0.1, 0.25, "closed"), (0.25, 0.4, "o")]
    assert lib.mora_frames(seg, 10, 6) == ["a", "closed", "closed", "o", None, None]


def test_mora_frames_clips_and_overwrites():
    assert lib.mora_frames([(-0.2, 0.15, "a"), (0.1, 5.0, "i")], 10, 4) == ["a", "i", "i", "i"]
    assert lib.mora_frames([], 10, 3) == [None] * 3


# ---------- mora_mouth ----------
def test_mora_mouth():
    assert lib.mora_mouth(1.0, "closed") is None and lib.mora_mouth(1.0, None) is None
    assert lib.mora_mouth(0.1, "a") is None                                   # 声が小さければ閉じる（choose_mouth と同じ）
    for lv in (0.2, 0.5, 0.9, 1.3):
        for k in "aiueon":
            assert lib.mora_mouth(lv, k) == lib.choose_mouth(lv, k)


def test_mora_pipeline_lips_close_visibly_at_30fps():
    # 「まめ」を 0.4 秒（30fps で 12 コマ）: 両唇音の頭が 2 コマ以上閉じ、smooth_mouth でも消えない
    seg = lib.mora_track("まめ", 0.0, 0.4)
    mouth = lib.smooth_mouth([lib.mora_mouth(1.0, k) for k in lib.mora_frames(seg, 30, 12)], 1)
    assert mouth[:3] == [None] * 3 and mouth[3] is not None                  # 0〜0.067 秒
    assert mouth[6:9] == [None] * 3 and mouth[9] is not None                 # 0.2〜0.267 秒
