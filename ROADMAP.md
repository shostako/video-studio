# ロードマップ

PR ごとに更新する。目的は、仕事で使う解説動画・まとめ動画の品質を上げること。

1. 生成音声の品質（アクセント・イントネーション）
2. マスコットの動き・大きさ・バランス・バリエーション・滑らかさ

## クラウドのスレッドがやること（鍵・GPU・耳が要らない範囲）

上から順に1つずつ。どれも**既定の挙動は変えない**（新しい機能は `config` のオプションか新しいコマンドで足す。既定を切り替える判断は `DECISIONS.md` の「未決」に書いて止まる）。

方針（2026-10-17 ユーザーと決めた。根拠は DECISIONS.md の同じ日）: 身振りの**種類**を増やすのが先。絵は丸ごとのキーポーズを主に持ち、部品にするのは小さくて形の崩れない所（顔・頭の傾き・脚、次に手の形）だけ。

解説動画の 3 つの型（2026-11-01 ユーザーと決めた。DECISIONS.md の同じ日）を、新PC でも旧PC でも、パックのマスコットの動きを組み合わせるだけで作れるようにする。上から順に:

1. 蘭のパックを凜と同じ形にする（2026-11-01 ユーザー決定: Wan で動かす。新PC で全姿勢 ⇄ home の 52 組を作り、`vm pack ran --with-cache`。凜は済み: `~/.local/share/video-scene/packs/rin`）。そのあと 2 つのパックを旧PC へ運んで、3 つの型を 1 本ずつ作る（完成の判定）
2. README を利用者向けに書き直す（入れ方、3 つの型、パックの取り方、許諾、Veo は別料金、Irodori-TTS の倫理の制限）

## 手元待ち（クラウドでは動かない。スレッドは手を出さず、必要なら `DECISIONS.md` の「未決」に書く）

- screen-explainer の撮影の道具（`excel_capture.py`・`web_capture.py`）を、作り直す動画（cad-viewer の解説）で実際に通す。組み立ては設備メンテナンス費の動画と同じコマが出ることを確かめ済み
- 身振りの役割（`references/roles.md`）を次の台本で使ってみる: 各行に場面の型を付け、手の形と意味の対応を台本の頭に書いてから events を書く。足りない型・決まりがあれば足す。H3 で `h3_checked: false` の句（`bow`・`span`・`pinch`・`arms_crossed`・`palm_stop` など）を使ったら、出たかを辞書に書く
- パックにあって辞書に無い姿勢（`nod`・`fist_r`・`count_4`・`count_5`・`thumb_r`・左手）を辞書に入れるか。手の部品・左右反転・流用で作った物なので、描かせる文だけでは作れない

- ベンチ（専門語を詰めた60秒の台本と、決めたマスコット1体）の確定と、本物の素材の用意
- TTS エンジンの比較（Gemini TTS、Irodori、アクセントを指定できるローカル系、新しいオープン重み）
- 声の聞き比べと、アクセントの最終判定（耳）
- フレーム補間（RIFE）: `vm render` に組み込んだ（`config.interp`、opt-in）。射出成形の解説動画の作り直し（作業フォルダ `icm-v2`）で、合掌の切り替えを 1.2 秒にした書き出しを見て、既定にするかを決める。切り絵リグはそのあと
- `vm overlay --preset` の数値（大きさの割合・安全領域 0.05）と、登場・退場の速さ・動き方が実物の動画で見て良いか（見た目の判定）
- `vs accent` の点数が本物の声で耳の判定と合うか（`--thresh` 1.5 半音は仮の値。Gemini TTS の声で「薄い板」の良い版・崩れた版を測って比べる）
- 作った機能を既定にするかの判断
- マスコットの向き・顔・視線の絵（`docs/mascot-views-spec.md` の段階 A）を `/img` で描き、揃い（足元・背の高さ・向きの取り違え）を確かめる。別の作業フォルダ `<名前>-views` で
- 新しいキャラ（別の絵）で `references/new-character.md` を通して試す。`vm init` の雛形・`vm face` の測った範囲・`anchor.mode: feet` が実物の絵で合うか
- 足すポーズ（`docs/mascot-poses-spec.md` の段階 A: 考える・お辞儀・片手を挙げる・伸び）を `/img` で描き、足が動いていないか・顔が見えるか・中割りが少しずつ動くか・`scale` 固定で大きさが自然かを見る。良ければ段階 B（屈む・軽い屈伸）
- 向きの切り替えと視線の見た目（`transition` の `fade`/`turn` と長さ・縮み、`gaze.lead`、回転の中割りが要るか、段階 B・C を作るか）。手順は `docs/mascot-views-spec.md` の「描く順番」5・6

