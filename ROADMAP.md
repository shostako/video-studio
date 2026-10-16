# ロードマップ

PR ごとに更新する。目的は、仕事で使う解説動画・まとめ動画の品質を上げること。

1. 生成音声の品質（アクセント・イントネーション）
2. マスコットの動き・大きさ・バランス・バリエーション・滑らかさ

## クラウドのスレッドがやること（鍵・GPU・耳が要らない範囲）

上から順に1つずつ。どれも**既定の挙動は変えない**（新しい機能は `config` のオプションか新しいコマンドで足す。既定を切り替える判断は `DECISIONS.md` の「未決」に書いて止まる）。

（今は無い。次の項目はユーザーかコーディネーターが足す）

## 手元待ち（クラウドでは動かない。スレッドは手を出さず、必要なら `DECISIONS.md` の「未決」に書く）

- ベンチ（専門語を詰めた60秒の台本と、決めたマスコット1体）の確定と、本物の素材の用意
- TTS エンジンの比較（Gemini TTS、Irodori、アクセントを指定できるローカル系、新しいオープン重み）
- 声の聞き比べと、アクセントの最終判定（耳）
- マスコットパック（姿勢・表情・部品を1回だけ作って使い回す）の作成: /img（ChatGPT の枠）を使う
- フレーム補間（RIFE）と切り絵リグの比較: 見た目の判定が要る
- 口パク `mora` と `amp` の見比べ（同じ作業フォルダで `vm render --lipsync mora` と既定を書き出して並べる）
- `vm overlay --preset` の数値（大きさの割合・安全領域 0.05）と、登場・退場の速さ・動き方が実物の動画で見て良いか（見た目の判定）
- `vs accent` の点数が本物の声で耳の判定と合うか（`--thresh` 1.5 半音は仮の値。Gemini TTS の声で「薄い板」の良い版・崩れた版を測って比べる）
- 二次運動（`--motion on`）と今までの動きの見比べ。首の傾き・うなずき・予備動作の大きさが実物の絵で自然か（`vm render <作業フォルダ> --motion on --mode white --from 0 --to 20` と既定を並べる）
- 作った機能を既定にするかの判断
- マスコットの向き・顔・視線の絵（`docs/mascot-views-spec.md` の段階 A）を `/img` で描き、揃い（足元・背の高さ・向きの取り違え）を確かめる。別の作業フォルダ `<名前>-views` で
- 新しいキャラ（別の絵）で `references/new-character.md` を通して試す。`vm init` の雛形・`vm face` の測った範囲・`anchor.mode: feet` が実物の絵で合うか
- 足すポーズ（`docs/mascot-poses-spec.md` の段階 A: 考える・お辞儀・片手を挙げる・伸び）を `/img` で描き、足が動いていないか・顔が見えるか・中割りが少しずつ動くか・`scale` 固定で大きさが自然かを見る。良ければ段階 B（屈む・軽い屈伸）
- 向きの切り替えと視線の見た目（`transition` の `fade`/`turn` と長さ・縮み、`gaze.lead`、回転の中割りが要るか、段階 B・C を作るか）。手順は `docs/mascot-views-spec.md` の「描く順番」5・6

## 済んだこと

