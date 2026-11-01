"""vm render --jobs の区間の分け方と引数（動画は作らない）。"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-mascot/scripts"))
import render_jobs as rj


def test_chunks_cover_the_range_without_gaps():
    for f0, f1, jobs, fps in [(0, 2964, 4, 60), (300, 900, 4, 60), (0, 100, 8, 30), (0, 54000, 4, 60), (7, 8, 4, 60)]:
        c = rj.plan_chunks(f0, f1, jobs, fps)
        assert c[0][0] == f0 and c[-1][1] == f1 and all(a < b for a, b in c) and all(x[1] == y[0] for x, y in zip(c, c[1:]))


def test_chunk_length_stays_in_bounds():
    assert len(rj.plan_chunks(0, 2964, 4, 60)) == 8           # 49 秒を 4 並列: 約 6 秒ずつ
    assert len(rj.plan_chunks(0, 600, 4, 60)) == 2            # 短い動画は 5 秒より細かくしない
    assert len(rj.plan_chunks(0, 216000, 4, 60)) == 120       # 1 時間でも 30 秒ごと


def test_frame_times_round_trip_for_every_frame():
    for fps in (24, 30, 60):
        for a in range(0, 20000, 7):
            ta, tb = rj.frame_times(a, a + 13, fps)
            assert int(ta * fps) == a and math.ceil(tb * fps) == a + 13


def test_child_args_replace_range_and_drop_parent_only_flags():
    argv = ["w", "--mode", "alpha", "--jobs", "4", "--from", "1", "--to", "9", "--out", "x.webm", "--strict", "--crop", "face", "--no-head"]
    got = rj.child_args(argv, 2.0, 3.0, "c.webm", "1,2,3")
    assert got == ["w", "--mode", "alpha", "--no-head", "--from", "2.000000", "--to", "3.000000", "--out", "c.webm", "--crop", "1,2,3"]


def test_white_chunks_leave_the_voice_to_the_parent():
    assert rj.child_args(["w"], 0.0, 1.0, "c.mp4", video_only=True)[-1] == "--video-only"
    assert "--video-only" not in rj.child_args(["w"], 0.0, 1.0, "c.webm")


def test_new_caches_are_made_by_one_process():
    assert rj.must_run_serial({"cache_todo": ["home→point"]})
    assert not rj.must_run_serial({"cache_todo": []}) and not rj.must_run_serial({})
    assert rj.without_jobs(["w", "--jobs", "4", "--strict", "--from", "1"]) == ["w", "--strict", "--from", "1"]
    assert "cache_todo" not in rj.merged_check({"cache_todo": ["x"], "problems": 0}, "o.webm")


def test_run_stops_parallel_before_any_chunk_when_caches_are_missing():
    src = (ROOT / "skills/video-mascot/scripts/render_jobs.py").read_text(encoding="utf-8")
    assert src.index("if must_run_serial(pre):") < src.index("plan_chunks(f0, f1, jobs, fps); parts")
    assert "\"cache_todo\"" in (ROOT / "skills/video-mascot/scripts/render.py").read_text(encoding="utf-8")


def test_concat_list_escapes_quotes():
    assert rj.concat_list(["/a/it's.webm"]) == "file '/a/it'\\''s.webm'\n"


def test_merged_check_points_to_the_output():
    assert rj.merged_check({"problems": 2, "video": None}, "o.webm")["problems"] == 2
