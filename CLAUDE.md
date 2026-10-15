# video-studio

動画生成スキル（video-scene / video-mascot）を改善していく開発リポ。

## 最初に読むもの
- `docs/handoff-2026-10-15.md` — このリポを作るまでの経緯、決めたこと、声のこもりの調査結果、次にやること
- `logs/yyyy-MM.md` — 作業ログ（進捗の正本は logs と git log）

## 置き場所の決まり（手元の話。クラウドのスレッドには関係しない）
- スキルの正本: `skills/video-scene`、`skills/video-mascot`。`~/.claude/skills/` からは symlink で指す（張り方と注意は README の「スキルの置き方」）
- `~/ClaudeCode/video-studio` は main のままにする。動いているスキルはここの中身なので、ブランチを切るのは worktree で
- コード・手順書・ログ: このリポ（パブリック）
- 素材・作業フォルダ: `~/.local/share/video-scene/work/<名前>/`（各PCのローカル、git に入れない）
- 生成物（動画・音声）: Google ドライブのマイドライブ（新旧PC・クラウドから見られるように）
- `research/` は調査で使った使い捨てに近いスクリプト。本採用するものはスキル側へ移す

## 実行環境
- スキルの Python は `~/.local/share/video-scene/venv`（3.12 以上）。システムの Python が 3.12 未満の機体（旧PC の 22.04 は 3.10）では、`setup.sh` が uv でユーザー領域に 3.12 の venv を作る（apt の Python には触らない）。古い venv は `venv.py310.bak` に退避する
- 書き出しは手元のPC（WSL）で行う。H3（新PCの GPU）、Irodori-TTS、/img（ChatGPT の枠）はクラウドでは動かない
- クラウドセッションでは、コードと手順書の改修、ffmpeg・HyperFrames・Gemini TTS での確認まで

## クラウドのスレッド（Claude Code Projects）の決まり

- 枠の外で決めた事は `ROADMAP.md`（今の段階と次にやること）と `DECISIONS.md`（決めたことと理由）にある。PR ごとに更新する。
- やるのは `ROADMAP.md` の「クラウドのスレッドがやること」を上から順に1つずつ。「手元待ち」には手を出さない。
- 毎回 `main` から枝を切って PR を出す。`ci` が緑なら自分でマージしてよい。
- **既定の挙動は変えない**。新しい機能は opt-in で足す。既定の切り替えが要ると思ったら、`DECISIONS.md` の「未決」に書いて止まる。
- 判断に迷う仕様は推測で進めず、`DECISIONS.md` の「未決」に書いて止まる。
- `.github/workflows/` の YAML は変えない（Claude の GitHub App には workflows 権限が無く、push が拒否される）。検査を増やすときは `scripts/ci.sh` か `requirements-ci.txt`。ジョブ名 `ci` は `main` の保護ルールが参照している。
- このリポは public。顧客名・実際の図面・本物の声や絵は入れない。サンプルは合成する。
- コードは Python 3.12 前提（f-string の式の中でバックスラッシュを使っている）。
- 作業ログは `logs/yyyy-MM.md` に `## yyyy-MM-dd 概要` の見出しで書く。
