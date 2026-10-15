"""veo.py — Veo（Gemini API）で素材の動画を1本作る。課金あり（成功した分だけ）。

使い方:
  vs veo --prompt-file prompt.txt --first start.png [--last end.png] [--model lite|fast|standard]
         [--duration 4|6|8] [--resolution 720p|1080p] [--aspect 16:9|9:16] [--neg "出さないもの"]
         [--name 名前 | --out 出力.mp4]

  - 画像は縦横比が合わなければ、端の色を伸ばして --aspect に合わせる（切り落とさない）
    合わせた画像（_first.png）と、元の絵がどこに入ったか（_pad.json）は控えとして指示文のフォルダ（作業フォルダ）に残す。
    動画の保存先には動画だけを置く。置き場を変えるなら --side-dir
  - --neg（出さないものの指定）は fast / standard だけ。lite に付けると外して警告する
  - 料金（音付き、1秒あたり、2026-10 時点）: lite $0.05(720p) / fast $0.10(720p) / standard $0.40

終了コード: 0 成功（標準出力に保存先） 2 引数 3 鍵・認証・請求 4 安全フィルタで止められた（課金なし）
           5 時間切れ 6 その他の失敗 7 使用枠の上限（429。課金なし）
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import gemini_client, out_path, die

MODELS = {"lite": "veo-3.1-lite-generate-preview", "fast": "veo-3.1-fast-generate-preview", "standard": "veo-3.1-generate-preview"}
PRICE = {"lite": {"720p": 0.05, "1080p": 0.08}, "fast": {"720p": 0.10, "1080p": 0.12}, "standard": {"720p": 0.40, "1080p": 0.40}}


def fit_aspect(src, aspect, dst):
    """端の色を伸ばして縦横比を合わせる。元の絵の位置を返す。"""
    import cv2
    im = cv2.imread(src)
    if im is None: die(f"画像を読めない: {src}", 2)
    h, w = im.shape[:2]; aw, ah = map(int, aspect.split(":")); target = aw / ah
    if abs(w / h - target) < 0.01:
        cv2.imwrite(dst, im); return {"left": 0, "top": 0, "width": w, "height": h, "canvas": [w, h]}
    if w / h < target:
        W = round(h * target); l = (W - w) // 2
        out = cv2.copyMakeBorder(im, 0, 0, l, W - w - l, cv2.BORDER_REPLICATE)
        info = {"left": l, "top": 0, "width": w, "height": h, "canvas": [W, h]}
    else:
        H = round(w / target); t = (H - h) // 2
        out = cv2.copyMakeBorder(im, t, H - h - t, 0, 0, cv2.BORDER_REPLICATE)
        info = {"left": 0, "top": t, "width": w, "height": h, "canvas": [w, H]}
    cv2.imwrite(dst, out); return info


def main():
    ap = argparse.ArgumentParser(description="Veo で素材の動画を作る")
    ap.add_argument("--prompt-file", required=True); ap.add_argument("--first", required=True); ap.add_argument("--last")
    ap.add_argument("--model", default="lite", choices=MODELS); ap.add_argument("--duration", type=int, default=8, choices=[4, 6, 8])
    ap.add_argument("--resolution", default="720p", choices=["720p", "1080p"]); ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--neg"); ap.add_argument("--seed", type=int); ap.add_argument("--name", default="veo"); ap.add_argument("--out")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--side-dir", help="控え（_first.png・_pad.json）の置き場。既定は指示文のフォルダ＝作業フォルダ")
    a = ap.parse_args()
    from google.genai import types

    prompt = open(a.prompt_file, encoding="utf-8").read().strip()
    out = out_path(f"{a.name}_veo31{a.model}_{a.duration}s", out=a.out)
    side_dir = a.side_dir or os.path.dirname(os.path.abspath(a.prompt_file)); os.makedirs(side_dir, exist_ok=True)
    side = os.path.join(side_dir, os.path.splitext(os.path.basename(out))[0])   # 動画の保存先に控えを散らかさない
    first_png = side + "_first.png"; pad = {"first": fit_aspect(a.first, a.aspect, first_png)}
    img = lambda p: types.Image(image_bytes=open(p, "rb").read(), mime_type="image/png")
    cfg = dict(aspect_ratio=a.aspect, resolution=a.resolution, duration_seconds=a.duration, number_of_videos=1)
    if a.last:
        last_png = side + "_last.png"; pad["last"] = fit_aspect(a.last, a.aspect, last_png); cfg["last_frame"] = img(last_png)
    if a.neg:
        if a.model == "lite": print("WARN: lite は --neg を受け付けないので外した（指示文に書く）", file=sys.stderr)
        else: cfg["negative_prompt"] = a.neg
    if a.seed is not None: cfg["seed"] = a.seed
    json.dump(pad, open(side + "_pad.json", "w"), indent=1)

    c = gemini_client(); t0 = time.time()
    try:
        op = c.models.generate_videos(model=MODELS[a.model], source=types.GenerateVideosSource(prompt=prompt, image=img(first_png)),
                                      config=types.GenerateVideosConfig(**cfg))
    except Exception as e:
        msg = str(e)
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg:   # 本文に billing の語が入るので先に見る
            die(f"使用枠の上限（429。1分あたり・1日あたり・請求の上限のどれかで、エラーには書かれない。"
                f"https://ai.dev/rate-limit で確かめる。断られた分は無料）: {msg[:200]}", 7)
        if any(k in msg for k in ("PERMISSION", "API key", "billing", "403", "401")): die(f"鍵・請求の問題: {msg[:300]}", 3)
        die(f"受け付けられなかった: {msg[:300]}", 6)
    while not op.done:
        if time.time() - t0 > a.timeout: die(f"{a.timeout} 秒で終わらなかった（operation: {op.name}）", 5)
        time.sleep(10); op = c.operations.get(op)
    if op.error: die(f"生成に失敗: {op.error}", 6)
    vids = getattr(op.response, "generated_videos", None) or []
    if not vids:
        reasons = getattr(op.response, "rai_media_filtered_reasons", None)
        die(f"安全フィルタ等で動画が出なかった（課金なし）: {reasons}", 4)
    v = vids[0].video; c.files.download(file=v)
    v.save(out + ".part"); os.replace(out + ".part", out)
    cost = PRICE[a.model][a.resolution] * a.duration
    print(f"elapsed {round(time.time() - t0)}s, cost ${cost:.2f} (model {a.model}, {a.duration}s {a.resolution})", file=sys.stderr)
    print(out)


if __name__ == "__main__":
    main()
