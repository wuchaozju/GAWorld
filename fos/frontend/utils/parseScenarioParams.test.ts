import { describe, it, expect } from 'vitest';
import { parseScenarioParams, findUnknownKeys } from './parseScenarioParams';

describe('parseScenarioParams — type coercion', () => {
  it('coerces integer strings to number', () => {
    expect(parseScenarioParams('x=5')).toEqual({ x: 5 });
    expect(parseScenarioParams('x=-3')).toEqual({ x: -3 });
  });

  it('coerces float strings to number', () => {
    expect(parseScenarioParams('x=1.5')).toEqual({ x: 1.5 });
    expect(parseScenarioParams('x=-0.1')).toEqual({ x: -0.1 });
  });

  it('coerces "true" and "false" to boolean', () => {
    expect(parseScenarioParams('a=true\nb=false')).toEqual({ a: true, b: false });
  });

  it('leaves non-numeric non-boolean values as strings', () => {
    expect(parseScenarioParams('mode=cooperative')).toEqual({ mode: 'cooperative' });
  });

  it('handles multiple params', () => {
    const result = parseScenarioParams('cooperate_reward=5\nmultiplier=1.5\ndebug=true');
    expect(result).toEqual({ cooperate_reward: 5, multiplier: 1.5, debug: true });
  });
});

describe('parseScenarioParams — ignored lines', () => {
  it('ignores blank lines', () => {
    expect(parseScenarioParams('\n\nx=1\n\n')).toEqual({ x: 1 });
  });

  it('ignores comment lines starting with #', () => {
    expect(parseScenarioParams('# this is a comment\nx=1')).toEqual({ x: 1 });
  });

  it('ignores lines without =', () => {
    expect(parseScenarioParams('noequals\nx=1')).toEqual({ x: 1 });
  });

  it('returns empty object for empty input', () => {
    expect(parseScenarioParams('')).toEqual({});
  });
});

describe('findUnknownKeys', () => {
  const base = { cooperate_reward: 3, multiplier: 2.0, n_rounds: 10 };

  it('returns empty when all keys are known', () => {
    expect(findUnknownKeys({ cooperate_reward: 5 }, base)).toEqual([]);
  });

  it('flags keys not present in base config', () => {
    expect(findUnknownKeys({ cooperate_rewrad: 5 }, base)).toEqual(['cooperate_rewrad']);
  });

  it('handles empty params', () => {
    expect(findUnknownKeys({}, base)).toEqual([]);
  });

  it('treats public goods average contribution as known for older saved configs', () => {
    expect(
      findUnknownKeys(
        { show_average_contribution: true },
        { resource_name: 'tokens', tokens_per_round: 10, multiplier: 1.3 },
      ),
    ).toEqual([]);
  });
});
