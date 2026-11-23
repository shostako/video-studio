"""動きの部品（vm units）: config.units の検め、台本の役から切り替えを組む plan、検査の judge。"""
import numpy as np
import pytest

import units as UN


def cfg(**kw):
    c = {"home": "home", "poses": {p: {} for p in ("home", "open", "span", "point_r", "raise_r", "count_2", "nod", "half_l", "half_r")},
         "head": {"chain": ["half_r", "home", "half_l"]},
         "units": {"base": "home", "roles": {
             "explain": [{"name": "ex_open", "pose": "open", "out": 0.8, "hold": 0.8, "back": 0.8},
                         {"name": "ex_span", "pose": "span", "out": 0.8, "hold": 0.8, "back": 0.8}],
             "point": [{"name": "pt", "pose": "point_r", "out": 0.8, "hold": 0.9, "back": 0.8}],
             "count": [{"name": "c1", "pose": "raise_r", "n": 1, "out": 0.7, "hold": 0.9, "back": 0.8},
                       {"name": "c2", "pose": "count_2", "n": 2, "out": 0.6, "hold": 0.9, "back": 0.7}]},
             "idle": {"sides": ["half_l", "half_r"]}}}
    c["units"].update(kw); return c


ALL = lambda x: True


def test_config_checks():
    U = UN.units_config(cfg())
    assert U["base"] == "home" and U["idle"]["min_gap"] == 1.8
    bad = cfg(); bad["units"]["roles"]["count"][0]["out"] = 0.6            # 同じ姿勢 raise_r を別の秒で使う部品
    bad["units"]["roles"]["emph"] = [{"name": "em", "pose": "raise_r", "out": 0.7, "hold": 0.8, "back": 0.8}]
    with pytest.raises(ValueError, match="out/back が違う"): UN.units_config(bad)
    with pytest.raises(ValueError, match="姿勢が無い"): UN.units_config(cfg(roles={"x": [{"name": "a", "pose": "zzz", "out": 1, "hold": 1, "back": 1}]}))
    with pytest.raises(ValueError, match="head.chain に無い"): UN.units_config(cfg(idle={"sides": ["look_l"]}))
    with pytest.raises(ValueError, match="知らない項目"): UN.units_config(cfg(roles={"x": [{"name": "a", "pose": "open", "out": 1, "hold": 1, "back": 1, "zz": 1}]}))


def test_base_must_be_home():
    with pytest.raises(ValueError, match="config.home"): UN.units_config(cfg(base="open"))


def test_rife_units_need_rife_pairs_and_cache_length_follows_settings():
    c = cfg(); c["interp"] = {"engine": "wan", "mult": 8, "wan": {"rife_pairs": ["home>nod"]}}
    assert UN.rife_pair(c, "home", "nod") and UN.rife_pair(c, "nod", "home") and not UN.rife_pair(c, "home", "open")
    assert UN.wan_n(c) == 47
    c["interp"]["mult"] = 12; c["inbetween_div"] = 4
    assert UN.wan_n(c) == 47                                                              # 4 × 12 − 1
    c["interp"]["mult"] = 16
    assert UN.wan_n(c) == 63


def test_plan_arrives_on_time_rotates_and_picks_by_n_and_name():
    U = UN.units_config(cfg())
    cues = [{"role": "explain", "t": 3.0}, {"role": "explain", "t": 8.0}, {"role": "count", "n": 2, "t": 13.0},
            {"role": "explain", "unit": "ex_span", "t": 18.0}]
    rows, ev, durs, heads = UN.plan(cues, U, ALL, 0.0, 22.0)
    assert [r[4]["name"] for r in rows] == ["ex_open", "ex_span", "c2", "ex_span"]       # 順に回す・n で選ぶ・名指し
    assert ev[0] == {"at": 2.2, "pose": "open"} and ev[1] == {"at": 3.8, "pose": "home"}  # 語に着くように 0.8 秒前に出る
    assert durs["home>count_2"] == 0.6 and durs["count_2>home"] == 0.7
    assert len(heads) % 4 == 0 and heads[1]["pose"] == "half_l" and heads[5]["pose"] == "half_r"   # 拠点にいる間の頭の往復（左右交互）


