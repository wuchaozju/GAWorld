/**
 * This file manages GAWorld population selection for the experiment builder.
 *
 * - loadPopulations lists the GAWorld cities/populations.
 * - chooseCity + loadAgents page through one city's residents.
 * - select/deselect keep exact GAWorld agent ids; the selection survives
 *   pagination (ids are stored independently of the visible page).
 * - startGeneration creates a GAWorld population job and polls it to
 *   completion.
 * - toAgentConfigs maps selected residents to FOS agent configs carrying
 *   properties.gaworld_agent_id with the original number id.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  GAWorldUnavailableError,
  getAgentDetail,
  loadAgents as fetchAgents,
  loadPopulations as fetchPopulations,
  pollGeneration,
  startGeneration as postStartGeneration,
  type GAWorldAgent,
  type GAWorldPopulation,
  type GenerationJobStatus,
} from '../../services/gaworldPopulation';

const POLL_INTERVAL_MS = 100;
const DEFAULT_PAGE_SIZE = 50;

export interface GAWorldAgentConfig {
  id: number;
  name: string;
  profile: string;
  role_prompt: string;
  properties: Record<string, unknown> & { gaworld_agent_id: number };
  llm_config: Record<string, never>;
}

export interface UseGAWorldPopulation {
  populations: GAWorldPopulation[];
  city: string;
  agents: GAWorldAgent[];
  total: number;
  limit: number;
  offset: number;
  selectedIds: number[];
  isSelected: (id: number) => boolean;
  toggle: (id: number) => void;
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
  generation: { jobId: string; status: string } | null;
  loadPopulations: () => Promise<void>;
  chooseCity: (slug: string) => Promise<void>;
  loadAgents: (opts?: { limit?: number; offset?: number }) => Promise<void>;
  select: (id: number) => void;
  deselect: (id: number) => void;
  startGeneration: (spec: Record<string, unknown>) => Promise<void>;
  getAgentDetail: (id: number) => ReturnType<typeof getAgentDetail>;
  toAgentConfigs: (agentsById?: Map<number, GAWorldAgent>) => GAWorldAgentConfig[];
}

export function useGAWorldPopulation(): UseGAWorldPopulation {
  const [populations, setPopulations] = useState<GAWorldPopulation[]>([]);
  const [city, setCity] = useState('');
  const [agents, setAgents] = useState<GAWorldAgent[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [offset, setOffset] = useState(0);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState<{ jobId: string; status: string } | null>(null);

  // Every agent ever seen, so the selection can be mapped to configs even
  // after the user turns the page.
  const agentsByIdRef = useRef<Map<number, GAWorldAgent>>(new Map());
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current);
    }
  }, []);

  const rememberAgents = useCallback((pageAgents: GAWorldAgent[]) => {
    for (const agent of pageAgents) {
      agentsByIdRef.current.set(agent.id, agent);
    }
  }, []);

  const loadPopulations = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      const page = await fetchPopulations();
      setPopulations(page.populations || []);
      setStatus('ready');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('error');
      if (!(err instanceof GAWorldUnavailableError)) {
        throw err;
      }
    }
  }, []);

  const loadAgents = useCallback(
    async (opts?: { limit?: number; offset?: number }) => {
      const nextLimit = opts?.limit ?? limit;
      const nextOffset = opts?.offset ?? 0;
      setStatus('loading');
      setError(null);
      try {
        const page = await fetchAgents(city, { limit: nextLimit, offset: nextOffset });
        rememberAgents(page.agents || []);
        setAgents(page.agents || []);
        setTotal(page.total ?? (page.agents || []).length);
        setLimit(page.limit ?? nextLimit);
        setOffset(page.offset ?? nextOffset);
        setStatus('ready');
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err));
        setStatus('error');
        if (!(err instanceof GAWorldUnavailableError)) {
          throw err;
        }
      }
    },
    [city, limit, rememberAgents],
  );

  const chooseCity = useCallback(
    async (slug: string) => {
      setCity(slug);
      setOffset(0);
      const params = { limit: limit, offset: 0 };
      setStatus('loading');
      setError(null);
      try {
        const page = await fetchAgents(slug, params);
        rememberAgents(page.agents || []);
        setAgents(page.agents || []);
        setTotal(page.total ?? (page.agents || []).length);
        setLimit(page.limit ?? limit);
        setOffset(page.offset ?? 0);
        setStatus('ready');
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err));
        setStatus('error');
        if (!(err instanceof GAWorldUnavailableError)) {
          throw err;
        }
      }
    },
    [limit, rememberAgents],
  );

  const select = useCallback((id: number) => {
    setSelectedIds((current) => (current.includes(id) ? current : [...current, id]));
  }, []);

  const deselect = useCallback((id: number) => {
    setSelectedIds((current) => current.filter((value) => value !== id));
  }, []);

  const toggle = useCallback(
    (id: number) => {
      if (selectedIds.includes(id)) {
        deselect(id);
      } else {
        select(id);
      }
    },
    [deselect, select, selectedIds],
  );

  const isSelected = useCallback((id: number) => selectedIds.includes(id), [selectedIds]);

  const pollJob = useCallback((jobId: string) => {
    pollTimerRef.current = setTimeout(async () => {
      try {
        const statusUpdate: GenerationJobStatus = await pollGeneration(jobId);
        setGeneration({ jobId, status: statusUpdate.status });
        if (statusUpdate.status === 'running' || statusUpdate.status === 'queued') {
          pollJob(jobId);
        }
      } catch {
        setGeneration({ jobId, status: 'failed' });
      }
    }, POLL_INTERVAL_MS);
  }, []);

  const startGeneration = useCallback(
    async (spec: Record<string, unknown>) => {
      setError(null);
      const ref = await postStartGeneration(spec);
      setGeneration({ jobId: ref.jobId, status: ref.status });
      if (ref.status === 'running' || ref.status === 'queued') {
        pollJob(ref.jobId);
      }
    },
    [pollJob],
  );

  const toAgentConfigs = useCallback(
    (agentsById?: Map<number, GAWorldAgent>): GAWorldAgentConfig[] => {
      const source = agentsById ?? agentsByIdRef.current;
      return selectedIds
        .map((id) => {
          const agent = source.get(id);
          if (!agent) {
            return null;
          }
          const profileText = String(agent.profile_text ?? '');
          const properties: GAWorldAgentConfig['properties'] = { gaworld_agent_id: agent.id };
          if (agent.gender !== undefined) {
            properties.gender = agent.gender;
          }
          if (agent.age !== undefined) {
            properties.age = agent.age;
          }
          if (agent.job !== undefined) {
            properties.job = agent.job;
          }
          if (agent.residence !== undefined) {
            properties.residence = agent.residence;
          }
          return {
            id: agent.id,
            name: String(agent.name ?? ''),
            profile: profileText,
            role_prompt: profileText,
            properties,
            llm_config: {} as Record<string, never>,
          };
        })
        .filter((config): config is GAWorldAgentConfig => config !== null);
    },
    [selectedIds],
  );

  return {
    populations,
    city,
    agents,
    total,
    limit,
    offset,
    selectedIds,
    isSelected,
    toggle,
    status,
    error,
    generation,
    loadPopulations,
    chooseCity,
    loadAgents,
    select,
    deselect,
    startGeneration,
    getAgentDetail: (id: number) => getAgentDetail(id, city),
    toAgentConfigs,
  };
}

export default useGAWorldPopulation;
