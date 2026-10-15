# scene.json の書き方

`vs compose scene.json` が読む。相対パスは scene.json の置き場所が基準。実例は `assets/examples/`（deploy_veo = Veo 素材、deploy_flipbook = パラパラ素材）。

## 全体

```json
{
  "name": "Monday_Deploy",          // 出力ファイル名に使う（Videos/generated/<日時>_<name>.mp4）
  "fps": 30, "duration": 8.0,       // 秒。Veo 素材なら素材の長さに合わせる
  "size": [1920, 1080],             // 既定 1920x1080
  "bg": "#fefdfd",                  // 素材の背景色に合わせる（白背景の素材なら端の色）
  "base": { ... },                  // 土台（1つ）
  "camera": { ... },                // 任意
  "overlays": [ ... ],              // 任意。書いた順に下から積む
  "audio": [{"src": "sfx.wav", "start": 0, "volume": 1.0}]   // 任意。追加の音
}
```

## 座標の決め方

画面は左上が (0,0)、右下が (1920,1080)。素材の置き場所は `rect: [左, 上, 幅, 高さ]`。

- 素材を左に寄せて右を空ける形（今日の型）: 1536x1024 の絵を高さ 1080 に合わせると幅 1620。左に 300 寄せて `[-300, 0, 1620, 1080]`。右側 1100〜1880 がターミナルなどの置き場になる
- Veo 素材は、元の絵の左右に白を足した 16:9（`veo.py` が作業フォルダの `*_pad.json` に元の絵の位置を残す）。1536x1024 の絵なら左右に 142px ずつ足して 1820x1024 になる。元の絵と同じ位置に置くなら `[-300 - 142*1.0547, 0, 1820*1.0547, 1080]` ≒ `[-450, 0, 1920, 1080]`
- 元の絵の上の点 (x, y) は、画面では `(x*k + 左, y*k + 上)`（k = rect の幅 ÷ 元の幅）。顔の中心を寄りの中心（origin）にするときはこれで計算する
- 右端がターミナルの下に入るなら `"fade_right": 0.86` で右端を背景色へぼかす

## base（土台）

### video — Veo の動画、持ち込んだ動画

```json
{"type": "video", "src": "clip.mp4", "rect": [-450, 0, 1920, 1080], "fade_right": 0.86,
 "cut": 7.79,                 // 任意: この時刻で動画を止め、直前のコマを最後まで静止画で残す（終わりの崩れ対策）
 "audio": "video"}            // "video"（素材の音）/ "none" / "声を直した.wav"
```
- `cut` は「最後のまともなコマの番号 + 1」÷ 素材の fps。止め絵は compose が自動で切り出す
- `cut` を付けても `audio: "video"` なら素材の音は最後まで流れる（別トラックにして続ける）

### flipbook — /img の差分（`vs flipbook` で作った状態の絵）

```json
{"type": "flipbook", "states_dir": "states", "rect": [-300, 0, 1620, 1080], "fade_right": 0.86,
 "timeline": [
   {"from": 0, "to": 4.27, "step": 0.1333, "cycle": ["N","F","N","B","F"], "template": "hand-{}_head-B"},
   [4.27, "hand-B_head-B"], [5.6, "shock"], [6.5, "panic"], [8.33, "angry"]],
 "overrides": [{"from": 3.33, "to": 5.6, "set": {"head": "S"}},
               {"from": 1.0, "to": 1.13, "set": {"head": "K"}}]}
```
- `timeline`: `[時刻, 状態名]` はその時刻から次の指定まで。`cycle` は step 秒ごとに順に切り替える（打鍵なら 1秒8枚 ≒ 0.133）
- `overrides`: 時間帯だけ層の記号を差し替える（まばたき・表情）。状態名が `層-記号_層-記号` の形のときだけ効く
- 0 秒から必ず状態が決まっていること

### sequence — 何本かの動画を順につなぐ（30秒前後の解説・寸劇）

```json
{"type": "sequence", "rect": [0, 0, 1920, 1080], "audio": "video",
 "clips": [{"src": "c1.mp4"}, {"src": "c2.mp4", "cut": 7.8}, {"src": "c4.mp4", "hold": 1.3}]}
```
- 各カットは前のカットの終わりから始まる（c2 は c1 の長さの位置から）。重ね表示の時刻は通しの秒で書く
- `cut` でそのカットを途中で切る、`hold` で最後のコマを止めて見せる（最後のカットに付けて、オチの字幕を読ませる時間を作る）
- 音はカットごとに取り出して並べる。カットごとに `audio`（"video"/"none"/wav）と `volume` を指定できる。wav もそのカットの長さ（cut）で切って次のカットに食い込ませない
- つなぎ目を目立たせないコツ: 全カットを同じ最初の絵から作り、どのカットも同じ姿勢（腰に手など）で終わるよう指示文に書く
- 実例: `assets/examples/molding_explainer/`（射出成形の32秒、Veo Lite 8秒×4）

### image — 1枚絵（風景の寄り・横流しなど）

```json
{"type": "image", "src": "still.png", "rect": [0, 0, 1920, 1080]}
```
動きは camera の push / pan で付ける。

## camera（土台と attach した重ね表示に効く）

