"""中割りのコマ補間（config.interp、opt-in）の純関数のテスト。RIFE そのものは呼ばない。"""
import pytest

import lib


def test_interp_config_off_by_default():
    assert lib.interp_config(None) is None
    assert lib.interp_config(False) is None
    assert lib.interp_config({"dur": 1.0}, "off") is None


def test_interp_config_on_fills_defaults():
    for c in (lib.interp_config(True), lib.interp_config({}), lib.interp_config(None, "rife"), lib.interp_config(False, "rife")):
        assert c == lib.INTERP_DEFAULTS


def test_interp_config_overrides():
    c = lib.interp_config({"mult": 4, "dur": 0.8, "ease": "sine", "durs": {"gap>gassho": 1.2}, "pairs": ["gap>gassho"]})
    assert (c["mult"], c["dur"], c["ease"]) == (4, 0.8, "sine")
    assert c["durs"] == {"gap>gassho": 1.2} and c["pairs"] == ["gap>gassho"]


@pytest.mark.parametrize("bad", [
    {"nope": 1}, {"engine": "film"}, {"mult": 1}, {"mult": 2.5}, {"mult": True}, {"dur": 0}, {"dur": True},
    {"ease": "bounce"}, {"durs": {"gap": 1.0}}, {"durs": {"a>b": 0}}, {"durs": []}, {"pairs": "a>b"}, {"pairs": ["a>b>c"]}, "on",
])
def test_interp_config_rejects(bad):
    with pytest.raises(ValueError):
        lib.interp_config(bad)


def test_interp_config_rejects_bad_flag():
    with pytest.raises(ValueError):
        lib.interp_config(None, "film")


def test_interp_on_and_dur_work_both_ways():
    c = lib.interp_config({"durs": {"gap>gassho": 1.2}, "pairs": ["gap>gassho"]})
    assert lib.interp_on(c, "gap", "gassho") and lib.interp_on(c, "gassho", "gap") and not lib.interp_on(c, "home", "open")
    assert lib.interp_dur(c, "gap", "gassho") == 1.2 and lib.interp_dur(c, "gassho", "gap") == 1.2
    assert lib.interp_dur(c, "home", "open") == c["dur"]
    assert lib.interp_on(lib.interp_config(True), "x", "y")


def test_dense_ks_hits_drawn_inbetweens():
    ks = lib.dense_ks(6, 8)
    assert len(ks) == 6 * 8 - 1 and ks[0] == 1 / 8 and ks[-1] == 6 - 1 / 8
    assert [k for k in ks if k == int(k)] == [1, 2, 3, 4, 5]


# ---------- plan_at の ib_dur ----------
SEQ = [f"d{j}" for j in range(1, 48)]           # 6 等分 × 8 倍 − 1 枚
EV = [(1.0, "gap", "gassho")]


def _dense(a, b): return SEQ if (a, b) == ("gap", "gassho") else None


def test_plan_at_ib_dur_stretches_to_given_seconds():
    dur = lambda a, b: (1.2, "in_out") if (a, b) == ("gap", "gassho") else None
    frames = [lib.plan_at(1.0 + i / 60, EV, "gap", _dense, 15, 5, None, None, dur) for i in range(90)]
    ib = [f for f in frames if f[0] == "ib"]
    assert len(ib) == 72                          # 1.2 秒 × 60fps のあいだ中割りを出す
    ks = [SEQ.index(f[1]) for f in ib]
    assert ks == sorted(ks) and ks[0] == 0 and ks[-1] >= len(SEQ) - 2
    assert ks.count(0) > 1                        # イージングで出だしはゆっくり
    assert ib[0][2] == "gap" and ib[-1][2] == "gassho"   # 前の 4 割は元の姿勢の部品
    assert frames[-1] == ("pose", "gassho")


def test_plan_at_ib_dur_none_keeps_old_behaviour():
    seq = [f"ib{k}" for k in range(1, 6)]; ib = lambda a, b: seq
    for t in (0.5, 1.0, 1.1, 1.3, 1.5):
        assert lib.plan_at(t, EV, "gap", ib, 15, 5, None, None, lambda a, b: None) == lib.plan_at(t, EV, "gap", ib, 15, 5)


def test_plan_at_ib_dur_yields_to_next_event():
    ev = [(1.0, "gap", "gassho"), (1.5, "gassho", "open")]
    seq2 = [f"e{j}" for j in range(1, 48)]
    ib = lambda a, b: SEQ if (a, b) == ("gap", "gassho") else (seq2 if (a, b) == ("gassho", "open") else None)
    dur = lambda a, b: (1.2, "linear")
    assert lib.plan_at(1.4, ev, "gap", ib, 15, 5, None, None, dur)[1] in SEQ
    f = lib.plan_at(1.5, ev, "gap", ib, 15, 5, None, None, dur)
    assert f == ("ib", "e1", "gassho")             # 次の切り替えが始まったら、前の補間は打ち切る
