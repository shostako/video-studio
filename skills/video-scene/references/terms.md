# 用語辞書（`data/terms.yaml`）と `vs terms`

専門語の**読み**と**アクセント**を1か所に置く辞書。場所は `skills/video-scene/data/terms.yaml`（スキルと一緒に動く）。

- **誤読・アクセント崩れが実際に見つかった語だけ**を人が足す。推測では書かない。空で始める
- 足したら `vs terms` で形を検査する。崩れていれば「何語目の何が悪いか」を出して終了コード 1
- 今は形と検査だけ。台本・TTS・`vs accent` へ自動で当てはめる処理はまだ無い

## 書き方

```yaml
terms:
  - word: 型締力            # 台本に出てくる表記（必須）
    reading: かたじめりょく  # ひらがな・カタカナ・ー だけ（必須）
    accent: LHHHHL          # 期待する高低の列（references/accent.md の書き方。低高 でも可）
    note: Veo が「かせんりょく」と読んだ   # 任意
  - word: キャビティ
    reading: きゃびてぃ
    type: 1                 # accent の代わりにアクセント型の数字（0＝平板、1＝頭高、k＝k モーラ目の後で下がる）
```
（上の語と型は書き方の例。辞書の中身ではない）

決まり:
- `accent` か `type` のどちらかは必須。両方書くなら一致させる。尾高は `type` で書く（列だけだと平板と同じ `LH…H` になり、型の数字は 0 として読む）
- `accent` の長さ＝読みのモーラ数（「きゃ」で1、「っ」「ん」「ー」も1）。語の中だけを書き、助詞は入れない
- `accent` は東京式の型になる列だけ通す（1モーラ目と2モーラ目は高さが違い、高いのは1か所のまとまり）。`LL`・`HH`・`LHLH` は書き間違いとして止める
- 同じ `word` は1回だけ。読みが文脈で割れる語（市場＝いちば／しじょう）は、どちらを載せるか人が決める
- 使えるキーは `word`・`reading`・`accent`・`type`・`note`。他のキーと、1語の中で同じキーを2回書くのは書き間違いとして止める
- 英字や数字だけの語（`ON`、`3D` など）は引用符で囲む（YAML は `on` を真偽値、`123` を数にする）

## Python から

```python
from terms import load_terms, as_dict
ts = load_terms()            # [Term(word, reading, accent="LHHHHL", type=5, morae=6, note), ...]
d = as_dict(ts)              # word → Term
```
