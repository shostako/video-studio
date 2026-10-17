# 身振りの辞書（data/gestures.yaml）

解説で使う身振りを、キャラに依らない形で1か所にまとめたもの。キャラが替わっても辞書はそのままで、作業フォルダの config に足して絵を描き直すだけで使える。
絵そのもの（キャラごと）は作業フォルダに持つ。辞書が持つのは「名前・意味・使う台詞の例・描かせる文・中割りの段階・大きさの決まり」だけ。

## 使い方

```bash
vm gestures                                     # 一覧（名前・確かめたか・どこから動くか・意味）
vm gestures <作業フォルダ> --add pinch span --print   # 足したあとの config.json を見るだけ
vm gestures <作業フォルダ> --add pinch span           # config.json に足す（元は config.json.bak）
vm gestures --check                             # 辞書の形の検査（CI でも回る）
```

足したら、いつもの順に描く: `vm poses <作業フォルダ> poses --dry-run` → `poses` → `inbetweens` → `parts`。
`checked: false` の身振りは、その文で実物を描いて見たことがない。描いたら1枚ずつ見る（左右・指の本数・足元・顔が隠れていないか）。

## 書き方

```yaml
gestures:
  - name: pinch                 # 姿勢の名前（英数字と _）。config の poses.<name> になる
    meaning: とても薄い・わずか   # 意味（台本で身振りを選ぶ時に読む）
    lines: ["厚みは0.3ミリ"]     # 使う台詞の例
    checked: false              # この文で実物を描いて確かめたか
    from: home                  # どの姿勢から動き出すか（既定 home）。中割りの組は [from, name]
    refs: [home]                # 描く時に渡す参照の姿勢（既定 [home]）
    desc: >-                    # 描かせる英語の文。{p} は所有格、{P} はその頭を大文字に
      facing the camera, ... {p} hand on the image-right side ...
    steps: [...]                # 中割りの各枚の様子（config の ib_steps。書かなければ chain のまま）
    inbetween: true             # false なら中割りの組を足さない（指だけ変える身振り。切り替えは一瞬か transition）
    scale: 1.0                  # 背が変わる身振りの大きさの固定（任意）
    expect_height: [0.85, 0.96] # 背の比の想定（任意。vm views が外れを知らせる）
```

- `preset: gestures|extras_a|extras_b` と書いた身振りは、描かせる文・参照・中割りの段階・大きさを `vm init` の雛形（`scripts/init.py`）から取る。ここには `desc` などを書かない（同じ文を2か所に持たない）
- 左右は「絵の左（image-left）」で書く（"viewer's left" は逆になることがあった。references/new-character.md）
- 中割りの段階は、1〜3枚目で「まだ伸ばさない・まだ組みから離れたばかり」と言い切る（両端を渡すと1枚目から動き切るため）
- キャラ固有の服・色・座標・代名詞は書かない（検査で止める）
- 足すときに、`from` と `refs` の姿勢が config に無ければ辞書から一緒に足す（`count_3` を足すと `raise_r` も入る）。config に既にある姿勢は `--force` が無ければ書き換えない。`--force` でも、絵が描けている姿勢（`poses/pose_<名前>.png` がある）と home は書き換えない（`vm poses` は描けた絵を飛ばすので、文だけ変わって絵が古いままになる）。描き直すなら、先にその絵と部品・中割りを別のフォルダへ移す

## 候補の身振りについて

`count_2`・`count_3` は `raise_r`（指を1本立てる）の腕のまま指だけ変える。手首から先しか変わらないので中割りは描かない。
指の数の切り替えが多くなったら、口と同じ「差分を描かせて切り抜く」部品（手の形の部品）にするかを考える。
