/**
 * This file stores the small starter groups for GAWorld residents.
 *
 * Each helper does one simple job:
 * - STARTER_POPULATION_OPTIONS lists the sizes users can choose from.
 * - RECOMMENDED_STARTER_POPULATION marks the default suggested size.
 * - getGAWorldStarterCohortIds returns the resident IDs for one starter size.
 */

export const STARTER_POPULATION_OPTIONS = [5, 10, 20, 50] as const;

export const RECOMMENDED_STARTER_POPULATION = 10;

const STARTER_COHORTS: Record<number, string[]> = {
  5: ['1', '2', '12', '21', '31'],
  10: ['1', '2', '4', '7', '12', '18', '21', '27', '31', '41'],
  20: ['1', '2', '3', '4', '5', '7', '9', '12', '14', '16', '18', '20', '21', '24', '27', '29', '31', '34', '38', '41'],
  50: Array.from({ length: 50 }, (_, index) => String(index + 1)),
};

export function getGAWorldStarterCohortIds(count: number): string[] {
  return STARTER_COHORTS[count] ? [...STARTER_COHORTS[count]] : [...STARTER_COHORTS[RECOMMENDED_STARTER_POPULATION]];
}
