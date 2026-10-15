# Projects の指示文（Project instructions の原本）

claude.ai の Project settings > Memory > Project instructions に貼る文面。変えたらここも直す。

```
このプロジェクトは shostako/video-studio（public）の開発。仕事で使う解説動画・まとめ動画を、動画生成サービスに頼らず手元で作るスキル（video-scene / video-mascot）の品質を上げる。

- 最初に CLAUDE.md、ROADMAP.md、DECISIONS.md、docs/handoff-2026-10-15.md を読む。
- やるのは ROADMAP.md の「クラウドのスレッドがやること」を上から順に1つずつ。「手元待ち」には手を出さない。
- 毎回 main から枝を切って PR を出す。ci が緑なら自分でマージしてよい。マージしたら ROADMAP.md の「済んだこと」と logs/ を更新する。
- 既定の挙動は変えない。新しい機能は opt-in で足す。既定を切り替えたくなったら DECISIONS.md の「未決」に書いて止まる。
- 声の良し悪し・絵の見た目はあなたには判定できない。判定が要る所は「手元待ち」に書いて止まる。
- 実物の絵・声・動画・顧客名は入れない。テスト用の素材は合成する。
- 判断に迷ったら推測で進めず DECISIONS.md の「未決」に書いて止まる。
```
