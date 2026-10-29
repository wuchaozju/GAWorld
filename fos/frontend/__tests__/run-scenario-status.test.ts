/**
 * This file checks how E2E scenario results are marked.
 *
 * The tests make sure warnings and backend failures stop a scenario from
 * being reported as passed.
 */

import { describe, expect, it } from 'vitest';

import {
  formatBackendRequestFailure,
  determineScenarioStatus,
  formatBackendResponseFailure,
  type ScenarioResult,
} from '../e2e/helpers/run-scenario';

function makeResult(overrides: Partial<ScenarioResult> = {}): ScenarioResult {
  return {
    id: 'policy_erosion',
    name: 'Policy Meaning Erosion',
    locale: 'en',
    status: 'unknown',
    uiErrors: [],
    warnings: [],
    backendErrors: [],
    testResultFiles: [],
    durationMs: 0,
    ...overrides,
  };
}

describe('determineScenarioStatus', () => {
  it('marks_clean_scenario_as_passed', () => {
    expect(determineScenarioStatus(makeResult())).toBe('passed');
  });

  it('marks_warning_as_ui_error', () => {
    const result = makeResult({
      warnings: ['Auto-advance failed: timeout'],
    });

    expect(determineScenarioStatus(result)).toBe('ui_errors');
  });

  it('marks_backend_failure_as_ui_error', () => {
    const result = makeResult({
      backendErrors: ['HTTP 500 GET /api/simulations/E6BF/tree/graph'],
    });

    expect(determineScenarioStatus(result)).toBe('ui_errors');
  });

  it('keeps_crashed_scenario_as_crashed', () => {
    const result = makeResult({
      status: 'crashed',
      uiErrors: ['Page crashed'],
    });

    expect(determineScenarioStatus(result)).toBe('crashed');
  });
});

describe('formatBackendResponseFailure', () => {
  it('shows_status_method_and_url_for_backend_failure', () => {
    const message = formatBackendResponseFailure(
      500,
      'GET',
      'http://127.0.0.1:8000/api/simulations/E6BF/tree/graph',
    );

    expect(message).toBe('HTTP 500 GET /api/simulations/E6BF/tree/graph');
  });
});

describe('formatBackendRequestFailure', () => {
  it('test_browser_cancelled_request_is_ignored', () => {
    expect(formatBackendRequestFailure(
      'GET',
      'http://127.0.0.1:5173/api/providers',
      'net::ERR_ABORTED',
    )).toBeNull();
  });

  it('test_navigation_cancelled_request_is_ignored', () => {
    expect(formatBackendRequestFailure(
      'GET',
      'http://127.0.0.1:5173/api/scenes',
      'NS_BINDING_ABORTED',
    )).toBeNull();
  });

  it.each([
    'net::ERR_CONNECTION_REFUSED',
    'net::ERR_NAME_NOT_RESOLVED',
    'net::ERR_TIMED_OUT',
  ])('test_real_network_failure_is_reported: %s', (failureText) => {
    expect(formatBackendRequestFailure(
      'GET',
      'http://127.0.0.1:5173/api/providers',
      failureText,
    )).toBe(`GET /api/providers: ${failureText}`);
  });
});
