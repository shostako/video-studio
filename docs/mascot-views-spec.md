# マスコットの向き・顔・視線の絵の仕様（描く側の手順書）

マスコットを「正面で手だけ動く」から、顔を少し横に向ける・視線を動かす・体を斜めや横に向ける、まで広げるための**絵の一覧と描き方**。新PC（手元）の Claude Code が、これを見て `/img`（ChatGPT の枠）で描く。描いた絵はリポに入れず、作業フォルダ（`~/.local/share/video-scene/work/<名前>/`）に置く。

描画の仕組み（向きの切り替え・視線の動き・首の向きとの連動）は `skills/video-mascot/references/config-spec.md` の「向きと視線」（opt-in。書かなければ今までの書き出しのまま）。

## 前提

- 仕事の解説動画のマスコット。**落ち着いた動きだけ**を基本にする。後ろ向き・前かがみは「バリエーション」として持つだけで、普段は使わない。
- 左右は**見る人から見て**（画面の左・右）。ただし描かせる文では "toward the viewer's left" だけだと逆を向くことがある（2026-10-15 の実測で turn_l が画面の右を向いた）。**「画面の左端の方を向く。鼻とつま先が絵の左を指す」**と、絵の中の向きで書く（下の config の desc はそう書いてある）。
- 名前の末尾 `_l` は画面の左へ向く、`_r` は画面の右へ向く。マスコットを画面の右に置いて、解説の中身が左にあるなら `_l` を使う。

## 用語

| 語 | 意味 | config の項目 |
|---|---|---|
| 体の向き | 足元を軸に体全体を回した角度。正面 0、画面の左へ向くほど負（−45 は斜め左、−90 は真横で左向き） | `poses.<名前>.yaw` |
| 顔の向き | 首から上だけの角度。体が正面のまま顔だけ横を向く絵に使う | `poses.<名前>.head_yaw`（無ければ `yaw` と同じ） |
| 視線 | 顔の向きはそのままで、黒目だけを動かす。目の部品の差し替えで出す | 部品 `g_l` `g_r` `g_u` `g_c` |

角度は描かせる時の目安で、絵が厳密にその角度である必要はない。描画の側は「どちらへ・どのくらい向いているか」の大小と符号だけを使う（視線の先回りの向き、切り替えのつなぎ方）。

## 絵の一覧

段階 A を先に作る。B・C は A を見て良ければ。

| 段階 | 名前 | 体の向き `yaw` | 顔の向き `head_yaw` | 手 | 使いどころ | 何を参照に描くか |
|---|---|---|---|---|---|---|
| 既存 | `home` ほか今の姿勢 | 0 | 0 | 今のまま | 正面で話す | （描き直さない） |
| A | `head_l` / `head_r` | 0 | −30 / +30 | home と同じ | 体は正面のまま、解説の中身の方へ顔だけ向ける | `home` の絵（顔の向き以外は同じ、と指示） |
| A | `turn_l` / `turn_r` | −40 / +40 | −40 / +40 | home と同じ（体の前で軽く組む） | 体ごと斜めに向いて、中身の方を見ながら話す | `mascot.png` と `home` |
| A | `present_l` / `present_r` | −40 / +40 | −40 / +40 | 向いた側の手を開いて、中身の方へ差し出す | 斜めに向いて「こちらを見て」と示す | `turn_l` / `turn_r` |
| B | `side_l` / `side_r` | −90 / +90 | −90 / +90 | 体の横に下ろす | 真横を向いて中身を見る（話すより、見ている間に使う） | `turn_l` / `turn_r` |
| C | `back` | 180 | 180 | 体の横に下ろす | 後ろを向いて中身を見上げる。口と目の部品なし（顔が見えない） | `mascot.png` |
| C | `lean_in` | 0 | 0 | 両手を胸の前で軽く握る | 少し前へ乗り出して強調する | `home` |

`_l` と `_r` は**左右を反転して作らない**（髪の分け目・ポケット・ボタンが逆になる）。それぞれ描く。

