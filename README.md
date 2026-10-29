# video-studio

Claude Code の動画生成スキル（video-scene / video-mascot / screen-explainer）を改善していく開発リポ。

- スキルの正本: `skills/video-scene`、`skills/video-mascot`、`skills/screen-explainer`（画面を撮って操作を説明する動画）
- 経緯と現状: `docs/handoff-2026-10-15.md`
- 作業ログ: `logs/`

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
