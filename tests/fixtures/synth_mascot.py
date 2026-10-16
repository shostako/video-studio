"""書き出しのスモーク用に、合成のマスコットの作業フォルダを作る（実物の絵・声は使わない）。
PIL で描いた人型（髪・顔・目・口・胴・腕・脚・黒い靴）を2姿勢（home: 腕を下ろす、point: 向かって右の腕を横へ）、
その間の中割り5枚、口7形・目2段の部品、合成の声（うなり音を音節ごとに強弱）と聞き取りの語を置く。
  python3 tests/fixtures/synth_mascot.py <出力フォルダ>   で手元でも作れる。"""
import json, math, os, sys, wave

import numpy as np
from PIL import Image, ImageDraw

W, H = 470, 768
SKIN, HAIR, NAVY, BLUE, SHOE, LIP = (250, 214, 190), (60, 40, 35), (40, 45, 90), (40, 70, 160), (15, 15, 15), (150, 50, 60)
MOUTH_ROI = [205, 236, 265, 270]
EYE_ROI = [180, 180, 290, 226]
LINES = [(0.3, 1.2), (1.9, 1.1)]      # 行の開始と長さ（秒）
END = 3.4


def arm_end(k):
    """向かって右の腕の先。k=0 は下ろした腕、k=1 は横へ伸ばした腕。"""
    a = math.radians(80 - 75 * k); return 290 + 150 * math.cos(a), 310 + 150 * math.sin(a)


def figure(k):
    im = Image.new("RGB", (W, H), (253, 253, 253)); d = ImageDraw.Draw(im)
    d.rectangle([190, 515, 228, 700], fill=NAVY); d.rectangle([242, 515, 280, 700], fill=NAVY)            # 脚
    d.ellipse([150, 692, 236, 734], fill=SHOE); d.ellipse([244, 692, 330, 734], fill=SHOE)                  # 靴
    d.line([(182, 312), (150, 480)], fill=BLUE, width=26); d.ellipse([138, 468, 164, 494], fill=SKIN)       # 向かって左の腕
    x, y = arm_end(k); d.line([(288, 312), (x, y)], fill=BLUE, width=26); d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=SKIN)
    d.rounded_rectangle([175, 292, 295, 525], radius=24, fill=BLUE)                                         # 胴
    d.rectangle([222, 270, 248, 300], fill=SKIN)                                                            # 首
    d.ellipse([140, 95, 330, 285], fill=HAIR); d.ellipse([157, 128, 313, 286], fill=SKIN)                  # 髪と顔
    d.ellipse([195, 192, 213, 214], fill=(30, 30, 40)); d.ellipse([257, 192, 275, 214], fill=(30, 30, 40))  # 目
    d.line([(222, 254), (248, 254)], fill=LIP, width=4)                                                     # 口（閉じ）
    return im


def mouth_part(open_w, open_h, round_=False):
    x0, y0, x1, y1 = MOUTH_ROI; im = Image.new("RGBA", (x1 - x0, y1 - y0), SKIN + (255,)); d = ImageDraw.Draw(im)
    cx, cy = (x1 - x0) / 2, (y1 - y0) / 2; w = open_w / (1.6 if round_ else 1)
    d.ellipse([cx - w / 2, cy - open_h / 2, cx + w / 2, cy + open_h / 2], fill=LIP)
    return im


def eye_part(h):
    x0, y0, x1, y1 = EYE_ROI; im = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for cx in (204, 266):
        d.ellipse([cx - x0 - 11, 190 - y0, cx - x0 + 11, 216 - y0], fill=SKIN + (255,))
        d.ellipse([cx - x0 - 9, 203 - y0 - h / 2, cx - x0 + 9, 203 - y0 + h / 2], fill=(30, 30, 40, 255))
    return im


