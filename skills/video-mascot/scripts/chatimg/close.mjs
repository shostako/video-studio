// 専用プロファイルの Chrome だけを閉じる（普段使いの Chrome には触らない）
import { chromium } from 'playwright-core';
import { ownedPort, shutdownBrowser } from './browser.mjs';

const port = await ownedPort();
if (!port) console.log('NOT_RUNNING');
else {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 5000 });
  await shutdownBrowser(browser);
  console.log('CLOSED');
}
process.exit(0);
