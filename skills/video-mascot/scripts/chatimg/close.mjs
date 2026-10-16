// 専用プロファイルの Chrome だけを閉じる（普段使いの Chrome には触らない）
import { chromium } from 'playwright-core';
import { PORT, shutdownBrowser } from './browser.mjs';

try {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${PORT}`, { timeout: 5000 });
  await shutdownBrowser(browser);
  console.log('CLOSED');
} catch {
  console.log('NOT_RUNNING');
}
process.exit(0);
