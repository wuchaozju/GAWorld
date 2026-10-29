/**
 * Tests for the GAWorld population API service.
 *
 * Written TDD-RED for Phase 3 STAGE A (task 2513). The service module
 * `./gaworldPopulation` does not exist yet — these tests specify its
 * contract against the REAL GAWorld dashboard API (recorded from
 * gaworld/apps/city_api.py and gaworld/apps/population_api.py):
 *
 * - loadPopulations()          GET /api/scenarios/gaworld/populations
 * - loadAgents(city, opts)     GET /api/scenarios/gaworld/agents?city=&limit=&offset=
 * - getAgentDetail(id, city)   GET /api/scenarios/gaworld/agents/{id}?city=
 * - startGeneration(spec)      POST /api/scenarios/gaworld/populations/generate
 * - pollGeneration(jobId)      GET /api/scenarios/gaworld/populations/jobs/{jobId}
 *
 * GAWorld agent ids are ints end to end. A down GAWorld raises
 * GAWorldUnavailableError (never silently falls back to the snapshot).
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  GAWorldUnavailableError,
  getAgentDetail,
  loadAgents,
  loadPopulations,
  pollGeneration,
  startGeneration,
} from './gaworldPopulation';

const POPULATIONS = {
  populations: [
    { slug: 'liuxi-cun', name: '柳溪村', selected: false, population: 3 },
  ],
  selected: 'liuxi-cun',
};

const AGENTS_PAGE = {
  city: { slug: 'liuxi-cun', name: '柳溪村' },
  total: 3,
  limit: 2,
  offset: 1,
  agents: [
    { id: 2, name: '周婉清', gender: '女', age: 26 },
    { id: 34, name: '徐桂兰', gender: '女', age: 42 },
  ],
};

function mockFetchOnce(status: number, payload: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
    new Response(JSON.stringify(payload), {
      status,
      statusText: status === 200 ? 'OK' : 'Service Unavailable',
    })
  );
}

describe('gaworldPopulation service', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('test_load_populations', async () => {
    const fetchMock = mockFetchOnce(200, POPULATIONS);
    const result = await loadPopulations();
    expect(result.populations[0].slug).toBe('liuxi-cun');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/scenarios/gaworld/populations',
      expect.anything()
    );
  });

  it('test_load_agents_passes_city_limit_offset', async () => {
    const fetchMock = mockFetchOnce(200, AGENTS_PAGE);
    const result = await loadAgents('liuxi-cun', { limit: 2, offset: 1 });
    expect(result.agents.map((a) => a.id)).toEqual([2, 34]);
    expect(result.total).toBe(3);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain('city=liuxi-cun');
    expect(url).toContain('limit=2');
    expect(url).toContain('offset=1');
  });

  it('test_load_agents_keeps_exact_gaworld_ids_as_numbers', async () => {
    mockFetchOnce(200, AGENTS_PAGE);
    const result = await loadAgents('liuxi-cun');
    expect(result.agents.every((a) => typeof a.id === 'number')).toBe(true);
  });

  it('test_get_agent_detail', async () => {
    const fetchMock = mockFetchOnce(200, {
      city: { slug: 'liuxi-cun', name: '柳溪村' },
      agent: { id: 34, name: '徐桂兰', profile_text: '# 徐桂兰' },
    });
    const detail = await getAgentDetail(34, 'liuxi-cun');
    expect(detail.agent.id).toBe(34);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toContain('/scenarios/gaworld/agents/34');
    expect(url).toContain('city=liuxi-cun');
  });

  it('test_start_generation_returns_job_ref', async () => {
    const fetchMock = mockFetchOnce(202, { job_id: 'pop-ab12cd34', status: 'running' });
    const ref = await startGeneration({ size: 30 });
    expect(ref.jobId).toBe('pop-ab12cd34');
    expect(ref.status).toBe('running');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/scenarios/gaworld/populations/generate');
    expect(init.method).toBe('POST');
  });

  it('test_poll_generation_maps_done_to_completed', async () => {
    mockFetchOnce(200, { job_id: 'pop-ab12cd34', status: 'completed', progress: 1 });
    const status = await pollGeneration('pop-ab12cd34');
    expect(status.status).toBe('completed');
  });

  it('test_poll_generation_maps_error_to_failed', async () => {
    mockFetchOnce(200, { job_id: 'pop-ab12cd34', status: 'failed', message: '合成失败' });
    const status = await pollGeneration('pop-ab12cd34');
    expect(status.status).toBe('failed');
  });

  it('test_unavailable_raises_typed_error', async () => {
    mockFetchOnce(503, { error: 'GAWorld backend unavailable' });
    await expect(loadAgents('liuxi-cun')).rejects.toBeInstanceOf(GAWorldUnavailableError);
  });
});