- リポを立てた。スキル2本を取り込み、`~/.claude/skills` から symlink で指す（2026-10-15）
- `render.py` の中にあった純関数（母音の時刻列、`events` の時刻の解決、口の形の選び方と平滑化、時間割）を `lib.py` に移し、`tests/test_mascot_lib.py` でテストを付けた。挙動は変えていない（旧コードと乱数入力 400 通りで一致を確認）（2026-10-15）
- 口パクをモーラ位置ベースにできるようにした（opt-in、`config.lipsync: "mora"` か `vm render --lipsync mora`）。行のかな台本を行の声の範囲にモーラの数で割り付け、両唇音・「っ」・句読点で口を閉じる。純関数（`kana_morae`・`mora_track`・`voiced_span`・`mora_frames`・`mora_mouth`）を `lib.py` に足し、`tests/test_mascot_mora.py` でテスト。既定（`amp`）は変えていない。見た目の良し悪しは手元で確かめる（2026-10-15）
- `vm overlay` に置き方のプリセット（`--preset left|right|center|corner-left|corner-right`、安全領域 `--safe`）と登場・退場（`--enter` / `--exit` の `fade`・`slide`、`--move-dur`、`--ease`）を opt-in で足した。計算は `placement.py` の純関数で `tests/test_mascot_placement.py` にテスト（合成の主動画とマスコットを実際に重ねて位置を画素で確かめるものを含む）。付けないときの書き出しは変える前と同じ（合成の素材 7 通りで、デコードした映像と音の MD5 が一致）（2026-10-15）
- アクセント計測器の F0 部分を足した（新しいコマンド `vs accent`、`skills/video-scene/scripts/accent.py`）。parselmouth で F0 を取り、語の時刻をモーラ数で割って各モーラの高さ（半音）を出し、期待する高低の列（`LHHHL`、1モーラ1文字）と隣どうしの上がり下がりを比べて `score`、下がり目の位置を比べて `drop_ok` を出す。無声化したモーラは飛ばす。書き方は `skills/video-scene/references/accent.md`（用語辞書もこれに揃える）。ピッチ列を指定した合成音で `tests/test_accent.py` にテスト。本物の声での確かめは手元待ち（2026-10-15）
- 用語辞書の形を決めた。`skills/video-scene/data/terms.yaml`（語・読み・アクセントの列か型の数字・メモ。中身は空）と、読み込み・検査の `terms.py`（新しいコマンド `vs terms`）。読みのモーラ数と列の長さ、東京式の型になるか、accent と type の食い違い、同じ語の重複、知らないキーを止める。書き方は `skills/video-scene/references/terms.md`。テストは `tests/test_terms.py`。台本や `vs accent` への当てはめはまだ無い（2026-10-15）
- 二次運動を足した（opt-in、`config.motion` か `vm render --motion on`）。呼吸の周期のゆらぎと吸う・吐くの非対称、体の揺れ、首から上だけの傾きと声の出だしのうなずき、まばたきの間隔のゆらぎ（2回続け・切り替えの頭）、姿勢の切り替えのイージング・予備動作・オーバーシュート。純関数を `lib.py` に足し `tests/test_mascot_motion.py` でテスト。`tests/fixtures/synth_mascot.py`（PIL で描いた合成の人型）で書き出しのスモーク（`tests/test_mascot_render_smoke.py`）。既定の出力は前とコマ単位で一致を確認。見た目の良し悪しは手元で確かめる（2026-10-15）
- マスコットの向き・顔・視線の絵の仕様を書いた（`docs/mascot-views-spec.md`）。段階 A（`head_l/r`・`turn_l/r`・`present_l/r`）、B（`side_l/r`）、C（`back`・`lean_in`）、足元・背の高さ・首の位置の揃え方、視線の部品、描く順番（2026-10-15）
- 向き・視線の描画を足した（opt-in）。`poses.<名前>.yaw`・`head_yaw`・`face`（姿勢ごとの口と目の範囲、`false` は顔なし）・`anchor`、`transition`（中割りの無い切り替えを `fade`/`turn` でつなぐ）、`events[].via`、`gaze`（視線の部品 `g_l` `g_r` `g_u` `g_c` と台本からの指定、顔の向きが変わる前に目が先に動く）。`vm poses parts` は `gaze` がある時だけ視線の部品も描く。テストは `tests/test_mascot_views.py`（合成の斜め・後ろ向きの人型）。既定の書き出しは前とコマ単位で一致（2026-10-15）
- 新PCで描いた段階 A の6枚の結果（左右の取り違え・黒目・present の回りの浅さ・足元と立ち位置のずれ）を仕様の desc と実測の表に入れた。立ち位置を揃える `anchor` の候補を出す `vm views` と、/img の codex・node が Windows 側を指すのを見つける `setup.sh` の検査を足した（2026-10-15）
- キャラが替わっても同じ手順で立ち上がるようにした。`vm init`（絵1枚と英語の説明から作業フォルダと config の雛形。向き・視線の姿勢の desc は代名詞を差し替えて書く。黒い靴が無ければ足元を `feet` で揃える）、`vm face`（描いた口・目の差分から範囲を測る）、`anchor.mode: feet`（色に依らない足元）、`mascot.pronoun`、手順書 `skills/video-mascot/references/new-character.md`（新PCで分かった描かせ方の注意を含む）（2026-10-16）
- 新PCで実物を回した結果を直した（2026-10-16）。`vm views` と `vm render`（boot）が、靴でない所（紺のズボンの裾）を軸足に拾った姿勢を知らせ `feet` を勧める（`vm views` の足元・背は色に依らずに測る）。`vm face` は目を頭の辺りの高さの揃った2つの塊から、口を目の下の目の幅の中から探し、怪しい範囲は書かない。中割りの言い方に `inbetween_prompt: "percent"`（opt-in、`vm init` は書く）。手順書に枚数・上限・再開。setup の /img を1行に
- 足すポーズの仕様を書いた（`docs/mascot-poses-spec.md`、2026-10-16）。段階 A（`think`・`bow`・`raise_r`・`stretch`）、B（`crouch`・`knee_bend`）、ターンは向きの絵をつなぐ形で後回し。`vm init --extras a|ab` が雛形を書く。背が変わるポーズの大きさを固定する `poses.<名前>.scale`（opt-in）
- 新しいキャラの基本の立ち姿を「両手を前で軽く組む」にした（手順書の元の絵の決まり、`vm init --redraw-home`、2026-10-16）
