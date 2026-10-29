import { describe, it, expect } from 'vitest';
import { extractApiErrorMessage, getBackendErrorDetail } from './apiError';

describe('extractApiErrorMessage', () => {
  it('returns response.data.error when present', () => {
    const e = Object.assign(new Error('Request failed with status code 500'), {
      response: { data: { error: 'DeepSeek API: 401 Unauthorized' } },
    });
    expect(extractApiErrorMessage(e)).toBe('DeepSeek API: 401 Unauthorized');
  });
  it('returns response.data.detail when error is absent', () => {
    const e = Object.assign(new Error('Request failed with status code 404'), {
      response: { data: { detail: 'Not found' } },
    });
    expect(extractApiErrorMessage(e)).toBe('Not found');
  });
  it('prefers error over detail when both are present', () => {
    const e = Object.assign(new Error('x'), {
      response: { data: { error: 'real error', detail: 'secondary' } },
    });
    expect(extractApiErrorMessage(e)).toBe('real error');
  });
  it('falls back to the Error message when there is no response body', () => {
    expect(extractApiErrorMessage(new Error('network down'))).toBe('network down');
  });
  it('ignores non-string error/detail and uses the Error message', () => {
    const e = Object.assign(new Error('fallback msg'), {
      response: { data: { error: 123, detail: null } },
    });
    expect(extractApiErrorMessage(e)).toBe('fallback msg');
  });
  it('stringifies a non-Error value with no response', () => {
    expect(extractApiErrorMessage('boom')).toBe('boom');
  });
});

describe('getBackendErrorDetail', () => {
  it('returns response.data.error when present', () => {
    const e = Object.assign(new Error('x'), { response: { data: { error: 'boom' } } });
    expect(getBackendErrorDetail(e)).toBe('boom');
  });

  it('returns response.data.detail when error is absent', () => {
    const e = Object.assign(new Error('x'), { response: { data: { detail: 'nope' } } });
    expect(getBackendErrorDetail(e)).toBe('nope');
  });

  it('prefers error over detail when both present', () => {
    const e = Object.assign(new Error('x'), { response: { data: { error: 'a', detail: 'b' } } });
    expect(getBackendErrorDetail(e)).toBe('a');
  });

  it('returns null when there is no response body', () => {
    expect(getBackendErrorDetail(new Error('network'))).toBeNull();
  });

  it('returns null for non-string error/detail', () => {
    const e = Object.assign(new Error('x'), { response: { data: { error: 123, detail: null } } });
    expect(getBackendErrorDetail(e)).toBeNull();
  });

  it('returns response.data.message when error and detail are absent', () => {
    const e = Object.assign(new Error('x'), { response: { data: { message: 'msg from backend' } } });
    expect(getBackendErrorDetail(e)).toBe('msg from backend');
  });

  it('returns null for a non-object thrown value', () => {
    expect(getBackendErrorDetail('boom')).toBeNull();
  });
});
