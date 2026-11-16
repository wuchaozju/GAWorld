/**
 * This file checks that the production /css/fos path renders real app content.
 *
 * Each test verifies one thing:
 * - css/fos smoke loads the app without missing chunks or a blank page.
 */

import { test, expect } from '@playwright/test';

const routes = ['/css/fos', '/css/fos/login', '/css/fos/dashboard'];

for (const route of routes) {
  test(`css fos smoke loads ${route}`, async ({ page }) => {
    const failedAssets: string[] = [];
    const pageErrors: string[] = [];

    page.on('response', (response) => {
      const url = response.url();
      const isAsset = url.includes('/assets/') || url.endsWith('.js') || url.endsWith('.css');
      if (isAsset && response.status() >= 400) {
        failedAssets.push(`${response.status()} ${url}`);
      }
    });
    page.on('pageerror', (error) => {
      pageErrors.push(error.message);
    });

    await page.goto(route, { waitUntil: 'networkidle' });

    const rootText = (await page.locator('#root').innerText()).trim();
    expect(rootText.length).toBeGreaterThan(0);
    expect(failedAssets).toEqual([]);
    expect(pageErrors).toEqual([]);
  });
}
