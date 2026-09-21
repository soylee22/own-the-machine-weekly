import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const paths = ['', 'data/', 'dossiers/', 'dossiers/bae-systems/', 'receipts/', 'archive/'];

for (const path of paths) {
  test(`page ${path || 'home'} renders cleanly`, async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', error => consoleErrors.push(error.message));

    const response = await page.goto(path, { waitUntil: 'networkidle' });
    expect(response?.ok(), `HTTP failure for ${path}`).toBeTruthy();
    await expect(page.locator('body')).toBeVisible();

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
    expect(consoleErrors, `console errors on ${path}`).toEqual([]);

    const results = await new AxeBuilder({ page }).analyze();
    const serious = results.violations.filter(v => v.impact === 'serious' || v.impact === 'critical');
    expect(serious, `serious accessibility violations on ${path}`).toEqual([]);
  });
}

test('home page internal links resolve', async ({ page, request }) => {
  await page.goto('', { waitUntil: 'networkidle' });
  const hrefs = await page.locator('a[href]').evaluateAll(anchors =>
    [...new Set(anchors.map(a => (a as HTMLAnchorElement).href))]
  );
  const local = hrefs.filter(href => href.startsWith('http://127.0.0.1:4321/own-the-machine-weekly/'));
  expect(local.length).toBeGreaterThan(5);
  for (const href of local) {
    const response = await request.get(href);
    expect(response.status(), `broken internal link: ${href}`).toBeLessThan(400);
  }
});
