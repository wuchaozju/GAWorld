/**
 * Parses "key=value" lines into a typed object with proper coercion.
 *
 * Coercion rules (applied in order):
 *   "true" / "false"          → boolean
 *   digits only (with opt -)  → integer
 *   digits with decimal point → float
 *   anything else             → string (trimmed)
 *
 * Lines that are blank or start with "#" are silently ignored.
 * Lines without "=" are silently ignored (not treated as errors).
 *
 * Example:
 *   parseScenarioParams("cooperate_reward=5\nmultiplier=1.5\ndebug=true")
 *   // → { cooperate_reward: 5, multiplier: 1.5, debug: true }
 */
export type ScenarioParamValue = string | number | boolean;

export function parseScenarioParams(
  text: string,
): Record<string, ScenarioParamValue> {
  const result: Record<string, ScenarioParamValue> = {};

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    const eqIdx = line.indexOf('=');
    if (eqIdx === -1) continue;

    const key = line.slice(0, eqIdx).trim();
    const rawVal = line.slice(eqIdx + 1).trim();
    if (!key) continue;

    if (rawVal === 'true')  { result[key] = true;  continue; }
    if (rawVal === 'false') { result[key] = false; continue; }
    if (/^-?\d+$/.test(rawVal))         { result[key] = parseInt(rawVal, 10); continue; }
    if (/^-?\d+\.\d+$/.test(rawVal))    { result[key] = parseFloat(rawVal);  continue; }
    result[key] = rawVal;
  }

  return result;
}

/**
 * Validates parsed params against a known base parameter set.
 * Returns a list of keys that are not present in the base config.
 * Used to show "unknown key" warnings in the UI.
 */
export function findUnknownKeys(
  params: Record<string, ScenarioParamValue>,
  baseParams: Record<string, unknown>,
): string[] {
  const compatibilityKeys = new Set(["show_average_contribution"]);

  return Object.keys(params).filter(
    (key) => !(key in baseParams) && !compatibilityKeys.has(key),
  );
}
