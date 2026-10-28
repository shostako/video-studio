# 身振りの辞書（data/gestures.yaml）

解説で使う身振りを、キャラに依らない形で1か所にまとめたもの。キャラが替わっても辞書はそのままで、作業フォルダの config に足して絵を描き直すだけで使える。
絵そのもの（キャラごと）は作業フォルダに持つ。辞書が持つのは「名前・意味・使う台詞の例・描かせる文・中割りの段階・大きさの決まり」だけ。

## 使い方

```bash
vm gestures                                     # 一覧（名前・確かめたか・どこから動くか・意味）
vm gestures <作業フォルダ> --add pinch span --print   # 足したあとの config.json を見るだけ
vm gestures <作業フォルダ> --add pinch span           # config.json に足す（元は config.json.bak）
vm gestures --check                             # 辞書の形の検査（CI でも回る）
vm gestures --roles                             # 場面の型と、その型で使う身振り（決まりは references/roles.md）
vm gestures --h3 point_r gap --pronoun she      # H3 の指示文に入れる身振りの句
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
    from: home                  # どの姿勢から動き出すか（既定 home）。中割りの組は [from, name]。身振りどうしの切り替えは config の via_home で home を経由できる
    refs: [home]                # 描く時に渡す参照の姿勢（既定 [home]）
    desc: >-                    # 描かせる英語の文。{p} は所有格、{P} はその頭を大文字に
      facing the camera, ... {p} hand on the image-right side ...
    steps: [...]                # 中割りの各枚の様子（config の ib_steps。書かなければ chain のまま）
    inbetween: true             # false なら中割りの組を足さない（指だけ変える身振り。切り替えは一瞬か transition）
    scale: 1.0                  # 背が変わる身振りの大きさの固定（任意）
    expect_height: [0.85, 0.96] # 背の比の想定（任意。vm views が外れを知らせる）
    roles: [size]               # 使う場面の型（一番上の roles の id。references/roles.md）
    h3: "raises {p} hand ..."   # H3 の指示文に入れる同じ身振りの英語の句（主語は書かず動詞から。vm gestures --h3 で代名詞を差し替えて出す）
    h3_checked: false           # その句を H3 で回して、身振りが出たか
```

- `preset: gestures|extras_a|extras_b` と書いた身振りは、描かせる文・参照・中割りの段階・大きさを `vm init` の雛形（`scripts/init.py`）から取る。ここには `desc` などを書かない（同じ文を2か所に持たない）
- 左右は「絵の左（image-left）」で書く（"viewer's left" は逆になることがあった。references/new-character.md）
- 中割りの段階は、1〜3枚目で「まだ伸ばさない・まだ組みから離れたばかり」と言い切る（両端を渡すと1枚目から動き切るため）
- キャラ固有の服・色・座標・代名詞は書かない。決め打ちの代名詞（her・his・she など）は検査で止める。服・色は検査では拾いきれないので、書く人が気をつける
- 足すときに、`from` と `refs` の姿勢が config に無ければ辞書から一緒に足す（`count_3` を足すと `raise_r` も入る）。config に既にある姿勢は書き換えない（直すなら config を手で直す。組や `ib_steps` の付け替えまで道具がやると、古い設定が残って食い違う）。絵が残っている姿勢（`poses/pose_<名前>.png`、その差分・部品・中割り。config に無い姿勢でも）と home にも書かない（`vm poses` は描けた絵を飛ばすので、文だけ変わって絵が古いままになる）。描き直すなら、先にその絵と部品・中割りを別のフォルダへ移す

## 候補の身振りについて

`count_2`・`count_3` は `raise_r`（指を1本立てる）の腕のまま指だけ変える。手首から先しか変わらないので中割りは描かない。
指の数の切り替えが多くなったら、口と同じ「差分を描かせて切り抜く」部品（手の形の部品）にするかを考える。

### 指の本数は手の部品で作る（vm hands）

全身の絵のまま「2本」「3本」を描かせると、立てた指の本数は合っても、曲げた指が1本指のときのまま残る（立てた2本＋曲げた3本で指が6本、など）。描かせる文を5通り変えても、ほぼ直らなかった（2026-10-18）。
1本指（`raise_r`）の絵から手の周りを切り出して参照にし、手だけを描かせると、立てた指と曲げた指の本数が合った。その手を `raise_r` の絵の同じ場所にはめ込めば、体は `raise_r` と同じ絵になり、指の切り替えで手以外が動かない。

```json
"hands": {
  "count_2": {"base": "raise_r", "box": [560, 520, 840, 880],
              "desc": "the hand shows the number two: the index and middle fingers point straight up, parallel and close together; the ring and little fingers are curled down into the palm (exactly TWO curled fingers), with the thumb folded across them. Count check: 2 raised + 2 curled + thumb = 5 digits."}
}
```

`vm hands <作業フォルダ> draw` → `check`（拡大した絵で、曲げた指まで数える）→ `place` → `vm parts <作業フォルダ> --borrow home count_2`。全身で描いた `pose_count_2.png` がもうある作業フォルダでは `place --force`（古い絵と、それから作った口・目の差分・部品・中割りは `reject/hands_replaced/` へ移る。付けないと置き換えずに終了コード 3）。`config.hands` に書いた姿勢は `vm poses poses` が全身の絵として描かない。
数えたあと手を下ろす・数える前に手を上げるときは、指を全部握った姿勢（グー）と home の中割りを描いて、グーを通す（1本指の中割りを通すと、一度1本に戻って見える）。

限界: 姿勢の絵（`poses/pose_<名前>.png`）を手で消してから `place` すると、古い絵から作った差分・部品・中割りは退避されずに残る（`place` は今ある絵しか見ないため）。置き換えは絵を消さずに `place --force` で行う。

