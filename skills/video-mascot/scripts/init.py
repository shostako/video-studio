"""新しいマスコットの作業フォルダを、絵1枚と英語の説明から作る（キャラに依らない雛形。手順は references/new-character.md）。
  vm init <作業フォルダ> <元の絵.png> --desc "英語の説明" [--pronoun she|he|it|they] [--views none|a|ab|abc] [--gestures] [--pedestal] [--force]
  vm init <作業フォルダ> --print [--pronoun ...] [--views ...] [--gestures]    書き込まずに、できる config.json を出すだけ
作るもの: mascot.png（元の絵の写し）、poses/pose_home.png（元の絵をそのまま home に使う）、config.json。
config.json には、キャラの説明・代名詞・足元の揃え方（黒い靴が見つかれば boot、無ければ色に依らない feet）・姿勢の雛形
（--views で向き・視線の段階、--gestures で正面の基本の身振り）・pairs・transition・gaze を書く。
口と目の範囲（face）は書かない（部品の差分を描いてから vm face で測る）。台詞（voice）と events は台本を決めてから書く。
既にある config.json は --force が無ければ上書きしない。描いた絵（poses/ の home 以外・parts/・parts_*/・ib/）が残っている作業フォルダには、--force でも作らない（新旧のキャラの絵が混ざるため）。"""
import argparse, json, os, shutil, sys
import cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import boot_anchor, feet_anchor, die

POSS = {"she": "her", "he": "his", "it": "its", "they": "their"}   # 描かせる文の所有格（mascot.pronoun。既定 she）
HOME_DESC = "standing naturally and facing the camera almost straight on, hands lightly clasped in front of {p} waist, calm closed mouth"
IRIS = "{p} irises sit near the corners of {p} eyes on the image-{s} side; do not copy the eye direction of the reference image"


def _side(s, S): return {"s": s, "S": S}


def view_presets(tiers):
    """向き・視線の姿勢の雛形（docs/mascot-views-spec.md の段階 A〜C）。{p} は所有格に、{s}/{S} は left/LEFT か right/RIGHT に置き換わる。
    左右の書き方は「鼻とつま先が絵の左端を指す」の形（"viewer's left" は逆を向くことがあった）。"""
    out, pairs = {}, []
    for k, s, S, sign in (("l", "left", "LEFT", -1), ("r", "right", "RIGHT", 1)):
        iris = IRIS.replace("{s}", s)
        if "a" in tiers:
            out[f"head_{k}"] = {"desc": ("exactly the same pose and body as the reference, shoulders and feet still facing the camera, "
                                         f"only {{p}} head is turned about 30 degrees so that {{p}} nose points toward the {S} edge of the image, {iris}, calm closed mouth"),
                                "refs": ["home"], "yaw": 0, "head_yaw": 30 * sign}
            out[f"turn_{k}"] = {"desc": (f"{{p}} whole body turned about 40 degrees (three-quarter view) so that {{p}} nose and {{p}} toes point toward the {S} edge of the image, "
                                         f"standing on exactly the same spot as the reference, hands lightly clasped in front of {{p}} waist, head facing the same direction as {{p}} body, "
                                         f"{iris}, calm closed mouth, same height as the reference"),
                                "refs": ["home"], "yaw": 40 * sign}
            out[f"present_{k}"] = {"desc": (f"keep exactly the same three-quarter body angle as the reference ({{p}} nose and {{p}} toes point toward the {S} edge of the image); "
                                            f"{{p}} torso must NOT turn back toward the camera. {{P}} arm on the image-{s} side is extended toward the {S} edge of the image "
                                            f"with an open palm, presenting something, {iris}, calm closed mouth, same spot and height as the reference"),
                                   "refs": [f"turn_{k}"], "yaw": 40 * sign}
            pairs.append([f"turn_{k}", f"present_{k}"])
        if "b" in tiers:
            out[f"side_{k}"] = {"desc": (f"{{p}} whole body turned 90 degrees (full side profile) so that {{p}} nose and {{p}} toes point toward the {S} edge of the image, "
                                         f"standing on exactly the same spot as the reference, arms relaxed at {{p}} sides, head facing the same direction as {{p}} body, "
                                         "calm closed mouth, same height as the reference"),
                                "refs": [f"turn_{k}"] if "a" in tiers else ["home"], "yaw": 90 * sign}
    if "c" in tiers:
        out["back"] = {"desc": ("seen from behind: {p} back faces the camera and only the back of {p} head is visible (the face is not visible), "
                                "arms relaxed at {p} sides, standing on exactly the same spot and at the same height as the reference"),
                       "yaw": 180, "face": False}
        out["lean_in"] = {"desc": ("facing the camera, leaning {p} upper body slightly forward toward the viewer, both hands lightly clenched in front of {p} chest, "
                                   "calm closed mouth, feet on exactly the same spot as the reference"),
                          "refs": ["home"], "yaw": 0}
    return out, pairs


def gesture_presets():
    """正面の基本の身振り（home と行き来する）。台本に合わせて足し引きする前提の最小限。"""
    out = {"open": {"desc": "facing the camera, both hands open at chest height with palms up, explaining something, calm closed mouth", "refs": ["home"]},
           "point_l": {"desc": "facing the camera, {p} arm on the image-left side extended toward the LEFT edge of the image with an open palm, presenting something, calm closed mouth", "refs": ["home"]},
           "point_r": {"desc": "facing the camera, {p} arm on the image-right side extended toward the RIGHT edge of the image with an open palm, presenting something, calm closed mouth", "refs": ["home"]}}
    return out, [["home", n] for n in out]


