/**
 * GAWorld run-progress rendering (task 2861).
 *
 * Covers the polled-snapshot path: while a node is queued/running the
 * NodeDetailPanel polls the backend wait-status endpoint and feeds the
 * returned `wait_status` into the same renderer. Each poll's snapshot must
 * produce the day/ticks/schedules/last-progress lines; an unavailable or
 * missing snapshot must render nothing (never fake numbers).
 */

import { describe, expect, it } from 'vitest';

import {
  gaworldProgressLines,
  isGaworldActiveStatus,
  pickGaworldProgressSnapshot,
} from '../gaworldProgress';

describe('polled wait-status snapshots', () => {
  it('renders a progression across successive polls (tick 2 → 3 → 4)', () => {
    const tick2 = {
      status: 'waiting',
      target_day: 5,
      elapsed_s: 120,
      last_day: 2,
      schedule_tick_count: 40,
      agent_schedule_count: 8,
      log_age_s: 3,
      latest_agent_log_age_s: 1,
    };
    const tick3 = { ...tick2, last_day: 3, schedule_tick_count: 61, agent_schedule_count: 12 };
    const tick4 = { ...tick2, last_day: 4, schedule_tick_count: 83, agent_schedule_count: 16 };

    const render = (snapshot: Record<string, unknown>) =>
      gaworldProgressLines(pickGaworldProgressSnapshot(null, snapshot)).map((l) => l.value);

    expect(render(tick2)).toEqual([2, 40, 8, 120, 1]);
    expect(render(tick3)).toEqual([3, 61, 12, 120, 1]);
    expect(render(tick4)).toEqual([4, 83, 16, 120, 1]);
  });

  it('renders nothing for an unavailable / null snapshot', () => {
    expect(gaworldProgressLines(pickGaworldProgressSnapshot(null, null))).toEqual([]);
    expect(gaworldProgressLines(pickGaworldProgressSnapshot(null, undefined))).toEqual([]);
    // A malformed polled payload degrades to nothing, never fabricated numbers.
    expect(gaworldProgressLines(pickGaworldProgressSnapshot(null, 'nope'))).toEqual([]);
    expect(gaworldProgressLines(pickGaworldProgressSnapshot(null, [1, 2, 3]))).toEqual([]);
  });

  it('prefers the polled snapshot over stale node meta', () => {
    const node = { meta: { gaworld_progress: { last_day: 1 } } };
    const lines = gaworldProgressLines(pickGaworldProgressSnapshot(node, { last_day: 4 }));
    expect(lines).toEqual([{ key: 'day', value: 4 }]);
  });

  it('falls back to node meta when no polled snapshot exists', () => {
    const node = { meta: { gaworld_wait_status: { last_day: 2, schedule_tick_count: 5 } } };
    const lines = gaworldProgressLines(pickGaworldProgressSnapshot(node, null));
    expect(lines).toEqual([
      { key: 'day', value: 2 },
      { key: 'ticks', value: 5 },
    ]);
  });
});

describe('poll gating', () => {
  it('polls only while the node is queued or running', () => {
    expect(isGaworldActiveStatus('queued')).toBe(true);
    expect(isGaworldActiveStatus('running')).toBe(true);
    expect(isGaworldActiveStatus('completed')).toBe(false);
    expect(isGaworldActiveStatus('failed')).toBe(false);
    expect(isGaworldActiveStatus(null)).toBe(false);
    expect(isGaworldActiveStatus(undefined)).toBe(false);
  });
});
