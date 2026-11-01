# video-studio

Claude Code で解説動画を作るスキル集。画面の操作を説明する動画に、口パクと身振りで話すマスコットを付けられる。声は手元の音声合成（Irodori-TTS）で作るので、動画生成サービスへの追加の支払いは要らない。

## 作れる動画

画面操作の解説動画は、次の 3 つの型から選ぶ（同じ撮影・台本・声から出せる）。

| 型 | 見た目 |
|---|---|
| カーソルだけ | 画面を全面に出し、目立つカーソル・クリックの波紋・赤い枠・キーの札・字幕で説明する。章が替わった所に左上へ見出しを数秒出す |
| ワイプ | 画面を縮めて右に寄せ、左の余白の下に丸いワイプの顔が口パクで話す。余白の上に章の見出し |
| 全身 | 同じ割り付けで、余白に小さな全身のマスコットが身振りしながら話す |

ほかに、Veo（Gemini API）や手元の動画モデルで数秒〜数十秒の短い場面を作るスキルも入っている。

| スキル | 役目 |
|---|---|
| `skills/screen-explainer` | Excel や Web アプリの画面を撮り、寄り・カーソル・強調・字幕を重ねた解説の画面を組む |
| `skills/video-mascot` | マスコットの声・口パク・身振りを書き出し、解説の画面に置く。3 つの型を 1 本に通す入口（`vm explain`） |
| `skills/video-scene` | 短い場面の動画（Veo・MiniMax H3・パラパラ）と、字幕・吹き出しなどの重ね |

## マスコットとパック

マスコットは「パック」で持つ。パックには、姿勢の絵、口と目の部品、姿勢の切り替えの動き（Wan2.2 で作った列の作り置き）が入っている。パックのあるキャラなら、台本の言葉に身振りを割り当てるだけで動画になり、Wan や RIFE の無い PC でも書き出せる。

基準のキャラは 2 体: **蘭**（ボブの丸顔）と **凜**（まとめ髪）。パックは GitHub Releases に zip で置き、どの版を使うかをリポの `skills/video-mascot/data/packs.json` に書いてある。`setup.sh`（か `vm packs fetch`）が足りない・古いパックを取ってきて `~/.local/share/video-scene/packs/` に置くので、**リポを同期して `setup.sh` を回せば、どの PC にも同じ版のパックがそろう**。`vm packs` で手元の版を確かめられる。新しいキャラを作る手順は `skills/video-mascot/references/new-character.md`（新PC 相当の GPU と ComfyUI が要る）。

## 確かめた環境

どこまで確かめたかを、そのまま書く。表に無い環境（macOS、WSL ではない Linux の PC での動画づくり）は試していない。

| 環境 | 確かめたこと |
|---|---|
| WSL2 の Ubuntu 24.04（作者の新PC、RTX 5070） | 全部（キャラ作り・Wan・RIFE を含む）。日々ここで作っている |
| WSL2 の Ubuntu 22.04（作者の旧PC、RTX 4060） | パックを Releases から入れ、蘭・凜で 3 つの型（カーソルだけ・ワイプ・全身）を作った。Wan・RIFE は使わない |
| WSL2 に新しく作った Ubuntu 24.04（何も入っていない） | README の手順だけで入れ、Web アプリの解説動画を蘭の全身の型で 1 本作った（2026-11-01） |
| WSL を使わない Windows 11（Git Bash） | 試験用の家（何も入れていない `HOME`）で、README の手順を Git Bash で流して入れ、同じ Web アプリの解説動画を蘭の全身の型で 1 本作った（2026-11-02）。書き出しは WSL より遅い（30 秒の動画で WSL 382 秒、Windows 616 秒）。Python・ffmpeg・Node.js などは元から入っていた PC で試した。別の日に、何も入っていない家の Claude Code に「README で入れて解説動画を作って」と頼み、51.8 秒の動画まで通した（全体 56 分、書き出し 19.6 分、2026-11-02）。声と動きの最終の確認は人がする |
| WSL ではない Ubuntu（GitHub Actions の CI） | テストだけ（PR ごと）。動画を作るところまでは試していない |

## 必要なもの

