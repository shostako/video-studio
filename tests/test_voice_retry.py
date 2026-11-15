"""vm voice retry（voice_retry.py と voice.retry）の試験。Irodori と音素の聞き取りは偽物に替える。"""
import glob, json, os, re, sys, wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "video-mascot", "scripts"))
import voice_retry as VR  # noqa: E402


def test_seeds_follow_the_base():
    assert VR.seeds(2024, 3) == [2025, 2026, 2027]


def test_choose_keeps_original_on_tie():
    assert VR.choose(1, [(5, 1), (6, 1)]) is None          # 元と同じ数なら元を残す
    assert VR.choose(2, [(5, 1), (6, 0), (7, 0)]) == 6     # いちばん少ない候補。同じ数なら先の seed
    assert VR.choose(0, [(5, 0)]) is None


def test_stuck_is_in_original_and_every_candidate():
    w = lambda k, word: {"kind": k, "word": word}
    orig = [w("reading", "描い"), w("accent", "表+に")]
    assert VR.stuck(orig, [[w("reading", "描い")], [w("reading", "描い"), w("accent", "表+に")]]) == {("reading", "描い")}
    assert VR.stuck(orig, []) == set()


def _wav(path, f):
    x = (np.sin(2 * np.pi * f * np.arange(8000) / 16000) * 8000).astype("<i2")    # CI に ffmpeg が無いので wave で書く
    with wave.open(str(path), "wb") as o: o.setnchannels(1); o.setsampwidth(2); o.setframerate(16000); o.writeframes(x.tobytes())


def _setup(tmp_path, monkeypatch, lines, seed=2024):
    import voice, phonemes, ojt
    os.makedirs(tmp_path / "voice")
    for n in range(1, len(lines) + 1): _wav(tmp_path / "voice" / f"l{n}.wav", 100 * n)
    json.dump({"name": "t", "poses": {"home": {}}, "voice": {"caption": "c", "seed": seed, "lines": lines}},
              open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    jobs, heard = [], []
    def fake_irodori(js, tmp):
        jobs.extend(js)
        for j in js: _wav(j["out"], 1000 + j["seed"])                # seed ごとに違う中身
    monkeypatch.setattr(voice, "run_irodori", fake_irodori)
    monkeypatch.setattr(phonemes, "hear", lambda ps: heard.extend(ps) or [{"path": p, "phones": [["a", 0.1, 0.2]]} for p in ps])
    monkeypatch.setattr(ojt, "available", lambda: True)
    return voice, jobs, heard


def test_retry_replaces_only_lines_with_fewer_warnings(tmp_path, monkeypatch, capsys):
    lines = [{"text": "一"}, {"text": "二"}, {"text": "三"}]
    voice, jobs, heard = _setup(tmp_path, monkeypatch, lines)
    w = lambda n: str(tmp_path / "voice" / f"l{n}.wav")
    orig = {n: VR.md5(w(n)) for n in (1, 2, 3)}
    # 警告: 行1 は元 2 件で seed 2026 が 0 件、行2 は警告なし、行3 は元 1 件で候補も 1 件（元を残す）
    def fake_warn(line, phones, wav, terms=()):
        base = re.sub(r"_[0-9a-f]{8}\.wav$", ".wav", os.path.basename(wav))     # 候補の名前の入力の鍵を外す
        k = {"l1.wav": 2, "l3.wav": 1, "l1_s2026.wav": 0, "l1_s2025.wav": 1}.get(base, 1 if base.startswith(("l1_", "l3_")) else 0)
        return [{"kind": "accent", "word": "x", "t": 0.1, "end": 0.2, "why": "w"}] * k
    monkeypatch.setattr(VR, "warnings", fake_warn)
    monkeypatch.setattr(sys, "argv", ["voice.py", str(tmp_path), "retry", "--n", "3"]); voice.main()
    out = capsys.readouterr().out
    cn = lambda n, s: glob.glob(str(tmp_path / "voice" / "retry" / f"l{n}_s{s}_*.wav"))
    assert sorted(j["out"] for j in jobs) == sorted(c for n in (1, 3) for s in (2025, 2026, 2027) for c in cn(n, s))
    assert len(jobs) == 6
    assert {j["ref"] for j in jobs if "l1_" in j["out"]} == {w(2)}        # synth 1 と同じ手本（作り直さない行のうち最初）
    assert {j["ref"] for j in jobs if "l3_" in j["out"]} == {w(1)}
    assert VR.md5(w(1)) == VR.md5(cn(1, 2026)[0])
    assert VR.md5(w(2)) == orig[2] and VR.md5(w(3)) == orig[3]
    assert VR.md5(str(tmp_path / "voice" / "retry" / f"l1_was_{orig[1][:8]}.wav")) == orig[1]   # 元の声を残す
    ph = json.load(open(tmp_path / "voice" / "phones.json", encoding="utf-8"))
    assert ph["1"]["md5"] == VR.md5(w(1))                                 # 差し替えた声の書き起こしを控える
    assert "行1: seed 2026" in out and "行3: 元の声を残す" in out and "行1 seed 2026" in out
    assert "x（高さ。0.10 秒、w。どの候補にも出た）" in out and "1 件は元の声にもどの候補にも出た" in out   # 行3 の警告は 3 本とも出た
    # 2 回目: 行1 の候補は作り置きを使う。行3 は手本（行1 の声）の中身が変わったので作り直す
    jobs.clear(); heard.clear()
    voice.main()
    assert {os.path.basename(j["out"])[:2] for j in jobs} == {"l3"} and len(jobs) == 3
    jobs.clear(); voice.main()
    assert jobs == []                                                     # 入力が同じなら何も作らない
    # say を直したら、同じ seed でも候補を作り直す（古い文の候補を使い回さない）
    cfg = json.load(open(tmp_path / "config.json", encoding="utf-8")); cfg["voice"]["lines"][2]["say"] = "さん"
    json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    voice.main()
    assert sorted(j["seed"] for j in jobs if "l3_" in j["out"]) == [2025, 2026, 2027] and {j["text"] for j in jobs if "l3_" in j["out"]} == {"さん"}


def test_retry_uses_voice_ref_and_line_seed(tmp_path, monkeypatch):
    lines = [{"text": "一", "seed": 7}]
    voice, jobs, _ = _setup(tmp_path, monkeypatch, lines)
    cfg = json.load(open(tmp_path / "config.json", encoding="utf-8")); cfg["voice"]["ref"] = "voice/ref.wav"
    json.dump(cfg, open(tmp_path / "config.json", "w", encoding="utf-8"), ensure_ascii=False)
    monkeypatch.setattr(VR, "warnings", lambda line, phones, wav, terms=(): [{"kind": "reading", "word": "x", "t": None, "end": None, "why": "w"}])
    monkeypatch.setattr(sys, "argv", ["voice.py", str(tmp_path), "retry", "--n", "2"]); voice.main()
    assert [j["seed"] for j in jobs] == [8, 9]
    assert {j["ref"] for j in jobs} == {str(tmp_path / "voice" / "ref.wav")}


def test_synth_uses_line_seed(tmp_path, monkeypatch):
    lines = [{"text": "一", "seed": 7}, {"text": "二"}]
    voice, jobs, _ = _setup(tmp_path, monkeypatch, lines)
    monkeypatch.setattr(voice, "report_match", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["voice.py", str(tmp_path), "synth", "1", "2"]); voice.main()
    assert [j["seed"] for j in jobs] == [7, 2024]
