// ChatGPT 通常 Chat 画面で画像を1枚生成して保存する。
// usage: node generate.mjs --prompt "..." --out out.png [--ref ref.png ...] [--timeout 300] [--minimized]
//        node generate.mjs --grab-only --out out.png   （開いている会話の最新の生成画像を回収）
// 終了コードは /img（img.sh）に揃える: 0=保存成功 / 2=引数の誤り / 3=ログイン切れ / 4=上限の表示を検知 / 5=タイムアウト / 1=その他
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { openBrowser, isLoggedIn } from './browser.mjs';

const args = process.argv.slice(2);
const opt = { ref: [] };
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--prompt') opt.prompt = args[++i];
  else if (a === '--out') opt.out = args[++i];
  else if (a === '--ref') opt.ref.push(resolve(args[++i]));
  else if (a === '--timeout') opt.timeout = Number(args[++i]);
  else if (a === '--minimized') opt.minimized = true;
  else if (a === '--grab-only') opt.grabOnly = true;
}
if ((!opt.prompt && !opt.grabOnly) || !opt.out) {
  console.error('usage: node generate.mjs --prompt "..." --out out.png [--ref ref.png] [--timeout 300]');
  process.exit(2);
}
const timeoutMs = (opt.timeout || 300) * 1000;

// 上限・制限の文言（日英）。見つけたら止める
const LIMIT_RE = /(上限に達|制限に達|利用上限|生成できる画像の上限|you['’]ve (hit|reached)|reached (the|your) .*limit|rate limit|usage cap|limit resets|try again (later|after|in))/i;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const { browser, page } = await openBrowser({ minimized: opt.minimized });
const done = async (code, msg) => {
  console.log(msg);
  // Chrome 本体は残す（exit で CDP が切れるだけ）
  process.exit(code);
};

if (!opt.grabOnly) await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded' });
const composer = page.locator('form [contenteditable="true"][role="textbox"], #prompt-textarea').first();
await composer.waitFor({ timeout: 30000 }).catch(() => {});
if (!(await isLoggedIn(page))) await done(3, 'NOT_LOGGED_IN: node login.mjs で専用プロファイルにログインしろ');

// 画面上の画像の一覧（生成画像は alt が「生成画像N」/「Generated image」。添付は「ユーザーの添付画像」）
const listImages = () =>
  page.evaluate(() =>
    [...document.querySelectorAll('main img')].map((im) => ({
      src: im.src,
      alt: im.alt || '',
      ok: im.complete && im.naturalWidth >= 256,
    })),
  );
const pickGenerated = (imgs, before) => {
  const c = imgs.filter((i) => i.ok && !before.has(i.src) && !/添付|attach|upload/i.test(i.alt));
  const named = c.filter((i) => /生成|generated/i.test(i.alt));
  return (named.length ? named : c).at(-1)?.src || null;
};
const STOP_SEL = '[data-testid="stop-button"], button[aria-label*="停止"], button[aria-label*="Stop"]';

let before = new Set();
if (opt.grabOnly) {
  // 送らずに、今開いている会話の最新の生成画像だけ保存する（タイムアウト後の回収用）
  before = new Set();
} else {
if (opt.ref.length) {
  // 画像を受け付ける file input を優先。無ければ ＋ ボタンを開いてから探す
  let input = page.locator('input[type="file"][accept*="image"]');
  if (!(await input.count())) input = page.locator('input[type="file"]');
  if (!(await input.count())) {
    await page.locator('[data-testid="composer-plus-btn"], form button[aria-label="ファイルなどを追加"]').first().click().catch(() => {});
    await sleep(800);
  }
  await input.first().setInputFiles(opt.ref);
  // 添付のアップロード完了を待つ（送信ボタンが押せるようになるまで）
}
await composer.click();
await page.keyboard.insertText(opt.prompt);
before = new Set((await listImages()).map((i) => i.src));
const send = page.locator('[data-testid="send-button"], form button[aria-label="送信"], form button[aria-label="Send prompt"], form button[aria-label="Send"]').first();
await send.waitFor({ timeout: 60000 });
for (let i = 0; i < 120 && (await send.isDisabled()); i++) await sleep(500);
await send.click();
}

const start = Date.now();
let lastSrc = null, stableSince = 0;
while (Date.now() - start < timeoutMs) {
  await sleep(2000);
  // 上限はトースト・バナーに出ることもあるので、30秒以上かかっていれば画面全体も見る
  if (Date.now() - start > 30000) {
    let body = await page.evaluate(() => document.body.innerText).catch(() => '');
    if (opt.prompt) body = body.split(opt.prompt).join(' '); // 自分の指示文に上限の語があっても拾わない
    const m = body.match(LIMIT_RE);
    if (m) await done(4, `LIMIT_DETECTED: ...${body.slice(Math.max(0, m.index - 120), m.index + 180).replace(/\s+/g, ' ')}`);
  }
  const generating = (await page.locator(STOP_SEL).count()) > 0;
  const src = pickGenerated(await listImages(), before);
  if (src && !generating) {
    if (src === lastSrc) {
      if (Date.now() - stableSince > 6000) {
        const b64 = await page.evaluate(async (u) => {
          const r = await fetch(u, { credentials: 'include' });
          const buf = new Uint8Array(await r.arrayBuffer());
          let s = '';
          for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
          return btoa(s);
        }, src);
        writeFileSync(opt.out, Buffer.from(b64, 'base64'));
        await done(0, `SAVED: ${resolve(opt.out)} (${page.url()})`);
      }
    } else {
      lastSrc = src;
      stableSince = Date.now();
    }
  }
}
await page.screenshot({ path: opt.out.replace(/\.\w+$/, '') + '.timeout.png' }).catch(() => {});
await done(5, 'TIMEOUT: 画像が出なかった');
