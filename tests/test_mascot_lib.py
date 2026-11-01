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


# ---------- num_to_kanji / words_hira ----------
@pytest.mark.parametrize("src, want", [
    ("2つ", "二つ"), ("100%", "百%"), ("2026年", "二千二十六年"), ("10", "十"), ("1000", "千"), ("12345", "一万二千三百四十五"),
    ("0", "零"), ("２つ", "二つ"), ("1.5倍", "1.5倍"), ("1,000円", "千円"), ("12,345,678", "千二百三十四万五千六百七十八"), ("かな", "かな"),
])
def test_num_to_kanji(src, want):
    assert lib.num_to_kanji(src) == want


def test_words_hira_reads_split_words_in_context():
    """Whisper が「見える」を「見」「える」に分けても、行の文脈で「み」「える」と読む（1 語ずつだと「けん」になった）。"""
    pykakasi = pytest.importorskip("pykakasi"); K = pykakasi.kakasi()
    hs = lib.words_hira(["ここが", "見", "える", "。", "2", "つ", "の", "考え"], K.convert)
    assert hs[1] + hs[2] == "みえる" and hs[4] + hs[5] == "ふたつ" and hs[7] == "かんがえ" and hs[3] == ""
    stream = [(ch, 0.0) for h in hs for ch in h]
    assert lib.find_time(stream, 0, 1, "みえる", 0.5)[1] == "声" and lib.find_time(stream, 0, 1, "ふたつ", 0.5)[1] == "声"


def test_words_hira_falls_back_per_word_when_lengths_do_not_match():
    calls = []
    def conv(t):
        calls.append(t); return [{"orig": t + "x", "hira": "あ"}] if len(calls) == 1 else [{"orig": t, "hira": "い"}]
    assert lib.words_hira(["a", "b"], conv) == ["い", "い"]



def test_words_hira_numbers_split_across_words():
    """数字が語の途中で分かれても、つないだ文の上で読む（「20」「26」「年」→ にせんにじゅうろくねん）（Codex の指摘）。"""
    pykakasi = pytest.importorskip("pykakasi"); K = pykakasi.kakasi()
    assert "".join(lib.words_hira(["20", "26", "年"], K.convert)) == "にせんにじゅうろくねん"
    hs = lib.words_hira(["1", ",", "000", "円"], K.convert)
    assert "".join(hs) == "せんえん"                                    # 桁区切りの数も千と読む（語への配り方は読みの塊の比で）


