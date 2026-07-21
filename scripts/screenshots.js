#!/usr/bin/env node
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:5000';
const DIR = '/home/ubuntu/hospital-workorder/static/demo/screenshots';
const fs = require('fs');
fs.mkdirSync(DIR, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath: '/snap/bin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  async function snap(name, url) {
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(2000);
      await page.screenshot({ path: `${DIR}/${name}`, fullPage: false });
      const kb = (fs.statSync(`${DIR}/${name}`).size / 1024).toFixed(0);
      console.log(`  [${kb.padStart(4)}KB] ${name}`);
    } catch(e) {
      console.log(`  [FAIL] ${name} -`, e.message.slice(0, 80));
    }
  }

  // Login using form submission
  console.log('[1/3] Logging in...');
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  // Wait for form to be ready
  await page.waitForTimeout(1000);
  // Try different selectors for the form
  const inputs = await page.locator('input').all();
  console.log(`  Found ${inputs.length} input fields`);
  
  // Fill credentials by label
  const usernameInput = page.locator('input[name="username"], input[type="text"]').first();
  const passwordInput = page.locator('input[name="password"], input[type="password"]').first();
  await usernameInput.fill('admin');
  await passwordInput.fill('admin123');

  // Submit
  const submitBtn = page.locator('button[type="submit"], input[type="submit"]').first();
  if (await submitBtn.isVisible()) {
    await submitBtn.click();
  } else {
    await page.keyboard.press('Enter');
  }
  await page.waitForTimeout(3000);

  // Check if we're logged in
  const currentUrl = page.url();
  console.log(`  After login URL: ${currentUrl}`);
  const pageText = await page.locator('body').innerText();
  console.log(`  Body preview: ${pageText.slice(0, 100)}`);

  console.log('\n[2/3] Taking screenshots...\n');

  // 1. Login page (before auth)
  await snap('01-login.png', `${BASE}/login`);

  // 2-5: Core pages  
  await snap('02-dashboard.png', `${BASE}/`);
  await snap('03-order-list.png', `${BASE}/orders`);
  await snap('04-publish-form.png', `${BASE}/orders/publish`);
  await snap('05-order-detail.png', `${BASE}/orders/1`);
  
  // 6-8: Mobile
  await snap('06-mobile-list.png', `${BASE}/mobile/`);
  await snap('07-mobile-detail.png', `${BASE}/mobile/order/1`);

  // 9-12: Data management
  await snap('08-data-manage.png', `${BASE}/data`);
  await snap('09-persons.png', `${BASE}/data/persons`);
  await snap('10-solutions.png', `${BASE}/data/solutions`);
  await snap('11-permissions.png', `${BASE}/data/permissions`);

  // 13-15: Asset & Stock
  await snap('12-asset-calendar.png', `${BASE}/asset`);
  await snap('13-asset-list.png', `${BASE}/asset/list`);
  await snap('14-stock.png', `${BASE}/stock`);
  
  // 16-17: Inspection
  await snap('15-inspection-templates.png', `${BASE}/inspection/templates`);
  await snap('16-inspection-plans.png', `${BASE}/inspection/plans`);

  // 18-20: Other
  await snap('17-knowledge.png', `${BASE}/data/knowledge`);
  await snap('18-duty-schedules.png', `${BASE}/data/duty-schedules`);
  await snap('19-report.png', `${BASE}/report`);
  await snap('20-audit-logs.png', `${BASE}/audit/logs`);

  // 21-22: Forms
  await snap('21-forms.png', `${BASE}/forms`);
  await snap('22-form-templates.png', `${BASE}/forms/templates`);

  console.log('\n[3/3] Done!');
  await browser.close();
})();
