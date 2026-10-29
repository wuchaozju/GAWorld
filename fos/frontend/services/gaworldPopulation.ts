/**
 * GAWorld population API service.
 *
 * Talks to the FOS backend's live GAWorld population endpoints:
 * - loadPopulations()          GET /api/scenarios/gaworld/populations
 * - loadAgents(city, opts)     GET /api/scenarios/gaworld/agents?city=&limit=&offset=
 * - getAgentDetail(id, city)   GET /api/scenarios/gaworld/agents/{id}?city=
 * - startGeneration(spec)      POST /api/scenarios/gaworld/populations/generate
 * - pollGeneration(jobId)      GET /api/scenarios/gaworld/populations/jobs/{jobId}
 *
 * GAWorld agent ids are ints end to end. A down GAWorld raises
 * GAWorldUnavailableError — never a silent fallback to the bundled snapshot.
 */

import { getApiBase } from './base';

const API_BASE = getApiBase().replace(/\/+$/, '');

export class GAWorldUnavailableError extends Error {
  constructor(message = 'GAWorld backend unavailable') {
    super(message);
    this.name = 'GAWorldUnavailableError';
  }
}

export interface GAWorldPopulation {
  slug: string;
  name: string;
  display_name?: string;
  population: number;
  selected?: boolean;
}

export interface GAWorldPopulationsPage {
  populations: GAWorldPopulation[];
  selected: string;
}

export interface GAWorldAgent {
  id: number;
  name: string;
  gender?: string;
  age?: number;
  job?: string;
  residence?: string;
  [key: string]: unknown;
}

export interface GAWorldAgentsPage {
  city: { slug: string; name: string; selected?: boolean };
  total: number;
  limit: number;
  offset: number;
  agents: GAWorldAgent[];
}

export interface GAWorldAgentDetail {
  city: { slug: string; name: string };
  agent: GAWorldAgent & { profile_text?: string };
}

export interface GenerationJobRef {
  jobId: string;
  status: string;
}

export interface GenerationJobStatus {
  jobId?: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress?: number;
  message?: string;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (error: unknown) {
    throw new GAWorldUnavailableError(
      `GAWorld backend unavailable: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (response.status === 503) {
    throw new GAWorldUnavailableError('GAWorld backend unavailable');
  }
  if (!response.ok) {
    throw new Error(`GAWorld request failed (${response.status}): ${url}`);
  }
  return (await response.json()) as T;
}

/** List the GAWorld cities/populations that can seed an experiment. */
export async function loadPopulations(): Promise<GAWorldPopulationsPage> {
  return requestJson<GAWorldPopulationsPage>(`${API_BASE}/scenarios/gaworld/populations`);
}

/** Load one page of a city's agents; GAWorld ids come back as exact numbers. */
export async function loadAgents(
  city: string,
  opts?: { limit?: number; offset?: number },
): Promise<GAWorldAgentsPage> {
  const params = new URLSearchParams();
  params.set('city', city || '');
  params.set('limit', String(opts?.limit ?? 200));
  params.set('offset', String(opts?.offset ?? 0));
  return requestJson<GAWorldAgentsPage>(
    `${API_BASE}/scenarios/gaworld/agents?${params.toString()}`,
  );
}

/** Fetch one agent's full detail (including profile text). */
export async function getAgentDetail(id: number, city?: string): Promise<GAWorldAgentDetail> {
  const params = new URLSearchParams();
  if (city) {
    params.set('city', city);
  }
  const query = params.toString();
  return requestJson<GAWorldAgentDetail>(
    `${API_BASE}/scenarios/gaworld/agents/${id}${query ? `?${query}` : ''}`,
  );
}

/** Start a GAWorld population generation job. */
export async function startGeneration(spec: Record<string, unknown>): Promise<GenerationJobRef> {
  const payload = await requestJson<{ job_id: string; status: string }>(
    `${API_BASE}/scenarios/gaworld/populations/generate`,
    { method: 'POST', body: JSON.stringify({ spec }) },
  );
  return { jobId: payload.job_id, status: payload.status };
}

/** Poll one generation job; the backend maps done→completed, error→failed. */
export async function pollGeneration(jobId: string): Promise<GenerationJobStatus> {
  const payload = await requestJson<{
    job_id?: string;
    status: string;
    progress?: number;
    message?: string;
  }>(`${API_BASE}/scenarios/gaworld/populations/jobs/${encodeURIComponent(jobId)}`);
  const status = payload.status as GenerationJobStatus['status'];
  return {
    jobId: payload.job_id ?? jobId,
    status,
    progress: payload.progress,
    message: payload.message,
  };
}
