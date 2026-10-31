"""video-mascot の lib.py の純関数（母音の時刻列、events の時刻の解決、口の形）のテスト。
入力はすべて合成。今の挙動をそのまま固定して、リファクタや opt-in の機能を足すときの安全網にする。"""
import pytest

import lib


# ---------- hira_vowels ----------
@pytest.mark.parametrize("h, want", [
    ("あいうえお", [("あ", "a"), ("い", "i"), ("う", "u"), ("え", "e"), ("お", "o")]),
    ("かん", [("か", "a"), ("ん", "n")]),
    ("きって", [("き", "i"), ("っ", "-"), ("て", "e")]),
    ("こーひー", [("こ", "o"), ("ー", "o"), ("ひ", "i"), ("ー", "i")]),
    ("きゃく", [("き", "a"), ("く", "u")]),            # 小書きは前の音にまとめ、母音を置き換える
    ("しぇ", [("し", "e")]),
    ("ゃあ", [("ゃ", "a"), ("あ", "a")]),               # 先頭の小書きは1音として残る
])
def test_hira_vowels(h, want):
    assert lib.hira_vowels(h) == want


def test_hira_vowels_long_vowel_after_sokuon_and_unknown():
    # 「ー」は直前の母音。「っ」の後なら "-"、知らない字は None（直前の母音は引き継がない）
    assert lib.hira_vowels("っー") == [("っ", "-"), ("ー", "-")]
    assert lib.hira_vowels("ゔー") == [("ゔ", None), ("ー", None)]
    assert lib.hira_vowels("あゔー") == [("あ", "a"), ("ゔ", None), ("ー", "a")]


# ---------- vowel_frames ----------
def test_vowel_frames_splits_word_evenly():
    # 1.0〜1.3 秒の「かいと」: 1音 0.1 秒、30fps で 3 コマずつ
    va, hs = lib.vowel_frames([("かいと", 1.0, 1.3)], 30, 60)
    assert [round(t, 6) for _, t in hs] == [1.0, 1.1, 1.2]
    assert [c for c, _ in hs] == ["か", "い", "と"]
    assert va[29] is None and va[30:33] == ["a"] * 3 and va[33:36] == ["i"] * 3 and va[36:39] == ["o"] * 3
    assert va[39] is None


def test_vowel_frames_skips_empty_and_clips_to_nall():
    va, hs = lib.vowel_frames([("", 0.0, 0.5), ("あ", 0.9, 2.0)], 10, 12)
    assert len(va) == 12 and hs == [("あ", 0.9)]
    assert va[:9] == [None] * 9 and va[9:] == ["a"] * 3


def test_vowel_frames_later_word_overwrites_overlap():
    va, _ = lib.vowel_frames([("あ", 0.0, 0.2), ("い", 0.1, 0.3)], 10, 4)
    assert va == ["a", "i", "i", None]


# ---------- find_time / find_word ----------
STREAM = [("は", 0.5), ("じ", 0.6), ("め", 0.7), ("ま", 2.0), ("す", 2.1), ("は", 5.0), ("じ", 5.1)]


def test_find_time_hits_first_in_window():
    assert lib.find_time(STREAM, 0.5, 2.0, "はじ", 0.5) == (0.5, "声")
    assert lib.find_time(STREAM, 4.0, 2.0, "はじ", 0.5) == (5.0, "声")      # 窓の外の 0.5 秒は見ない


def test_find_time_window_margin_is_02s():
    assert lib.find_time(STREAM, 2.2, 1.0, "ます", 0.5) == (2.0, "声")      # 行頭の 0.2 秒前まで含む
    assert lib.find_time(STREAM, 2.25, 1.0, "ます", 0.5) == (2.75, "推定")  # 窓の外 → 行の割合で見積もる


