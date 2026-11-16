/**
 * This file checks provider service calls.
 *
 * - The first test checks that createProvider sends the exact payload.
 * - The second test checks that updateProvider does not hide request failures.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from './client';
import { createProvider, updateProvider } from './providers';

vi.mock('./client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('provider services', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('test_create_provider_sends_the_payload_to_the_backend', async () => {
    const provider = {
      id: 1,
      name: 'Local Ollama',
      provider: 'ollama',
      model: 'llama3',
      base_url: 'http://localhost:11434',
      has_api_key: false,
    };
    const payload = {
      name: 'Local Ollama',
      provider: 'ollama',
      model: 'llama3',
      base_url: 'http://localhost:11434',
      api_key: null,
    };
    vi.mocked(apiClient.post).mockResolvedValue({ data: provider });

    const result = await createProvider(payload);

    expect(apiClient.post).toHaveBeenCalledWith('providers', payload);
    expect(result).toEqual(provider);
  });

  it('test_update_provider_does_not_hide_backend_errors', async () => {
    const error = new Error('backend rejected provider');
    vi.mocked(apiClient.patch).mockRejectedValue(error);

    await expect(updateProvider(7, { model: 'gemini-pro' })).rejects.toThrow(
      'backend rejected provider',
    );
  });
});