- パック化（公開の準備の手元分）: 凜（`cand04-howto`）をパックにする。全姿勢 ⇄ home の Wan の切り替え（48 本、新PC で約 3 時間）を作り置き、A→B の逆再生が B→A に使えるかを確かめる。`reject/`・`out/`・`voice/`・config の控えを外して 1 ファイルずつ確かめ、GitHub Releases に zip で付ける。蘭も同じ
- 完成の判定: 旧PC で、3 つの型を 1 本ずつ、パックだけで作る（研究フォルダ・Wan・画像生成に頼らない）。「Claude Code デスクトップの使い方」の凜での作り直しをその 1 本にする

- 姿勢の切り替えを Wan で動かす（`interp.engine: "wan"`）を、実際の作業フォルダで `vm render` から通す（新PC。これまでは research の `render_wan.py` で作った）。止めて話す所・切り替え・口の重ね・足元が、research 版と同じに出るか。旧PC の「Claude Code デスクトップの使い方」のマスコット部分の作り直しで使う

## 済んだこと

- 公開物から元の呼び名を外し蘭に（2026-11-01、#63）: 例の台本・説明書・ROADMAP。蘭も Wan に揃える決定を DECISIONS に

- スキルの入口を 2 段に（2026-11-01）: video-mascot の SKILL.md を「動画作り（ふだん。パックから）」と「キャラ作り（新PC。姿勢・部品・切り替えの作り置き・パック）」に分け、description を 3 つの型・パック・基準キャラに合わせた

- 手元の PC だけの決め打ちを外す（2026-11-01、#62）: RIFE の exe・一時フォルダ・ComfyUI の場所を環境変数（VM_RIFE_EXE・VM_RIFE_TMP・VM_COMFY_ROOT・VM_WIN_HOME）で、Windows のユーザーのフォルダは cmd.exe で調べる（CP932 も読む）。voice.py は VIDEO_SCENE_HOME、video-scene の出力先も同じ調べ方

- 入口のコマンド `vm explain`（2026-11-01）: 型（cursor・wipe・full）を選ぶと、screen-explainer の組み立て → マスコットの下見・書き出し → 余白に置く → 身振りの測定まで回す。screen-explainer の組み立ては声が絵より短くても落ちない（apad）
- 凜のパック（2026-11-01）: `vm pack rin --from b-cad --with-cache`（396MB）。Wan も RIFE も呼べない条件で cad を最後まで書き出し、63 件全部動いた

- パックに作り置きを入れる（2026-11-01）: `vm pack --with-cache`（使える組だけを WebP で、元のコマは外し raw_stamp は残し、`.readonly`）、`vm pack --new` は作り置きをパックへのリンクに（`--own-cache` で写す）。頭の動きの予定（head.events）はパックに持ってこない

- パックの作り置きを読む側（2026-11-01）: 列を WebP のまま読む、Wan の元のコマが無くても仕上がった列と raw_stamp.json で使う、`.readonly` の置き場は作り直さずに止める、下見で「Wan で作る組」と「RIFE で作る列（Wan の後処理を含む）」を分けて出す

- 作り置きの判定を中身の印に（2026-11-01）: Wan・RIFE の列の stamp を更新時刻でなく md5 で比べ、写した作業フォルダ・パックでも作り直さない。前の形の stamp は合えば書き換える（パックの作り直しの前提）

- ワイプの型（2026-11-01）: `vm layout --style wipe`（顔の周りを丸く切り抜いて余白の左下、橙と白の縁と影）と、顔用に身振りを止めて書き出す `vm render --no-events`（`--no-head` で頭の向きも）

