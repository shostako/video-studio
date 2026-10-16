# 足すポーズの仕様（描く側の手順書）

正面の構え（home）・身振り・向きと視線（`docs/mascot-views-spec.md`）に、**解説の流れで使いやすい正面のポーズ**を足すための一覧と描き方。2026-10-16、向きと視線の見比べ（向き_v2）を見たユーザーの「他にもポーズを足してよい（軽く伸び、軽く屈伸、屈む、ターンなど。選ぶのは任せる）」から。

新PC（手元）の Claude Code が、これを見て `/img`（ChatGPT の枠）で描く。描いた絵はリポに入れず、作業フォルダに置く。キャラに依らない（下の desc は `vm init --extras` が代名詞を差し替えて書く）。

## 選んだもの

仕事の解説動画で、台詞のどこで使うかがはっきりしているものを先にした。大きく体が動くもの（ジャンプ・回転の連続）は入れない。

| 段階 | 名前 | 動き | 使いどころ（台詞の例） | 背の高さ |
|---|---|---|---|---|
| A | `think` | 手をあごに当てて考える | 「なぜでしょう」「ここで疑問が」 | 変わらない |
| A | `bow` | はっきりしたお辞儀（上体を 30 度ほど前へ。頭のてっぺんが 1 割ほど下がる） | 冒頭のあいさつ、締めの「以上です」 | 低くなる（`scale` 固定） |
| A | `raise_r` | 片手を顔の高さに挙げ、人差し指を立てる | 「ポイントは一つ」「ここで注意」 | 変わらない |
| A | `stretch` | 両手を頭の上で組んで軽く伸び | 話の区切り、「さて」「一息」 | 高くなる（`scale` 固定） |
| B | `crouch` | 屈んで、画面の右下を指す | 画面の下の方（図の下・足元の部品）を示す | 低くなる（`scale` 固定） |
| B | `knee_bend` | 軽い屈伸（膝を少し曲げる） | 「よし」と区切る、強調の前の溜め | 少し低くなる（`scale` 固定） |
| 後で | ターン | 一回転 | 場面の切り替え | 新しく描かない（下の「ターン」） |

段階 A を先に描く。B は A を見て良ければ。

## 描き方の決まり

`docs/mascot-views-spec.md` の「どの絵にも共通の決まり」（同じ画素の大きさ・白の無地・足元を home に揃える・透過にしない・口を閉じた落ち着いた顔）に加えて:

- **足は動かさない**: どのポーズも「立っている場所は参照と同じ」。お辞儀・屈む・屈伸でも足の位置と靴の底の高さは home のまま。
- **顔を隠さない**: お辞儀・屈むでも顔が見える角度にとどめる（口と目の部品を作るため）。
- **背の高さが変わるポーズは `"scale": 1.0`**: `vm render` は姿勢ごとに背の高さで大きさを揃える（描いた絵の数%の大きさの違いを吸収するため）。伸びは背が高く、お辞儀・屈むは低くなるのが正しいので、揃えると伸びが縮み、お辞儀が大きくなる。`scale` を書いたポーズは揃えずにその倍率で置く。描いた絵の大きさが home と違って見えたら、頭の幅を `vm grid` で比べて `scale` を直す（例 home の頭の幅 / そのポーズの頭の幅）。
- **中割りは前の1枚から少しずつ**: config に `"inbetween_prompt": "chain"`（`vm init` は書く）。始めの姿勢だけを参照に「全体の 17% だけ動かす」編集で1枚目、それを参照に2枚目、と順に描く（両端を参照に渡すと、割合を数で言っても 1 枚目から動き切った）。
- **背の比の想定 `expect_height`**: 背の変わるポーズには想定の範囲（home=1）を書き、`vm views` が外れを知らせる。お辞儀は描かせても背の比 0.998 と浅かった（2026-10-16 の実物。中割りの方が深く下がった）ので、お辞儀の文を「30 度ほど、頭のてっぺんが背の 1 割ほど下がる」に強め、範囲 `[0.85, 0.96]` で浅いのを拾う。
- 口と目の範囲: お辞儀・屈むは顔の位置が home から大きく動くので、`vm face <作業フォルダ> bow crouch` で測るか、怪しければ `vm grid` で読んで `poses.<名前>.face` に書く。考える・片手・伸びは home からの自動の写しで足りるはず（`vm parts --check` で確かめる）。

## config.json に足すもの

