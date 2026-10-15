"""絵の一部に方眼（20画素ごとの緑、100画素ごとの赤）を引いて拡大する。口・目の範囲や軸足の位置を読み取るための補助。
  vm grid <絵> x0 y0 x1 y1 [--out grid.png] [--zoom 2]
赤い線の座標は、切り出した範囲の左上 (x0,y0) からの距離ではなく、元の絵の座標で数えられるよう、x0,y0 を100の倍数に丸めて引く。"""
import sys, os
import cv2, numpy as np
a = [x for x in sys.argv[1:] if not x.startswith("--")]
if len(a) < 5: sys.exit("使い方: vm grid <絵> x0 y0 x1 y1 [--out grid.png] [--zoom 2]")
im = cv2.imread(a[0]); x0, y0, x1, y1 = map(int, a[1:5]); z = float(sys.argv[sys.argv.index("--zoom") + 1]) if "--zoom" in sys.argv else 2.0
out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "grid.png"
c = im[y0:y1, x0:x1].copy()
for x in range((x0 // 20) * 20, x1 + 1, 20):
    if x >= x0: cv2.line(c, (x - x0, 0), (x - x0, y1 - y0), (0, 0, 255) if x % 100 == 0 else (0, 200, 0), 1)
for y in range((y0 // 20) * 20, y1 + 1, 20):
    if y >= y0: cv2.line(c, (0, y - y0), (x1 - x0, y - y0), (0, 0, 255) if y % 100 == 0 else (0, 200, 0), 1)
for x in range(((x0 + 99) // 100) * 100, x1, 100): cv2.putText(c, str(x), (x - x0 + 3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
for y in range(((y0 + 99) // 100) * 100, y1, 100): cv2.putText(c, str(y), (3, y - y0 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
cv2.imwrite(out, cv2.resize(c, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)); print(out, "（赤い線は100画素ごと、数字は元の絵の座標）")
