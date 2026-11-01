---
name: screen-explainer
description: Excel のブックや Web アプリ（ローカルのダッシュボードなど）の使い方を、実際の画面を撮って説明する解説動画を作る。撮った画面に、寄り（カメラ）・目立つカーソル・赤い枠の強調・クリックの波紋・キーの札・字幕・口パクする右下の丸いワイプを重ね、台詞の声に合わせて 1 本の mp4 にする。声は手元の Irodori-TTS（video-mascot の vm voice）なので追加の支払いは無い。「このExcelの使い方の動画を作って」「アプリの操作説明の動画」「画面を見せながら解説する動画」「操作手順の解説動画」「チュートリアル動画」で発動。マスコットが全身で身振りする動画は video-mascot、Veo や H3 で生成する短い場面は video-scene。
---

# 画面操作の解説動画（screen-explainer）

本物の画面を静止画で撮り、動画の側で寄り・カーソル・強調を動かす。画面を録画しないので、撮り直しは場面 1 枚で済み、カーソルの動きも強調の時刻も台詞に合わせて後から直せる。

| 入れるもの | 出てくるもの |
|---|---|
| 説明するブック（の写し）か Web アプリ、台本、口を閉じた顔の絵 1 枚と口の部品 3 枚 | 1920×1080 の mp4（字幕の帯つき。`compose.py` だけなら 30fps、`vm explain` で蘭のパックの全身の型を作ると 60fps）。30MB を超えるならスマホ用に圧縮した版も |

道具は `scripts/` にある（以下 `S=~/.claude/skills/screen-explainer/scripts`）。

| 道具 | 動かす Python | 役目 |
|---|---|---|
| `excel_capture.py` | Windows 側の Python（3.12 以上、`pip install pywin32 pillow`。WSL の python では動かない） | Excel の写しを開いて場面ごとに撮り、セルの画面座標を `rects.json` に書く |
| `web_capture.py` | video-scene の venv（`~/.local/share/video-scene/venv/bin/python`、Windows は `venv/Scripts/python.exe`。video-scene の setup.sh が Playwright と Chromium を入れる） | Web アプリを裏のブラウザで開いて撮り、要素の座標を `rects.json` に書く |
| `wipe_faces.py` | OpenCV の入った Python | 顔の絵と口の部品から、ワイプの顔 `mouth0〜3.png` を作る |
| `word_timing.py` | faster-whisper の入った Python（video-scene の venv） | 声の語ごとの長さを測り、読み違いと溜めを見つける |
| `compose.py` | Pillow と ffmpeg | 撮影・声・場面の割り付けから動画を組む |

## 出せる型（同じ撮影・声・scenes.py から選ぶ）

| 型 | compose.py の指定 | 余白のマスコット |
|---|---|---|
| カーソルだけ | `--layout full`（既定）。`--chapters` で、章が替わった所に左上へ見出しを数秒出して消す | なし |
| ワイプ | `--layout margin [--scale 0.73]`。画面を縮めて右に寄せ、字幕はその下。`--chapters` は余白の左上に出し続ける | 丸いワイプを左下に（video-mascot の `vm layout`） |
| 全身・小 | 同上 | 全身を余白の下に（`vm layout`） |

3 つの型を 1 本に通すなら video-mascot の `vm explain <作業フォルダ> --shots <撮影> --scenes scenes.py --style cursor|wipe|full --out 出力.mp4`（下の 6・7 の組み立てとマスコットの書き出し・重ね・検査をまとめて回す）。

`--scale` を上げると画面の字は大きくなるが、余白（0.73 で 496px、0.8 で 384px、0.83 で 320px）は狭くなる。書き出すと `<出力>.layout.json` に余白の幅が残り、`vm layout` はそれに合わせてマスコットを置く。章の見出しの JSON は video-mascot の `scripts/chapters.py` の先頭に書き方がある。マスコット付きの型では、見出しは compose か `vm layout` のどちらか一方で付ける（両方だと二重に出る。`vm layout` が注意を出す）。

## 進め方

作業フォルダは `~/.local/share/video-scene/work/<名前>/`（声）と、撮影フォルダ（Excel なら Windows から見える `C:\Users\<you>\AppData\Local\Temp\...`）。

1. **台本を書く**。1 行 = 1 場面。汎用の内容にして、案件の数字は読まない（画面に出る数字は読み上げない）。ユーザーが「詳しく」と言えば、シート・欄ごとに「何を入れる所か」「どこに効くか」「直すときの注意」まで書く。メールや会話など中身が私的な画面は、台本にも入れず、撮影でぼかす。
2. **声を作る**。`config.json` に `{"name": ..., "fps": 30, "poses": {"none": {}}, "voice": {"lines": [{"text": ...}, ...], "gap": 0.6, "caption": ..., "seed": ..., "ref": ...}}` を書き、`vm voice <作業フォルダ> synth` → `master`。声の決まり（どの声を使うか）は利用者ごとの記憶にあるので、それに従う。決まりが無ければ、既定の声 `"caption": "ニュースのナレーターのような、癖のない落ち着いた女性の声。丁寧に、聞き取りやすく説明している。クリアな音質。", "seed": 2024` で作る（README の例と同じ）。声の候補探しで回数を重ねない。
   - `synth` の「台本との一致」が低い行と、`word_timing.py` で `←` の付く語（文末・読点の前は自然に長い）を見る。「エンター」が「Enter」と聞き取られたような、表記の違いだけで下がった一致は読み違いではない。読み違えた行にだけ `say`（ふりがな）を書いて、その行だけ作り直す（`vm voice <作業フォルダ> synth 3 9`）。全行に `say` を入れると抑揚が崩れる。
   - 英字・記号はカタカナに開く（Shift+Enter →「シフトエンター」）。「税抜きの」が「ぜいぬきん」になるような、漢字のままでつながる誤読は仮名に開く。
