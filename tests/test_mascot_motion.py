"""video-mascot の二次運動（config.motion）の純関数のテスト。入力はすべて合成。"""
import math
import random

import numpy as np
import pytest

import lib


# ---------- motion_config ----------
def test_motion_config_off_by_default():
    assert lib.motion_config(None) is None
    assert lib.motion_config(False) is None
    assert lib.motion_config({"breath": {}}, "off") is None


def test_motion_config_on_fills_defaults():
    for m in (lib.motion_config(True), lib.motion_config({}), lib.motion_config(None, "on"), lib.motion_config(False, "on")):
        assert m == lib.MOTION_DEFAULTS
    m = lib.motion_config({"head": {"roll": 2.0}, "blink": False})
    assert m["head"]["roll"] == 2.0 and m["head"]["nod"] == lib.MOTION_DEFAULTS["head"]["nod"]
    assert m["blink"] is None and m["breath"] == lib.MOTION_DEFAULTS["breath"]
    assert lib.motion_config({"switch": True})["switch"] == lib.MOTION_DEFAULTS["switch"]


@pytest.mark.parametrize("value, flag", [({"brath": {}}, None), ({"head": {"rol": 1}}, None), ({"head": 3}, None),
                                         ({"switch": {"ease": "bounce"}}, None), (True, "yes"), ("on", None),
                                         ({"blink": {"max": 0}}, None), ({"blink": {"min": 3, "max": 2}}, None), ({"blink": {"mean": 0}}, None)])
def test_motion_config_rejects_typos(value, flag):
    with pytest.raises(ValueError):
        lib.motion_config(value, flag)


def test_motion_defaults_not_mutated():
    m = lib.motion_config(True); m["head"]["roll"] = 99
    assert lib.MOTION_DEFAULTS["head"]["roll"] != 99


# ---------- ease / smooth01 ----------
@pytest.mark.parametrize("name", ["linear", "in", "out", "in_out", "sine"])
def test_ease_endpoints_and_monotone(name):
    us = np.linspace(0, 1, 201); v = [lib.ease(name, u) for u in us]
    assert v[0] == pytest.approx(0) and v[-1] == pytest.approx(1)
    assert all(b >= a - 1e-12 for a, b in zip(v, v[1:]))
    assert lib.ease(name, -1) == pytest.approx(0) and lib.ease(name, 2) == pytest.approx(1)


def test_ease_shapes():
    assert lib.ease("in_out", 0.5) == pytest.approx(0.5)
    assert lib.ease("in", 0.25) < 0.25 < lib.ease("out", 0.25)
    assert lib.ease("in_out", 0.1) < 0.1                       # 出だしはゆっくり
    with pytest.raises(ValueError):
        lib.ease("bounce", 0.5)


def test_smooth01():
    assert lib.smooth01(-1) == 0 and lib.smooth01(2) == 1 and lib.smooth01(0.5) == 0.5


# ---------- wobble / breath ----------
def test_wobble_bounded_smooth_and_seeded():
    ts = np.arange(0, 60, 1 / 30); w = np.array([lib.wobble(t, 5.3, 7) for t in ts])
    assert np.abs(w).max() <= 1 + 1e-9 and np.abs(w).max() > 0.5
    assert np.abs(np.diff(w)).max() < 0.1                       # 30fps で飛ばない
    assert lib.wobble(3.3, 5.3, 7) == lib.wobble(3.3, 5.3, 7)
    assert lib.wobble(3.3, 5.3, 7) != lib.wobble(3.3, 5.3, 8)


def test_breath_phase_monotone_with_jitter_and_mean_rate():
    ts = np.arange(0, 120, 1 / 30); ph = np.array([lib.breath_phase(t, 3.6, 0.3, 1) for t in ts])
    assert (np.diff(ph) > 0).all()
    assert ph[-1] == pytest.approx(ts[-1] / 3.6, abs=1.0)        # 平均の周期は period のまま
    assert lib.breath_phase(10.0, 3.6, 0.0) == pytest.approx(10.0 / 3.6)
    with pytest.raises(ValueError):
        lib.breath_phase(1.0, 3.6, 1.0)