def test_idle_head_turns_fill_long_gaps():
    U = UN.units_config(cfg())
    _, _, _, heads = UN.plan([{"role": "point", "t": 30.0}], U, ALL, 0.0, 33.0)
    turns = [h["at"] for h in heads[1::4]]
    assert len(turns) == 4 and all(b - a > 5 for a, b in zip(turns, turns[1:]))          # 0〜29.2 秒のあきに 6 秒ごと
    _, _, _, heads = UN.plan([{"role": "point", "t": 2.0}, {"role": "explain", "t": 4.5}], U, ALL, 0.0, 6.5)
    assert heads == []
    with pytest.raises(ValueError, match="往復 1 回の長さ"): UN.units_config(cfg(idle={"sides": ["half_l"], "every": 1}))
    U = UN.units_config(cfg(idle={"sides": ["half_l", "half_r"], "every": 1.7}))
    _, _, _, heads = UN.plan([{"role": "point", "t": 4.8}], U, ALL, 0.0, 7.0)        # あき 0〜4.0 秒
    ats = [h["at"] for h in heads]
    assert ats == sorted(ats) and ats[-1] <= 4.0 and ats[0] >= 0.0                         # 往復どうしが重ならず、あきに収まる                                                                      # あきが短ければ入れない


def test_plan_shrinks_hold_and_stops_when_too_tight():
    U = UN.units_config(cfg())
    rows, *_ = UN.plan([{"role": "point", "t": 2.0}, {"role": "explain", "t": 4.5}], U, ALL, 0.0, 10.0)
    assert abs((rows[0][2] - rows[0][1]) - 0.9) < 1e-9                                 # 間に合う所は止まる秒のまま
    rows, *_ = UN.plan([{"role": "point", "t": 2.0}, {"role": "explain", "t": 4.0}], U, ALL, 0.0, 10.0)
    assert abs((rows[0][2] - rows[0][1]) - 0.4) < 1e-9 and abs(rows[0][3] - rows[1][0]) < 1e-9   # 縮めて次の出だしに拠点へ着く
    with pytest.raises(ValueError, match="詰まりすぎ"): UN.plan([{"role": "point", "t": 2.0}, {"role": "explain", "t": 3.5}], U, ALL, 0.0, 10.0)
    with pytest.raises(ValueError, match="拠点に戻らない"): UN.plan([{"role": "point", "t": 9.5}], U, ALL, 0.0, 10.0)


def test_plan_uses_only_checked_units():
    U = UN.units_config(cfg())
    rows, *_ = UN.plan([{"role": "explain", "t": 3.0}, {"role": "explain", "t": 8.0}], U, lambda x: x["name"] != "ex_open", 0.0, 12.0)
    assert [r[4]["name"] for r in rows] == ["ex_span", "ex_span"]
    with pytest.raises(ValueError, match="検査を通った部品が無い"): UN.plan([{"role": "point", "t": 3.0}], U, lambda x: False, 0.0, 12.0)


def test_judge_flags_still_frames_landing_and_face_jump():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (40, 40, 3), np.uint8); b = rng.integers(0, 255, (40, 40, 3), np.uint8)
    seq = [a] + [(a * (1 - t) + b * t).astype(np.uint8) for t in np.linspace(0.08, 1.0, 12)] + [b]   # Wan の最後のコマは終点の絵に着く
    steady = lambda im: (0.99, np.array([10.0, 10.0]))
    assert UN.judge(seq, b, [], 0.05, steady)["ok"]
    still = seq[:4] + [seq[4]] * 5 + seq[9:]
    assert "止まる続き" in UN.judge(still, b, [], 0.05, steady)["why"]
    dark = seq[:-2] + [(seq[-2] * 0.5).astype(np.uint8), b]
    assert "着地の差" in UN.judge(dark, b, [], 0.05, steady)["why"]
    pos = iter([np.array([10.0, 10.0])] * 6 + [np.array([16.0, 10.0])] + [np.array([10.0, 10.0])] * 10)
    assert "顔の跳び" in UN.judge(seq, b, [], 0.05, lambda im: (0.99, next(pos)))["why"]
