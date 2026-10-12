/**
 * This file checks that moving between experiment creation and settings never empties the page.
 *
 * The test repeats the transition, records browser and asset errors, and watches the root element.
 */

import { expect } from "@playwright/test";
import { test } from "./fixtures";

test("scenario and settings navigation always keeps visible content", async ({ page, authedPage }) => {
  const pageErrors: string[] = [];
  const failedAssets: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const resourceType = response.request().resourceType();
    if (resourceType === "script" || resourceType === "stylesheet") {
      failedAssets.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/simulations/create");
  await page.evaluate(() => {
    const root = document.querySelector("#root");
    if (!root) throw new Error("The app root is missing");
    (window as typeof window & { fosRootWasEmpty?: boolean }).fosRootWasEmpty = false;
    new MutationObserver(() => {
      if ((root.textContent || "").trim().length === 0) {
        (window as typeof window & { fosRootWasEmpty?: boolean }).fosRootWasEmpty = true;
      }
    }).observe(root, { childList: true, subtree: true, characterData: true });
  });

  for (let index = 0; index < 3; index += 1) {
    await page.locator('a[href="/settings/providers"]').first().click();
    await page.waitForURL(/\/settings\/providers/);
    await expect(page.locator("#root")).not.toBeEmpty();
    await expect(page.locator("nav.nav")).toBeVisible();

    await page.locator('a[href="/simulations/new"]').first().click();
    await page.waitForURL(/\/simulations\/new/);
    await expect(page.locator("#root")).not.toBeEmpty();
    await expect(page.locator("nav.nav")).toBeVisible();
  }

  const rootWasEmpty = await page.evaluate(
    () => (window as typeof window & { fosRootWasEmpty?: boolean }).fosRootWasEmpty,
  );
  expect(rootWasEmpty).toBe(false);
  expect(pageErrors).toEqual([]);
  expect(failedAssets).toEqual([]);
});
