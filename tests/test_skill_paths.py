"""スキルどうしの呼び合いは実体のパスで探す。~/.claude/skills のリンクが 1 本欠けていても、隣のスキルを見失わない。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PIL")
ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(os.name == "nt", reason="リンクの張り方が違う")
def test_compose_finds_chapters_without_its_own_link(tmp_path):
    skills = tmp_path / "skills"; skills.mkdir()
    (skills / "video-mascot").symlink_to(ROOT / "skills/video-mascot")   # screen-explainer のリンクは張らない
    compose = skills / "video-mascot/scripts/../../screen-explainer/scripts/compose.py"
    r = subprocess.run([sys.executable, str(compose), "--shots", "x", "--voice", "x", "--scenes", "x", "--out", "x"],
                       capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert "No module named 'chapters'" not in r.stderr, r.stderr


@pytest.mark.parametrize("rel", ["skills/screen-explainer/scripts/compose.py", "skills/screen-explainer/scripts/word_timing.py",
                                 "skills/video-mascot/scripts/explain.py", "skills/video-mascot/scripts/qwenimg/qwenimg.py"])
def test_sibling_lookup_uses_real_path(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "dirname(os.path.realpath(__file__))" in text
    assert "dirname(os.path.abspath(__file__)), \"..\"" not in text
