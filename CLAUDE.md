# video-studio

動画生成スキル（video-scene / video-mascot）を改善していく開発リポ。

## 最初に読むもの
- `docs/handoff-2026-10-15.md` — このリポを作るまでの経緯、決めたこと、声のこもりの調査結果、次にやること
- `logs/yyyy-MM.md` — 作業ログ（進捗の正本は logs と git log）

## 置き場所の決まり
- スキルの正本: `skills/video-scene`、`skills/video-mascot`。`~/.claude/skills/` からは symlink で指す（張り方と注意は README の「スキルの置き方」）
- `~/ClaudeCode/video-studio` は main のままにする。動いているスキルはここの中身なので、ブランチを切るのは worktree で
- コード・手順書・ログ: このリポ（パブリック）
- 素材・作業フォルダ: `~/.local/share/video-scene/work/<名前>/`（各PCのローカル、git に入れない）
- 生成物（動画・音声）: Google ドライブのマイドライブ（新旧PC・クラウドから見られるように）
- `research/` は調査で使った使い捨てに近いスクリプト。本採用するものはスキル側へ移す

## 実行環境
- 書き出しは手元のPC（WSL）で行う。H3（新PCの GPU）、Irodori-TTS、/img（ChatGPT の枠）はクラウドでは動かない
- クラウドセッションでは、コードと手順書の改修、ffmpeg・HyperFrames・Gemini TTS での確認まで
