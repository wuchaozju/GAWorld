const POLICY_CASCADE_SCENARIO_IDS = new Set([
  'policy_erosion',
  'policyerosion',
  'policy_diffusion',
  'policydiffusion',
]);

export const isPolicyCascadeScenarioId = (scenarioId: unknown): boolean => {
  const normalized = String(scenarioId || '').trim().toLowerCase();
  return POLICY_CASCADE_SCENARIO_IDS.has(normalized);
};

export const isPolicyCascadeScenario = (
  scenario: { id?: unknown; sceneType?: unknown } | null | undefined,
): boolean => {
  if (!scenario) return false;
  return (
    scenario.sceneType === 'policy_cascade_scene' ||
    isPolicyCascadeScenarioId(scenario.id)
  );
};
