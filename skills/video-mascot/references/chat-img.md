# Chat 画面で描く（`vm poses --img chat`、opt-in）

既定の `/img` は ChatGPT Plus の **Codex の枠**で描く。`--img chat` は、同じ ChatGPT の**通常の Chat 画面**（chatgpt.com）に描かせる。Windows 側の Chrome を Playwright で動かす。Chat が上限を返したら、残りの枚は自動で `/img`（Codex）で描く（二段構え）。

## 分かっていること（2026-10-16、旧PC で実測）

- Chat 画面のサイドバーに出る「使用可能量（5時間・1週間）」は **Codex/Work の枠**。Chat で画像を2枚描いても 1% / 69% から動かなかった
- Codex の枠を使い切った（`codex exec` が「You've hit your usage limit」を返した）後でも、Chat の画像生成（参照画像の編集）は通った（1枚 40〜65 秒）
- Chat 側の画像生成の上限には、まだ当たっていない。上限の文言は推測で `chat_img.py` の `LIMIT_RE` に書いてある。当たったら、画面と本文が `~/.local/share/video-scene/chat-img-evidence/`（Windows 側）に残るので、それを見て `LIMIT_RE` を直す
- 出てくる絵の大きさは 941×1672（縦長を頼んだ時）。Codex の `/img` と大きさが違うことがあるので、**1つの作業フォルダの中で経路を混ぜると、向きの違う姿勢の大きさの検査（`vm render`）で止まることがある**。その時は同じ経路で描き直すか、大きさを揃える
- Chat は1つのプロファイルを1枚ずつ使う（同じプロファイルの Chrome は同時に1つしか開けない）。`-j 4` でも Chat の枚は順番待ちになる。Codex に切り替わった後は並列に戻る

## 準備（機体ごとに初回だけ。Windows 側）

1. 専用の venv（Hermes など既存の Python は汚さない）
   ```powershell
   uv venv --python 3.12 $HOME\.local\share\video-scene\chatimg-venv
   uv pip install --python $HOME\.local\share\video-scene\chatimg-venv\Scripts\python.exe playwright pillow
   ```
   Chrome は普段の `C:\Program Files\Google\Chrome\Application\chrome.exe` を使う（Playwright の Chromium は落とさなくてよい）。別の場所なら環境変数 `CHAT_IMG_CHROME`
2. ログイン（**人が手で**。2段階認証・パスキーがあるので自動にしない）
   ```powershell
   $PY = "$HOME\.local\share\video-scene\chatimg-venv\Scripts\python.exe"
   & $PY <リポ>\skills\video-mascot\scripts\chat_img.py login
   ```
   専用プロファイル（`~\.local\share\video-scene\chatgpt-profile`）の Chrome が開く。ログインが済んだらウィンドウを閉じる。ログインは Playwright を通さない素の Chrome で開く（自動操作の印が付いた Chrome だと、外部アカウントでのログインが弾かれることがある）
3. 確かめる: `& $PY chat_img.py probe` で、入力欄・添付欄などのセレクタが今の画面で見つかるかが数で出る（0 の行があれば UI が変わった）
4. WSL 側に、Windows の python.exe の場所を教える（`~/.bashrc` など）
   ```bash
   export VM_CHAT_IMG_PY=/mnt/c/Users/<Windowsの名前>/.local/share/video-scene/chatimg-venv/Scripts/python.exe
   ```
   `setup.sh --check` の「Chat で描く」の行で確かめられる

## 使い方

```bash
vm poses <作業フォルダ> parts --img chat     # 環境変数 VM_IMG=chat でもよい
# 1枚だけ: skills/video-mascot/scripts/img_chat.sh -p "…" -r 参照.png -o 出力.png   （img.sh と同じ使い方・終了コード）
```

終了コード（`img.sh` と同じ）: 0 成功 / 2 道具が無い / 3 ログインしていない（`login` をやり直す）/ 4 上限 / 5 タイムアウト / 6 画像が出ない（断られた）。

## 中で何をしているか

1. ロックを取って、専用プロファイルで Chrome を開き chatgpt.com へ（新しいチャット。会話は履歴に残る）
2. 参照画像を添付欄（`input[type=file]`）に入れ、「画像生成ツールで画像を1枚だけ作って」＋プロンプトを入れて送る
3. 送る前に見えていた大きい画像（512px 以上）と比べて、新しく出た画像を待つ。添付した参照は alt（「添付」）で除く。「停止」ボタンが消え、同じ画像が2回続けて見えたら出来上がり
4. 画像を取り出して、`-o` の名前のとおりに保存（webp・jpeg で返っても `.png` を頼まれたら PNG に直す）

2026-10 の画面では、発言ごとの印（`data-message-author-role`）が無く、入力欄は `#prompt-textarea` ではなく `role="textbox"` の ProseMirror だった。画面が変わったら `probe` から見る。
