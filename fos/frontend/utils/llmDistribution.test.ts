/**
 * Unit tests for LLM distribution functionality.
 *
 * Tests the largest-remainder algorithm for fair distribution
 * of LLM providers across agents.
 */

import { describe, it, expect } from 'vitest';
import { applyLlmDistribution, type LLMAllocation } from './llmDistribution';

interface Agent {
  id: string;
  name: string;
  llmConfig?: { provider: string; model: string };
  provider_id?: number;
  properties?: Record<string, unknown>;
}

describe('LLM Distribution - Largest Remainder Algorithm', () => {
  const defaultConfig = { provider: 'default', model: 'default-model' };

  describe('Default behavior (no allocations)', () => {
    it('should apply default config to all agents when no allocations provided', () => {
      const agents: Agent[] = [
        { id: '1', name: 'Agent 1' },
        { id: '2', name: 'Agent 2' },
        { id: '3', name: 'Agent 3' }
      ];

      const result = applyLlmDistribution(agents, [], 'sim-1', defaultConfig);

      expect(result).toHaveLength(3);
      result.forEach(agent => {
        expect(agent.llmConfig).toEqual(defaultConfig);
      });
    });
  });

  describe('Validation', () => {
    it('should throw error if allocations do not sum to 100%', () => {
      const agents: Agent[] = [
        { id: '1', name: 'Agent 1' },
        { id: '2', name: 'Agent 2' }
      ];

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 30 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 30 }
      ];

      expect(() => applyLlmDistribution(agents, allocations, 'sim-1', defaultConfig))
        .toThrow('LLM allocations must sum to 100%');
    });
  });

  describe('Distribution correctness', () => {
    it('should distribute evenly when 50/50 split', () => {
      const agents: Agent[] = Array.from({ length: 10 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 50 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 50 }
      ];

      const result = applyLlmDistribution(agents, allocations, 'sim-test', defaultConfig);

      const openaiCount = result.filter(a => a.llmConfig?.provider === 'OpenAI').length;
      const anthropicCount = result.filter(a => a.llmConfig?.provider === 'Anthropic').length;

      expect(openaiCount).toBe(5);
      expect(anthropicCount).toBe(5);
    });

    it('should use largest-remainder method for 33/33/34 split across 10 agents', () => {
      const agents: Agent[] = Array.from({ length: 10 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 33 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 33 },
        { providerId: 3, providerName: 'Google', modelName: 'gemini', percentage: 34 }
      ];

      const result = applyLlmDistribution(agents, allocations, 'sim-test', defaultConfig);

      const openaiCount = result.filter(a => a.llmConfig?.provider === 'OpenAI').length;
      const anthropicCount = result.filter(a => a.llmConfig?.provider === 'Anthropic').length;
      const googleCount = result.filter(a => a.llmConfig?.provider === 'Google').length;

      // 33% of 10 = 3.3 -> floor 3, remainder 0.3
      // 34% of 10 = 3.4 -> floor 3, remainder 0.4
      // Total floors = 9, leftover = 1
      // Largest remainder (0.4) gets the extra slot
      expect(openaiCount).toBe(3);
      expect(anthropicCount).toBe(3);
      expect(googleCount).toBe(4);
    });

    it('should ensure total assignments equals agent count (no gaps or overflow)', () => {
      // Test with odd percentages
      const agents: Agent[] = Array.from({ length: 17 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 41 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 35 },
        { providerId: 3, providerName: 'Google', modelName: 'gemini', percentage: 24 }
      ];

      const result = applyLlmDistribution(agents, allocations, 'sim-test', defaultConfig);

      const openaiCount = result.filter(a => a.llmConfig?.provider === 'OpenAI').length;
      const anthropicCount = result.filter(a => a.llmConfig?.provider === 'Anthropic').length;
      const googleCount = result.filter(a => a.llmConfig?.provider === 'Google').length;

      // Total should equal agent count
      expect(openaiCount + anthropicCount + googleCount).toBe(17);
    });
  });

  describe('Reproducibility', () => {
    it('should produce same shuffle for same simulation ID', () => {
      const agents: Agent[] = Array.from({ length: 10 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 50 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 50 }
      ];

      const result1 = applyLlmDistribution(agents, allocations, 'same-sim-id', defaultConfig);
      const result2 = applyLlmDistribution(agents, allocations, 'same-sim-id', defaultConfig);

      // Same seed should produce same order
      const providers1 = result1.map(a => a.llmConfig?.provider);
      const providers2 = result2.map(a => a.llmConfig?.provider);

      expect(providers1).toEqual(providers2);
    });

    it('should produce different shuffle for different simulation ID', () => {
      const agents: Agent[] = Array.from({ length: 10 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 50 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 50 }
      ];

      const result1 = applyLlmDistribution(agents, allocations, 'sim-id-1', defaultConfig);
      const result2 = applyLlmDistribution(agents, allocations, 'sim-id-2', defaultConfig);

      // Different seeds should produce different orders (highly likely)
      const providers1 = result1.map(a => a.llmConfig?.provider).join(',');
      const providers2 = result2.map(a => a.llmConfig?.provider).join(',');

      expect(providers1).not.toEqual(providers2);
    });
  });

  describe('Edge cases', () => {
    it('should handle single agent', () => {
      const agents: Agent[] = [{ id: '1', name: 'Agent 1' }];

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 100 }
      ];

      const result = applyLlmDistribution(agents, allocations, 'sim-test', defaultConfig);

      expect(result).toHaveLength(1);
      expect(result[0].llmConfig?.provider).toBe('OpenAI');
    });

    it('should handle single LLM at 100%', () => {
      const agents: Agent[] = Array.from({ length: 20 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 100 }
      ];

      const result = applyLlmDistribution(agents, allocations, 'sim-test', defaultConfig);

      result.forEach(agent => {
        expect(agent.llmConfig?.provider).toBe('OpenAI');
      });
    });

    it('should handle 100 agents with multiple LLMs', () => {
      const agents: Agent[] = Array.from({ length: 100 }, (_, i) => ({
        id: `${i + 1}`,
        name: `Agent ${i + 1}`
      }));

      const allocations: LLMAllocation[] = [
        { providerId: 1, providerName: 'OpenAI', modelName: 'gpt-4', percentage: 25 },
        { providerId: 2, providerName: 'Anthropic', modelName: 'claude-3', percentage: 25 },
        { providerId: 3, providerName: 'Google', modelName: 'gemini', percentage: 25 },
        { providerId: 4, providerName: 'Meta', modelName: 'llama-3', percentage: 25 }
      ];

      const result = applyLlmDistribution(agents, allocations, 'sim-test', defaultConfig);

      const counts: Record<string, number> = {};
      result.forEach(agent => {
        const provider = agent.llmConfig?.provider || 'unknown';
        counts[provider] = (counts[provider] || 0) + 1;
      });

      // Each should have exactly 25 agents
      expect(counts['OpenAI']).toBe(25);
      expect(counts['Anthropic']).toBe(25);
      expect(counts['Google']).toBe(25);
      expect(counts['Meta']).toBe(25);
    });
  });
});
