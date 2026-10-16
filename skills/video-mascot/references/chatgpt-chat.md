# ChatGPT の通常 Chat 画面で絵を描く（`vm poses --img chat`）

`/img` は Codex の枠（Codex の作業・燕と共有）を使う。枠が尽きたときや、Codex の作業に枠を残したいときに、ChatGPT の通常 Chat 画面（ブラウザ）で描く道具を opt-in で選べる。既定は今まで通り `/img`。

**規約上グレーな使い方なので、自分の作業用に低頻度で使う。** 大量の連続生成や他人の分には使わない。

## 何をしているか

- 専用プロファイルの Chrome（普段使いの Chrome とは別）を起動し、Playwright を CDP でつなぐ。ログインは人が一度手でして、そのプロファイルを次からも使う。
- 新しいチャットを開き、参照画像を添付し、指示文を入れて送る。返ってきた生成画像（`alt` が「生成画像」/ Generated image）が落ち着いたら、ページの中から取り出して保存する。
- 画面に上限の文言（「上限に達」「you've hit/reached … limit」など）が出たら終了コード 4 で止まる。
- 中身は `skills/video-mascot/scripts/chatimg/`。`chatimg.sh` は `/img`（img.sh）と同じ引数（`-p` `-r` `-o`）と終了コード（0 成功 / 2 引数 / 3 ログイン切れ / 4 上限 / 5 タイムアウト）。

## 準備（機体ごとに初回だけ）

Windows に Chrome と node が要る（WSL から呼ぶと Windows 側の `node.exe` と Chrome を使う。ログインしたプロファイルが Windows 側にあるため）。

```bash
cd ~/.claude/skills/video-mascot/scripts/chatimg && npm install    # playwright-core だけ（ブラウザは落とさない）
node.exe "$(wslpath -w login.mjs)"                                  # 専用 Chrome が開く。chatgpt.com に手でログイン（2段階認証も）
```

- プロファイルは `%LOCALAPPDATA%\video-studio\chatgpt-chat-profile`（`CHATGPT_CHAT_PROFILE` で変えられる）。CDP のポートは 9333（`CHATGPT_CHAT_PORT`）。
- ログインは1回でよい。Chrome を閉じても、次に描くときに最小化で起動してログインしたまま描ける（新PCで確かめた）。ログインが切れると終了コード 3。`login.mjs` をやり直す。
- 専用 Chrome だけを閉じるのは `node.exe "$(wslpath -w close.mjs)"`（普段使いの Chrome には触らない）。

## 使い方

```bash
vm poses <作業フォルダ> parts --img chat         # Chat だけで描く。上限で止まる（終了コード 4）
vm poses <作業フォルダ> parts --img chat+codex   # Chat で描き、上限かログイン切れで止まったら残りを /img で描く
```

- config に `"img": "chat+codex"` と書いても同じ（`--img` が優先）。書かなければ `/img`。
- Chat は画面が1つなので1枚ずつ描く（`-j` は効かない。`chat+codex` で `/img` に切り替えた後は `-j` の並列に戻る）。1枚 45 秒〜1 分ほど。
- 1枚だけ描くなら `chatimg.sh -p "…" -r ref.png -o out.png`。
- 描けたかの良し悪し（指示が通ったか、絵柄・体格・位置が揃うか）は、Codex で描いた物と並べて人が見る。

## つまずき

- 画面の作りが変わると、入力欄・送信ボタン・生成画像を見つけられなくなる。`generate.mjs` の選び方（`form [contenteditable][role=textbox]`、`aria-label="送信"`、`img[alt*=生成画像]`）を今の画面に合わせて直す。
- タイムアウトした会話の絵は、その会話を開いたまま `node.exe generate.mjs --grab-only --out x.png` で回収できる（枠を使わない）。
