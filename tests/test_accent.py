"""accent.py のテスト。音はピッチ列を指定して合成する（本物の声は使わない）。"""
import json, subprocess, sys, wave
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("parselmouth")
import accent as ac

SR = 16000
L_HZ, H_HZ = 170.0, 230.0  # 差は約 5.2 半音
SCRIPT = Path(__file__).resolve().parent.parent / "skills/video-scene/scripts/accent.py"


def synth(levels, mora=0.15, lead=0.2, tail=0.2, glide=0.02, unvoiced=(), lo=L_HZ, hi=H_HZ):
    """モーラごとの高さ（0/1）で倍音の多い声もどきを作る。unvoiced の番号のモーラは無音にする。
    返り値は (標本, 語の開始時刻, 語の終了時刻)。"""
    n = len(levels)
    f = np.concatenate([np.full(int(mora * SR), hi if v else lo) for v in levels])
    k = max(1, int(glide * SR))  # 段差を少しなめらかにする（境目は計測で使わない）
    f = np.convolve(np.pad(f, (k, k), mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = sum(np.sin(h * ph) / h for h in range(1, 9))
    env = np.ones_like(x)
    for i in unvoiced:
        env[int(i * mora * SR):int((i + 1) * mora * SR)] = 0.0
    x = 0.3 * x / np.max(np.abs(x)) * env
    x = np.concatenate([np.zeros(int(lead * SR)), x, np.zeros(int(tail * SR))])
    return x, lead, lead + n * mora


def test_parse_accent_forms():
    assert ac.parse_accent("LHHHL") == (0, 1, 1, 1, 0)
    assert ac.parse_accent("低高高高低") == (0, 1, 1, 1, 0)
    assert ac.parse_accent("l-h h・L") == (0, 1, 1, 0)
    with pytest.raises(ValueError):
        ac.parse_accent("LXH")
    with pytest.raises(ValueError):
        ac.parse_accent(" - ")


@pytest.mark.parametrize("n,k,want", [
    (1, 0, "L"), (1, 1, "H"), (3, 0, "LHH"), (3, 1, "HLL"), (3, 2, "LHL"), (3, 3, "LHH"),
    (5, 4, "LHHHL"), (4, 0, "LHHH"),
])
def test_accent_from_type(n, k, want):
    assert ac.accent_from_type(n, k) == want


def test_accent_from_type_rejects():
    with pytest.raises(ValueError):
        ac.accent_from_type(3, 4)
    with pytest.raises(ValueError):
        ac.accent_from_type(0, 0)


def test_score_pitches_skips_unvoiced_and_classifies():
    r = ac.score_pitches([-2.0, None, 3.0, 2.5, -2.0], "LHHHL", thresh=1.5)
    assert r["unvoiced"] == [1]
    assert [(p["from"], p["to"]) for p in r["pairs"]] == [(0, 2), (2, 3), (3, 4)]
    assert r["want"] == "↑→↓" and r["got"] == "↑→↓" and r["score"] == 1.0
    assert r["drop_want"] == 4 and r["drop_got"] == 4 and r["drop_ok"]
    r = ac.score_pitches([0.0, 0.0], "LH", thresh=1.5)
    assert r["got"] == "→" and r["score"] == 0.0
    assert ac.score_pitches([None, 1.0], "LH")["score"] is None
    with pytest.raises(ValueError):
        ac.score_pitches([0.0], "LH")


def test_measured_f0_matches_synth():
    x, s, e = synth((0, 1))
    t, f0 = ac.f0_track((x, SR))
    m = lambda a, b: np.nanmedian(f0[(t > a) & (t < b)])
    assert abs(m(s + 0.04, s + 0.11) - L_HZ) < 3
    assert abs(m(s + 0.19, s + 0.26) - H_HZ) < 3
    assert np.all(np.isnan(f0[t < s - 0.05]))  # 頭の無音は声なし


@pytest.mark.parametrize("pattern", ["LHHHL", "HLLL", "LHHH", "LHL", "LHLHL"])
def test_correct_pattern_scores_full(pattern):
    x, s, e = synth(ac.parse_accent(pattern))
    [r] = ac.score_words((x, SR), [{"word": "w", "start": s, "end": e, "accent": pattern}])
    assert r["score"] == 1.0, r
    assert r["got"] == r["want"] and r["drop_ok"]


def test_broken_accent_scores_low():
    # ハンドオフの例: 「薄い板」は LHHHL が正しい。崩れた声（LHLHL）を正しい列で測ると点が下がる
    x, s, e = synth(ac.parse_accent("LHLHL"))
    [r] = ac.score_words((x, SR), [{"word": "薄い板", "start": s, "end": e, "accent": "LHHHL"}])
    assert r["got"] == "↑↓↑↓" and r["want"] == "↑→→↓"
    assert r["score"] == 0.5
    assert r["drop_want"] == 4 and r["drop_got"] == 2 and r["drop_ok"] is False


def test_heiban_vs_atamadaka_distinguished():
    x, s, e = synth(ac.parse_accent("HLLL"))
    w = {"start": s, "end": e}
    good, bad = ac.score_words((x, SR), [dict(w, type=1, morae=4), dict(w, type=0, morae=4)])
    assert good["accent"] == "HLLL" and good["score"] == 1.0
    assert good["drop_want"] == good["drop_got"] == 1 and good["drop_ok"]
    # 平らな組が多いので score は 2/3 残る。型の取り違えは下がり目で分かる
    assert bad["accent"] == "LHHH" and bad["score"] < 1.0
    assert bad["drop_want"] is None and bad["drop_got"] == 1 and bad["drop_ok"] is False


def test_unvoiced_mora_is_skipped():
    # 「うすい」の「す」の無声化をまねて、2モーラ目を無音にする
    x, s, e = synth(ac.parse_accent("LHHHL"), unvoiced=(1,))
    [r] = ac.score_words((x, SR), [{"word": "w", "start": s, "end": e, "accent": "LHHHL"}])
    assert r["unvoiced"] == [1]
    assert r["want"] == "↑→↓" and r["score"] == 1.0


def test_semitones_do_not_depend_on_voice_height():
    lv = ac.parse_accent("LHHL")
    res = []
    for scale in (1.0, 0.6):  # 低い声でも同じ結果
        x, s, e = synth(lv, lo=L_HZ * scale, hi=H_HZ * scale)
        [r] = ac.score_words((x, SR), [{"start": s, "end": e, "accent": "LHHL"}])
        res.append(r)
    assert res[0]["got"] == res[1]["got"] == "↑→↓"
    assert all(abs(a - b) < 0.3 for a, b in zip(res[0]["pitches"], res[1]["pitches"]))


def test_explicit_bounds():
    x, s, e = synth((0, 1, 0), mora=0.15)
    b = [s, s + 0.15, s + 0.30, s + 0.45]
    [r] = ac.score_words((x, SR), [{"start": 0, "end": 0, "accent": "LHL", "bounds": b}])
    assert r["score"] == 1.0
    with pytest.raises(ValueError):
        ac.score_words((x, SR), [{"start": s, "end": e, "accent": "LHL", "bounds": b[:3]}])


def test_cli_on_wav(tmp_path):
    x, s, e = synth(ac.parse_accent("LHHHL"))
    wav = tmp_path / "v.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    words = tmp_path / "w.json"
    words.write_text(json.dumps([{"word": "薄い板", "start": s, "end": e, "accent": "低高高高低"}], ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "r.json"
    p = subprocess.run([sys.executable, str(SCRIPT), str(wav), str(words), "--json", str(out)], capture_output=True, text=True, check=True)
    assert "薄い板" in p.stdout and "1.00" in p.stdout
    assert json.loads(out.read_text(encoding="utf-8"))[0]["score"] == 1.0
