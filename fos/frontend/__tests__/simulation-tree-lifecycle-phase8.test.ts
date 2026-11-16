/**
 * Phase 8 STAGE A — lifecycle + budget frontend (RED).
 *
 * Specifies the frontend seams from PHASE8-BRIEF.md §12/§13:
 * - simulationTree.ts exposes cancelNode for queued/running branches
 * - runtime statuses queued / cancelled / timed_out are displayable
 * - branch-cap / day-budget / LLM-budget errors render estimated vs budget
 *   without raw exceptions or credentials
 *
 * Every test here must fail because the API does not exist yet, not because
 * of a syntax error.
 */
import * as api from "../services/simulationTree";

function feature<T>(value: T | undefined, name: string): T {
  expect(value).toBeDefined();
  if (value === undefined) {
    throw new Error(`feature missing: simulationTree.${name} (Phase 8 RED)`);
  }
  return value;
}

describe("SimTree lifecycle API surface (Phase 8)", () => {
  it("exposes treeCancelNode", async () => {
    const cancel = feature(
      (api as Record<string, unknown>).treeCancelNode as (
        base: string,
        id: string,
        node: number,
        token?: string,
      ) => Promise<{ ok: boolean }>,
      "treeCancelNode",
    );
    expect(typeof cancel).toBe("function");
  });

  it("exposes a runtime-status helper covering queued/cancelled/timed_out", async () => {
    const statuses = feature(
      (api as Record<string, unknown>).RUNTIME_STATUSES as readonly string[] | undefined,
      "RUNTIME_STATUSES",
    );
    for (const expected of ["queued", "running", "cancelled", "timed_out"]) {
      expect(statuses).toContain(expected);
    }
  });

  it("exposes a budget-error formatter without leaking credentials", async () => {
    const format = feature(
      (api as Record<string, unknown>).formatBudgetError as
        | ((error: Record<string, unknown>) => string)
        | undefined,
      "formatBudgetError",
    );
    const message = format({
      provider: "openai",
      estimated: 120,
      budget: 100,
      unit: "calls",
      api_key: "sk-SENTINEL-SECRET",
    });
    expect(message).toContain("120");
    expect(message).toContain("100");
    expect(message).not.toContain("SENTINEL");
    expect(message).not.toContain("sk-");
  });
});
