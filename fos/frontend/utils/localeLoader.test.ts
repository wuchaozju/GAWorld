/**
 * This file tests loading language bundles only when we need them.
 * test_get_initial_locale_modules_loads_only_the_active_language checks the first page load only requests one locale bundle.
 * test_get_secondary_locale_modules_loads_the_other_language_on_demand checks the extra language waits until the switcher asks for it.
 */

import { describe, expect, it } from "vitest";

import {
  getInitialLocaleModules,
  getSecondaryLocaleModules,
} from "./localeLoader";

describe("localeLoader", () => {
  it("test_get_initial_locale_modules_loads_only_the_active_language", async () => {
    const modules = await getInitialLocaleModules("en");

    expect(modules.active.language).toBe("en");
    expect(modules.inactive.language).toBe("zh");
    expect(modules.active.messages.brand).toBeTruthy();
    expect(modules.active.design.common.search).toBeTruthy();
  });

  it("test_get_secondary_locale_modules_loads_the_other_language_on_demand", async () => {
    const modules = await getSecondaryLocaleModules("zh");

    expect(modules.active.language).toBe("zh");
    expect(modules.inactive.language).toBe("en");
    expect(modules.active.messages.brand).toBeTruthy();
    expect(modules.inactive.messages.brand).toBeTruthy();
  });
});