3. **撮る**。台詞の行ごとに、見せる画面を決めて `states.json` を書く（書き方は各スクリプトの先頭）。
   - Excel: 元のブックは開かずに写しを作って撮る（`excel_capture.py <写し> <states.json> <出力>`）。撮った後に `rects.json` の枠を 1 枚の画像に描いて、ずれていないかを見る。
   - Web: `~/.local/share/video-scene/venv/bin/python $S/web_capture.py <states.json> <出力>`（Windows は `venv/Scripts/python.exe`）。Web アプリは手元で動かしておく（HTML 1 枚なら、その HTML のあるフォルダで `python3 -m http.server 8770 --bind 127.0.0.1` を動かして配る）。取り込み・削除・送信などのボタンは押さない。欄の Enter は既定で送らない。計算などに Enter が要り、送信や削除が起きないと HTML や動きで確かめたアプリでは送ってよい。本物の端末や会話がつながる画面は `block_websocket` で切り、中身は `blur_css` / `frame_css` でぼかす。
   - 3D の画面のようにボタンで指せない所は、`click_xy`・`drag`・`wheel` か、アプリに固有の操作を `hooks.py` の関数に書いて `["call", 関数名, ...]` で呼ぶ。関数が返す枠は rects.json に入るので、クリックした点にカーソルを置ける。アプリにテスト用の窓口（3D の点を画面の座標にする関数など）があれば使う。
   - 回す・寄る・ずらすのような連続した動きは、`drag_film` / `wheel_film` で動きを 25〜30 に刻んで 1 刻みごとに撮り、`add(..., film=[(始め, 終わり, 名前)])` で流す。1 秒前後で流すと毎秒 30 コマ近くになり、なめらかに動いて見える。動きの前後を 1 枚ずつ撮って重ねるだけだと、パラパラに見える（ユーザーの指摘）。
   - 撮影に使うアプリのデータ（保存される計測・最近のファイルなど）は、普段使いと分けた場所に向ける。撮る前に消して、毎回同じ状態から撮る。
4. **ワイプの顔を作る**（顔の絵が変わったときだけ）。`wipe_faces.py --pose <閉じた顔> --parts <小> <中> <大> --out <口の絵のフォルダ>`。口だけを貼るので頭は動かない。出来た 4 枚を並べて見る（開き過ぎの形は入れない）。
5. **場面を割り付ける**。`scenes.py` に 1 行 1 回 `add(...)` を書く。書き方は `assets/example_scenes.py`。割合はその行の声の長さを 1 とした位置。カーソルは台詞で言う物の上に、言う少し前に着ける。強調は言っている間だけ。
6. **見本のコマで確かめる**。`compose.py ... --preview 3.0,12.5,...` で、場面の切り替えの前後・強調の出る所・ワイプが角を移る所を PNG にして Read で見る。枠のずれ、ワイプと枠の重なり、字幕のはみ出しを直す。
7. **書き出す**。`compose.py --shots <撮影> --voice <作業フォルダ> --scenes scenes.py --out <名前>.mp4 [--chapters 章.json]`（カーソルだけの型。マスコット付きの型は `--layout margin` で書き出し、video-mascot の `vm layout` で余白にマスコットを置く。画面の角に重ねる古いワイプは `--wipe <口の絵のフォルダ>`）（Excel は `--clip-bottom 948`、右のスクロールバーを避けるなら `--clip-right 1895`）。一部だけなら `--from` / `--to`。
   - ワイプの角は、画面のどこに操作の欄があるかで決める。右に操作パネルが縦に続くアプリ（cad-viewer など）は `--wipe-home BL`。既定の BR のままだと、ずっとパネルに被る（ユーザーの指摘）。
8. **送る**。30MB を超えたら `ffmpeg -i in.mp4 -c:v libx264 -crf 29 -preset slow -c:a aac -b:a 96k out_スマホ用.mp4`。ユーザーに耳と目で確かめてもらい、指摘の行だけ声か場面を直して 7 から。

## 確かめること

- 声: 読み違い（台本との一致、`word_timing.py`）と、最後の行の終わりまで入っているか。私は音を聞けないので、最後はユーザーの耳で決める。
- 絵: 強調の枠が言っている物を囲んでいるか（ウィンドウ枠の固定・ズームでずれる）、ワイプが枠やカーソルに重なっていないか、私的な中身が写っていないか。
- 長さ: `compose.py` の最後に出る秒数が、声の `timing.json` の `end` より 0.8 秒長いか（終わりの余白として足している）。

## 罠

`references/lessons.md` にまとめた。Excel の COM（打ち込み中は拒否、プルダウンはマウスで、固定枠の区画）、ブラウザのスクロール、PowerShell 5.1 の COM、送れる大きさなど。