## どの絵にも共通の決まり

描画は「全部の絵が同じ画面の同じ場所に立っている」ことを前提に、足元を揃えて重ねる。ずれは小さいほど切り替えが自然になる。

- **画素の大きさ**: `mascot.png` と同じ幅・高さ（縦長）。違う大きさで出てきたら、縦横比を変えずに縮めて、足りない所を背景の白で埋めて同じ大きさにする（引き伸ばさない）。
- **背景**: 今までと同じ**ほぼ白の無地**（影・床・グラデーションなし）。**透過にしない**（切り抜きは描画の側で白から作る）。台座があるキャラは、どの向きでも同じ台座を描く（`floor.clean` で消す前提）。
- **足元（基準点 1）**: 靴の底が `home` と同じ高さの水平線に乗る。目安 ±10 画素。体を回しても、立っている場所（両足の真ん中）は `home` と同じ横位置に置く。
- **背の高さ（基準点 2）**: 靴の底から頭のてっぺんまでが `home` と同じ。目安 ±3%。斜め・横で頭の形が変わっても、背は縮めない。
- **首の位置（基準点 3）**: 正面と斜めでは、あごの下（首の付け根）が `home` と同じ高さ。目安 ±15 画素。首の傾きの二次運動は、ここを中心に頭を回す。
- **顔の大きさ・描き方・服・照明**: `home` と同じ。`mascot.description` の説明を毎回そのまま使う（`vm poses` が自動で入れる）。
- **表情**: 口を閉じた落ち着いた顔。目は開いて、**顔の向いている方を見る**（斜め・横の絵で、目だけカメラを見るのは部品 `g_c` で出す）。参照の `home` の目（正面を見ている）に引っぱられて黒目が逆に残りやすいので、desc に「黒目は向いている側の目尻に寄せる。参照の目の向きは写さない」と最初から書く。
- **全身が画面に入る**: 手を差し出す絵（`present_*`）の指先が端で切れない。

## 口・目・視線の部品

部品は、姿勢の絵を「ほかは全部同じに保ち、ここだけ変える」と指示して描いた差分から切り抜く（今の `vm poses parts` → `vm parts` と同じ流れ）。

| 部品 | 中身 | 作る姿勢 |
|---|---|---|
| `m1`〜`m7` | 口の7形（今までと同じ） | `back` 以外の全部 |
| `e1` `e2` | まばたきの2段（今までと同じ） | `back` 以外の全部 |
| `g_l` `g_r` | 黒目を画面の左・右へ寄せる。顔の向きはそのまま | 顔が正面の姿勢（`home`、既存の身振り、`lean_in`） |
| `g_u` | 黒目を少し上へ（考えている目） | 顔が正面か斜めの姿勢（`back`・`side_*` 以外） |
| `g_c` | 黒目をカメラ（見る人）へ向ける。顔の向きはそのまま | 顔が斜めの姿勢（`head_*`、`turn_*`、`present_*`） |

- `side_*` は口と目（`m*` `e*`）だけ。真横の視線は描き分けない。
- 斜め・横の顔は口と目の位置が `home` から大きくずれるので、**口と目の範囲は姿勢ごとに測る**（下の config の `face`）。正面の姿勢は今までどおり `home` から自動で写る。
- まばたき（`e1` `e2`）は視線より優先する（目を閉じている間は視線の部品を貼らない）。

## 中割り

- **向きを変える中割り（体や顔が回る途中の絵）は、最初は描かない**。生成の絵は回転の途中で顔や服が崩れやすく、枚数も多い。向きの切り替えは描画の側でクロスフェード（短い溶かし）でつなぐ。見て物足りなければ、段階 A の `home`↔`head_l` などから中割りを足す（`pairs` に足して `vm poses inbetweens`）。
- **同じ向きの中の手の動き**は今までどおり中割りを描く: `turn_l`↔`present_l`、`turn_r`↔`present_r`（5枚ずつ）。

