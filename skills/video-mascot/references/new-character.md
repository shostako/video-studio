# 新しいキャラを立ち上げる手順（キャラに依らない）

マスコットの絵が新しく来たときに、姿勢・口・目・顔と体の向き・視線の絵を描かせ、部品を切り抜き、足元を揃え、config を整えるまでを、同じ順番で通すための手順書。手元のPC（新PC）の Claude Code が、これを上から実行する前提で書いてある。

キャラに固有の値（口と目の範囲、足元の点、描かせる説明）は**作業フォルダの config.json にだけ**置く。コードや手順書には書かない。

## 0. 道具の確かめ（機体ごとに1回）

```bash
~/.claude/skills/video-mascot/scripts/setup.sh --check
```

- `/img` の行が `ok` でも、`bash -lc` の中で `codex` や `node` が Windows 側（`/mnt/c/...`）に解決されると描けない。setup が `NG` を出したら、WSL 側の `codex` が PATH の先に来るようにする（`which -a codex` で確かめる）。
- `/img` は ChatGPT の枠を使う。上限（`vm poses` が終了コード 4 で止まる）に当たったら、時間をおいて同じコマンドを再実行する（描けた分は飛ばす）。

## 1. 元の絵を用意する

| 決まり | 理由 |
|---|---|
| 全身・縦長（9:16 くらい）・正面寄り・口を閉じた落ち着いた顔 | 口の差分と重ねが崩れにくい |
| 背景はほぼ白の無地。影・床・グラデーションなし。透明にしない | 切り抜き（透明）は描画の側で白から作る |
| 足が両方見える | 足元を揃える基準になる |

台座つきのフィギュアは `--pedestal`（台座を消す処理は黒い靴と紺の服を前提にしている。違う色の服なら台座なしの絵を描かせ直す方が早い）。

## 2. 作業フォルダを作る

```bash
vm init ~/.local/share/video-scene/work/<名前> <元の絵.png> \
  --desc "<英語の説明>" --pronoun she|he|it|they --views a [--gestures]
```

- `--desc`: 絵を描かせるたびに毎回そのまま入る、キャラの英語の説明。服・髪・目・質感・体の比率など、**変わってほしくない所**を具体的に書く（例: "a chibi figurine boy with short black hair, round glasses, a navy cardigan over a white shirt, matte cotton texture, grey trousers, brown leather shoes"）。
- `--pronoun`: 描かせる文の代名詞（"her nose" の her）。キャラに合わせる。
- `--views`: 向きと視線の姿勢の段階（`a` = 顔だけ横・体ごと斜め・斜めで手を差し出す の左右6枚。`ab` で真横、`abc` で後ろ向きと前かがみも）。`none` で正面だけ。
- `--gestures`: 正面の身振り（両手を開く・左右へ差し出す）。台本に合わせて config で足し引きする。
- 黒い靴が見つかれば足元の揃え方は `boot`、無ければ色に依らない `feet` を自動で選ぶ。
- `home` は元の絵そのもの（描き直さない）。
- `vm init <作業フォルダ> --print --views ab` なら、書き込まずに雛形だけ見られる。

## 3. 姿勢の絵を描く

```bash
vm poses <作業フォルダ> poses --dry-run          # 描く予定
vm poses <作業フォルダ> poses --only head         # 体は正面のまま顔だけ横
vm poses <作業フォルダ> poses --only turn         # 体ごと斜め
vm poses <作業フォルダ> poses --only present      # 斜めで手を差し出す（turn_* を参照するので後）
vm poses <作業フォルダ> poses                     # 残り（身振りなど）
```

描けたら1枚ずつ Read して確かめる。崩れた絵は消して同じコマンドで描き直す。

1. 同じキャラか（服・髪型・顔つき）。指が崩れていないか。
2. **向き**: `_l` の絵は、鼻とつま先が**絵の左端**を指しているか（取り違えが一番起きやすい）。
3. **黒目**: 向いた側の目尻に寄っているか（元の絵の正面の目に引っぱられて、逆に残りやすい）。
4. `head_*` は肩・手・足が home のままか。`present_*` は体が正面へ戻っていないか（`turn_*` と同じ斜めか）。
5. 揃い: `vm views <作業フォルダ>` の表で、大きさ・足元・背の比を見る。
   - 「大きさが home と違う」: 縦横比を変えずに縮め、足りない所を白で埋めて同じ大きさにする。
   - 背が ±3% を超える: 描き直す。
   - 立ち位置の横のずれ（`boot` のとき）: 出てきた anchor の候補を `poses.<姿勢>.anchor` に書く。`feet` は両足の真ん中で揃うので要らない。

描かせる文の書き方で、うまくいかなかった所と直し方（config の desc を直すときに守る）:

| 起きたこと | 直し方 |
|---|---|
| "toward the viewer's left" で逆を向いた | 「鼻とつま先が絵の左端を指す（nose and toes point toward the LEFT edge of the image）」と、絵の中の向きで書く |
| 斜めの絵で黒目が反対側に残った | 「黒目は向いた側の目尻に寄せる。参照の目の向きは写さない」と最初から書く |
| 手を差し出すと体が正面へ戻り、20 度くらいしか回らなかった | 「体の角度は参照のまま。胴を正面へ戻さない（torso must NOT turn back toward the camera）」 |

## 4. 中割りを描く

```bash
vm poses <作業フォルダ> inbetweens
```

`pairs` の組ごとに5枚。向きを変える組（`home`↔`turn_l` など）は描かない（描画の側で溶かす）。同じ向きの中の手の動き（`turn_l`↔`present_l`）と、正面の身振り（`home`↔`open`）だけ。

## 5. 口・目・視線の差分を描いて、範囲を測る

```bash
vm poses <作業フォルダ> parts                    # 姿勢ごとに口7形・目2段（config に gaze があれば視線も）
vm face <作業フォルダ>                           # 差分から口と目の範囲を測る（表を見る）
vm face <作業フォルダ> --write                   # home は face に、斜めの姿勢は poses.<姿勢>.face に書く
vm parts <作業フォルダ>                          # 部品に切り抜く
vm parts <作業フォルダ> --check                  # parts_check/<姿勢>.png を Read して確かめる
```

- `vm face` の表で「目が口より下」や、範囲が顔より大きいものは、差分の絵が髪や服まで変えている。その差分を消して描き直すか、`vm grid` で読んで直接書く。
- `--check` で見ること: 口が元と違って見えるか、e1/e2 で両目が閉じているか、輪郭や髪が二重になっていないか、視線の部品で黒目が動いているか。

## 6. 台本・声・切り替え・書き出し

ここからはキャラに依らない（SKILL.md の「進め方」の 1・2・8〜11）。向き・視線の書き方は references/config-spec.md の「向きと視線」。

```bash
vm render <作業フォルダ> --mode white --from 秒 --to 秒   # 短い範囲で見てから全編
```

## 7. 残すもの

- 作業フォルダの `notes.md` に、描き直した絵、`vm views` の表、気づいたことを書く。
- 描かせる文の書き方で新しく分かったこと（3 の表に足すもの）は、リポの `references/new-character.md` と `scripts/init.py` の雛形を直す PR にする（キャラに固有の値は入れない）。
