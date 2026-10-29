import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useSimulationStore } from '../index';

describe('Auto-advance state management', () => {
  beforeEach(() => {
    useSimulationStore.setState({
      isAutoAdvancing: false,
      autoAdvanceTotal: 0,
      autoAdvanceCurrent: 0,
      highlightedNodeId: null,
    } as any);
  });

  it('should initialize with correct default values', () => {
    const state = useSimulationStore.getState() as any;
    expect(state.isAutoAdvancing).toBe(false);
    expect(state.autoAdvanceTotal).toBe(0);
    expect(state.autoAdvanceCurrent).toBe(0);
    expect(state.highlightedNodeId).toBeNull();
  });

  it('stopAutoAdvance should reset all auto-advance state', () => {
    useSimulationStore.setState({
      isAutoAdvancing: true,
      autoAdvanceTotal: 10,
      autoAdvanceCurrent: 5,
      highlightedNodeId: 'node-3',
    } as any);

    (useSimulationStore.getState() as any).stopAutoAdvance();

    const state = useSimulationStore.getState() as any;
    expect(state.isAutoAdvancing).toBe(false);
    expect(state.autoAdvanceTotal).toBe(0);
    expect(state.autoAdvanceCurrent).toBe(0);
    expect(state.highlightedNodeId).toBeNull();
  });

  it('startAutoAdvance should guard against missing simulation', async () => {
    useSimulationStore.setState({
      currentSimulation: null,
      selectedNodeId: null,
    } as any);

    await (useSimulationStore.getState() as any).startAutoAdvance(5);

    const state = useSimulationStore.getState() as any;
    expect(state.isAutoAdvancing).toBe(false);
  });

  it('startAutoAdvance should not start if already auto-advancing', async () => {
    useSimulationStore.setState({
      currentSimulation: { id: 'sim-1' },
      selectedNodeId: 'node-1',
      isAutoAdvancing: true,
    } as any);

    // Attempt to start again — should no-op
    await (useSimulationStore.getState() as any).startAutoAdvance(5);

    // Still just the old isAutoAdvancing state, autoAdvanceTotal not updated
    const state = useSimulationStore.getState() as any;
    expect(state.autoAdvanceTotal).toBe(0); // was never set by the second call
  });

  it('startAutoAdvance should clamp steps to 1–100', async () => {
    const mockAdvance = vi.fn().mockResolvedValue(undefined);
    const mockNotify = vi.fn();

    useSimulationStore.setState({
      currentSimulation: { id: 'sim-1' },
      selectedNodeId: 'node-1',
      nodes: [{ id: 'node-1' }],
      isAutoAdvancing: false,
      isGenerating: false,
      advanceSimulation: mockAdvance,
      addNotification: mockNotify,
    } as any);

    // Pass delayMs=100 (minimum) so 100 steps finish in ~10 s; extend timeout to 15 s
    await (useSimulationStore.getState() as any).startAutoAdvance(200, 100);

    // Should have called advanceSimulation 100 times (clamped from 200)
    expect(mockAdvance).toHaveBeenCalledTimes(100);
  }, 15000);

  it('should stop when stopAutoAdvance is called mid-loop', async () => {
    const mockAdvance = vi.fn().mockImplementation(async () => {
      // Simulate some work
      await new Promise((r) => setTimeout(r, 10));
    });
    const mockNotify = vi.fn();

    useSimulationStore.setState({
      currentSimulation: { id: 'sim-1' },
      selectedNodeId: 'node-1',
      nodes: [{ id: 'node-1' }],
      isAutoAdvancing: false,
      isGenerating: false,
      advanceSimulation: mockAdvance,
      addNotification: mockNotify,
    } as any);

    // Start with 50 steps, 100ms delay
    const promise = (useSimulationStore.getState() as any).startAutoAdvance(50, 100);

    // Stop after a short delay
    await new Promise((r) => setTimeout(r, 50));
    (useSimulationStore.getState() as any).stopAutoAdvance();

    await promise;

    // Should have been called fewer than 50 times
    expect(mockAdvance.mock.calls.length).toBeLessThan(50);
    expect((useSimulationStore.getState() as any).isAutoAdvancing).toBe(false);
  });

  it('should stop on advanceSimulation error', async () => {
    const mockAdvance = vi.fn()
      .mockResolvedValueOnce(undefined) // Step 1 succeeds
      .mockRejectedValueOnce(new Error('Backend timeout')); // Step 2 fails
    const mockNotify = vi.fn();

    useSimulationStore.setState({
      currentSimulation: { id: 'sim-1' },
      selectedNodeId: 'node-1',
      nodes: [{ id: 'node-1' }],
      isAutoAdvancing: false,
      isGenerating: false,
      advanceSimulation: mockAdvance,
      addNotification: mockNotify,
    } as any);

    await (useSimulationStore.getState() as any).startAutoAdvance(5, 100);

    expect(mockAdvance).toHaveBeenCalledTimes(2);
    expect((useSimulationStore.getState() as any).isAutoAdvancing).toBe(false);
    // In tests i18n may return the raw key or a translated string; check the call happened
    expect(mockNotify).toHaveBeenCalledWith('error', expect.any(String));
  });
});
