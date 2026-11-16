/**
 * Tests for scenario API helpers.
 *
 * Checks that GAWorld default agent loading can recover when the dynamic route
 * is not matched by the backend.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { getScenarioDefaultAgents } from './scenarios';

describe('scenario services', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('test_gaworld_default_agents_uses_static_fallback_after_404', async () => {
    const profileAgents = [
      {
        id: '34',
        name: 'Xu Guilan',
        role: '',
        avatarUrl: '',
        profile: 'Age: 42',
        llmConfig: { provider: 'backend', model: 'default' },
        properties: {},
        history: {},
        memory: [],
        knowledgeBase: [],
      },
    ];
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('', { status: 404, statusText: 'Not Found' }))
      .mockResolvedValueOnce(new Response(JSON.stringify(profileAgents), { status: 200 }));

    const result = await getScenarioDefaultAgents('gaworld', '34');

    expect(result).toEqual(profileAgents);
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/scenarios/gaworld/default-agents?agent_ids=34');
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/scenarios/default-agents/gaworld?agent_ids=34');
  });

  it('test_gaworld_default_agents_uses_scenario_detail_fallback_after_route_404', async () => {
    const defaultAgents = [
      {
        id: '34',
        name: 'Xu Guilan',
        role: '',
        avatarUrl: '',
        profile: 'Age: 42',
        llmConfig: { provider: 'backend', model: 'default' },
        properties: {},
        history: {},
        memory: [],
        knowledgeBase: [],
      },
      {
        id: '35',
        name: 'Li Hua',
        role: '',
        avatarUrl: '',
        profile: 'Age: 51',
        llmConfig: { provider: 'backend', model: 'default' },
        properties: {},
        history: {},
        memory: [],
        knowledgeBase: [],
      },
    ];
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('', { status: 404, statusText: 'Not Found' }))
      .mockResolvedValueOnce(new Response('', { status: 404, statusText: 'Not Found' }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'gaworld', default_agents: defaultAgents }), { status: 200 }));

    const result = await getScenarioDefaultAgents('gaworld', '35');

    expect(result).toEqual([defaultAgents[1]]);
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/scenarios/gaworld');
  });
});
