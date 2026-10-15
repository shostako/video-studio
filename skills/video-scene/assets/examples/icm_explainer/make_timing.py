"""anchors.json（カットの長さと、カット内の声に合わせた秒）から 3D の timing.json を作る。
  python make_timing.py anchors.json timing.json
anchors.json: {"lens": [8 本の長さ], "c3": {...}, "c5": {...}, "c6": {...}, "c7": {...}}（秒はカットの頭から）"""
import json, sys
A = json.load(open(sys.argv[1], encoding="utf-8")); L = A["lens"]
B = [0.0]
for x in L: B.append(round(B[-1] + x, 3))
at = lambda k, r: round(B[k - 1] + r, 3)          # カット k（1始まり）の頭から r 秒
c3, c5, c6, c7 = A["c3"], A["c5"], A["c6"], A["c7"]
warp = [[0, 0], [at(3, c3["close0"]), 0.5], [at(3, c3["contact"]), 1.3], [at(3, c3["squeeze0"]), 1.3], [at(3, c3["standby"]), 1.8],
        [at(5, c5["open0"]), 1.9], [at(5, c5["open1"]), 2.05], [at(5, c5["fill1"]), 2.95], [at(5, c5["close0"]), 2.95], [at(5, c5["close1"]), 3.1],
        [at(6, c6["comp0"]), 3.5], [at(6, c6["comp1"]), 4.5],
        [at(7, c7["cool0"]), 4.7], [at(7, c7["cool1"]), 5.4], [at(7, c7["open0"]), 6.0], [at(7, c7["open1"]), 7.0],
        [at(7, c7["slide0"]), 7.25], [at(7, c7["slide1"]), 7.85], [B[8], 8.0]]
# 同じ動きの秒が続く所は止まって見える。表示の秒は増える順になっていること
assert all(p[0] < q[0] for p, q in zip(warp, warp[1:])), warp
focus = [[B[1], B[2], ["frame", "springs", "gap"]],
         [at(3, c3["close0"]), at(3, c3["contact"]) + 0.3, ["frame", "pl"]],
         [at(3, c3["squeeze0"]) - 0.3, B[3], ["springs", "gap"]],
         [B[3], B[4], ["pl", "gap", "springs"]],
         [B[4], B[5], ["valve", "resin", "gap"]],
         [B[5], B[6], ["core", "springs", "resin", "gap"]],
         [B[6], at(7, c7["open0"]), ["resin"]],
         [at(7, c7["open0"]), B[7], ["frame", "resin"]]]
caps = [[B[0], B[1], "射出圧縮成形"],
        [B[1], B[2], "型開き：外周の枠がバネで浮いている"],
        [B[2], B[3], "① 射出待機位置まで型閉じ"],
        [B[3], B[4], "② PL面が密着、残りが圧縮ストローク"],
        [B[4], at(5, c5["close0"]), "③ 射出"],
        [at(5, c5["close0"]), B[5], "④ バルブを閉じる"],
        [B[5], B[6], "⑤ 圧縮：コアだけ前に出る"],
        [B[6], at(7, c7["open0"]), "⑥ 冷却"],
        [at(7, c7["open0"]), B[7], "⑦ 型開き：成形品は可動側に残る"],
        [B[7], B[8], "広く入れて、薄く仕上げる"]]
json.dump({"dur": B[8], "warp": warp, "focus": focus, "caps": caps, "bounds": B}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("dur", B[8], "bounds", B)