## config.json に足すもの（段階 A の例）

新しいキャラなら `vm init <作業フォルダ> <元の絵> --desc "…" --pronoun she|he|it|they --views a` が、下と同じ姿勢（代名詞はキャラに合わせる）を書く（手順は `skills/video-mascot/references/new-character.md`）。下の例は `--pronoun she` の時の中身で、テストが `vm init` の雛形と一致することを確かめている。desc を直すときは `skills/video-mascot/scripts/init.py` と両方を直す。

今の作業フォルダを丸ごと写した**別の作業フォルダ**（例 `<名前>-views`）で作業する（見比べが済むまで普段使いの作業フォルダは変えない）。斜め・横の姿勢は `face` を書くまで `vm parts`・`vm render` が口と目の範囲を自動で写そうとして止まることがある。

```json
"poses": {
  "home": {"desc": "...（今のまま）"},
  "head_l": {"desc": "exactly the same pose and body as the reference, shoulders and feet still facing the camera, only her head is turned about 30 degrees so that her nose points toward the LEFT edge of the image, her irises sit near the corners of her eyes on the image-left side; do not copy the eye direction of the reference image, calm closed mouth",
             "refs": ["home"], "yaw": 0, "head_yaw": -30},
  "head_r": {"desc": "exactly the same pose and body as the reference, shoulders and feet still facing the camera, only her head is turned about 30 degrees so that her nose points toward the RIGHT edge of the image, her irises sit near the corners of her eyes on the image-right side; do not copy the eye direction of the reference image, calm closed mouth",
             "refs": ["home"], "yaw": 0, "head_yaw": 30},
  "turn_l": {"desc": "her whole body turned about 40 degrees (three-quarter view) so that her nose and her toes point toward the LEFT edge of the image, standing on exactly the same spot as the reference, hands lightly clasped in front of her waist, head facing the same direction as her body, her irises sit near the corners of her eyes on the image-left side; do not copy the eye direction of the reference image, calm closed mouth, same height as the reference",
             "refs": ["home"], "yaw": -40},
  "turn_r": {"desc": "her whole body turned about 40 degrees (three-quarter view) so that her nose and her toes point toward the RIGHT edge of the image, standing on exactly the same spot as the reference, hands lightly clasped in front of her waist, head facing the same direction as her body, her irises sit near the corners of her eyes on the image-right side; do not copy the eye direction of the reference image, calm closed mouth, same height as the reference",
             "refs": ["home"], "yaw": 40},
  "present_l": {"desc": "keep exactly the same three-quarter body angle as the reference (her nose and her toes point toward the LEFT edge of the image); her torso must NOT turn back toward the camera. Her arm on the image-left side is extended toward the LEFT edge of the image with an open palm, presenting something, her irises sit near the corners of her eyes on the image-left side; do not copy the eye direction of the reference image, calm closed mouth, same spot and height as the reference",
                "refs": ["turn_l"], "yaw": -40},
  "present_r": {"desc": "keep exactly the same three-quarter body angle as the reference (her nose and her toes point toward the RIGHT edge of the image); her torso must NOT turn back toward the camera. Her arm on the image-right side is extended toward the RIGHT edge of the image with an open palm, presenting something, her irises sit near the corners of her eyes on the image-right side; do not copy the eye direction of the reference image, calm closed mouth, same spot and height as the reference",
                "refs": ["turn_r"], "yaw": 40}
},
"pairs": [["turn_l", "present_l"], ["turn_r", "present_r"]]
```

