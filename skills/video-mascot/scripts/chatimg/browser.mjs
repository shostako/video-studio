// 専用プロファイルの Chrome を起動し、CDP で Playwright を繋ぐ。
// 人が一度手でログインしたプロファイルを、次からもそのまま使う。普段使いのプロファイルには触らない。
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
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
export const PORT = Number(process.env.CHATGPT_CHAT_PORT || 9333);

async function cdpAlive() {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
    return r.ok;
  } catch {
    return false;
  }
}

export async function openBrowser({ minimized = false } = {}) {
  if (!(await cdpAlive())) {
    const exe = CHROME_CANDIDATES.find((p) => existsSync(p));
    if (!exe) throw new Error('Chrome が見つからない。CHATGPT_CHAT_CHROME で場所を指定しろ');
    mkdirSync(PROFILE_DIR, { recursive: true });
    const args = [
      `--user-data-dir=${PROFILE_DIR}`,
      `--remote-debugging-port=${PORT}`,
      '--no-first-run',
      '--no-default-browser-check',
    ];
    if (minimized) args.push('--start-minimized');
    args.push('https://chatgpt.com/');
    spawn(exe, args, { detached: true, stdio: 'ignore' }).unref();
    for (let i = 0; i < 60 && !(await cdpAlive()); i++) await new Promise((r) => setTimeout(r, 500));
    if (!(await cdpAlive())) throw new Error(`Chrome の CDP (port ${PORT}) に繋がらない`);
  }
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`);
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
