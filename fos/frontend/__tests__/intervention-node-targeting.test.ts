/**
 * Intervention targeting — selected-node + branch integration (task 2832).
 *
 * SPEC-gaworld-isolation-interventions.md invariant 2: an intervention
 * targets the SELECTED node — the request carries node_id = selectedNodeId;
 * no backend inference from "latest". Integration with the branch-selection
 * fix (dc2e20ff): branch from A → child B auto-selected → intervention X
 * must target B, never A or a sibling C.
 *
 * Mirrors frontend/__tests__/simtree-branch-selection.test.ts setup.
 * RED-note: the store already forwards selectedNodeId — these are REGRESSION
 * GUARDS that must stay green while the backend isolation work lands.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  applyEnvironmentEvent: vi.fn(),
  treeBranch: vi.fn(),
  getTreeGraph: vi.fn(),
}));

vi.mock("../services/environmentSuggestions", () => ({
  applyEnvironmentEvent: mocks.applyEnvironmentEvent,
}));

vi.mock("../services/simulationTree", () => mocks);

import { useSimulationStore } from "../store";

function graphWithNodes(ids: number[], root = 0) {
  const nodes = ids.map((id) => ({ id, depth: id }));
  const edges = nodes
    .filter((n) => n.id !== root)
    .map((n) => ({ from: n.id - 1, to: n.id }));
  return { root, nodes, edges, running: [] };
}

function seedState(selectedNodeId: string, nodeIds: number[]) {
  useSimulationStore.setState({
    currentSimulation: { id: "sim-1" },
    selectedNodeId,
    nodes: nodeIds.map((id) => ({
      id: String(id),
      display_id: String(id),
      parentId: id === 0 ? null : String(id - 1),
      depth: id,
      isLeaf: true,
      status: "completed",
    })) as any,
    isGenerating: false,
    engineConfig: { endpoint: "http://test", token: null },
    addNotification: vi.fn(),
    injectLog: vi.fn(),
  } as any);
}

const suggestionX = {
  event_type: "policy",
  description: "intervention X",
  severity: "info",
};

describe("intervention targets the selected node", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.applyEnvironmentEvent.mockResolvedValue({
      success: true,
      message: "ok",
    });
  });

  it("selected B → request node_id=B", async () => {
    seedState("2", [0, 1, 2]);
    await useSimulationStore.getState().applyEnvironmentSuggestion(suggestionX);
    expect(mocks.applyEnvironmentEvent).toHaveBeenCalledTimes(1);
    const [simId, payload] = mocks.applyEnvironmentEvent.mock.calls[0];
    expect(simId).toBe("sim-1");
    expect(payload.node_id).toBe("2");
  });

  it("selected C → request node_id=C (retargeting follows selection)", async () => {
    seedState("2", [0, 1, 2]);
    await useSimulationStore.getState().applyEnvironmentSuggestion(suggestionX);
    expect(mocks.applyEnvironmentEvent.mock.calls[0][1].node_id).toBe("2");

    seedState("3", [0, 1, 2, 3]);
    await useSimulationStore.getState().applyEnvironmentSuggestion(suggestionX);
    expect(mocks.applyEnvironmentEvent.mock.calls[1][1].node_id).toBe("3");
    expect(mocks.applyEnvironmentEvent.mock.calls[1][1].node_id).not.toBe("2");
  });

  it("branch (A→B auto-selected) → intervention X targets B, not A", async () => {
    // tree root(0) → A(1); user branches from A; backend returns child B(2)
    // and the branch-selection fix auto-selects B. The subsequent
    // intervention must carry node B.
    seedState("1", [0, 1]);
    mocks.treeBranch.mockResolvedValue({ child: 2 });
    mocks.getTreeGraph.mockResolvedValue(graphWithNodes([0, 1, 2]));
    await useSimulationStore.getState().branchSimulation();
    expect(useSimulationStore.getState().selectedNodeId).toBe("2");

    await useSimulationStore.getState().applyEnvironmentSuggestion(suggestionX);
    const payload = mocks.applyEnvironmentEvent.mock.calls[0][1];
    expect(payload.node_id).toBe("2");
    expect(payload.node_id).not.toBe("1");
    expect(payload.node_id).not.toBeNull();
    expect(payload.node_id).not.toBeUndefined();
  });
});