def voice(path, sr=24000):
    t = np.arange(int(END * sr)) / sr; x = np.zeros_like(t)
    for s, d in LINES:
        on = (t >= s) & (t < s + d); syl = 0.55 + 0.45 * np.sin(2 * np.pi * 6 * (t - s)) ** 2
        f0 = 140 + 20 * np.sin(2 * np.pi * 1.3 * (t - s))
        ph = 2 * np.pi * np.cumsum(f0) / sr; buzz = sum(np.sin(h * ph) / h for h in range(1, 8))
        x += np.where(on, 0.25 * buzz * syl, 0)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def make(root):
    os.makedirs(root, exist_ok=True); p = lambda *a: os.path.join(root, *a)
    for d in ("poses", "ib", "voice", "out", "parts"): os.makedirs(p(d), exist_ok=True)
    cfg = {"name": "synth", "fps": 30, "pad": 40, "out_height": 384, "home": "home", "seed": 5,
           "poses": {"home": {"desc": "arms down"}, "point": {"desc": "right arm out"}}, "pairs": [["home", "point"]],
           "face": {"mouth_roi": MOUTH_ROI, "eye_roi": EYE_ROI}, "floor": {"clean": True}, "anchor": {"mode": "boot"},
           "events": [{"at": 0.6, "pose": "point"}, {"line_end": 1, "pose": "home"}, {"line_start": 2, "offset": 0.6, "pose": "point"}],
           "voice": {"lines": [{"text": "あいうえお"}, {"text": "ぱんだ、です"}]}}
    json.dump(cfg, open(p("config.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    figure(0).save(p("poses", "pose_home.png")); figure(1).save(p("poses", "pose_point.png"))
    for k in range(1, 6): figure(k / 6).save(p("ib", f"ib_home_point_{k}.png"))
    parts = {"m1": mouth_part(26, 6), "m2": mouth_part(30, 16), "m3": mouth_part(34, 24), "m4": mouth_part(30, 14, True),
             "m5": mouth_part(22, 8, True), "m6": mouth_part(36, 8), "m7": mouth_part(28, 11), "e1": eye_part(6), "e2": eye_part(1)}
    for pose in ("home", "point"):
        od = p(f"parts_{pose}"); os.makedirs(od, exist_ok=True); meta = {}
        for k, im in parts.items():
            im.save(os.path.join(od, f"{k}.png")); meta[k] = (MOUTH_ROI[:2] if k.startswith("m") else EYE_ROI[:2])
        json.dump(meta, open(os.path.join(od, "parts.json"), "w"))
    voice(p("voice", "master.wav"))
    json.dump({"lines": [{"n": i + 1, "start": s, "dur": d} for i, (s, d) in enumerate(LINES)], "end": END}, open(p("voice", "timing.json"), "w"))
    words = p("voice", "master.words.json")
    json.dump([["あいうえお", 0.3, 1.5], ["ぱんだ", 1.9, 2.4], ["です", 2.5, 3.0]], open(words, "w"), ensure_ascii=False)
    st = os.stat(p("voice", "master.wav")); os.utime(words, (st.st_atime + 10, st.st_mtime + 10))   # 聞き取り（Whisper）を走らせない
    return root


TURN_DX = -40                          # 斜め左の顔: 目と口を画面の左へ寄せる
TURN_MOUTH_ROI = [MOUTH_ROI[0] + TURN_DX, MOUTH_ROI[1], MOUTH_ROI[2] + TURN_DX, MOUTH_ROI[3]]
TURN_EYE_ROI = [EYE_ROI[0] + TURN_DX, EYE_ROI[1], EYE_ROI[2] + TURN_DX, EYE_ROI[3]]


def figure_turn():
    """斜め左を向いた人型（胴を細く、目と口を左へ寄せる）。足元・背の高さは home と同じ。"""
    im = figure(0); d = ImageDraw.Draw(im)
    d.rectangle([150, 120, 330, 290], fill=(253, 253, 253))                                                 # 顔を描き直す
    d.ellipse([140, 95, 330, 285], fill=HAIR); d.ellipse([157 + TURN_DX // 2, 128, 313 + TURN_DX // 2, 286], fill=SKIN)
    for cx in (204 + TURN_DX, 266 + TURN_DX): d.ellipse([cx - 9, 192, cx + 9, 214], fill=(30, 30, 40))
    d.line([(222 + TURN_DX, 254), (248 + TURN_DX, 254)], fill=LIP, width=4)
    return im


def figure_back():
    """後ろ向き（顔の所が髪だけ）。"""
    im = figure(0); d = ImageDraw.Draw(im); d.ellipse([140, 95, 330, 290], fill=HAIR); return im


def gaze_part(roi, dx, dy, cxs=(204, 266)):
    """黒目を (dx, dy) 寄せた目の部品。"""
    x0, y0, x1, y1 = roi; im = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for cx in cxs:
        d.ellipse([cx - x0 - 11, 190 - y0, cx - x0 + 11, 216 - y0], fill=(255, 255, 255, 255))
        d.ellipse([cx - x0 - 6 + dx, 197 - y0 + dy, cx - x0 + 6 + dx, 209 - y0 + dy], fill=(30, 30, 40, 255))
    return im


def make_views(root):
    """make() に、向きの違う姿勢（turn_l: 斜め左、back: 後ろ向き）と視線の部品、transition・gaze・via を足す。"""
    make(root); p = lambda *a: os.path.join(root, *a)
    cfg = json.load(open(p("config.json"), encoding="utf-8"))
    cfg["poses"]["turn_l"] = {"desc": "turned left", "yaw": -40, "face": {"mouth_roi": TURN_MOUTH_ROI, "eye_roi": TURN_EYE_ROI}}
    cfg["poses"]["back"] = {"desc": "back", "yaw": 180, "face": False}
    cfg["transition"] = {"mode": "fade", "dur": 0.3}
    cfg["gaze"] = {"lead": 0.15, "events": [{"at": 0.1, "look": "r", "until": 0.5}]}
    cfg["events"] = [{"at": 0.6, "pose": "point"}, {"line_end": 1, "pose": "home"}, {"at": 2.0, "pose": "turn_l", "via": "turn"},
                     {"at": 2.7, "pose": "back"}, {"at": 3.1, "pose": "home", "via": "cut"}]
    json.dump(cfg, open(p("config.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    figure_turn().save(p("poses", "pose_turn_l.png")); figure_back().save(p("poses", "pose_back.png"))
    od = p("parts_turn_l"); os.makedirs(od, exist_ok=True); meta = {}
    tcx = (204 + TURN_DX, 266 + TURN_DX)
    parts = {"m1": mouth_part(26, 6), "m2": mouth_part(30, 16), "e1": eye_part(6), "e2": eye_part(1),
             "g_c": gaze_part(TURN_EYE_ROI, 6, 0, tcx), "g_u": gaze_part(TURN_EYE_ROI, 0, -5, tcx)}
    for k, im in parts.items():
        im.save(os.path.join(od, f"{k}.png")); meta[k] = (TURN_MOUTH_ROI[:2] if k.startswith("m") else TURN_EYE_ROI[:2])
    json.dump(meta, open(os.path.join(od, "parts.json"), "w"))
    for pose in ("home", "point"):                  # 正面の視線
        od = p(f"parts_{pose}"); meta = json.load(open(os.path.join(od, "parts.json")))
        for k, (dx, dy) in {"g_l": (-6, 0), "g_r": (6, 0), "g_u": (0, -5)}.items():
            gaze_part(EYE_ROI, dx, dy).save(os.path.join(od, f"{k}.png")); meta[k] = EYE_ROI[:2]
        json.dump(meta, open(os.path.join(od, "parts.json"), "w"))
    return root


if __name__ == "__main__":
    print(make_views(sys.argv[2]) if sys.argv[1:2] == ["--views"] else make(sys.argv[1]))