新しいキャラなら `vm init <作業フォルダ> <元の絵> --desc "…" --extras a`（B も入れるなら `ab`）が下と同じものを書く。前からある作業フォルダには、下を写して足す（代名詞はキャラに合わせて her を直す）。desc を直すときは `skills/video-mascot/scripts/init.py` の `extra_presets` と両方を直す（テストが一致を確かめる）。

段階 A:

```json
"poses": {
  "think": {"desc": "facing the camera, standing on exactly the same spot as the reference, her hand on the image-right side raised so that her index finger and thumb lightly touch her chin, the other arm folded across her waist supporting that elbow, thinking calmly, calm closed mouth", "refs": ["home"]},
  "bow": {"desc": "a clear polite bow: her upper body bent forward about 30 degrees from the hips, so that the top of her head is clearly lower than in the reference (about 10 percent of her height lower), head lowered with the face still visible, hands lightly clasped in front of her waist, feet on exactly the same spot as the reference, calm closed mouth", "refs": ["home"], "scale": 1.0, "expect_height": [0.85, 0.96]},
  "raise_r": {"desc": "facing the camera, her hand on the image-right side raised to the height of her face with the index finger pointing straight up, as when saying 'here is one point', the other arm relaxed at her side, standing on exactly the same spot as the reference, calm closed mouth", "refs": ["home"]},
  "stretch": {"desc": "a light, relaxed stretch: both arms raised above her head with the hands lightly clasped, back straight, facing the camera, standing on exactly the same spot as the reference, eyes open, calm closed mouth", "refs": ["home"], "scale": 1.0, "expect_height": [1.03, 1.6]}
},
"pairs": [["home", "think"], ["home", "bow"], ["home", "raise_r"], ["home", "stretch"]]
```

段階 B:

```json
"poses": {
  "crouch": {"desc": "crouching down on exactly the same spot as the reference with both knees bent and her body lowered, facing the camera, her hand on the image-right side pointing down toward the lower right of the image, face still clearly visible, calm closed mouth", "refs": ["home"], "scale": 1.0, "expect_height": [0.5, 0.88]},
  "knee_bend": {"desc": "a slight knee bend: both knees bent a little so that her whole body is about 5 percent lower, back straight, hands lightly clasped in front of her waist, facing the camera, feet on exactly the same spot as the reference, calm closed mouth", "refs": ["home"], "scale": 1.0, "expect_height": [0.9, 0.985]}
},
"pairs": [["home", "crouch"], ["home", "knee_bend"]]
```

あわせて `"inbetween_prompt": "chain"` を config に足す（無ければ。`percent` なら `chain` に替える）。

## 描く順番と枚数（段階 A）

| 順 | コマンド | 枚数 |
|---|---|---|
| 1 | `vm poses <作業フォルダ> poses --only think` ほか（`bow` `raise_r` `stretch`） | 4 |
| 2 | 1枚ずつ Read して確かめる（同じキャラ・指・足の位置・顔が見えるか）。`vm views <作業フォルダ>` で足元と大きさ | — |
| 3 | `vm poses <作業フォルダ> inbetweens --only think` ほか（home との中割り、各 5 枚） | 20 |
| 4 | `vm poses <作業フォルダ> parts --only think` ほか（口 7・目 2、`gaze` があれば視線 3） | 4×9（視線ありで 4×12） |
| 5 | `vm face <作業フォルダ> bow --write`（怪しければ方眼）→ `vm parts <作業フォルダ>` → `--check` | — |
| 6 | `events` に足して、短い範囲で見比べを書き出す | — |

合計は段階 A で 60 枚（視線ありで 72 枚）。ChatGPT の上限で止まったら、時間をおいて同じコマンドをもう一度（描けた分は飛ばす。`skills/video-mascot/references/new-character.md` の「枚数と ChatGPT の上限」）。

## 確かめること

1. 足が動いていないか（`vm views` の立ち位置のずれ）。お辞儀・屈むで足が前後に動いていたら描き直す。
2. 指（`think` のあご、`raise_r` の人差し指）が崩れていないか。
3. お辞儀・屈むで顔が見えているか。
4. 中割り 5 枚を順に並べて、少しずつ動いているか（1 枚目で動き切っていないか）。
5. 書き出しで、伸び・お辞儀の大きさが不自然に変わっていないか（`scale` が効いているか）。

## ターン（後で）

一回転は新しい絵を描かず、向きの絵（段階 A の `turn_*`、B の `side_*`、C の `back`）を短い `turn` の溶かしで続けてつなぐ（home → turn_l → side_l → back → side_r → turn_r → home）。段階 B・C の絵が要る。今の `transition.dur` は全体で1つなので、ターンだけ短くするには切り替えごとの長さの指定が要る（必要になったら足す）。