def test_find_time_crosses_word_boundary_and_falls_back():
    assert lib.find_time(STREAM, 0.5, 2.0, "めま", 0.5) == (0.7, "声")     # 語をまたいでも音の並びで探す
    assert lib.find_time(STREAM, 0.0, 4.0, "ない", 0.25) == (1.0, "推定")


def test_find_time_small_kana_keyword_is_not_found():
    # 今の挙動: 音の並びには小書きが入らない（「きゃ」は「き」1音）ので、小書きを含むキーワードは見つからず推定になる
    _, hs = lib.vowel_frames([("きゃく", 1.0, 1.2)], 30, 60)
    assert lib.find_time(hs, 1.0, 1.0, "きゃく", 0.5) == (1.5, "推定")
    assert lib.find_time(hs, 1.0, 1.0, "きく", 0.5) == (1.0, "声")


WORDS = [("それでは", 0.3, 0.8), ("ほんばん", 1.0, 1.5), ("です", 1.5, 1.8), ("ほんばん", 6.0, 6.5)]


def test_find_word():
    assert lib.find_word(WORDS, 0.5, 2.0, ("ほんばん",), 0.5) == (1.0, "語")
    assert lib.find_word(WORDS, 5.0, 2.0, ("ほんばん", "です"), 0.5) == (6.0, "語")
    assert lib.find_word(WORDS, 0.5, 2.0, ("です", "それでは"), 0.5) == (0.3, "語")   # 候補の順ではなく、時刻の早い語
    assert lib.find_word(WORDS, 0.5, 2.0, ("ほん",), 0.5) == (1.5, "推定")              # 語全体の一致だけ


# ---------- resolve_events ----------
STARTS = {1: 0.5, 2: 4.0}
DURS = {1: 2.0, 2: 3.0}
IBDUR = 5 / 15


def _resolve(events, **kw):
    return lib.resolve_events(events, "home", STARTS, DURS, IBDUR, STREAM, WORDS, **kw)


def test_resolve_events_each_kind():
    ev = _resolve([
        {"pose": "a", "line": 1, "kw": "はじ"},                    # 0.5 - ibdur - 0.04
        {"pose": "b", "line": 2, "word": ["ほんばん"], "offset": 0.1},
        {"pose": "c", "at": 8.0},
        {"pose": "d", "line_start": 2, "offset": -0.5},
        {"pose": "e", "line_end": 1},                               # offset の既定は 0.05
    ])
    want = [(0.5 - IBDUR - 0.04, "home", "a"), (2.55, "d", "e"), (3.5, "c", "d"),
            (6.0 - IBDUR - 0.04 + 0.1, "a", "b"), (8.0, "b", "c")]
    assert [(round(s, 9), a, b) for s, a, b in ev] == [(round(s, 9), a, b) for s, a, b in want]


def test_resolve_events_keeps_config_order_for_from_pose_then_sorts():
    # 前の姿勢は config に書いた順でつながる。並べ替えは開始時刻だけ
    ev = _resolve([{"pose": "a", "at": 5.0}, {"pose": "b", "at": 1.0}])
    assert ev == [(1.0, "a", "b"), (5.0, "home", "a")]


def test_resolve_events_fallback_and_log():
    logs = []
    ev = _resolve([{"pose": "a", "line": 2, "kw": "ない", "fallback": 0.2}], log=logs.append)
    assert ev[0][0] == pytest.approx(4.0 + 3.0 * 0.2 - IBDUR - 0.04)
    assert len(logs) == 1 and "推定" in logs[0] and "home→a" in logs[0]


def test_resolve_events_at_ignores_offset():
    assert _resolve([{"pose": "a", "at": 2.0, "offset": 1.0}]) == [(2.0, "home", "a")]


def test_resolve_events_missing_start_dies():
    with pytest.raises(SystemExit):
        _resolve([{"pose": "a"}])


def test_resolve_events_empty():
    assert _resolve([]) == []


# ---------- plan_at ----------
def _ib_seq(a, b):
    if (a, b) == ("home", "a"): return [f"ib{k}" for k in range(1, 6)]
    return None


