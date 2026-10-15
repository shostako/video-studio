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
- 毎回 `main` から枝を切って PR を出す。**マージしてよいのは、`python3 scripts/pr_gate.py <PR番号>` が `OK` を返す（終了コード 0）ときだけ。マージは、門が表示した `gh pr merge ... --match-head-commit <SHA>` の形で行う**（判定のあとに push が入っても、判定していないコミットはマージされない）。 ci が緑で、Codex のレビューが **PR の先頭コミットに対して**完了していて、未解決の指摘が無いことを見る。
  - 終了コード 2 は「待つ」（ci か Codex が走行中、または push の後で再レビュー前）。数分おいてもう一度。
  - 終了コード 1 は「だめ」。指摘を `gh api repos/shostako/video-studio/pulls/<PR番号>/comments` で読み、直して push する。判断に迷う指摘は `DECISIONS.md` の「未決」に書いて止まる。
  - **直した指摘のスレッドは、返信して解決済みにする。** 門は GitHub 上の未解決スレッドの数で判断する（Codex の要約の `has_unresolved_findings` はレビュー時点の写しで、解決しても更新されない）。スレッドの ID は `gh api graphql -f query='query{repository(owner:"shostako",name:"video-studio"){pullRequest(number:<PR番号>){reviewThreads(first:100){nodes{id isResolved path}}}}}'` で取る。返信は `addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$b})`、解決は `resolveReviewThread(input:{threadId:$id})`（どちらも `gh api graphql -f query='mutation(...){...}' -f id=...`）。
  - **Codex は PR を開いたときに自動でレビューするだけで、push では再レビューしない。** 指摘を直して push したら、PR に `@codex review` とコメントして再レビューを頼む（Codex の枠を1回使うので、指摘を直した push のあとだけ。何度も頼まない）。そのあと門を流し、先頭コミットへのレビューが終わるまで待つ。「You have reached your Codex usage limits」と返ってきたら、`DECISIONS.md` の「未決」に書いて止まる（人が決める）。
  - push するたびに先頭が変わるので、直したあとは必ずもう一度流す。CI だけを見てマージすると、指摘付きの PR が入る（別リポで実際に起きた）。
- **既定の挙動は変えない**。新しい機能は opt-in で足す。既定の切り替えが要ると思ったら、`DECISIONS.md` の「未決」に書いて止まる。
- 判断に迷う仕様は推測で進めず、`DECISIONS.md` の「未決」に書いて止まる。
- `.github/workflows/` の YAML は変えない（Claude の GitHub App には workflows 権限が無く、push が拒否される）。検査を増やすときは `scripts/ci.sh` か `requirements-ci.txt`。ジョブ名 `ci` は `main` の保護ルールが参照している。
- このリポは public。顧客名・実際の図面・本物の声や絵は入れない。サンプルは合成する。
- コードは Python 3.12 前提（f-string の式の中でバックスラッシュを使っている）。
- 作業ログは `logs/yyyy-MM.md` に `## yyyy-MM-dd 概要` の見出しで書く。
