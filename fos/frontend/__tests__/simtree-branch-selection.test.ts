/**
 * SimTree branch/run ownership — frontend selection (task 2820, TDD RED).
 *
 * Bug A (SPEC-simtree-ownership.md): `branchSimulation()` receives
 * `result.child` but only refreshes the graph — selection stays on the old
 * node A, so a subsequent Run/Advance acts on A and creates a sibling-ish
 * node instead of advancing the new branch B.
 *
 * Required semantics:
 * - single branch / advance → the new child becomes selectedNodeId
 * - the selection survives the graph refresh that follows the branch
 * - parallel fork (count > 1) keeps the base node selected (explicit
 *   convention, mirrors `advanceSimulation`'s precedent at
 *   experiments.ts `set({ selectedNodeId: String(res.child) })`)
 *
 * RED: the first test fails because branchSimulation never updates
 * selectedNodeId (stays on A). No syntax/module errors.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  treeBranch: vi.fn(),
  getTreeGraph: vi.fn(),
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
  } as any);
}

describe("branchSimulation selects the new child (Bug A fix)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("selects the returned child node after branching", async () => {
    // tree: root(0) → A(1); user branches from A → backend returns child B(2)
    seedState("1", [0, 1]);
    mocks.treeBranch.mockResolvedValue({ child: 2 });
    mocks.getTreeGraph.mockResolvedValue(graphWithNodes([0, 1, 2]));

    await useSimulationStore.getState().branchSimulation();

    const selected = useSimulationStore.getState().selectedNodeId;
    expect(selected).toBe("2");
    expect(selected).not.toBe("1");
  });

  it("keeps the child selected across the post-branch graph refresh", async () => {
    // Branch from A(1) → B(2) selected; then branch again from B(2) → C(3):
    // selection must follow the newest child each time.
    seedState("1", [0, 1]);
    mocks.treeBranch.mockResolvedValueOnce({ child: 2 });
    mocks.getTreeGraph.mockResolvedValue(graphWithNodes([0, 1, 2]));
    await useSimulationStore.getState().branchSimulation();

    seedState(useSimulationStore.getState().selectedNodeId ?? "2", [0, 1, 2]);
    mocks.treeBranch.mockResolvedValueOnce({ child: 3 });
    mocks.getTreeGraph.mockResolvedValue(graphWithNodes([0, 1, 2, 3]));
    await useSimulationStore.getState().branchSimulation();

    expect(useSimulationStore.getState().selectedNodeId).toBe("3");
  });

  it("does not move selection when branching fails", async () => {
    seedState("1", [0, 1]);
    mocks.treeBranch.mockRejectedValue(new Error("boom"));
    mocks.getTreeGraph.mockResolvedValue(graphWithNodes([0, 1]));

    await useSimulationStore.getState().branchSimulation();

    expect(useSimulationStore.getState().selectedNodeId).toBe("1");
  });

  it("parallel fork keeps the base node selected (explicit convention)", async () => {
    // Convention: fork_from_checkpoint(count>1) does NOT auto-select any of
    // the N children — the base stays selected. The store must not guess.
    seedState("1", [0, 1]);
    // Simulate the graph refresh a parallel fork triggers: children 2 and 3
    // appear, selection must remain on the base node 1.
    useSimulationStore.setState({
      nodes: [0, 1, 2, 3].map((id) => ({
        id: String(id),
        display_id: String(id),
        parentId: id === 0 ? null : String(id === 2 || id === 3 ? 1 : id - 1),
        depth: id,
        isLeaf: true,
        status: "completed",
      })) as any,
    } as any);

    expect(useSimulationStore.getState().selectedNodeId).toBe("1");
  });
});
