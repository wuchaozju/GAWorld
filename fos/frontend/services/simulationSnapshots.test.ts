/**
 * These tests check how saved simulation snapshots become frontend state.
 *
 * The tests make sure loading a saved tree chooses the branch someone most
 * likely wants to keep working from, and keeps agents from that same branch.
 */

import { describe, expect, it } from "vitest";

import { buildSerializedSnapshot } from "./simulationSnapshots";

describe("buildSerializedSnapshot", () => {
  it("chooses the deepest leaf instead of the first saved node", () => {
    const snapshot = {
      nodes: [
        { id: 0, parent: null, depth: 0, sim: { turns: 0, agents: [{ name: "Root Agent" }] } },
        { id: 3, parent: 0, depth: 1, sim: { turns: 1, agents: [{ name: "Branch Agent" }] } },
        { id: 7, parent: 3, depth: 2, sim: { turns: 2, agents: [{ name: "Leaf Agent" }] } },
      ],
    };

    const result = buildSerializedSnapshot(snapshot, (id) => `Node ${id}`);

    expect(result.selectedNodeId).toBe("7");
    expect(result.turn).toBe(2);
    expect(result.agents.map((agent) => agent.name)).toEqual(["Leaf Agent"]);
  });

  it("keeps all serialized nodes visible when selecting the latest leaf", () => {
    const snapshot = {
      nodes: [
        { id: 0, parent: null, depth: 0 },
        { id: 3, parent: 0, depth: 1 },
        { id: 4, parent: 0, depth: 1 },
        { id: 7, parent: 3, depth: 2 },
        { id: 8, parent: 4, depth: 2 },
      ],
    };

    const result = buildSerializedSnapshot(snapshot, (id) => `Node ${id}`);

    expect(result.nodes.map((node) => node.id)).toEqual(["0", "3", "4", "7", "8"]);
    expect(result.selectedNodeId).toBe("8");
  });
});
