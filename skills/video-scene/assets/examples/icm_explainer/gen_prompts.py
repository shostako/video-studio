"""射出圧縮成形の解説（蘭）の Veo 指示文 cut1〜8.txt を書き出す。"""
import os

HEAD = ("A glossy resin chibi figurine girl in a navy work uniform stands on a small clear display base "
        "on the left side of the frame. ")
TAIL = ("The right half of the frame stays empty plain white background the whole time. "
        "Sound: quiet studio room tone.\n"
        "Static camera, locked-off shot, plain white studio background, soft studio lighting. "
        "Keep the character design, proportions, outfit and figurine look exactly as in the first frame. "
        "She has exactly two arms and two legs. Her eyes stay dry the whole time (no tears). "
        "No text, letters, captions, speech bubbles or written symbols appear anywhere in the video; "
        "the dialogue is spoken only. Her voice is a young woman's, slightly husky, calm and confident, "
        "like a skilled engineer explaining, speaking Japanese.")

CUTS = {
    1: ('She looks at the camera with a serious, confident look and says in Japanese, '
        '"普通の射出成形だと、薄物は樹脂が回りきらない". '
        'Then she raises her right hand and points to the empty space on the right side of the frame, '
        'like a presenter pointing at a chart, and says, "そこで射出圧縮成形だ". '
        'Then she puts her hand back on her hip and stays still for the last second. '),
    2: ('She points with her index finger at a spot in the empty space on the right side of the frame, '
        'like pointing at a detail on a chart, and says in Japanese, '
        '"がいしゅうの枠はバネで浮いてて、バネの力でこの隙間が開いてる". '
        'Then she turns back to the camera, raises her index finger and says firmly, "こいつを覚えとけ". '
        'Then she puts her hand back on her hip and stays still for the last second. '),
    3: ('She holds both palms facing each other in front of her chest, wide apart, and slowly brings them '
        'closer together like two halves of a mold closing, stopping when they are a short distance apart, '
        'and says in Japanese, "金型が射出待機位置まで閉じる". '
        'Then she moves her palms a little closer, as if squeezing a spring, and says, "このかたじめりょくで、バネがちぢむ". '
        'She stays still for the last second. '),
    4: ('She holds both hands in front of her chest, palms facing each other with a small gap about one finger '
        'wide between them, and says in Japanese, "バネの力で、がいしゅうのPL面がぴたりと閉じる". '
        'Keeping that small gap, she glances at it and then looks at the camera and says, '
        '"さっきの隙間の残りが、あっしゅくしろだ". '
        'She stays still for the last second. '),
    5: ('She points to the empty space on the right side of the frame with her right hand and says in Japanese, '
        '"バルブを開いて、少し広めのキャビティに樹脂を詰める". '
        'Then she makes a small twisting motion with her fingers, like turning a valve shut, and says, '
        '"詰め終わったら、バルブを閉じる". '
        'Then she puts her hand back on her hip and stays still for the last second. '),
    6: ('She holds both hands in front of her chest, palms facing each other with a small gap about one finger '
        'wide between them, and says in Japanese, "ここからが圧縮だ。バネがさらにちぢんで、動くのはコアだけ". '
        'Then she slowly brings her palms together until they touch, looks at the camera and says, '
        '"あっしゅくしろがゼロになったら止まる". '
        'She stays still for the last second. '),
    7: ('She spreads both hands apart as if opening something and says in Japanese, '
        '"冷やして型を開けば、成形品は可動側に食い付いて残る". '
        'Then she puts her hands on her hips and stays still for the last second. '),
    8: ('She crosses her arms with a confident look and says in Japanese, '
        '"広く入れて、薄く仕上げる。圧が均一だから、反りも出にくい". '
        'Then she nods once and says, "それが射出圧縮成形だ". '
        'For the last second she stays still, smiling confidently at the camera. '),
}

here = os.path.dirname(os.path.abspath(__file__))
for n, body in CUTS.items():
    with open(os.path.join(here, f"cut{n}.txt"), "w", encoding="utf-8") as f:
        f.write(HEAD + body + TAIL + "\n")
print("wrote", len(CUTS))
