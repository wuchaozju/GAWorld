/**
 * Result collector for E2E health-check tests.
 *
 * Reads LLM debug log files from test_results/ (written by the backend
 * during simulation runs) and copies them to organized output directories
 * grouped by scenario ID.
 *
 * Cleans up stale files from previous runs before each collection to
 * prevent old debug logs from contaminating current results.
 *
 * Exports: ResultCollector
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Path from frontend/e2e/helpers/ to repo root test_results/
const TEST_RESULTS_DIR = path.resolve(__dirname, '../../../test_results');
const OUTPUT_DIR = path.resolve(__dirname, '../collected-results');

export class ResultCollector {
  private scenarioId: string;
  private runStartTime: Date;

  constructor(scenarioId: string) {
    this.scenarioId = scenarioId;
    this.runStartTime = new Date();
  }

  /**
   * Called after scenario finishes.
   * Grabs any .txt files modified since this.runStartTime.
   * Copies them to collected-results/<scenarioId>/
   */
  collect(): string[] {
    const scenarioOutputDir = path.join(OUTPUT_DIR, this.scenarioId);
    fs.mkdirSync(scenarioOutputDir, { recursive: true });

    // Clean up any stale files from a previous run in this scenario's dir
    this.cleanStaleFiles(scenarioOutputDir);

    if (!fs.existsSync(TEST_RESULTS_DIR)) {
      return [`WARNING: test_results dir not found at ${TEST_RESULTS_DIR}`];
    }

    const files = fs.readdirSync(TEST_RESULTS_DIR)
      .filter(f => f.endsWith('.txt'))
      .filter(f => {
        const stat = fs.statSync(path.join(TEST_RESULTS_DIR, f));
        return stat.mtime >= this.runStartTime;
      });

    for (const file of files) {
      const src = path.join(TEST_RESULTS_DIR, file);
      const dest = path.join(scenarioOutputDir, file);
      fs.copyFileSync(src, dest);
    }

    return files.map(f => path.join(scenarioOutputDir, f));
  }

  /**
   * Remove files from a previous run that would contaminate results.
   * Only deletes files older than this run's start time.
   */
  private cleanStaleFiles(dir: string): void {
    if (!fs.existsSync(dir)) return;

    const files = fs.readdirSync(dir);
    for (const file of files) {
      const filePath = path.join(dir, file);
      const stat = fs.statSync(filePath);
      if (stat.mtime < this.runStartTime) {
        fs.unlinkSync(filePath);
      }
    }
  }
}