EV = [(1.0, "home", "a"), (3.0, "a", "b")]


@pytest.mark.parametrize("t, want", [
    (0.0, ("pose", "home")),
    (0.999, ("pose", "home")),
    (1.0, ("ib", "ib1", "home")),
    (1.0 + 1.5 / 15, ("ib", "ib2", "home")),
    (1.0 + 2.5 / 15, ("ib", "ib3", "a")),        # 中割り5枚のうち前の2枚（4割）は元の姿勢の部品
    (1.0 + 4.5 / 15, ("ib", "ib5", "a")),
    (1.0 + 5.5 / 15, ("pose", "a")),
    (3.0, ("pose", "b")),                        # 中割りの無い組は即座に切り替える
    (10.0, ("pose", "b")),
])
def test_plan_at(t, want):
    assert lib.plan_at(t, EV, "home", _ib_seq, 15, 5) == want


# ---------- choose_mouth ----------
@pytest.mark.parametrize("lv, v, want", [
    (0.1, "a", None), (1.0, None, None), (1.0, "-", None),
    (0.15, "n", "m1"), (1.5, "n", "m1"),
    (0.41, "a", "m1"), (0.42, "a", "m7"), (0.79, "a", "m7"), (0.8, "a", "m2"), (1.14, "a", "m2"), (1.15, "a", "m3"),
    (0.44, "i", "m1"), (0.45, "e", "m7"), (1.09, "i", "m7"), (1.1, "e", "m6"),
    (0.29, "u", "m1"), (0.3, "u", "m5"),
    (0.29, "o", "m1"), (0.3, "o", "m4"),
    (1.0, "x", "m1"),
])
def test_choose_mouth(lv, v, want):
    assert lib.choose_mouth(lv, v) == want


# ---------- smooth_mouth ----------
def test_smooth_mouth_r1_drops_single_frame_blips():
    src = ["m1", "m4", "m1", "m1", "m2", "m2", "m5"]
    assert lib.smooth_mouth(src, 1) == ["m1", "m1", "m1", "m1", "m2", "m2", "m5"]   # 最後のコマは触らない
    assert src[1] == "m4"                                                           # 元のリストは変えない


def test_smooth_mouth_r1_is_sequential():
    # 左から順に置き換えるので、直した結果が次の判定に効く
    assert lib.smooth_mouth(["a", "b", "c", "d"], 1) == ["a", "a", "a", "d"]


def test_smooth_mouth_r2_drops_runs_up_to_r():
    src = ["m1", "m1", "m4", "m4", "m2", "m2", "m2", None, "m5", "m5"]
    assert lib.smooth_mouth(src, 2) == ["m1", "m1", "m1", "m1", "m2", "m2", "m2", "m2", "m5", "m5"]


def test_smooth_mouth_r2_keeps_last_run_and_first_frame():
    assert lib.smooth_mouth(["m3", "m1", "m1", "m1", "m4"], 2) == ["m3", "m1", "m1", "m1", "m4"]
    assert lib.smooth_mouth([], 2) == [] and lib.smooth_mouth(["m1"], 1) == ["m1"]


# ---------- frame_levels ----------
@pytest.mark.parametrize("sr, fps", [(16000, 60), (16000, 30), (44100, 60), (48000, 24)])
def test_frame_levels_stays_on_time_at_the_end(sr, fps):
    """280 秒の無音の終わり近く（277.4 秒）に 0.5 秒の音を置き、音が鳴っているコマがその時刻に来る（sr // fps の歩幅だとずれた）。"""
    import numpy as np
    dur, t0, t1 = 280.0, 277.4, 277.9
    x = np.zeros(int(dur * sr), np.float32); x[int(t0 * sr):int(t1 * sr)] = 0.5
    nall = int(dur * fps); win = sr * 2 // 30
    lv = lib.frame_levels(x, sr, fps, nall, win)
    on = np.nonzero(lv > 0.25)[0]
    w = win / sr                                                     # 窓（約 0.067 秒）が音にかかっているコマだけが鳴る
    assert t0 - w - 1 / fps <= on[0] / fps <= t0 and t1 - w <= on[-1] / fps <= t1   # sr // fps の歩幅だと 16000 Hz・60fps で 0.69 秒早くずれた
    assert lv[-1] == 0 and len(lv) == nall