- 画面を縮めて右に寄せる割り付け（2026-11-01）: screen-explainer の `compose.py --layout margin --scale`（字幕は画面の下、`<出力>.layout.json`）と章の見出し `--chapters`（カーソルだけの型は替わり目に左上へ数秒、余白ありの型は余白の左上に出し続け、長い見出しは 2 行に折る）。見出しの JSON は video-mascot の `chapters.py` で `vm layout` と共通

- 画面を縮めた解説の余白にマスコットを置く `vm layout`（2026-11-01）: 研究用の compose_layout.py を移し、左上の章の見出し（番号・見出し・下線）とサンプルの出どころの表示（`--chapters`）を足した。元の cad-viewer の解説（蘭の版）と同じ見た目

- 書き出しの検査と口パクの直し（2026-10-31〜11-01）: 頭の動きの間の身振り消え（#48）、切り替えの下見・表・画素での測定 `vm check`（#49）、口の部品の無い姿勢で話す所の検査（#50）、長い動画の終わりで口が声より先に動くずれ（#51、`SR // FPS` の切り捨て）

- 姿勢の切り替えを Wan2.2 の First-Last-Frame で動かす（2026-10-31）: `interp.engine: "wan"`（opt-in）と `legs_lock.fix_x`。調べた中身・見本の作り方は `research/2026-10-31-wan-transition/`

- 画面操作の解説動画のスキル screen-explainer（2026-10-29）: Excel 2 本と Web アプリ 1 本を作った道具を汎用にした。撮影（Excel・Web）、ワイプの顔、語ごとの長さ、組み立て。場面の割り付けは外の `scenes.py` に書く

- 身振りの役割の体系化（2026-10-29）: 場面の型 11 種を辞書の `roles` に、使い方の決まり（意味の固定・量・時刻・つなぎ・目・H3 での書き方）を `references/roles.md` に。身振りごとに H3 の句（`h3`）を持たせ、`vm gestures --roles` と `--h3` を足した。候補5つを確かめ済みにした
- home 経由の切り替えの見た目: 2本目（仕組み）の v9 の確定で使った（2026-10-18）

- 蘭（基準キャラ A）のマスコットパック（2026-10-19、各PC のローカル `~/.local/share/video-scene/packs/monday-suit`）: 射出成形の `icm-v3` と仕組みの `mascot-howto-v2` を `vm pack` でまとめ、左手を `vm mirror` で作り、中割り2組（open>gassho・gassho>gap）を描き足した。point>raise_r・raise_r>think は via_home で home を通すので組から外した。足りない絵は無い。旧PC には無い（新PC で作った）

- 口パクの方式と二次運動の見比べ（2026-10-19、ユーザーの判定）: 口はモーラ式、首の傾き・うなずきは採用、呼吸・体の揺れ・切り替えの予備動作は不採用。Monday のパックの config に入れた。既定は変えていない（DECISIONS.md の同じ日）