```json
{"push":  [{"from": 0, "to": 5.5, "scale": 1.04, "origin": [565, 590]}],   // ゆっくり寄る（ease）
 "punch": [{"t": 6.4, "scale": 1.08, "origin": [375, 274], "damping": 9, "stiffness": 180}],  // ばねで寄る
 "shake": [{"from": 3.7, "to": 5.2, "amp": 7, "decay": true}],             // 揺れ（px）
 "pan":   [{"from": 0, "to": 8, "dx": -80, "dy": 0}]}                      // 横・縦に流す
```
- origin は各種類の最初の指定のものを使う（同じ種類で origin を変えられない）

## overlays（重ね表示）

共通: `"attach": true` でカメラと一緒に動く（キャラの頭に付ける記号など）。既定は画面に固定。

| type | 主な項目 | 用途 |
|---|---|---|
| `terminal` | `rect`, `title`, `prefill`（書き済み）, `typing`[{text, from, to}], `cursor_until`, `lines`[{t, text, kind: dim/ok/err/info/plain, bold, progress, mark, mark_t}], `glow`[{type: flash, t, color} / {type: pulse, from, to, color}], `font_size`, `line_height`, `appear` | コードを打つ、結果が流れる、光る（既定は赤、`color: [r,g,b]` で成功の緑など）。行が溢れたら自動で下へ送る |
| `bubble` | `text`, `from`, `to`, `pos`[x,y], `style`: normal/panic/angry/soft, `size`, `tail`: left/right/dots/none, `jitter` | セリフの吹き出し。ばねで弾んで出る。soft は点線＋丸い点の尻尾（寝言・つぶやき）。text の改行（\n）で2行にできる（縦の画面で幅が足りないとき） |
| `caption` | `text`, `from`, `to`, `size`, `bottom` | 下の字幕帯 |
| `text` | `text`（改行可）, `from`, `to`, `pos`, `size`, `color`, `weight`, `bg`, `anchor`: center/left/topleft, `anim`: fade/pop, `style`{CSS} | 題名、説明の文字、ラベル、判子（style に border・padding・border-radius・background・rotate を書くと枠ごと pos に寄る） |
| `wash` | `color`[r,g,b], `segments`: {type: flash, t, peak, decay, hold, until} / {type: pulse, from, to, low, high, period} / {type: fade, t, from, to, dur, until} | 画面の縁を色で染める（危険・警告の赤など） |
| `mark` | `shape`: anger/exclaim/sweat/heart/zzz/sparkle, `t`, `to`, `pos`, `size`, `rotate`, `pulse`, `color`, `period`（zzz） | 怒りマーク、びっくり、汗、居眠りの Z（3つが右上へ昇る。pos は出発点）、星の瞬き（成功・嬉しい）。頭に付けるなら attach |
| `image` | `src`, `rect`, `from`, `to` | ロゴ、図、画面写真などを重ねる |
| `svg` | `src`（SVGファイル）, `rect`, `from`, `to`, `fade`, `anims`[{sel, prop: x/y/scale/scaleX/scaleY/rotation/opacity, keys: [[秒, 値]...], ease: linear/inout/step, origin: "x y"} / {sel, attr, keys}] | 動く図解・工程図。SVG の中の要素に id を付け、キーフレームで動かす（型が閉じる、樹脂が流れ込む、部品が落ちる） |
| `video` | `src`, `rect`, `from`, `length`, `blend`（multiply など） | 別に書き出した動画（3D のアニメ、図の動画）を枠に重ねる。音は使わない。白い背景の図を白っぽい土台に重ねるなら `blend: "multiply"`（白が透けて、境目の四角が出ない） |

- 吹き出しの文言は台本でなく「実際に聞こえるセリフ」にする（`vs analyze` の書き起こし）
- 吹き出しの出る時刻はセリフの開始 + 0.1〜0.15 秒、消えるのは終了 + 0.15 秒か次のセリフの開始の早い方。最後のセリフは `to` を duration にして最後まで残す
- 進み具合のバー（terminal の lines の1行）: `{"t": 0, "text": "building", "kind": "info", "progress": {"width": 14, "keys": [[0, 96], [0.7, 99], [1.42, 99], [1.47, 100]]}}`。keys は [時刻, %] を直線でつなぐ。「99% で止まって、音と同時に 100%」のような溜めが作れる
- 行の中の語に印（`"mark": "monday", "mark_t": 3.75`）: その語に黄色の帯が付き、mark_t で点滅してから残る。git blame の書いた人、ログの中の名前などを目立たせる
- 縦の画面（ショート）は `"size": [1080, 1920]`。人物を下半分、ターミナルを上に置く。吹き出しは横幅が足りないので2行にする。実例: `assets/examples/git_blame_flow/`
- 実例: `assets/examples/build_doze_veo/`（居眠り→通知音で起きる。進み具合のバー、緑の光、zzz、sparkle、soft の吹き出し）
- SVG の図: id はページ全体で重ならないよう接頭辞を付ける（`mm-` など）。流れ込みは `scaleX` と `origin`（流れ出す側の端）で表す。熱い→冷えたの色の変化は、色違いの図形を重ねて opacity で切り替える。字幕は図の下に `text`（bg 付き）で出す
- 新しい種類の重ね表示が要るときは compose.py に `ov_<type>` を足す（コマごとの値を返す関数を `track` に登録する形）

## 書き出し

- `vs compose scene.json` → lint（エラーで止まる）→ 書き出し → 保存先のパスを標準出力に1行
- `--draft` で低画質の試し書き出し（作業フォルダの draft.mp4 に上書き。保存先には置かない）、`--no-render` で HTML だけ作る（hf/index.html）
