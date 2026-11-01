// 用 playwright-core 驱动本地 Chromium，把 HTML 渲染成 PNG 长图
// 用法: node shot.js <html绝对路径> <png输出绝对路径> [图片宽度px]
const { chromium } = require("playwright-core");
const path = require("path");
const fs = require("fs");

// 浏览器路径：优先环境变量 CHROME_PATH（云端/CI），其次本机已知路径，最后交给 playwright 自带
const CHROME = (process.env.CHROME_PATH || "").trim() ||
  ["C:/Users/吴江平/AppData/Local/ms-playwright/chromium-1248/chrome-win64/chrome.exe"]
    .find((p) => fs.existsSync(p)) || undefined;

(async () => {
  const htmlPath = process.argv[2];
  const outPath = process.argv[3];
  const width = parseInt(process.argv[4] || "900", 10);
  if (!htmlPath || !outPath) {
    console.error("usage: node shot.js <html> <png> [width]");
    process.exit(2);
  }
  if (!fs.existsSync(htmlPath)) {
    console.error("html not found: " + htmlPath);
    process.exit(3);
  }

  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--disable-dev-shm-usage"],
  });
  // 中文字体兜底（Linux 无微软雅黑时由系统 CJK 字体承接）
  const page = await browser.newPage({
    viewport: { width: width, height: 1200 },
    deviceScaleFactor: 1.5,
  });
  await page.goto("file:///" + htmlPath.replace(/\\/g, "/"), {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  // 等字体与布局稳定
  await page.waitForTimeout(600);

  // 裁掉底部多余空白
  const h = await page.evaluate(() => {
    const b = document.body;
    const kids = Array.from(b.children);
    let max = 0;
    for (const k of kids) {
      const r = k.getBoundingClientRect();
      if (r.bottom > max) max = r.bottom;
    }
    return Math.ceil(max + 8);
  });
  await page.setViewportSize({ width: width, height: Math.max(600, h) });
  await page.waitForTimeout(200);

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  await page.screenshot({ path: outPath, fullPage: false });
  await browser.close();
  console.log("OK " + outPath);
})().catch((e) => {
  console.error("FAIL " + (e && e.message ? e.message : e));
  process.exit(1);
});
