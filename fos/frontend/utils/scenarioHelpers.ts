/**
 * Scenario helper functions for frontend.
 *
 * Provides utility functions that resolve custom action and resource names
 * from scenario parameters with appropriate fallbacks.
 *
 * Exports: getActionConfig, getResourceName, fillTemplate
 */

/**
 * Resolves action name and description from scenario params.
 *
 * @param params - Scenario parameters object
 * @param actionIndex - 1-based action index (1 or 2)
 * @returns Object with name and description
 */
export function getActionConfig(
  params: Record<string, unknown>,
  actionIndex: number
): { name: string; description: string } {
  const nameKey = `action_${actionIndex}_name`;
  const descKey = `action_${actionIndex}_description`;

  const name =
    (params[nameKey] as string) || (params[`default_${nameKey}`] as string) || `Action ${actionIndex}`;
  const description = (params[descKey] as string) || (params[`default_${descKey}`] as string) || '';

  return { name, description };
}

/**
 * Resolves resource name, handling custom option.
 *
 * @param params - Scenario parameters object
 * @returns The effective resource name
 */
export function getResourceName(params: Record<string, unknown>): string {
  const resourceName = (params.resource_name as string) || 'Tokens';
  if (resourceName === 'Custom') {
    return (params.resource_name_custom as string) || 'Tokens';
  }
  return resourceName;
}

/**
 * Replaces placeholders in a template string with scenario values.
 *
 * @param template - Template string with {placeholder} syntax
 * @param params - Scenario parameters object
 * @returns String with placeholders replaced
 */
export function fillTemplate(
  template: string,
  params: Record<string, unknown>
): string {
  const resource = getResourceName(params);
  return template
    .replace(/{resource}/g, resource.toLowerCase())
    .replace(/{action_name}/g, (params.action_name as string) || 'Contribute');
}