# ---------- tail_blip（行の声の終わりのゴミの音）----------
def _voice_like(parts, sr=24000):
    """[(秒, 大きさ), ...] を順につないだ合成の声（大きさ 0 は無音、それ以外は 220Hz の正弦波）。"""
    import numpy as np
    out = []
    for d, a in parts:
        t = np.arange(int(d * sr)) / sr; out.append((a * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
    return np.concatenate(out), sr


def test_tail_blip_finds_a_cut_off_sound_after_silence():
    """旧PC の l11.wav の形: 読み終えて 0.36 秒黙ったあと、0.04 秒の大きい音（0.56）がファイルの端で切れている。"""
    x, sr = _voice_like([(1.5, 0.4), (0.36, 0.0), (0.04, 0.56)])
    a, b = lib.tail_blip(x, sr)
    assert abs(a / sr - 1.86) < 0.02 and b == len(x)


def test_tail_blip_finds_a_small_sound_just_before_the_end():
    """旧PC の l8.wav の形: 黙ったあと、端の 0.06 秒手前の 40 ミリ秒の小さい音（0.047）。端の 20 ミリ秒は静か。"""
    x, sr = _voice_like([(1.5, 0.4), (0.4, 0.0), (0.04, 0.047), (0.02, 0.0)])
    a, b = lib.tail_blip(x, sr)
    assert abs(a / sr - 1.90) < 0.02 and b == len(x)


def test_tail_blip_finds_a_click_inside_the_last_partial_window():
    """端の 10 ミリ秒に満たない区切りだけで鳴る 5 ミリ秒の音も拾う（Codex の指摘）。"""
    x, sr = _voice_like([(1.5, 0.4), (0.36, 0.0), (0.005, 0.5)])
    assert len(x) % int(sr * 0.01) != 0
    a, b = lib.tail_blip(x, sr)
    assert b == len(x) and abs(a / sr - 1.86) < 0.02


@pytest.mark.parametrize("parts", [
    [(1.0, 0.4), (0.84, 0.0), (0.5, 0.4), (0.3, 0.0)],     # 読点の間のあとに語が続き、端の前に終わる（l12 の「以上だ」）
    [(1.5, 0.4), (0.36, 0.0), (0.3, 0.4)],                 # 端で切れているが長い＝本物の語
    [(1.5, 0.4), (0.1, 0.0), (0.04, 0.5)],                 # 黙りが短い（語の続き）
    [(1.5, 0.4), (0.4, 0.0)],                              # 終わりは静か
    [(0.4, 0.0), (0.05, 0.5)],                             # 前に声が無い
])
def test_tail_blip_leaves_real_speech(parts):
    x, sr = _voice_like(parts)
    assert lib.tail_blip(x, sr) is None


@pytest.mark.skipif(not (__import__("shutil").which("ffmpeg") and __import__("shutil").which("ffprobe")), reason="ffmpeg・ffprobe が無い")
def test_voice_master_mutes_tail_blip_without_changing_timing(tmp_path):
    """vm voice master は、行の声の終わりのゴミの音を無音にして master を組む。行の長さ（時刻）は変えない。"""
    import json, subprocess, sys, wave
    from pathlib import Path
    import numpy as np
    root = tmp_path / "proj"; (root / "voice").mkdir(parents=True)
    json.dump({"name": "t", "fps": 30, "poses": {"home": {}}, "voice": {"lines": [{"text": "あ"}, {"text": "い"}], "gap": 0.5}},
              open(root / "config.json", "w"), ensure_ascii=False)
    for n, parts in ((1, [(1.0, 0.4), (0.5, 0.0)]), (2, [(1.5, 0.4), (0.36, 0.0), (0.04, 0.56)])):
        x, sr = _voice_like(parts)
        with wave.open(str(root / "voice" / f"l{n}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((x * 32767).astype(np.int16).tobytes())
    scripts = Path(__file__).resolve().parent.parent / "skills" / "video-mascot" / "scripts"
    r = subprocess.run([sys.executable, "-B", str(scripts / "voice.py"), str(root), "master"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "行2: 終わりのゴミの音を消した" in r.stdout and "行1:" not in r.stdout.split("終わりのゴミ")[0].splitlines()[-1]
    tm = json.load(open(root / "voice" / "timing.json"))
    assert abs(tm["lines"][1]["dur"] - 1.90) < 0.02                       # 行の長さはそのまま
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(root / "voice" / "master.wav"), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
    m = np.frombuffer(raw, np.float32); st = tm["lines"][1]["start"]
    tail = m[int((st + 1.87) * 48000):int((st + 1.90) * 48000)]
    assert np.abs(tail).max() < 0.02                                       # ゴミの音の所は無音


# ---------- short_holds（着く前に上書きされる身振り）----------
def test_short_holds_flags_overlap_but_not_quick_wag_or_home():
    sw = [(10.0, 0.6, "home", "point_r"), (10.3, 0.6, "point_r", "home"),      # point_r に着く前（10.6）に次が始まる（旧PC の 29.04 秒）
          (20.0, 0.6, "home", "wag_r"), (20.65, 0.3, "wag_r", "wag_l"),        # 着いて 0.05 秒で次（指を振る）＝見える
          (21.0, 0.6, "wag_l", "home"), (21.6, 0.6, "home", "open")]            # home に一瞬寄るのは数えない
    out = lib.short_holds(sw, "home")
    assert [(o["at"], o["pose"]) for o in out] == [(10.0, "point_r")] and out[0]["hold"] < 0
    assert lib.short_hold_report([]) == [] and "上書き" in lib.short_hold_report(out)[0]


def test_short_holds_tolerates_float_rounding():
    """ちょうど接する切り替えを、0.1+0.2 > 0.3 の誤差で重なりと見ない（Codex の指摘）。"""
    assert lib.short_holds([(0.1, 0.2, "home", "point"), (0.3, 0.2, "point", "home")], "home") == []


# ---------- matte の範囲指定（ワイプ用、vm render --crop）----------
def _figure():
    """白地に、黒い髪（すき間の白あり）・肌の顔・白目・黒い輪郭で囲んだ白いシャツの人型。足元に影。"""
    import numpy as np
    H, W = 420, 300; img = np.full((H, W, 3), 253, np.uint8)
    img[40:150, 90:210] = (25, 25, 30)                                  # 髪
    img[60:62, 120:150] = 253; img[90:93, 100:104] = 253                # 毛束の間の白（小さい）
    img[100:170, 110:190] = (190, 210, 240)                             # 顔（肌）
    img[120:126, 125:135] = 250; img[120:126, 160:170] = 250            # 白目
    img[170:400, 80:220] = (30, 30, 30); img[174:396, 84:216] = 236     # 黒い輪郭で囲んだ白いシャツ（影で少し灰色）
    sh = np.zeros((H, W), np.float32); sh[398:412, 70:230] = 0.4
    return img, sh, [(110, 100, 190, 170)]


@pytest.mark.parametrize("roi", [(60, 20, 240, 200), (0, 0, 300, 420), (100, 150, 200, 260), (0, 300, 120, 420), (290, 410, 300, 420)])
def test_matte_roi_matches_full_crop(roi):
    """roi を渡しても、全体で作って切り抜いたものと 1 画素も違わない。切り口がシャツの白を横切っても抜けない。"""
    import numpy as np
    img, sh, keeps = _figure()
    full = lib.matte(img, sh, keeps)
    part = lib.matte(img, sh, keeps, roi=roi)
    assert part.shape == (roi[3] - roi[1], roi[2] - roi[0], 4)
    assert np.array_equal(part, full[roi[1]:roi[3], roi[0]:roi[2]])
    assert full[250, 150, 3] >= 250 and full[5, 5, 3] == 0              # シャツの白は不透明、外の白は透明


def test_matte_roi_outside_is_an_error():
    img, sh, keeps = _figure()
    with pytest.raises(ValueError):
        lib.matte(img, sh, keeps, roi=(400, 0, 500, 100))


def test_wipe_box_none_without_figure():
    import numpy as np
    assert lib.wipe_box(np.zeros((50, 40), bool)) is None
    fg = np.zeros((1280, 720), bool); fg[200:1160, 260:460] = True
    x, y, side = lib.wipe_box(fg)
    assert side == int(0.44 * 959) // 2 * 2 and x + side <= 720


# ---------- matte の囲まれた白（enclosed: keep、opt-in）----------
def _figure_gap():
    """_figure に、背景の色そのものの囲まれたすき間（脚の間の代わり）と、毛の間の白を足す。シャツは純白（253）の陰影つき。"""
    import numpy as np
    img, sh, keeps = _figure()
    img[174:396, 84:216] = 253; img[174:396:6, 84:216] = 244          # 白いシャツ（陰影の筋が入る）
    img[196:384, 226:284] = (30, 30, 30); img[200:380, 230:280] = 253   # 体の横に、黒い枠で囲んだ背景の色のすき間（腕と体の間の代わり）
    return img, sh, keeps


def test_matte_enclosed_keep_closes_shirt_but_opens_flat_gap():
    img, sh, keeps = _figure_gap()
    old = lib.matte(img, sh, keeps); new = lib.matte(img, sh, keeps, enclosed="keep")
    assert old[250, 120, 3] == 0                                       # 今まで: 顔の箱の外の囲まれた白（シャツ）は抜ける
    assert new[250, 120, 3] >= 250                                     # keep: シャツはキャラとして閉じる
    assert new[290, 255, 3] == 0 and old[290, 255, 3] == 0             # 背景の色そのもののすき間は、どちらでも抜ける
    assert new[5, 5, 3] == 0                                           # 外の白は透明のまま


def test_matte_enclosed_keep_protects_eye_white_inside_face_box():
    """顔の箱の中の白目・歯は、背景の色そのもの（253）でも keep で抜かない（bg と同じ。Codex の指摘）。"""
    img, sh, keeps = _figure_gap()
    img[140:146, 140:150] = 253                                        # 肌の顔の中に、背景と同じ色の白目
    for mode in ("bg", "keep"):
        assert lib.matte(img, sh, keeps, enclosed=mode)[143, 145, 3] >= 250, mode


def test_matte_enclosed_keep_roi_matches_full_crop():
    import numpy as np
    img, sh, keeps = _figure_gap()
    full = lib.matte(img, sh, keeps, enclosed="keep")
    for roi in [(60, 200, 240, 420), (220, 190, 290, 390), (100, 240, 260, 300)]:
        assert np.array_equal(lib.matte(img, sh, keeps, roi=roi, enclosed="keep"), full[roi[1]:roi[3], roi[0]:roi[2]])


def test_matte_enclosed_rejects_unknown():
    img, sh, keeps = _figure()
    with pytest.raises(ValueError):
        lib.matte(img, sh, keeps, enclosed="close")