def fill(poses, pron):
    p = POSS[pron]
    return {n: {**c, "desc": c["desc"].replace("{p}", p).replace("{P}", p.capitalize())} for n, c in poses.items()}


def build(name, desc, pron="she", tiers="a", gestures=False, anchor_mode="boot", pedestal=False):
    tiers = "" if tiers == "none" else tiers
    poses = {"home": {"desc": HOME_DESC}}; pairs = []
    if gestures: g, gp = gesture_presets(); poses.update(g); pairs += gp
    if tiers: v, vp = view_presets(tiers); poses.update(v); pairs += vp
    cfg = {"name": name, "fps": 30, "pad": 100, "home": "home", "seed": 5,
           "mascot": {"description": desc, "pronoun": pron},
           "poses": fill(poses, pron), "pairs": pairs,
           "floor": {"clean": bool(pedestal)}, "anchor": {"mode": anchor_mode},
           "inbetween_prompt": "percent"}
    if tiers: cfg["transition"] = {"mode": "fade", "dur": 0.25}; cfg["gaze"] = {}
    cfg["events"] = []
    cfg["voice"] = {"candidates": [], "lines": []}
    return cfg


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="vm init", description=__doc__.splitlines()[0])
    ap.add_argument("dir"); ap.add_argument("image", nargs="?")
    ap.add_argument("--desc", help="キャラの英語の説明（服・髪・目・質感。描かせる度に毎回そのまま使う）")
    ap.add_argument("--pronoun", choices=sorted(POSS), default="she", help="描かせる文の代名詞（既定 she）")
    ap.add_argument("--views", choices=["none", "a", "ab", "abc"], default="a", help="向き・視線の姿勢の段階（既定 a）")
    ap.add_argument("--gestures", action="store_true", help="正面の基本の身振り open・point_l・point_r を足す")
    ap.add_argument("--pedestal", action="store_true", help="台座つきの絵（floor.clean: true。黒い靴と紺の服の前提の処理）")
    ap.add_argument("--print", action="store_true", help="書き込まずに config.json を出す")
    ap.add_argument("--force", action="store_true", help="既にある config.json を上書きする")
    a = ap.parse_args(); root = os.path.abspath(a.dir); name = os.path.basename(root.rstrip("/"))
    if a.print:
        print(json.dumps(build(name, a.desc or "(英語の説明)", a.pronoun, a.views, a.gestures, "boot", a.pedestal), ensure_ascii=False, indent=1)); sys.exit(0)
    if not a.image or not a.desc: die("使い方: vm init <作業フォルダ> <元の絵.png> --desc \"英語の説明\"（--print なら絵と説明なしで雛形だけ出す）")
    img = cv2.imread(a.image)
    if img is None: die(f"絵が読めない: {a.image}")
    H, W = img.shape[:2]; cfgp = os.path.join(root, "config.json")
    if os.path.exists(cfgp) and not a.force: die(f"config.json が既にある（上書きするなら --force）: {cfgp}")
    made = [os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs
            if os.path.relpath(d, root).split(os.sep)[0] in ("poses", "parts", "ib") or os.path.relpath(d, root).startswith("parts_")]
    made = [m for m in made if m != os.path.join("poses", "pose_home.png")]
    if made: die(f"描いた絵が残っている（{len(made)} 枚。例 {made[0]}）。--force でも、前のキャラの絵と混ざるので作り直さない。新しい作業フォルダで")
    if H <= W: print(f"注意: 絵が縦長でない（{W}x{H}）。全身・縦長・白い無地の背景の絵にすると、口の差分も重ねも崩れにくい", file=sys.stderr)
    corner = img[:8, :8].reshape(-1, 3).mean(0)
    if corner.min() < 235: print(f"注意: 左上の背景が白くない（{corner.round().tolist()}）。背景はほぼ白の無地が前提（透明にするのは描画の側）", file=sys.stderr)
    boot = boot_anchor(img); feet = feet_anchor(img)
    if boot and feet and abs(boot[1] - feet[1]) > 0.01 * H: boot = None   # 黒い塊が足元まで届かない（黒いスカート・裾など）は靴ではない
    mode = "boot" if boot else ("feet" if feet else "none")
    print(f"足元の揃え方: {mode}（黒い靴 {'あり' if boot else 'なし'}、足元 {tuple(round(v, 1) for v in feet) if feet else 'なし'}）", file=sys.stderr)
    for d in ("poses", "parts", "ib", "voice", "out"): os.makedirs(os.path.join(root, d), exist_ok=True)
    shutil.copyfile(a.image, os.path.join(root, "mascot.png"))
    hp = os.path.join(root, "poses", "pose_home.png")
    if not os.path.exists(hp) or a.force: shutil.copyfile(a.image, hp)
    cfg = build(name, a.desc, a.pronoun, a.views, a.gestures, mode, a.pedestal)
    with open(cfgp, "w", encoding="utf-8") as f: json.dump(cfg, f, ensure_ascii=False, indent=1)
    print(f"作った: {root}（姿勢 {len(cfg['poses'])}: {', '.join(cfg['poses'])}、pairs {len(cfg['pairs'])}）")
    print("次: vm poses <作業フォルダ> poses --dry-run で描く予定を見てから、references/new-character.md の順に")