- `vm pack` を足した（opt-in）。作業フォルダの姿勢・部品・中割り・手の部品を1つのパックにまとめ（後の `--from` が勝つ）、`--new` でパックから新しい作業フォルダを作る。中割りは端の絵がパックと同じ作業フォルダからだけ持ってくる（逆向きの組も同じ組）。台本・声・動き・視線の予定は持ってこない。テストは `tests/test_mascot_pack.py`（2026-10-19）

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
- 新PCで #18 を確かめた結果を直した: 中割りの各枚の様子 `ib_steps`（turn→present の腕の段階）、お辞儀の雛形を強め、背の比の想定 `expect_height` を `vm views` が見る（どれも opt-in、2026-10-16）
- 絵を ChatGPT の通常 Chat 画面（専用プロファイルの Chrome を Playwright で操作）で描く道具を足した（opt-in、`vm poses --img chat|chat+codex` か `config.img`）。`chat+codex` は Chat の上限かログイン切れで残りを `/img` に切り替える。中身は `skills/video-mascot/scripts/chatimg/`（`chatimg.sh` は img.sh と同じ引数・終了コード）、手順は `references/chatgpt-chat.md`。新PCで、参照画像つきの1枚通し・Chrome を閉じた後の最小化での再実行・WSL からの呼び出しを確かめた。既定は `/img` のまま（2026-10-16）
- Chat と Codex を蘭で見比べた（向き6枚・turn→present の中割り5枚・home→raise_r の12等分の途中まで）。Chat は斜めの姿勢と中割りで頭身が伸びて体格が崩れ、既存のキャラを保つのに向かない。ユーザーの判定で、キャラを保つ描き足しは Codex、Chat は一発出し・キャラ選びに使う（2026-10-16）
- 新PCの手組み版（手を前で組んだ home から全姿勢と中割りを描き直した作業フォルダ）で #20・#21 を確かめた。turn→present の中割りは `ib_steps` で腕が段階を追った（1枚目で手はもう組みから離れる）。お辞儀は #21 の強い文で背の比 0.958 と範囲に入った。chain だけで崩れた指し示し・お辞儀・伸びの中割りに `ib_steps` を足して描き直し、同じ文を `vm init` の雛形にした（`--gestures` の `home>point_l/r`、`--extras a` の `home>bow`・`home>stretch`。お辞儀は 4〜20 度の浅い刻み）。全18姿勢を一通り回す白背景の書き出しはマイドライブ `動画見比べ_20261016/手組み_v1`・`手組み_v2`（2026-10-16）
- 正面の姿勢と中割りの腰から下を1つの姿勢の下半身に差し替える `legs_lock` を足した（opt-in）。手組み版は home・bow・head_l/r と他の正面8姿勢で脚の開きが2組に分かれていて、切り替えのたびに足元が動いていた。帯の中は腰の輪郭を行ごとに伸び縮みさせてから混ぜ、元の絵の手は残す。手組み版の 0〜30 秒で足首の左右の端のコマ間の跳び（3px 超）が 19 回から 5 回（残りは斜めの姿勢）に。見比べはマイドライブ `動画見比べ_20261016/下半身_v1`（2026-10-17）
- 中割りのコマ補間を `vm render` に組み込んだ（opt-in、`config.interp` か `--interp rife`）。描いた絵の間を RIFE（rife-ncnn-vulkan）で 8 倍に細かくし、中割りのある切り替えを `dur`（既定 0.6 秒、組ごとは `durs`）と ease-in-out で出す。列は `ib_interp/` にためる。純関数（`interp_config`・`interp_dur`・`dense_ks`、`plan_at` の `ib_dur`）を `tests/test_mascot_interp.py` でテスト。付けない時の書き出しは前とコマ単位で一致（2026-10-17）
- `interp.direct`（opt-in）: 中割りの無い組も端の姿勢2枚の間で直に補間する（向きの同じ組だけ）。手が大きく動く組ではにじむので、中割りを描くまでのつなぎ（2026-10-17）
- 身振りの辞書 `skills/video-mascot/data/gestures.yaml` と `vm gestures` を足した（opt-in）。名前・意味・使う台詞の例・描かせる文・中割りの段階を1か所に持ち、`--add` で作業フォルダの config に足す。`vm init` の雛形にある9つは文を雛形から取り（同じ文になることをテストで確かめる）、候補8つ（`count_2`・`count_3`・`pinch`・`span`・`gap`・`gassho`・`arms_crossed`・`palm_stop`）は実物で未確認。書き方は `references/gestures.md`、テストは `tests/test_mascot_gestures.py`（2026-10-17）
- home 経由の切り替えを足した（opt-in、`config.via_home`）。中割りの無い組 A→B を、A→home と home→B の中割りでつなぐ（`hold` で home にとどまる秒）。両方の端に home との組がある時だけで、`transition`・`interp.direct` より先、`events[].via` より後に効く。`kw`・`word` は語の直前に B に着くように早く始める。純関数（`via_home_config`・`home_route`、分けるのは `resolve_events` の `route`）と合成のマスコットの書き出しを `tests/test_mascot_via_home.py` でテスト。付けない時の書き出しは前とコマ単位で一致（2026-10-17）
