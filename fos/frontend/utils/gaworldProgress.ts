/**
 * GAWorld run-progress snapshot helpers (UI half of the progress fix).
 *
 * The backend writes `gaworld_wait_status.json` for a running GAWorld node
 * (day/ticks/schedules/log-age). Until a status endpoint serves those fields,
 * the UI consumes them defensively from the node's meta as a nullable
 * snapshot object: every field is optional and missing fields simply hide
 * their line. No fake percentages or numbers are ever produced here.
 */

export interface GaworldProgressSnapshot {
  status?: string;
  target_day?: number | null;
  elapsed_s?: number | null;
  last_day?: number | null;
  schedule_tick_count?: number | null;
  agent_schedule_count?: number | null;
  log_age_s?: number | null;
  latest_agent_log_age_s?: number | null;
  observed_file_change?: boolean | null;
  [key: string]: unknown;
}

export type GaworldProgressLineKey = 'day' | 'ticks' | 'schedules' | 'elapsed' | 'lastProgress';

export interface GaworldProgressLine {
  key: GaworldProgressLineKey;
  value: number;
}

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/** Node statuses during which the wait-status endpoint should be polled. */
export const GAWORLD_ACTIVE_STATUSES: readonly string[] = ["queued", "running"];

export const isGaworldActiveStatus = (status: string | null | undefined): boolean =>
  typeof status === "string" && GAWORLD_ACTIVE_STATUSES.includes(status);

/**
 * Picks the snapshot to render: the polled endpoint snapshot wins when it is
 * a usable object; otherwise fall back to whatever the node meta carries.
 * An unavailable/absent polled snapshot yields null (nothing is rendered,
 * never fabricated numbers).
 */
export function pickGaworldProgressSnapshot(
  node: { meta?: Record<string, any> | null } | null | undefined,
  polled: unknown,
): GaworldProgressSnapshot | null {
  if (polled && typeof polled === "object" && !Array.isArray(polled)) {
    return polled as GaworldProgressSnapshot;
  }
  return extractGaworldProgress(node);
}

/**
 * Extracts the progress snapshot from a node, tolerating several meta keys
 * and any absent/invalid shape. Returns null when there is nothing to show.
 */
export function extractGaworldProgress(
  node: { meta?: Record<string, any> | null } | null | undefined,
): GaworldProgressSnapshot | null {
  const meta = (node?.meta ?? null) as Record<string, any> | null;
  if (!meta || typeof meta !== 'object') return null;
  const snapshot = (meta.gaworld_progress ?? meta.gaworld_wait_status ?? null) as
    | GaworldProgressSnapshot
    | null;
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return null;
  return snapshot;
}

/**
 * Turns a snapshot into the ordered list of renderable lines. Fields that are
 * missing or non-numeric are dropped, so a null/partial snapshot degrades
 * gracefully (renders nothing, never fabricated numbers).
 */
export function gaworldProgressLines(
  snapshot: GaworldProgressSnapshot | null | undefined,
): GaworldProgressLine[] {
  if (!snapshot) return [];
  const lines: GaworldProgressLine[] = [];
  if (isFiniteNumber(snapshot.last_day)) {
    lines.push({ key: 'day', value: snapshot.last_day });
  }
  if (isFiniteNumber(snapshot.schedule_tick_count)) {
    lines.push({ key: 'ticks', value: snapshot.schedule_tick_count });
  }
  if (isFiniteNumber(snapshot.agent_schedule_count)) {
    lines.push({ key: 'schedules', value: snapshot.agent_schedule_count });
  }
  if (isFiniteNumber(snapshot.elapsed_s)) {
    lines.push({ key: 'elapsed', value: snapshot.elapsed_s });
  }
  const lastAge = isFiniteNumber(snapshot.latest_agent_log_age_s)
    ? snapshot.latest_agent_log_age_s
    : isFiniteNumber(snapshot.log_age_s)
      ? snapshot.log_age_s
      : null;
  if (lastAge !== null) {
    lines.push({ key: 'lastProgress', value: Math.max(0, Math.round(lastAge)) });
  }
  return lines;
}
