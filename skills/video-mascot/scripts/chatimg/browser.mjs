// 専用プロファイルの Chrome を起動し、CDP で Playwright を繋ぐ。
// 人が一度手でログインしたプロファイルを、次からもそのまま使う。普段使いのプロファイルには触らない。
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright-core';

const CHROME_CANDIDATES = [
  process.env.CHATGPT_CHAT_CHROME,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome',
].filter(Boolean);

export const PROFILE_DIR =
  process.env.CHATGPT_CHAT_PROFILE ||
  join(
    process.env.LOCALAPPDATA ||
      (process.env.USERPROFILE && join(process.env.USERPROFILE, 'AppData', 'Local')) ||
      join(process.env.HOME || '.', '.local', 'share'),
    'video-studio',
    'chatgpt-chat-profile',
  );
// ポートの先の CDP の ws の道（/devtools/browser/<id>）。繋がらなければ null
async function cdpWsPath(port) {
  try {
    const r = await fetch(`http://127.0.0.1:${port}/json/version`);
    if (!r.ok) return null;
    return new URL((await r.json()).webSocketDebuggerUrl).pathname;
  } catch {
    return null;
  }
}

// 専用プロファイルの Chrome の CDP のポート。動いていなければ null。
// ポートは固定にせず Chrome に空きを選ばせ（--remote-debugging-port=0）、Chrome がプロファイルに書く
// DevToolsActivePort（1行目がポート、2行目が ws の道）と、そのポートの先の ws の道が一致する時だけ使う。
// 別の Chrome がたまたま同じポートを開いていても、取り違えて操作したり閉じたりしない。
export async function ownedPort() {
  try {
    const [port, path] = readFileSync(join(PROFILE_DIR, 'DevToolsActivePort'), 'utf8').split(/\r?\n/);
    if (Number(port) > 0 && (await cdpWsPath(Number(port))) === path) return Number(port);
  } catch {}
  return null;
}

export async function openBrowser({ minimized = false } = {}) {
  let port = await ownedPort();
  if (!port) {
    const exe = CHROME_CANDIDATES.find((p) => existsSync(p));
    if (!exe) throw new Error('Chrome が見つからない。CHATGPT_CHAT_CHROME で場所を指定しろ');
    mkdirSync(PROFILE_DIR, { recursive: true });
    const args = [
      `--user-data-dir=${PROFILE_DIR}`,
      '--remote-debugging-port=0',
      '--no-first-run',
      '--no-default-browser-check',
    ];
    if (minimized) args.push('--start-minimized');
    args.push('https://chatgpt.com/');
    spawn(exe, args, { detached: true, stdio: 'ignore' }).unref();
    for (let i = 0; i < 60 && !(port = await ownedPort()); i++) await new Promise((r) => setTimeout(r, 500));
    if (!port) throw new Error('専用プロファイルの Chrome の CDP に繋がらない（同じプロファイルの Chrome が CDP なしで開いていたら閉じてから）');
  }
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const context = browser.contexts()[0];
  let page = context.pages().find((p) => p.url().startsWith('https://chatgpt.com')) || context.pages()[0];
  if (!page) page = await context.newPage();
  return { browser, context, page };
}

export async function isLoggedIn(page) {
  // DOM は未ログインでも入力欄が出るので当てにならない。セッション API の user 有無で見る。
  // 返り値には accessToken が入るので、真偽だけ取り出してログには出さない。
  if (!page.url().startsWith('https://chatgpt.com')) return false;
  return page
    .evaluate(() => fetch('/api/auth/session', { credentials: 'include' }).then((r) => r.json()).then((s) => !!(s && s.user)))
    .catch(() => false);
}

// CDP 接続を切って Node を終わらせる。Chrome 本体（とログイン状態）は残す。
export function detachAndExit(code) {
  process.exit(code);
}

// 専用 Chrome 本体を閉じる（他の Chrome には触らない）
export async function shutdownBrowser(browser) {
  const s = await browser.newBrowserCDPSession();
  await s.send('Browser.close').catch(() => {});
}