def test_breath_wave_shape():
    T = 4.0; ts = np.arange(0, 3 * T, 0.01); v = np.array([lib.breath_wave(t, T, 0.0, 0.4) for t in ts])
    assert v.min() >= 0 and v.max() <= 1
    assert lib.breath_wave(0.0, T, 0.0, 0.4) == pytest.approx(0)
    assert lib.breath_wave(0.4 * T, T, 0.0, 0.4) == pytest.approx(1)      # 吸いきるのは周期の 4 割
    assert np.abs(np.diff(v)).max() < 0.02                                  # つなぎ目も飛ばない
    with pytest.raises(ValueError):
        lib.breath_wave(0.0, T, 0.0, 1.0)


def test_breath_period_varies_with_jitter():
    # 吸いきる（ピーク）の間隔が、jitter ありだとばらつく
    def peaks(j):
        ts = np.arange(0, 80, 0.01); v = np.array([lib.breath_wave(t, 3.6, j, 0.4, 3) for t in ts])
        i = [k for k in range(1, len(v) - 1) if v[k] >= v[k - 1] and v[k] > v[k + 1] and v[k] > 0.99]
        return np.diff(ts[i])
    assert np.std(peaks(0.0)) < 0.02
    assert np.std(peaks(0.2)) > 0.05


# ---------- onset_env ----------
def test_onset_env_rises_on_onsets_and_decays():
    lv = np.zeros(90); lv[30:60] = 1.0
    e = lib.onset_env(lv, 30, tau=0.2)
    assert e[:30].max() == 0
    assert e[30] == pytest.approx(1.0)
    assert e[36] < e[31] and e[45] < 0.2                          # 声が続いても下がる
    assert lib.onset_env(np.zeros(10), 30).max() == 0


# ---------- 首 ----------
def test_head_weight_regions():
    pv, rx, band = (100.0, 200.0), 50.0, 20.0
    assert lib.head_weight(100, 150, pv, rx, band) == pytest.approx(1)   # 頭の中
    assert lib.head_weight(100, 200, pv, rx, band) == pytest.approx(0)   # 首の高さ
    assert lib.head_weight(100, 260, pv, rx, band) == pytest.approx(0)   # 体
    assert lib.head_weight(100 + 80, 150, pv, rx, band) == pytest.approx(0)   # 頭の横の外（1.6rx）
    assert 0 < lib.head_weight(100, 190, pv, rx, band) < 1


def test_head_move_rotates_head_keeps_body():
    pv = (100.0, 200.0)
    x, y = lib.head_move(100.0, 100.0, pv, 90.0, 0.0, 200.0, 10.0)       # 真上の点を 90 度（時計回り）→ 首の右
    assert float(x) == pytest.approx(200.0, abs=1e-3) and float(y) == pytest.approx(200.0, abs=1e-3)
    x, y = lib.head_move(130.0, 260.0, pv, 30.0, 5.0, 200.0, 10.0)       # 首より下は動かない
    assert (float(x), float(y)) == (130.0, 260.0)
    x, y = lib.head_move(100.0, 100.0, pv, 0.0, 4.0, 200.0, 10.0)        # うなずきは下へ
    assert float(y) == pytest.approx(104.0)


def test_head_maps_inverse_of_head_move():
    pv, ang, dy, rx, band = (60.0, 80.0), 2.0, 3.0, 40.0, 15.0
    mx, my = lib.head_maps(0, 0, 120, 100, pv, ang, dy, rx, band)
    assert mx.shape == (100, 120) and mx.dtype == np.float32
    for (sx, sy) in [(60.0, 20.0), (45.0, 40.0), (75.0, 30.0)]:          # 頭の中の点を動かして、写像で元へ戻るか
        qx, qy = lib.head_move(sx, sy, pv, ang, dy, rx, band); qx, qy = int(round(float(qx))), int(round(float(qy)))
        assert float(mx[qy, qx]) == pytest.approx(sx, abs=0.7) and float(my[qy, qx]) == pytest.approx(sy, abs=0.7)
    assert float(mx[95, 10]) == 10 and float(my[95, 10]) == 95           # 首より下は恒等


def test_head_rig():
    (px, py), rx, band = lib.head_rig([450, 575, 600, 680], [370, 500, 640, 600], neck=0.6, radius=0.9)
    d = (575 + 680) / 2 - (500 + 600) / 2
    assert px == pytest.approx((525 + 505) / 2) and py == pytest.approx(680 + 0.6 * d)
    assert rx == pytest.approx(0.9 * 270) and band == pytest.approx(d / 2)


