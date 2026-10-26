"""h3（vs h3）のグラフ: --audio を渡したときだけ声を当てるノードが入り、渡さないときは今までどおりであること。
GPU と ComfyUI は CI に無いので、実際に作るところは手元で確かめる。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills/video-scene/scripts"))
import h3  # noqa: E402


def test_graph_without_audio_is_unchanged():
    g = h3.graph("p", "vs/a.png", None, 480, 864, 209, 8, True, 1, "t")
    assert "30" not in g and "31" not in g
    assert g["16"]["inputs"]["conditioning"] == ["104", 0]
    assert not any(v["class_type"] in ("LoadAudio", "MiniMaxH3AddGuide") for v in g.values())


def test_graph_with_audio_guides_from_frame_zero():
    g = h3.graph("p", "vs/a.png", "vs/b.png", 480, 864, 209, 8, True, 1, "t", audio="vs_x_audio.wav")
    assert g["30"] == {"class_type": "LoadAudio", "inputs": {"audio": "vs_x_audio.wav"}}
    guide = g["31"]
    assert guide["class_type"] == "MiniMaxH3AddGuide"
    assert guide["inputs"]["positive"] == ["104", 0] and guide["inputs"]["latent"] == ["104", 1]
    assert guide["inputs"]["audio"] == ["30", 0] and guide["inputs"]["audio_vae"] == ["24", 0]
    assert guide["inputs"]["frame_idx"] == 0
    assert g["16"]["inputs"]["conditioning"] == ["31", 0]          # 声を当てた条件で絵を作る
    assert g["14"]["inputs"]["latent_image"] == ["104", 1]         # 潜在は元のまま（長さは動画が決める）
    assert g["104"]["inputs"]["last_frame"] == ["2", 0]           # 最後の絵の指定と併用できる
