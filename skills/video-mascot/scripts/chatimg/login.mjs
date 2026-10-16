// 専用プロファイルで chatgpt.com を開き、人が手でログインし終えるのを待つ。
import { openBrowser, isLoggedIn, PROFILE_DIR } from './browser.mjs';

const { browser, page } = await openBrowser();
if (!page.url().startsWith('https://chatgpt.com')) await page.goto('https://chatgpt.com/');
console.log(`profile: ${PROFILE_DIR}`);
console.log('Chrome の窓で chatgpt.com にログインしてくれ（最大15分待つ）');
const deadline = Date.now() + 15 * 60 * 1000;
while (Date.now() < deadline) {
  try {
    if (await isLoggedIn(page)) {
      console.log('LOGGED_IN');
      // Chrome 本体は残す（exit で CDP が切れるだけ）
      process.exit(0);
    }
  } catch {}
  await new Promise((r) => setTimeout(r, 3000));
}
console.log('TIMEOUT');
process.exit(2);
