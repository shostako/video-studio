"""口の部品の離れ小島（髪・首の縁の切れ端）を、Wan の切り替えのコマへ写すときに捨てる（lib.trim_islands）。"""
import numpy as np

from lib import trim_islands


def part(boxes, h=80, w=120):
    im = np.zeros((h, w, 4), np.uint8); im[:, :, :3] = (40, 80, 200)
    for x0, y0, x1, y1 in boxes: im[y0:y1, x0:x1, 3] = 255
    return im


def test_island_outside_mouth_roi_is_dropped():
    im = part([(40, 20, 80, 50), (100, 60, 118, 78)])        # 口の本体と、右下の髪の切れ端
    out = trim_islands(im, 400, 500, (430, 510, 510, 570))   # 口の範囲（絵の座標）。切れ端も矩形の角に入っている
    assert out[30, 60, 3] == 255 and out[70, 110, 3] == 0
    assert im[70, 110, 3] == 255                              # 元の部品は書き換えない


def test_small_mouth_island_wins_over_bigger_hair_island():
    im = part([(50, 30, 70, 45), (0, 50, 60, 80)])           # 蘭の m1: 髪の島の方が大きい
    out = trim_islands(im, 0, 0, (45, 25, 75, 50))
    assert out[35, 60, 3] == 255 and out[70, 20, 3] == 0


def test_unchanged_when_single_island_or_roi_misses():
    one = part([(40, 20, 80, 50)])
    assert trim_islands(one, 0, 0, (40, 20, 80, 50)) is one
    two = part([(40, 20, 80, 50), (100, 60, 118, 78)])
    assert trim_islands(two, 0, 0, (500, 500, 600, 600)) is two   # 中心の近くに島が無ければ何も捨てない
