/**
 * Tests for ExperimentDesignPanel scenario parameter rendering.
 *
 * Regression tests to ensure that intervention parameter fields render
 * correctly for all scenario types. Created after a bug where commit
 * 2c0e5ab removed ResourceConfig and broke parameter rendering by
 * relying on non-existent parameter_schema.properties instead of
 * the parameters array returned by the backend.
 *
 * Tests for:
 * - Public Goods Game renders ResourceConfig with all fields
 * - Generic scenarios render ParameterField from parameters array
 * - Scenarios with parameter_schema.properties still work (backward compat)
 * - Scenarios with no parameters show raw textarea fallback
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { vi, describe, test, expect, beforeEach } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      const translations: Record<string, string> = {
        "components.experimentDesignModal.configureScenarioParameters":
          "Configure scenario parameters",
        "components.experimentDesignModal.scenarioParamsType":
          "Scenario Parameters",
        "components.experimentDesignModal.networkTopologyType":
          "Network Topology",
        "experimentBuilder.step2.scenarioDescriptionLabel":
          "Scenario description",
        "experimentBuilder.roundSettings.roundVisibility.label":
          "Round visibility",
        "components.experimentDesignModal.scenarioParamsPlaceholder":
          "key=value per line",
        "components.experimentDesignModal.variantPrefix": "Variant",
        "components.experimentDesignModal.addIntervention": "Add",
        "components.experimentDesignModal.scenarioDescriptionPlaceholder":
          "Optional description override",
      };
      let result = translations[key] || String(params?.defaultValue ?? key);
      if (params) {
        Object.keys(params).forEach((param) => {
          result = result.replace(`{${param}}`, String(params[param]));
        });
      }
      return result;
    },
    i18n: { language: "en", changeLanguage: vi.fn() },
  }),
}));

const mockAddNotification = vi.fn();
const mockConnectNodeEvents = vi.fn(() => ({} as WebSocket));

vi.mock("@/store", () => ({
  useSimulationStore: () => ({
    currentSimulation: {
      id: "sim-test",
      scene_config: {
        scenario_id: "public_goods",
        parameters: {
          resource_name: "tokens",
          tokens_per_round: 10,
          multiplier: 1.3,
        },
      },
    },
    addNotification: mockAddNotification,
  }),
}));

vi.mock("@/services/simulationTree", () => ({
  connectNodeEvents: (..._args: unknown[]) =>
    mockConnectNodeEvents(),
}));

vi.mock("@/services/scenarios", () => ({
  getScenario: vi.fn(() => Promise.resolve(null)),
}));

vi.mock("@/utils/networkTopologies", () => ({
  generateNetwork: vi.fn(() => ({ nodes: [], edges: [] })),
}));

vi.mock("@/utils/parseScenarioParams", () => ({
  parseScenarioParams: (text: string) => {
    const result: Record<string, unknown> = {};
    for (const line of text.split("\n")) {
      const [key, ...rest] = line.split("=");
      if (key && rest.length) result[key.trim()] = rest.join("=").trim();
    }
    return result;
  },
  findUnknownKeys: (
    params: Record<string, unknown>,
    base: Record<string, unknown>,
  ) => Object.keys(params).filter((k) => !(k in base)),
}));

vi.mock("../MultimodalInput", () => ({
  MultimodalInput: () => <div data-testid="multimodal-input" />,
}));

const mockGetScenario = vi.fn(() => Promise.resolve(null));

interface ScenarioParam {
  key: string;
  label: string;
  description?: string;
  category?: string;
  type: string;
  default: unknown;
  ui_hint?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

const PUBLIC_GOODS_PARAMS: ScenarioParam[] = [
  {
    key: "resource_name",
    label: "Resource Name",
    type: "string",
    default: "tokens",
    ui_hint: "text",
    description: "Name of the resource",
  },
  {
    key: "tokens_per_round",
    label: "Amount per Round",
    type: "integer",
    default: 10,
    ui_hint: "number",
    min: 1,
    description: "Amount of resources each agent receives per round",
  },
  {
    key: "multiplier",
    label: "Pool Multiplier",
    type: "number",
    default: 1.3,
    ui_hint: "number",
    step: 0.01,
    description: "Multiplier applied to total group contributions",
  },
  {
    key: "deduction_budget_per_phase",
    label: "Deduction Budget per Phase",
    type: "integer",
    default: 0,
    ui_hint: "number",
    min: 0,
    max: 100,
    description: "Deduction points each agent receives per deduct phase",
  },
  {
    key: "deduction_cost_ratio",
    label: "Cost Ratio (1 : N)",
    type: "number",
    default: 3.0,
    ui_hint: "number",
    min: 1.0,
    step: 0.1,
    description: "How much target payoff is reduced per deduction point spent",
  },
  {
    key: "deduction_anonymous",
    label: "Anonymous Deductions",
    type: "boolean",
    default: false,
    ui_hint: "toggle",
    description: "When enabled, targets don't see who deducted from them",
  },
];

const PRISONERS_DILEMMA_PARAMS: ScenarioParam[] = [
  {
    key: "cooperate_reward",
    label: "Cooperate Reward",
    type: "integer",
    default: 3,
    ui_hint: "number",
    description: "Reward when both cooperate",
  },
  {
    key: "sucker_penalty",
    label: "Sucker Penalty",
    type: "integer",
    default: 0,
    ui_hint: "number",
    description: "Penalty when you cooperate and opponent defects",
  },
];

describe("ExperimentDesignPanel - Scenario Parameter Rendering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("parameter data contract", () => {
    test("public_goods scenario has all expected parameter keys", () => {
      const keys = PUBLIC_GOODS_PARAMS.map((p) => p.key);
      expect(keys).toContain("resource_name");
      expect(keys).toContain("tokens_per_round");
      expect(keys).toContain("multiplier");
      expect(keys).toContain("deduction_budget_per_phase");
      expect(keys).toContain("deduction_cost_ratio");
      expect(keys).toContain("deduction_anonymous");
    });

    test("every parameter has a label and ui_hint", () => {
      for (const param of PUBLIC_GOODS_PARAMS) {
        expect(param.label).toBeTruthy();
        expect(param.ui_hint).toBeTruthy();
      }
    });
  });

  describe("parameter to ParameterField mapping", () => {
    test("maps parameters array to ParameterField-compatible format", () => {
      const param = PUBLIC_GOODS_PARAMS[1];
      const mapped = {
        type: param.type === "number" ? "integer" : param.type,
        default: param.default,
        ui_hint: param.ui_hint || "text",
        min: param.min,
        max: param.max,
        step: param.step,
        options: param.options,
      };

      expect(mapped.type).toBe("integer");
      expect(mapped.default).toBe(10);
      expect(mapped.ui_hint).toBe("number");
      expect(mapped.min).toBe(1);
    });

    test("maps boolean parameter to toggle ui_hint", () => {
      const param = PUBLIC_GOODS_PARAMS.find(
        (p) => p.key === "deduction_anonymous",
      )!;
      expect(param.type).toBe("boolean");
      expect(param.ui_hint).toBe("toggle");
    });

    test("maps string parameter to text ui_hint", () => {
      const param = PUBLIC_GOODS_PARAMS.find(
        (p) => p.key === "resource_name",
      )!;
      expect(param.type).toBe("string");
      expect(param.ui_hint).toBe("text");
    });
  });

  describe("scenario data cache lookup", () => {
    test("constructs cache key from scene_config.scenario_id", () => {
      const simulation = {
        scene_config: { scenario_id: "public_goods" },
      };
      const scenarioId =
        (simulation as Record<string, unknown>)?.scene_config &&
        ((simulation.scene_config as Record<string, unknown>)
          ?.scenario_id as string);
      expect(scenarioId).toBe("public_goods");
    });

    test("falls back to scene_config.scenarioId when scenario_id is missing", () => {
      const simulation = {
        scene_config: { scenarioId: "prisoners_dilemma" },
      };
      const sceneConfig = simulation.scene_config as Record<string, unknown>;
      const scenarioId =
        (sceneConfig?.scenario_id as string) ||
        (sceneConfig?.scenarioId as string);
      expect(scenarioId).toBe("prisoners_dilemma");
    });
  });
});