- `refs` の絵が先に要るので、`head_*`・`turn_*` を描いてから `present_*` を描く（`vm poses <作業フォルダ> poses --only turn` → `--only present`）。`vm poses` は描けている絵を飛ばす。
- 既存の `pairs` は残して、上の2組を足す。
- 斜めの姿勢の口と目の範囲は、描けてから `vm grid poses/pose_turn_l.png …` で測り、`"face": {"mouth_roi": [...], "eye_roi": [...]}` をその姿勢に足す（`home` の `face` と同じ書き方）。
- 足元の高さ（靴の底）と背の高さは、`vm render` が軸足の靴（`anchor.mode: boot`）で自動で揃える。立ち位置の横のずれ（斜めは靴の見え方が変わり、向かって左の靴で揃えると体の真ん中がずれる）は、`vm views <作業フォルダ>` が出す「anchor の候補」（両足の真ん中を `home` に揃える点）をその姿勢の `"anchor": [x, y]` に書く。靴が見つからない姿勢は `vm grid` で読んで書く。
- 段階 B は同じ形で `side_l`（`"yaw": -90`、refs `turn_l`）ほか、段階 C の `back` は `"yaw": 180, "face": false`（部品を作らない）。

## 実測（2026-10-15、新PC・スーツのマスコット、段階 A の6枚）

| 姿勢 | 足元のずれ | 立ち位置の横のずれ | 背 |
|---|---|---|---|
| `head_l` / `head_r` | 0〜1 | 0〜1 | ±1.3% 以内 |
| `turn_l` | +15 | −28 | 同 |
| `turn_r` | 0 | +20 | 同 |
| `present_l` | +14 | +12 | 同 |
| `present_r` | +5 | +43 | 同 |

- 足元のずれは render が自動で吸収する。横のずれは `vm views` の候補の `anchor` で揃える。
- `present_*` は手を出すと体が正面へ戻りやすく、20 度くらいにしか回らなかった。上の desc は「体の角度は参照のまま、正面に戻さない」と書き足してある。
- 左右の取り違えと黒目の残りは、上の「前提」「表情」の書き方で直った。

## 描く順番と枚数（段階 A）

| 順 | コマンド | 枚数 | いつ |
|---|---|---|---|
| 1 | `vm poses <作業フォルダ> poses --only head` と `--only turn` | 4 | 今すぐ（今の `vm poses` で描ける） |
| 2 | `vm poses <作業フォルダ> poses --only present` | 2 | 1 のあと |
| 3 | 下の「描けたら確かめること」と `vm views <作業フォルダ>` | — | 2 のあと |
| 4 | `vm poses <作業フォルダ> inbetweens --only turn` | 10 | 3 のあと |
| 5 | config に `"gaze": {}` を足して `vm poses <作業フォルダ> parts`（新しい姿勢の口7・目2 と、全姿勢の視線）→ 斜めの `face` を測って書く → `vm parts` | 新しい姿勢 6×9＋視線（正面の姿勢×3、斜め6×2） | 3 のあと |
| 6 | `transition`・`events` の `via`・`gaze.events` を書いて `vm render <作業フォルダ> --mode white --from … --to …` で見比べ | — | 5 のあと |

段階 A の新しい絵は 6＋10＋54 で 70 枚、視線を足して約 100 枚（正面の姿勢が 6 なら 18、斜め 6 姿勢で 12）。`/img` の枠の上限で止まったら、時間をおいて同じコマンドを再実行する。

## 描けたら確かめること（見るのは人か、手元の Claude Code）

1. 6 枚を `home` と横に並べて見る: 同じキャラか、服・髪型・顔つきが揃っているか、指が崩れていないか。崩れた絵は消して描き直す。
2. 足元・立ち位置・背の高さ: `vm views <作業フォルダ>` の表を見る（足元のずれと背の比は render が揃える。背が ±3% を超えたら描き直し。立ち位置は `anchor` の候補を書く）。
3. 大きさ: 表に「大きさが home と違う」が出たら、縦横比を変えずに縮めて白で埋める（`vm render` は大きさが違うと止まる）。
4. 向き: `_l` が本当に画面の左を向いているか（取り違えが一番起きやすい）。
5. `head_*` は体が `home` と同じままか（肩や手まで回っていたら描き直す）。

結果（どれを描き直したか、足元のずれの画素）は作業フォルダの `notes.md` に書いておく。見比べの動画はマイドライブへ。
