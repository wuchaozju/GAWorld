/**
 * Phase 6 STAGE A — fork-from-checkpoint + failure-recovery frontend (RED).
 *
 * Specifies the frontend seam from PHASE6-BRIEF.md §12/§13:
 * - simulationTree.ts exposes fork / retry / fix-and-retry / substitute calls
 * - node meta exposes fork-capable checkpoint days and recovery state
 *
 * Every test here must fail because the API does not exist yet, not because
 * of a syntax error.
 */
import * as api from "../services/simulationTree";

function feature<T>(value: T | undefined, name: string): T {
  expect(value).toBeDefined();
  if (value === undefined) {
    throw new Error(`feature missing: simulationTree.${name} (Phase 6 RED)`);
  }
  return value;
}

describe("SimTree fork + recovery API surface", () => {
  it("exposes forkFromCheckpoint", async () => {
    const fork = feature(
      (api as Record<string, unknown>).forkFromCheckpoint as (
        base: string,
        id: string,
        parent: number,
        checkpoint: Record<string, unknown>,
        token?: string,
      ) => Promise<{ children: number[] }>,
      "forkFromCheckpoint",
    );
    expect(typeof fork).toBe("function");
  });

  it("exposes retryNode", async () => {
    const retry = feature(
      (api as Record<string, unknown>).retryNode as (
        base: string,
        id: string,
        node: number,
        token?: string,
      ) => Promise<{ child: number }>,
      "retryNode",
    );
    expect(typeof retry).toBe("function");
  });

  it("exposes fixAndRetryNode", async () => {
    const fix = feature(
      (api as Record<string, unknown>).fixAndRetryNode as (
        base: string,
        id: string,
        node: number,
        runtimeConfig: Record<string, unknown>,
        token?: string,
      ) => Promise<{ child: number }>,
      "fixAndRetryNode",
    );
    expect(typeof fix).toBe("function");
  });

  it("exposes substituteProvider", async () => {
    const substitute = feature(
      (api as Record<string, unknown>).substituteProvider as (
        base: string,
        id: string,
        node: number,
        agentId: number,
        provider: string,
        model: string,
        token?: string,
      ) => Promise<{ child: number }>,
      "substituteProvider",
    );
    expect(typeof substitute).toBe("function");
  });

  it("GraphNode meta carries a checkpoint reference", () => {
    const meta = {
      checkpoint: {
        checkpoint_id: "day_0003",
        checkpoint_path: "/runs/x/checkpoints/day_0003",
        day: 3,
        manifest_sha: "a".repeat(64),
        parent_checkpoint: "day_0002",
      },
    };
    const node: api.GraphNode = { id: 1, depth: 0, meta };
    expect(node.meta?.checkpoint).toBeDefined();
    expect(node.meta?.checkpoint.day).toBe(3);
  });

  it("GraphNode meta can express a failed runtime with a pending recovery", () => {
    const meta = {
      runtime_status: "failed",
      runtime_error: "LLM timeout",
      recovery: { action: "retry", attempt_dir: "/runs/x/attempts/day_0005_attempt_2" },
    };
    const node: api.GraphNode = { id: 2, depth: 1, meta };
    expect(node.meta?.runtime_status).toBe("failed");
    expect((node.meta?.recovery as Record<string, unknown>).action).toBe("retry");
  });
});
