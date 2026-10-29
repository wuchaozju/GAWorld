/**
 * Page object for the simulation workspace after experiment creation.
 *
 * Drives auto-advance and advance-turn controls in the workspace log panel
 * using locale-aware selectors. Collects error toasts. Never throws —
 * all errors are collected and returned as strings.
 *
 * Exports: SimulationWorkspace
 */

import { Page } from '@playwright/test';
import { t } from './locale-helper';

export class SimulationWorkspace {
  readonly page: Page;
  readonly locale: string;

  constructor(page: Page, locale: string) {
    this.page = page;
    this.locale = locale;
  }

  /** Wait for the simulation workspace to fully load */
  async waitForReady() {
    const advanceText = t('simPage.advance', this.locale);
    await this.page.getByRole('button', { name: new RegExp(advanceText, 'i') }).waitFor({
      state: 'visible',
      timeout: 30_000,
    });
    await this.page.waitForTimeout(2_000);
  }

  /**
   * Run N rounds using auto-advance, with fallback to manual advance.
   * Never throws — returns error messages instead.
   */
  async advanceRounds(rounds: number = 3, timeoutMs: number = 180_000): Promise<string[]> {
    if (rounds <= 0) return [];

    const errors: string[] = [];

    try {
      await this.runWithAutoAdvance(rounds, timeoutMs);
    } catch (autoAdvanceError) {
      errors.push(`Auto-advance failed: ${String(autoAdvanceError)}`);
      try {
        for (let i = 0; i < rounds; i++) {
          await this.clickAdvanceTurn();
          await this.waitForRoundComplete();
        }
      } catch (manualError) {
        errors.push(`Manual advance failed: ${String(manualError)}`);
      }
    }

    return errors;
  }

  /** Collect all visible error toast messages */
  async collectErrorMessages(): Promise<string[]> {
    const errorToasts = this.page.locator('.border-red-200.text-red-800');
    const count = await errorToasts.count();
    const messages: string[] = [];

    for (let i = 0; i < count; i++) {
      const text = await errorToasts.nth(i).textContent();
      if (text) {
        messages.push(text.replace(/\s*×?\s*$/, '').trim());
      }
    }

    return messages;
  }

  /** Check if auto-advance is currently running */
  async isAutoAdvancing(): Promise<boolean> {
    const stopText = t('simPage.stop', this.locale);
    const stopBtn = this.page.getByRole('button', { name: new RegExp(`^${stopText}$`, 'i') });
    return stopBtn.isVisible({ timeout: 1_000 }).catch(() => false);
  }

  // --- Private methods ---

  /** Use auto-advance to run N rounds */
  private async runWithAutoAdvance(rounds: number, timeoutMs: number = 180_000) {
    const stepsTitle = t('simPage.enterSteps', this.locale);

    // Set the step count
    const stepInput = this.page.getByTitle(new RegExp(stepsTitle, 'i'));
    await stepInput.clear();
    await stepInput.fill(String(rounds));

    // Click "Advance node"; the step count turns this into a multi-step run.
    const advanceText = t('simPage.advance', this.locale);
    const advanceBtn = this.page.getByRole('button', {
      name: new RegExp(advanceText, 'i'),
    });
    // Wait for the button to be enabled (selected node must be a backend node)
    await this.page.waitForFunction(
      (text) => {
        const buttons = document.querySelectorAll('button');
        const btn = Array.from(buttons).find(b => b.textContent?.includes(text));
        return btn != null && !((btn as HTMLButtonElement).disabled);
      },
      advanceText,
      { timeout: 15_000 },
    );
    await advanceBtn.click();

    // Wait for auto-advance to complete (Stop button disappears)
    const stopText = t('simPage.stop', this.locale);
    const maxWaitMs = timeoutMs;
    const pollInterval = 2_000;
    let elapsed = 0;

    while (elapsed < maxWaitMs) {
      const stopVisible = await this.page.getByRole('button', {
        name: new RegExp(`^${stopText}$`, 'i'),
      }).isVisible({ timeout: 1_000 }).catch(() => false);

      if (!stopVisible) {
        await this.page.waitForTimeout(1_000);
        return;
      }

      await this.page.waitForTimeout(pollInterval);
      elapsed += pollInterval;
    }

    throw new Error(`Auto-advance did not complete within ${maxWaitMs / 1000}s`);
  }

  /** Click "Advance node" for a single turn */
  private async clickAdvanceTurn() {
    const advanceText = t('simPage.advance', this.locale);
    const advanceBtn = this.page.getByRole('button', {
      name: new RegExp(advanceText, 'i'),
    });
    // Wait for the button to be enabled (selected node must be a backend node)
    await advanceBtn.waitFor({ state: 'visible', timeout: 15_000 });
    await this.page.waitForFunction(
      (text) => {
        const buttons = document.querySelectorAll('button');
        const btn = Array.from(buttons).find(b => b.textContent?.includes(text));
        return btn != null && !((btn as HTMLButtonElement).disabled);
      },
      advanceText,
      { timeout: 15_000 },
    );
    await advanceBtn.click();
  }

  /** Wait for a single round to complete */
  private async waitForRoundComplete() {
    const advancingText = t('simPage.advancing', this.locale);
    await this.page.waitForFunction(
      (text) => {
        const buttons = document.querySelectorAll('button');
        const advancingBtn = Array.from(buttons).find(
          b => b.textContent?.includes(text)
        );
        return !advancingBtn;
      },
      advancingText,
      { timeout: 90_000 }
    ).catch(() => {
      // Timeout — proceed anyway
    });

    await this.page.waitForTimeout(2_000);
  }
}
