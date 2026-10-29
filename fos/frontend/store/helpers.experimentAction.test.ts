import { describe, expect, it } from 'vitest';
import { mapBackendEventsToLogs } from './helpers';

describe('mapBackendEventsToLogs - experiment_action', () => {
  it('includes summary and payoff in mapped action logs', () => {
    const logs = mapBackendEventsToLogs(
      [
        {
          type: 'experiment_action',
          data: {
            agent: 'Alice',
            action: 'contribute',
            summary: 'Alice chose contribute (amount=7, pool=main)',
            payoff: 18.25,
            round: 1,
          },
        },
      ],
      '1',
      1,
      [{ id: 'a1', name: 'Alice' } as any],
      true,
    );

    expect(logs).toHaveLength(1);
    expect(logs[0].content).toBe('Alice chose contribute (amount=7, pool=main) -> payoff=18.25');
  });
});
