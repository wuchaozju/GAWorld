/**
 * RED tests for the GAWorld population selection flow in Step 4 (task 2513).
 *
 * The hook under test does not exist yet. Assumed contract for the
 * implementer (all plain researcher-facing, brief §8/§11/§14):
 *
 *   useGAWorldPopulation() from frontend/components/experiment/useGAWorldPopulation.ts
 *
 *   state exposed:
 *     populations: {slug, name, population, selected}[]
 *     city: string                       — chosen city slug ("" = default world)
 *     agents: {id:number, name, ...}[]   — current page
 *     total / limit / offset
 *     selectedIds: number[]              — SURVIVES pagination, exact GAWorld ids
 *     isSelected(id: number) => boolean
 *     toggle(id: number) => void
 *     status: 'idle'|'loading'|'ready'|'error'
 *     error: string | null               — "GAWorld backend unavailable" when down
 *     generation: {jobId, status} | null — startGeneration → pollGeneration
 *   actions exposed:
 *     loadPopulations(), chooseCity(slug), loadAgents(page?),
 *     select(id), deselect(id), startGeneration(spec)
 *   mapping exposed:
 *     toAgentConfigs(agentsById) => FOS agent configs carrying
 *     properties.gaworld_agent_id with the ORIGINAL number id.
 *
 * These tests mock fetch (never the network) and use the service module
 * ./frontend/services/gaworldPopulation, so behaviour and wiring are
 * covered together.
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useGAWorldPopulation } from '../useGAWorldPopulation';

const POPULATIONS = {
  populations: [{ slug: 'liuxi-cun', name: '柳溪村', selected: false, population: 3 }],
  selected: 'liuxi-cun',
};

function page(offset: number) {
  return {
    city: { slug: 'liuxi-cun', name: '柳溪村' },
    total: 4,
    limit: 2,
    offset,
    agents:
      offset === 0
        ? [
            { id: 1, name: '李泽宇', gender: '男', age: 24 },
            { id: 2, name: '周婉清', gender: '女', age: 26 },
          ]
        : [
            { id: 3, name: '陈默', gender: '男', age: 31 },
            { id: 34, name: '徐桂兰', gender: '女', age: 42 },
          ],
  };
}

describe('useGAWorldPopulation', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('test_load_populations_then_choose_city', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify(POPULATIONS), { status: 200 })
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(page(0)), { status: 200 }));

    const { result } = renderHook(() => useGAWorldPopulation());

    await act(async () => {
      await result.current.loadPopulations();
    });
    expect(result.current.populations).toHaveLength(1);

    await act(async () => {
      await result.current.chooseCity('liuxi-cun');
    });
    expect(result.current.city).toBe('liuxi-cun');
    expect(result.current.agents).toHaveLength(2);
    expect((fetchMock.mock.calls[1][0] as string).toContain('city=liuxi-cun'));
  });

  it('test_selection_survives_pagination', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(POPULATIONS), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(page(0)), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(page(2)), { status: 200 }));

    const { result } = renderHook(() => useGAWorldPopulation());
    await act(async () => {
      await result.current.loadPopulations();
      await result.current.chooseCity('liuxi-cun');
    });
    act(() => {
      result.current.select(2);
      result.current.select(34);
    });
    expect(result.current.selectedIds).toEqual([2, 34]);

    // Turn the page — the agent list changes but the selection must not.
    await act(async () => {
      await result.current.loadAgents({ offset: 2 });
    });
    expect(result.current.agents.map((a) => a.id)).toEqual([3, 34]);
    expect(result.current.selectedIds).toEqual([2, 34]);
  });

  it('test_start_generation_polls_to_completion', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(POPULATIONS), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(page(0)), { status: 200 }))
      // POST generate → 202 job ref
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: 'pop-ab12cd34', status: 'running' }), { status: 202 })
      )
      // first poll: running
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: 'pop-ab12cd34', status: 'running', progress: 0.4 }), {
          status: 200,
        })
      )
      // second poll: completed
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: 'pop-ab12cd34', status: 'completed', progress: 1 }), {
          status: 200,
        })
      );

    const { result } = renderHook(() => useGAWorldPopulation());
    await act(async () => {
      await result.current.loadPopulations();
      await result.current.chooseCity('liuxi-cun');
    });

    await act(async () => {
      await result.current.startGeneration({ size: 30 });
    });
    expect(result.current.generation?.jobId).toBe('pop-ab12cd34');
    await waitFor(() => {
      expect(result.current.generation?.status).toBe('completed');
    });
  });

  it('test_unavailable_shows_error_not_snapshot_fallback', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'GAWorld backend unavailable' }), { status: 503 })
    );

    const { result } = renderHook(() => useGAWorldPopulation());
    await act(async () => {
      await result.current.loadPopulations().catch(() => undefined);
    });
    expect(result.current.status).toBe('error');
    expect(result.current.error).toContain('GAWorld');
    expect(result.current.agents).toHaveLength(0); // no silent snapshot fallback
  });

  it('test_stored_config_uses_gaworld_ids_not_positions_or_names', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify(POPULATIONS), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(page(0)), { status: 200 }));

    const { result } = renderHook(() => useGAWorldPopulation());
    await act(async () => {
      await result.current.loadPopulations();
      await result.current.chooseCity('liuxi-cun');
    });
    act(() => {
      result.current.select(2);
    });

    const configs = result.current.toAgentConfigs();
    expect(configs).toHaveLength(1);
    expect(configs[0].properties.gaworld_agent_id).toBe(2); // exact GAWorld id, a number
  });
});