- Claude Code と、次のどちらか: Windows の WSL2（Ubuntu。下の手順の基本）か、WSL を使わない Windows（Git Bash で動かす。下の「WSL を使わない Windows」）
- `ffmpeg`（libvpx-vp9 入り）、`python3` と `python3-venv`、日本語の太字フォント（`fonts-noto-cjk`）: `sudo apt update && sudo apt install ffmpeg python3 python3-venv fonts-noto-cjk`（入れたばかりの Ubuntu は、先に `apt update` をしないとパッケージが見つからない）
- Node.js 22 以上（字幕・吹き出しの重ねに使う HyperFrames の要件。nvm などで入れる）
- `uv`（音声合成 Irodori-TTS を入れて動かすのに使う）: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- スキルの Python（3.12 以上）と音声合成 Irodori-TTS: 上がそろっていれば `setup.sh` が入れる（Irodori-TTS は数 GB。GPU が無ければ CPU 版）
- 絵を描くとき（キャラ作り）: Codex CLI と ChatGPT Plus（Codex の画像生成）。呼び出しの道具はスキルに同梱している（`skills/video-mascot/scripts/img/img.sh`）。別の画像生成に替えるなら `VM_IMG_CMD`（`references/new-character.md`）。蘭・凜のパックで動画を作るだけなら要らない
- Web アプリの画面を撮るとき: Playwright と Chromium（video-scene の `setup.sh` が venv に入れる。ブラウザの部品が足りないと出たら、その行のとおり `sudo ... playwright install-deps chromium`）
- Excel の画面を撮るとき: Windows の Excel と、Windows 側の Python（3.12 以上）に `pip install pywin32 pillow`
- 姿勢の切り替えを新しく作るとき（キャラ作り）: NVIDIA の GPU（8GB 以上）、ComfyUI portable と Wan2.2 I2V・Lightning の LoRA、RIFE（rife-ncnn-vulkan）。パックの作り置きを使うだけなら要らない
- Veo の場面: Gemini API の鍵（**別料金**）

## 入れ方

```bash
git clone https://github.com/shostako/video-studio.git ~/ClaudeCode/video-studio
mkdir -p ~/.claude/skills                                         # 入れたばかりの Claude Code には無い
~/ClaudeCode/video-studio/scripts/link-skills.sh                 # ~/.claude/skills/ に symlink を張る
~/.claude/skills/video-scene/scripts/setup.sh                    # 道具を入れる
~/.claude/skills/video-mascot/scripts/setup.sh                   # 音声合成とマスコットのパック（蘭・凜）を入れる
```

入れたあとは Claude Code を起動し直す。動いているセッションの途中で入れたスキルは、一覧に出ないことがある。

場所は環境変数で変えられる: `VIDEO_SCENE_HOME`（道具と作業フォルダ、既定 `~/.local/share/video-scene`）、`VM_RIFE_EXE`・`VM_RIFE_TMP`（RIFE）、`VM_COMFY_ROOT`（ComfyUI）、`VM_WIN_HOME`（Windows のユーザーのフォルダ）、`VIDEO_SCENE_OUT`（短い場面の出力先）、`VM_IMG_CMD`（絵を描く道具）。

### WSL を使わない Windows

Windows 版の Claude Code は、コマンドを Git Bash で動かす。スキルも Git Bash で動く（2026-11-02 に、試験用の家で入れるところから蘭の解説動画を 1 本作って確かめた）。

- 入れるもの（winget や scoop で）: Git for Windows（Git Bash）、Python（版は問わない。スキルの venv は uv が 3.12 で作る）、`uv`、`ffmpeg`（libvpx-vp9 入りの full ビルド。例 `winget install Gyan.FFmpeg`）、Node.js 22 以上
- Git Bash の `~/.bashrc` に `export PYTHONUTF8=1` を書く。Windows の Python は既定で CP932 で読み書きするので、日本語の入ったファイルや出力が化けたり落ちたりする（`vm`・`vs` の入口は自分で付けるが、`compose.py` などを直に動かすときに要る）
- 手順は上の「入れ方」と同じコマンドを Git Bash で打つ。`link-skills.sh` は、Windows ではシンボリックリンクの代わりにジャンクション（管理者権限の要らないフォルダのリンク）を張る。パックから作った作業フォルダの作り置きもジャンクションで読む
- venv の Python は `~/.local/share/video-scene/venv/Scripts/python.exe`（Linux の `bin/python` の代わり）。Web の撮影はこの Python で `web_capture.py` を動かす
- Excel の撮影（`excel_capture.py`）は、pywin32 と Pillow を入れた Python で直に動かす
- まだ確かめていないこと: キャラ作り（Wan・RIFE で切り替えを新しく作る）、Veo・H3 の場面

## 作り方の流れ（マスコット付きの解説動画）

