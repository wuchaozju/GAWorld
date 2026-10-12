/**
 * Tests for toolbar translation keys.
 *
 * Verifies that the toolbar labels added to the workspace header exist in
 * both English and Chinese locale files.
 *
 * Exports: None (test file)
 */

import { describe, expect, it } from "vitest";
import en from "../../locales/en.json";
import zh from "../../locales/zh.json";

describe("ContextToolbar translation keys", () => {
  const requiredKeys = ["running", "agents"];

  it("all toolbar keys exist in English locale", () => {
    const simKeys = (en as any).sim;

    requiredKeys.forEach((key) => {
      expect(simKeys[key]).toBeDefined();
      expect(typeof simKeys[key]).toBe("string");
      expect(simKeys[key].length).toBeGreaterThan(0);
    });
  });

  it("all toolbar keys exist in Chinese locale", () => {
    const simKeys = (zh as any).sim;

    requiredKeys.forEach((key) => {
      expect(simKeys[key]).toBeDefined();
      expect(typeof simKeys[key]).toBe("string");
      expect(simKeys[key].length).toBeGreaterThan(0);
    });
  });
});