def test_frame_levels_outside_the_wave_is_zero():
    import numpy as np
    lv = lib.frame_levels(np.ones(1000, np.float32), 16000, 60, 10, 533)
    assert lv[0] == pytest.approx(1.0) and lv[4] == 0 and lv[9] == 0     # 1000 サンプルの外のコマ（4 は 1067 から）は 0


# ---------- word_hira / fill_vowel_gaps / mouth_shut_spans ----------
@pytest.mark.parametrize("hira, word, want", [
    ("つかいかた", "使い方", "つかいかた"),     # かながあればそのまま
    ("", "CAD", "あ"), ("", "100", "あ"), ("", "%", "あ"), ("", "×", "あ"),   # 英字・数字・記号は「あ」
    ("", " ", ""), ("", "。", ""), ("", "", ""),                              # 空白・句読点だけなら母音なし
])
def test_word_hira(hira, word, want):
    assert lib.word_hira(hira, word) == want


def test_fill_vowel_gaps_near_words_only():
    fps = 10
    v = ["a", None, None, None, None, None, None, None, None, None, "o"]   # 語の間に 9 コマ（0.9 秒）
    loud = [True] * 11
    out = lib.fill_vowel_gaps(v, loud, fps, max_gap=0.3)
    assert out == ["a", "a", "a", "a", None, None, None, "o", "o", "o", "o"]   # 両端から 0.3 秒以内だけ、近い側の母音
    assert v[1] is None                                                      # 元のリストは変えない


def test_fill_vowel_gaps_keeps_quiet_frames_and_edges():
    fps = 10
    v = [None, None, "i", None, None]; loud = [True, False, True, True, False]
    assert lib.fill_vowel_gaps(v, loud, fps, max_gap=0.4) == ["i", None, "i", "i", None]
    assert lib.fill_vowel_gaps([None] * 4, [True] * 4, fps) == [None] * 4     # 語が無ければ何もしない


def test_mouth_shut_spans():
    fps = 10
    loud = [True] * 8 + [False] * 2
    speak = [True, False, False, True, False, False, False, True, False, False]
    assert lib.mouth_shut_spans(loud, speak, fps, f0=20, long_s=0.2) == [
        {"from": 2.1, "to": 2.3, "dur": 0.2}, {"from": 2.4, "to": 2.7, "dur": 0.3}]
    assert lib.mouth_shut_spans(loud, speak, fps, f0=0, long_s=0.25) == [{"from": 0.4, "to": 0.7, "dur": 0.3}]
    assert lib.mouth_shut_report([]) == [] and "△" in lib.mouth_shut_report([{"from": 1, "to": 2, "dur": 1}], problem=False)[1]


def test_speech_loud_skips_sokuon_closure():
    """「きって」の「っ」は意図して口を閉じる所。声が残っていても口の検査では数えない（Codex の指摘）。"""
    fps, R = 30, 1
    va, _ = lib.vowel_frames([("きって", 0.0, 0.9)], fps, 27)
    mouth = lib.smooth_mouth([lib.choose_mouth(0.7, v) for v in va], R)
    loud = [lib.speech_loud(0.7, v) for v in va]
    assert lib.mouth_shut_spans(loud, [m is not None for m in mouth], fps, 0) == []
    assert lib.mouth_shut_spans([True] * 27, [m is not None for m in mouth], fps, 0) != []   # 「っ」を外さないと引っかかる
    assert lib.speech_loud(0.1, "a") is False and lib.speech_loud(0.5, None) is True