# ---------- 姿勢の切り替え ----------
def test_switch_offset_anticipation_then_overshoot():
    sw = [(2.0, 0.4)]; f = lambda t: lib.switch_offset(t, sw, 0.15, 5.0, 4.0, 0.45)
    assert f(1.0) == 0 and f(1.85) == 0 and f(3.5) == 0
    assert f(1.999) == pytest.approx(5.0, abs=0.01)              # 開始の直前にいちばん沈む（下が正）
    assert 0 < f(2.1) < 5.0 and f(2.2) == pytest.approx(0)       # 動きの前半で戻る
    ts = np.arange(2.4, 2.85, 0.001); v = np.array([f(t) for t in ts])
    assert v.min() == pytest.approx(-4.0, abs=0.05)              # 終わってから上へ行き過ぎる
    assert v.max() > 0                                            # 少し戻る
    assert abs(f(2.849)) < 0.01                                   # 止まる


def test_switch_offset_disabled_parts_and_continuity():
    sw = [(2.0, 0.4)]
    assert lib.switch_offset(1.95, sw, 0.0, 5.0, 4.0, 0.45) == 0
    assert lib.switch_offset(2.5, sw, 0.15, 5.0, 4.0, 0.0) == 0
    ts = np.arange(1.5, 3.2, 1 / 240); v = np.array([lib.switch_offset(t, sw) for t in ts])
    assert np.abs(np.diff(v)).max() < 0.5                        # 240fps でも飛ばない（なめらか）
    assert lib.switch_offset(2.5, []) == 0


# ---------- まばたき ----------
def test_blink_times_intervals_and_doubles():
    ts = lib.blink_times(600, random.Random(1), mean=3.4, spread=0.35, lo=1.6, hi=7.0, double=0.15)
    gaps = np.diff(ts)
    assert ts[0] == pytest.approx(1.2) and all(t < 600 for t in ts)
    assert gaps.min() >= 0.3 and gaps.max() <= 7.0 + 1e-9
    singles = gaps[gaps > 1.0]; doubles = gaps[gaps < 0.5]
    assert singles.min() >= 1.6 - 0.45 and np.median(singles) == pytest.approx(3.4, rel=0.15)
    assert 0.05 < len(doubles) / len(ts) < 0.25
    assert np.std(singles) > 0.5                                  # 等間隔でない


def test_blink_times_extra_and_gap_and_seed():
    a = lib.blink_times(20, random.Random(3), double=0.0)
    assert a == lib.blink_times(20, random.Random(3), double=0.0)
    b = lib.blink_times(20, random.Random(3), double=0.0, extra=[5.0, a[1] + 0.1, -1, 25])
    assert 5.0 in b or any(abs(t - 5.0) < 0.3 for t in a)
    assert all(y - x >= 0.3 for x, y in zip(b, b[1:]))
    assert all(0 <= t < 20 for t in b)


# ---------- plan_at のイージング ----------
def test_plan_at_ease_keeps_duration_and_order():
    seq = [f"ib{k}" for k in range(1, 6)]; ev = [(1.0, "home", "point")]; ib = lambda a, b: seq
    nib, fps = 5, 15
    lin = [lib.plan_at(1.0 + i / 150, ev, "home", ib, fps, nib) for i in range(60)]
    eas = [lib.plan_at(1.0 + i / 150, ev, "home", ib, fps, nib, "in_out") for i in range(60)]
    assert [p[0] for p in lin] == [p[0] for p in eas]             # 中割りを出す長さは同じ
    ks = [seq.index(p[1]) for p in eas if p[0] == "ib"]
    assert ks == sorted(ks) and ks[0] == 0 and ks[-1] == nib - 1
    assert ks.count(0) > [seq.index(p[1]) for p in lin if p[0] == "ib"].count(0)   # 出だしはゆっくり
    assert lib.plan_at(0.5, ev, "home", ib, fps, nib, "in_out") == ("pose", "home")
    assert lib.plan_at(1.4, ev, "home", ib, fps, nib, "in_out") == ("pose", "point")
    assert lib.plan_at(1.2, ev, "home", lambda a, b: None, fps, nib, "in_out") == ("pose", "point")


@pytest.mark.parametrize("mean, lo, hi", [(3.4, 1.6, 0.0), (3.4, 0.0, 7.0), (0.0, 1.6, 7.0), (3.4, 5.0, 2.0)])
def test_blink_times_rejects_intervals_that_cannot_advance(mean, lo, hi):
    with pytest.raises(ValueError):
        lib.blink_times(10, random.Random(0), mean=mean, lo=lo, hi=hi)
