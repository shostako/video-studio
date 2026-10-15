# 実例: 射出圧縮成形の解説（Monday フィギュア、69秒）

- `config.json`: 今回の設定そのまま（姿勢6、pairs 6、events 11、声9行）。台詞は voice.lines.text。
- 主動画は、Three.js で作った金型の3D（白い背景）。`render --mode white` の出力を乗算で重ねた（HyperFrames の compose で、右に3D、左にマスコット）。
  別の主動画に重ねるなら `vm render --mode alpha` → `vm overlay`。
- 作業フォルダの標準配置: poses/ parts/ ib/ voice/ の中身は /img と Irodori が作る。ここには入れていない（大きいので）。