```bash
vm pack rin --new ~/.local/share/video-scene/work/my-howto      # パックから作業フォルダ（名前だけなら ~/.local/share/video-scene/packs/ の中）
# config.json に声の設定と台詞、身振りを書く（パックには声の設定が入っていない）。例:
#   "voice": {"caption": "落ち着いた若い女性の声で、はきはきと説明する", "seed": 2024, "lines": [{"text": "このエクセルの使い方を説明する。"}, ...]},
#   "events": [{"line": 1, "kw": "せつめい", "pose": "open"}, ...]   （行 1 の声の「せつめい」の直前に open へ。書き方は skills/video-mascot/references/config-spec.md）
#   声を選ぶなら voice.candidates に説明文を数通り書いて vm voice <作業フォルダ> candidates で聞き比べ、決めた 1 本を voice.ref に
vm voice ~/.local/share/video-scene/work/my-howto synth && vm voice ~/.local/share/video-scene/work/my-howto master   # 声
# 画面を撮る（screen-explainer の excel_capture.py / web_capture.py）、scenes.py に場面ごとの寄り・カーソルを書く
vm explain ~/.local/share/video-scene/work/my-howto --shots <撮影> --scenes scenes.py --style full --out my-howto.mp4
```

`vm` は `~/.claude/skills/video-mascot/scripts/vm`。くわしい手順は各スキルの `SKILL.md`（Claude Code に「マスコット付きの解説動画を作って」と頼めば読まれる）。

## 許諾

- パック（キャラの絵・部品・切り替えの作り置き）: CC0（公開するとき）
- 使っているモデルの許諾: Irodori-TTS・DACVAE は MIT、Wan2.2・Lightning の LoRA は Apache 2.0、RIFE は MIT。出力の商用利用はできる
- **Irodori-TTS の利用条件**: 実在の人物のなりすまし・誤情報の作成に使わない。生成した声には聞こえない電子透かしが入る（消さない）
- このリポのコード: MIT（`LICENSE`）。パックの絵・部品・作り置きは CC0 で別

## 開発の決まり

- 経緯と現状: `docs/handoff-2026-10-15.md`、決めたこと `DECISIONS.md`、次にやること `ROADMAP.md`、使う人に効く変更の記録 `CHANGELOG.md`、作業ログ `logs/`
- パックを作り直したら: `vm packs export <パック> <名前>-pack.zip --version <日付>` → 出た zip を新しい Release（`packs-<日付>`）に上げる → 出力の 1 行（版・大きさ・sha256）と Release の URL を `skills/video-mascot/data/packs.json` に書いて PR にする。各 PC は同期して `setup.sh` を回せば新しい版に替わる
- PR は `scripts/pr_gate.py <番号>` が通ってからマージする（`CLAUDE.md`）

## スキルの置き方

Claude Code が読むのは `~/.claude/skills/<名前>/`。そこにはこのリポの `skills/<名前>` を指す symlink を置く。
`~/.claude`（claude-wsl-config）の git には入れない。

- `~/ClaudeCode/video-studio` は **常に main をチェックアウトしておく**。symlink はチェックアウト中の中身を指すので、ここでブランチを切ると動いているスキルもそのブランチに変わる。
- 機能の作業は worktree で行う（例: `git worktree add ../.wt-video-studio-<名前> -b <ブランチ>`）。
- `~/.claude/.gitignore` には `skills/video-scene`・`skills/video-mascot`・`skills/screen-explainer` を **末尾の `/` 無しで**書く。`/` 付きのパターンはディレクトリにしか効かず、symlink に置き換えると外れて、git-sync がリンクを自動でコミットしてしまう。

### リンクを張る・確かめる

```bash
~/ClaudeCode/video-studio/scripts/link-skills.sh          # 張る（何度実行してもよい）
~/ClaudeCode/video-studio/scripts/link-skills.sh --check  # 確かめるだけ
```

置き換えるのは、リポに無い内容を持たないディレクトリだけ（同期で中身が消えた跡、リポと同じ中身）。置き換えたディレクトリは `~/.local/share/video-studio/replaced/<日時>/` に移す。リポと違う内容があれば、止まって違うファイルを並べる。

### もう1台のPCへ移す手順（旧PC VAIO-2nd など）

`~/.claude` の「登録解除」のコミットを pull すると、そのPCの `~/.claude/skills/video-*` の中身は消える。先に手元の変更が無いことを確かめる。

1. `git -C ~/.claude status --short skills/video-scene skills/video-mascot` が空であること。変更があれば、このリポに取り込んでから進める。
2. 「同期して」（git-sync）で `~/.claude` を pull する。video-studio も同期の対象に入っている。
3. このリポが無ければ clone する: `git clone git@github.com:shostako/video-studio.git ~/ClaudeCode/video-studio`
4. `~/ClaudeCode/video-studio/scripts/link-skills.sh` を実行し、`--check` がすべて ok になるのを見る。
5. `~/.claude/skills/video-scene/scripts/setup.sh --check` と `~/.claude/skills/video-mascot/scripts/setup.sh --check` で、スキルが読めていることを確かめる。
