/**
 * Starter-size presets for GAWorld residents.
 *
 * Each helper does one simple job:
 * - STARTER_POPULATION_OPTIONS lists the sizes users can choose from.
 * - RECOMMENDED_STARTER_POPULATION marks the default suggested size.
 * - getGAWorldStarterCohortIds derives the first N resident IDs from the
 *   LIVE GAWorld population (via /api/scenarios/gaworld/default-agents).
 *
 * This file is a size preset only — it never bundles resident data. The IDs
 * always come from the live GAWorld population at call time, so the preset
 * stays a filter over the selected city instead of a second canonical
 * dataset (hardcoded 1–50 silently short-fell on any other city).
 */

import { getScenarioDefaultAgents } from '../../services/scenarios';

export const STARTER_POPULATION_OPTIONS = [5, 10, 20, 50] as const;

export const RECOMMENDED_STARTER_POPULATION = 10;

export async function getGAWorldStarterCohortIds(count: number): Promise<string[]> {
  const residents = await getScenarioDefaultAgents('gaworld');
  return residents.slice(0, count).map((resident) => String(resident.id));
}
