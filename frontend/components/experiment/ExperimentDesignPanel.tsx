/**
 * This file shows the full experiment design area.
 *
 * ExperimentDesignPanel lets people name an experiment, change each
 * variant, preview the changes, and start the run.
 */

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Beaker,
  Network,
  Plus,
  Settings,
  Sliders,
  Trash2,
  UserCog,
  X,
  Zap,
} from "lucide-react";

import { useSimulationStore } from "../../store";
import {
  ExperimentVariant,
  Intervention,
  NetworkParams,
  NetworkResult,
} from "../../types";
import type { ScenarioData } from "../../services/scenarios";
import { connectNodeEvents } from "../../services/simulationTree";
import { getScenario } from "../../services/scenarios";
import { generateNetwork } from "../../utils/networkTopologies";
import {
  findUnknownKeys,
  parseScenarioParams,
} from "../../utils/parseScenarioParams";
import { MultimodalInput } from "../MultimodalInput";
import ParameterField from "./ParameterField";
import { ResourceConfig } from "./ResourceConfig";

interface ExperimentDesignPanelProps {
  mode?: "modal" | "embedded";
  onClose?: () => void;
}

interface ScenarioParameterDefinition {
  type?: string;
  description?: string;
  default?: unknown;
  ui_hint?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
}

interface ScenarioDataWithSchema extends ScenarioData {
  parameter_schema?: {
    properties?: Record<string, ScenarioParameterDefinition>;
  };
}

const extractMarkdownImages = (text: string): string[] => {
  const matches = Array.from(text.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g));
  return matches.map((match) => match[1]).filter(Boolean);
};

const parseConditionUpdates = (text: string): Record<string, unknown> => {
  let updates: Record<string, unknown> = {};

  try {
    const parsed = JSON.parse(text || "{}");
    if (parsed && typeof parsed === "object" && "updates" in parsed) {
      updates = (parsed as { updates: Record<string, unknown> }).updates;
    } else if (parsed && typeof parsed === "object") {
      updates = parsed as Record<string, unknown>;
    }
  } catch {
    String(text || "")
      .split(",")
      .map((item) => item.trim())
      .forEach((pair) => {
        const [key, ...rest] = pair.split("=");
        if (!key) return;
        const valueText = rest.join("=").trim();
        const numberValue = Number(valueText);
        updates[key.trim()] = Number.isNaN(numberValue)
          ? valueText
          : numberValue;
      });
  }

  return updates;
};

const inferThreadKind = (text: string): string => {
  const normalized = String(text || "");
  if (/è¶Šçº§|è·³çº§|æŠ•è¯‰|å‘ŠçŠ¶/.test(normalized)) {
    return "skip_level_complaint";
  }
  if (
    /å‡çº§åé¦ˆ|å‡çº§ä¸ŠæŠ¥|å‡çº§åæ˜ |ç»§ç»­å‡çº§/.test(
      normalized
    )
  ) {
    return "escalation";
  }
  if (/åé¦ˆ|æ±‡æŠ¥|ä¸ŠæŠ¥/.test(normalized)) return "upward_feedback";
  if (/é€šçŸ¥|è½¬åŠž/.test(normalized)) return "subordinate_notice";
  if (/åå•†|è®¨è®º|å•†é‡|ç§èŠ|å‘æ¶ˆæ¯|å‘é€æ¶ˆæ¯/.test(normalized)) {
    return "peer_consult";
  }
  return "peer_consult";
};

const parseThreadSeed = (
  text: string,
  agentNames: string[]
): Record<string, unknown> => {
  let seed: Record<string, unknown> = {};

  try {
    const parsed = JSON.parse(text || "{}");
    if (parsed && typeof parsed === "object") {
      seed = parsed as Record<string, unknown>;
    }
  } catch {
    String(text || "")
      .split(",")
      .map((item) => item.trim())
      .forEach((pair) => {
        const [key, ...rest] = pair.split("=");
        if (!key) return;
        seed[key.trim()] = rest.join("=").trim();
      });

    if (!Object.keys(seed).length) {
      const rawText = String(text || "").trim();
      const compact = rawText.replace(/ï¼Œ/g, ",").replace(/ï¼š/g, ":");
      const orderedNames = [...agentNames].sort((a, b) => b.length - a.length);
      const matches = orderedNames
        .map((name) => ({ name, index: compact.indexOf(name) }))
        .filter((item) => item.index >= 0)
        .sort((a, b) => a.index - b.index);

      if (matches[0]) seed.sender = matches[0].name;
      if (matches[1]) seed.recipient = matches[1].name;

      const messagePatterns = [
        /æ¶ˆæ¯å†…å®¹(?:ä¸º|æ˜¯)?[:ï¼š]?\s*(.+)$/,
        /å†…å®¹(?:ä¸º|æ˜¯)?[:ï¼š]?\s*(.+)$/,
        /è¯´[:ï¼š]?\s*(.+)$/,
        /å‘æ¶ˆæ¯[:ï¼š]?\s*(.+)$/,
        /å‘é€æ¶ˆæ¯[:ï¼š]?\s*(.+)$/,
      ];
      for (const pattern of messagePatterns) {
        const matched = compact.match(pattern);
        if (matched && matched[1]) {
          seed.message = matched[1].trim();
          break;
        }
      }

      if (!seed.message) {
        const generic = compact.match(
          /(?:ç»™|å‘).+?(?:å‘æ¶ˆæ¯|å‘é€æ¶ˆæ¯|ç§èŠ|åé¦ˆ|æ±‡æŠ¥|ä¸ŠæŠ¥|é€šçŸ¥|è½¬åŠž)[,ï¼Œ:]?\s*(.+)$/
        );
        if (generic && generic[1]) {
          seed.message = generic[1].trim();
        }
      }

      seed.kind = inferThreadKind(compact);
    }
  }

  return seed;
};

const toParameterFieldType = (
  type: string | undefined
): "integer" | "string" | "boolean" | "array" => {
  if (type === "boolean") return "boolean";
  if (type === "array") return "array";
  if (type === "number" || type === "integer" || type === "float") {
    return "integer";
  }
  return "string";
};

const toParameterUiHint = (definition: ScenarioParameterDefinition): string => {
  if (definition.ui_hint) return definition.ui_hint;
  if (definition.type === "boolean") return "toggle";
  if (definition.type === "number" || definition.type === "integer" || definition.type === "float") {
    return "number";
  }
  if (definition.type === "array") return "list";
  return "text";
};

const hasMeaningfulInterventionText = (text: string): boolean =>
  String(text || "").trim().length > 0;

const humanizeBackendLabel = (value: string): string => {
  const normalized = String(value || "").trim();
  if (!normalized) return "";
  return normalized
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
};

export const ExperimentDesignPanel: React.FC<ExperimentDesignPanelProps> = ({
  mode = "embedded",
  onClose,
}) => {
  const { t } = useTranslation();
  const runExperiment = useSimulationStore((state) => state.runExperiment);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const nodes = useSimulationStore((state) => state.nodes);
  const agents = useSimulationStore((state) => state.agents);
  const engineConfig = useSimulationStore((state) => state.engineConfig);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const addNotification = useSimulationStore((state) => state.addNotification);
  const baseNode = nodes.find((node) => node.id === selectedNodeId);
  const expectedVariantParentId = baseNode
    ? baseNode.parentId == null
      ? baseNode.id
      : baseNode.parentId
    : null;
  const currentSceneType =
    currentSimulation?.scene_type ||
    (currentSimulation as { sceneType?: string } | null)?.sceneType ||
    (
      currentSimulation as {
        scene_config?: { scene_type?: string; sceneType?: string };
      } | null
    )?.scene_config?.scene_type ||
    (
      currentSimulation as {
        scene_config?: { scene_type?: string; sceneType?: string };
      } | null
    )?.scene_config?.sceneType ||
    "";
  const isPolicyCascadeTemplate = currentSceneType === "policy_cascade_scene";
  const latestNodeSocketsRef = useRef<Record<string, WebSocket | null>>({});

  const [experimentName, setExperimentName] = useState("");
  const [variants, setVariants] = useState<ExperimentVariant[]>([
    {
      id: "v1",
      name: `${t("components.experimentDesignModal.variantPrefix")} A`,
      description: "",
      interventions: [],
    },
  ]);
  const [showPreview, setShowPreview] = useState(false);
  const [nodeLogs, setNodeLogs] = useState<Record<string, unknown[]>>({});
  const [nodeSockets, setNodeSockets] = useState<Record<string, WebSocket | null>>(
    {}
  );
  const [scenarioDataCache, setScenarioDataCache] = useState<
    Record<string, ScenarioDataWithSchema>
  >({});

  const closePanel = (): void => {
    onClose?.();
  };

  const translateVariantStatus = (status: string): string => {
    switch (status) {
      case "pending":
        return t("components.experimentDesignModal.statusPending");
      case "running":
        return t("components.experimentDesignModal.statusRunning");
      case "completed":
        return t("components.experimentDesignModal.statusCompleted");
      case "failed":
        return t("components.experimentDesignModal.statusFailed");
      default:
        return humanizeBackendLabel(status);
    }
  };

  const translateExperimentLogType = (value: string): string => {
    switch (value) {
      case "SYSTEM":
      case "system_broadcast":
      case "system_announcement":
        return t("components.logViewer.typeSystem");
      case "AGENT_METADATA":
        return t("components.logViewer.typeAgentMetadata");
      case "AGENT_SAY":
        return t("components.logViewer.typeDialogue");
      case "AGENT_ACTION":
      case "action_start":
      case "action_end":
        return t("components.logViewer.typeAction");
      case "ENVIRONMENT":
      case "environment":
      case "environment_event":
        return t("components.logViewer.typeEnvironment");
      default:
        return humanizeBackendLabel(value || "evt");
    }
  };

  const translateNetworkPreset = (preset: string): string => {
    switch (preset) {
      case "full":
        return t("components.experimentDesignModal.presetFull");
      case "ring":
        return t("components.experimentDesignModal.presetRing");
      case "star":
        return t("components.experimentDesignModal.presetStar");
      case "random":
        return t("components.experimentDesignModal.presetRandom");
      case "newman-watts":
        return t("components.experimentDesignModal.presetNewmanWatts");
      case "core-periphery":
        return t("components.experimentDesignModal.presetCorePeriphery");
      case "holme-kim":
        return t("components.experimentDesignModal.presetHolmeKim");
      case "waxman":
        return t("components.experimentDesignModal.presetWaxman");
      case "sbm":
        return t("components.experimentDesignModal.presetSbm");
      case "custom":
        return t("components.experimentDesignModal.presetCustom");
      default:
        return humanizeBackendLabel(preset);
    }
  };

  const translateInterventionType = (type: string): string => {
    switch (type) {
      case "SCENARIO_PARAMS":
        return t("components.experimentDesignModal.scenarioParamsType");
      case "SCENARIO_DESCRIPTION":
        return t("experimentBuilder.step2.scenarioDescriptionLabel", {
          defaultValue: "Scenario description",
        });
      case "NETWORK_TOPOLOGY":
        return t("components.experimentDesignModal.networkTopologyType");
      case "ROUND_VISIBILITY":
        return t("experimentBuilder.roundSettings.roundVisibility.label", {
          defaultValue: "Round visibility",
        });
      case "INSTRUCTION":
        return t("components.experimentDesignModal.instructionType");
      case "AGENT_PROPERTY":
        return t("components.experimentDesignModal.propertyType");
      case "ENVIRONMENT":
        return t("components.experimentDesignModal.environmentType");
      case "FOLLOW_UP_CONDITION":
        return t("components.experimentDesignModal.followUpConditionType");
      case "FOLLOW_UP_THREAD_SEED":
        return t("components.experimentDesignModal.followUpThreadSeedType");
      default:
        return humanizeBackendLabel(type);
    }
  };

  useEffect(() => {
    latestNodeSocketsRef.current = nodeSockets;
  }, [nodeSockets]);

  useEffect(() => {
    return () => {
      Object.values(latestNodeSocketsRef.current).forEach((socket) => {
        try {
          socket?.close();
        } catch {
          // Ignore socket cleanup issues when the panel leaves the page.
        }
      });
    };
  }, []);

  useEffect(() => {
    if (!baseNode || !currentSimulation?.id) return;

    variants.forEach((variant) => {
      const nodeByMeta = nodes.find(
        (node) =>
          (node as { meta?: { variant_id?: string } }).meta?.variant_id &&
          node.parentId === expectedVariantParentId &&
          node.name.includes(variant.name)
      );
      const nodeByName = nodes.find(
        (node) => node.name === `${experimentName}: ${variant.name}`
      );
      const node = nodeByMeta || nodeByName;
      const nodeId = node?.id;
      if (!nodeId || nodeSockets[String(nodeId)]) return;

      try {
        const socket = connectNodeEvents(
          engineConfig.endpoint || "",
          currentSimulation.id || "",
          Number(nodeId),
          (engineConfig as { token?: string }).token,
          (event: unknown) => {
            setNodeLogs((previous) => {
              const next = { ...previous };
              const currentLogs = [...(next[String(nodeId)] || []), event];
              next[String(nodeId)] =
                currentLogs.length > 500
                  ? currentLogs.slice(-500)
                  : currentLogs;
              return next;
            });
          }
        );
        setNodeSockets((previous) => ({ ...previous, [String(nodeId)]: socket }));
      } catch {
        // Ignore live log connection problems so the panel still works.
      }
    });
  }, [
    agents,
    baseNode,
    currentSimulation?.id,
    engineConfig,
    expectedVariantParentId,
    experimentName,
    nodeSockets,
    nodes,
    variants,
  ]);

  useEffect(() => {
    if (mode !== "modal" || baseNode) return;
    addNotification(
      "error",
      t("store.selectNodeFirst") || "Please select a simulation node first"
    );
    closePanel();
  }, [addNotification, baseNode, mode, t]);

  useEffect(() => {
    if (isPolicyCascadeTemplate) return;
    setVariants((previous) =>
      previous.map((variant) => ({
        ...variant,
        interventions: (variant.interventions || []).map((intervention) =>
          intervention.type === "FOLLOW_UP_CONDITION" ||
          intervention.type === "FOLLOW_UP_THREAD_SEED"
            ? { ...intervention, type: "ENVIRONMENT" }
            : intervention
        ),
      }))
    );
  }, [isPolicyCascadeTemplate]);

  useEffect(() => {
    const sceneConfig = (
      currentSimulation as { scene_config?: { scenario_id?: string; scenarioId?: string } } | null
    )?.scene_config;
    const scenarioId = sceneConfig?.scenario_id || sceneConfig?.scenarioId;
    if (!scenarioId || scenarioDataCache[scenarioId]) return;

    getScenario(scenarioId)
      .then((data) => {
        setScenarioDataCache((previous) => ({ ...previous, [scenarioId]: data }));
      })
      .catch((error: unknown) => {
        console.error("Failed to fetch scenario data:", error);
      });
  }, [currentSimulation, scenarioDataCache]);

  if (!baseNode) {
    if (mode === "modal") return null;

    return (
      <div
        className="h-full flex items-center justify-center p-6"
        style={{ background: "var(--ss-workspace-bg)" }}
      >
        <div
          className="max-w-xl rounded-3xl border p-8 text-center"
          style={{
            background: "var(--ss-workspace-surface)",
            borderColor: "var(--ss-workspace-border)",
            color: "var(--ss-workspace-text)",
          }}
        >
          <h2 className="text-lg font-semibold">
            {t("simPage.designExperiment")}
          </h2>
          <p className="mt-3 text-sm" style={{ color: "var(--ss-workspace-muted)" }}>
            {t("store.selectNodeFirst", {
              defaultValue: "Please select a simulation node first",
            })}
          </p>
        </div>
      </div>
    );
  }

  const handleAddVariant = (): void => {
    setVariants([
      ...variants,
      {
        id: `v${Date.now()}`,
        name: `${t("components.experimentDesignModal.variantPrefix")} ${String.fromCharCode(
          65 + variants.length
        )}`,
        description: "",
        interventions: [],
      },
    ]);
  };

  const handleRemoveVariant = (id: string): void => {
    setVariants(variants.filter((variant) => variant.id !== id));
  };

  const handleUpdateVariant = (
    id: string,
    field: keyof ExperimentVariant,
    value: unknown
  ): void => {
    setVariants(
      variants.map((variant) =>
        variant.id === id ? { ...variant, [field]: value } : variant
      )
    );
  };

  const addIntervention = (variantId: string): void => {
    setVariants(
      variants.map((variant) => {
        if (variant.id !== variantId) return variant;
        return {
          ...variant,
          interventions: [
            ...variant.interventions,
            {
              id: `iv${Date.now()}`,
              type: "INSTRUCTION",
              description: "",
            },
          ],
        };
      })
    );
  };

  const updateIntervention = (
    variantId: string,
    interventionId: string,
    field: keyof Intervention,
    value: unknown
  ): void => {
    setVariants(
      variants.map((variant) => {
        if (variant.id !== variantId) return variant;
        return {
          ...variant,
          interventions: variant.interventions.map((intervention) =>
            intervention.id === interventionId
              ? { ...intervention, [field]: value }
              : intervention
          ),
        };
      })
    );
  };

  const removeIntervention = (
    variantId: string,
    interventionId: string
  ): void => {
    setVariants(
      variants.map((variant) => {
        if (variant.id !== variantId) return variant;
        return {
          ...variant,
          interventions: variant.interventions.filter(
            (intervention) => intervention.id !== interventionId
          ),
        };
      })
    );
  };

  const handleEmbedInterventionImage = (
    variantId: string,
    interventionId: string,
    url: string
  ): void => {
    setVariants((previous) =>
      previous.map((variant) => {
        if (variant.id !== variantId) return variant;
        return {
          ...variant,
          interventions: variant.interventions.map((intervention) =>
            intervention.id === interventionId
              ? {
                  ...intervention,
                  description: `${intervention.description || ""}${
                    intervention.description ? "\n" : ""
                  }![image](${url})`,
                }
              : intervention
          ),
        };
      })
    );
    addNotification("success", t("components.experimentDesignModal.imageUploaded"));
  };

  const buildPreviewData = () => {
    const baseParams =
      (
        currentSimulation as {
          scene_config?: { parameters?: Record<string, unknown> };
        } | null
      )?.scene_config?.parameters || {};
    const baseDescription =
      (
        currentSimulation as {
          scene_config?: { description?: string };
        } | null
      )?.scene_config?.description || "";
    const baseRoundVisibility =
      (
        currentSimulation as {
          scene_config?: { round_visibility?: string };
        } | null
      )?.scene_config?.round_visibility || "simultaneous";
    const agentNames = agents.map((agent) => agent.name);

    return variants.map((variant) => {
      const paramChanges: Array<{
        key: string;
        was: unknown;
        new: unknown;
        unknown?: boolean;
      }> = [];
      const otherInterventions: Array<{ type: string; description: string }> = [];

      (variant.interventions || []).forEach((intervention) => {
        if (intervention.type === "SCENARIO_PARAMS") {
          const parsed =
            intervention.parsedParams ||
            parseScenarioParams(intervention.rawParamsText || "");
          Object.entries(parsed).forEach(([key, nextValue]) => {
            paramChanges.push({
              key,
              was: baseParams[key],
              new: nextValue,
              unknown: !(key in baseParams),
            });
          });

          if (
            intervention.scenarioDescription !== undefined &&
            intervention.scenarioDescription !== baseDescription
          ) {
            otherInterventions.push({
              type: "SCENARIO_DESCRIPTION",
              description: t(
                "components.experimentDesignModal.previewDescriptionChanged",
                { defaultValue: "Description changed" }
              ),
            });
          }

          if (
            intervention.roundVisibility !== undefined &&
            intervention.roundVisibility !== baseRoundVisibility
          ) {
            otherInterventions.push({
              type: "ROUND_VISIBILITY",
              description: t(
                "components.experimentDesignModal.previewRoundVisibilityChanged",
                {
                  from: baseRoundVisibility,
                  to: intervention.roundVisibility,
                  defaultValue: `Round visibility: ${baseRoundVisibility} -> ${intervention.roundVisibility}`,
                }
              ),
            });
          }
          return;
        }

        if (intervention.type === "NETWORK_TOPOLOGY") {
          let network: NetworkResult;
          if (intervention.networkPreset === "custom" && intervention.customEdges) {
            network = { edges: intervention.customEdges, preset: "custom", seed: 0 };
          } else if (intervention.networkPreset) {
            network = generateNetwork(
              intervention.networkPreset as never,
              agentNames,
              intervention.networkParams as never
            );
          } else {
            network = generateNetwork("full", agentNames);
          }
          otherInterventions.push({
            type: "NETWORK_TOPOLOGY",
            description: `${translateNetworkPreset(
              intervention.networkPreset || "full"
            )}: ${network.edges.length} ${t(
              "components.experimentDesignModal.previewEdges"
            )}, ${t("components.experimentDesignModal.previewSeed")}=${network.seed}`,
          });
          return;
        }

        otherInterventions.push({
          type: intervention.type,
          description: intervention.description || "",
        });
      });

      return {
        variantId: variant.id,
        variantName: variant.name,
        paramChanges,
        otherInterventions,
      };
    });
  };

  const handleSubmit = (): void => {
    if (!experimentName) {
      window.alert(t("components.experimentDesignModal.pleaseEnterName"));
      return;
    }

    const variantsWithOps = variants.map((variant) => {
      const ops: Array<Record<string, unknown>> = [];
      const pendingFollowUpConditions: Record<string, unknown> = {};
      const pendingThreadSeeds: Array<Record<string, unknown>> = [];

      (variant.interventions || []).forEach((intervention) => {
        if (intervention.type === "AGENT_PROPERTY" && intervention.targetId) {
          const updates = parseConditionUpdates(intervention.description || "");
          if (!Object.keys(updates).length) return;

          const target = agents.find((agent) => agent.id === intervention.targetId);
          const name = target ? target.name : intervention.targetId;
          ops.push({ op: "agent_props_patch", name, updates });
          return;
        }

        if (intervention.type === "INSTRUCTION") {
          if (!hasMeaningfulInterventionText(intervention.description || "")) return;
          ops.push({ op: "public_broadcast", text: intervention.description || "" });
          return;
        }

        if (intervention.type === "ENVIRONMENT") {
          if (!hasMeaningfulInterventionText(intervention.description || "")) return;
          if (isPolicyCascadeTemplate) {
            ops.push({
              op: "environment_event",
              text: intervention.description || "",
              event_type: "environment",
            });
          } else {
            ops.push({ op: "public_broadcast", text: intervention.description || "" });
          }
          return;
        }

        if (
          intervention.type === "FOLLOW_UP_CONDITION" &&
          isPolicyCascadeTemplate
        ) {
          const updates = parseConditionUpdates(intervention.description || "");
          if (!Object.keys(updates).length) return;
          Object.assign(pendingFollowUpConditions, updates);
          return;
        }

        if (
          intervention.type === "FOLLOW_UP_THREAD_SEED" &&
          intervention.targetId &&
          isPolicyCascadeTemplate
        ) {
          const seed = parseThreadSeed(
            intervention.description || "",
            agents.map((agent) => agent.name)
          );
          const target = agents.find((agent) => agent.id === intervention.targetId);
          const recipient =
            (seed.recipient as string | undefined) ||
            (target ? target.name : intervention.targetId);
          if (!recipient || (!seed.message && !seed.notice)) return;
          pendingThreadSeeds.push({
            recipient,
            sender: seed.sender,
            kind: seed.kind || "peer_consult",
            message: seed.message || "",
            notice: seed.notice || "",
            metadata: seed.metadata || {},
          });
          return;
        }

        if (intervention.type === "SCENARIO_PARAMS") {
          const userChanges = intervention.parsedParams || {};
          const updates: Record<string, unknown> = {};
          Object.entries(userChanges).forEach(([key, value]) => {
            if (value !== "__DELETE__") {
              updates[key] = value;
            }
          });

          if (Object.keys(updates).length > 0) {
            ops.push({ op: "config_params_patch", updates });
          }

          if (
            intervention.scenarioDescription !== undefined &&
            intervention.scenarioDescription !== ""
          ) {
            const baseDescription =
              (
                currentSimulation as {
                  scene_config?: { description?: string };
                } | null
              )?.scene_config?.description || "";
            if (intervention.scenarioDescription !== baseDescription) {
              ops.push({
                op: "config_description_patch",
                description: intervention.scenarioDescription,
              });
            }
          }

          if (intervention.roundVisibility !== undefined) {
            const baseRoundVisibility =
              (
                currentSimulation as {
                  scene_config?: { round_visibility?: string };
                } | null
              )?.scene_config?.round_visibility || "simultaneous";
            if (intervention.roundVisibility !== baseRoundVisibility) {
              ops.push({
                op: "config_settings_patch",
                settings: { round_visibility: intervention.roundVisibility },
              });
            }
          }
          return;
        }

        if (intervention.type === "NETWORK_TOPOLOGY") {
          const agentNames = agents.map((agent) => agent.name);
          let network: NetworkResult;
          if (intervention.networkPreset === "custom" && intervention.customEdges) {
            network = { edges: intervention.customEdges, preset: "custom", seed: 0 };
          } else if (intervention.networkPreset) {
            network = generateNetwork(
              intervention.networkPreset as never,
              agentNames,
              intervention.networkParams as never
            );
          } else {
            network = generateNetwork("full", agentNames);
          }
          ops.push({ op: "network_replace", network });
        }
      });

      if (Object.keys(pendingFollowUpConditions).length > 0) {
        ops.push({
          op: "scene_state_patch",
          updates: { pending_follow_up_conditions: pendingFollowUpConditions },
        });
      }

      if (pendingThreadSeeds.length > 0) {
        ops.push({
          op: "scene_state_patch",
          updates: { follow_up_thread_seeds: pendingThreadSeeds },
        });
      }

      return { ...variant, ops };
    });

    runExperiment(baseNode.id, experimentName, variantsWithOps);
    closePanel();
    setExperimentName("");
    setVariants([
      {
        id: "v1",
        name: `${t("components.experimentDesignModal.variantPrefix")} A`,
        description: "",
        interventions: [],
      },
    ]);
  };

  const rootClassName =
    mode === "modal"
      ? "rounded-xl w-full max-w-5xl h-[85vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200"
      : "h-full flex flex-col overflow-hidden";
  const rootStyle =
    mode === "modal"
      ? {
          background: "var(--ss-surface)",
          border: "1px solid var(--ss-border)",
          boxShadow: "var(--ss-shadow-3)",
          color: "var(--ss-text)",
        }
      : {
          background: "var(--ss-workspace-bg)",
          color: "var(--ss-text)",
        };

  return (
    <div className={rootClassName} style={rootStyle}>
      <div
        className="px-6 py-4 flex justify-between items-center shrink-0"
        style={{
          borderBottom: "1px solid var(--ss-border)",
          background:
            mode === "modal"
              ? "var(--ss-brand-soft)"
              : "var(--ss-workspace-surface)",
        }}
      >
        <div>
          <h2
            className="text-lg font-bold flex items-center gap-2"
            style={{ color: "var(--ss-heading)" }}
          >
            <Beaker style={{ color: "var(--ss-brand-primary)" }} size={24} />
            {t("components.experimentDesignModal.title")}
          </h2>
          <p
            className="text-xs mt-1"
            style={{ color: "var(--ss-brand-primary)" }}
            dangerouslySetInnerHTML={{
              __html: t("components.experimentDesignModal.subtitle", {
                displayId: baseNode.display_id,
                name: baseNode.name,
              }),
            }}
          />
        </div>
        {onClose ? (
          <button onClick={closePanel} style={{ color: "var(--ss-text-subtle)" }}>
            <X size={24} />
          </button>
        ) : null}
      </div>

      <div className="flex-1 overflow-hidden flex flex-col md:flex-row">
        <div
          className="w-full md:w-80 p-6 overflow-y-auto shrink-0 space-y-6"
          style={{
            background:
              mode === "modal"
                ? "var(--ss-surface-muted)"
                : "var(--ss-workspace-surface)",
            borderRight: "1px solid var(--ss-border)",
          }}
        >
          <div>
            <label
              className="block text-sm font-bold mb-2"
              style={{ color: "var(--ss-heading)" }}
            >
              {t("components.experimentDesignModal.experimentNameLabel")}
            </label>
            <input
              type="text"
              value={experimentName}
              onChange={(event) => setExperimentName(event.target.value)}
              placeholder={t(
                "components.experimentDesignModal.experimentNamePlaceholder"
              )}
              className="w-full px-3 py-2 border rounded-lg outline-none text-sm"
              style={{
                background: "var(--ss-input-bg)",
                borderColor: "var(--ss-border)",
                color: "var(--ss-text)",
              }}
            />
          </div>

          <div
            className="border rounded-lg p-4 relative overflow-hidden"
            style={{
              background: "var(--ss-layer-card)",
              borderColor: "var(--ss-border)",
              boxShadow: "var(--ss-shadow-1)",
            }}
          >
            <div
              className="absolute top-0 left-0 w-1 h-full"
              style={{ background: "var(--ss-border-strong)" }}
            />
            <h3
              className="text-sm font-bold mb-1"
              style={{ color: "var(--ss-heading)" }}
            >
              {t("components.experimentDesignModal.controlGroup")}
            </h3>
            <p
              className="text-xs mb-3"
              style={{ color: "var(--ss-text-muted)" }}
            >
              {t("components.experimentDesignModal.controlGroupDescription")}
            </p>
            <div
              className="text-xs p-2 rounded"
              style={{
                background: "var(--ss-surface-inset)",
                color: "var(--ss-text)",
              }}
            >
              {t("components.experimentDesignModal.controlGroupState")}
            </div>
          </div>

          <div
            className="text-xs leading-relaxed"
            style={{ color: "var(--ss-text-subtle)" }}
          >
            <p>{t("components.experimentDesignModal.hintTitle")}</p>
            <ul className="list-disc pl-4 space-y-1 mt-1">
              <li>{t("components.experimentDesignModal.hintAddVariant")}</li>
              <li>{t("components.experimentDesignModal.hintDefineVariables")}</li>
              <li>{t("components.experimentDesignModal.hintAutoParallel")}</li>
            </ul>
          </div>
        </div>

        <div
          className="flex-1 p-6 overflow-y-auto relative"
          style={{ background: "var(--ss-surface-inset)" }}
        >
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            {variants.map((variant) => (
              <div
                key={variant.id}
                className="border rounded-xl overflow-hidden group transition-shadow"
                style={{
                  background: "var(--ss-layer-card)",
                  borderColor: "var(--ss-border)",
                  boxShadow: "var(--ss-shadow-1)",
                }}
              >
                <div
                  className="px-4 py-3 border-b flex justify-between items-center"
                  style={{
                    background: "var(--ss-surface)",
                    borderColor: "var(--ss-border)",
                  }}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="text"
                      value={variant.name}
                      onChange={(event) =>
                        handleUpdateVariant(variant.id, "name", event.target.value)
                      }
                      className="font-bold bg-transparent border-b border-transparent outline-none px-1"
                      style={{ color: "var(--ss-heading)" }}
                    />
                    {(() => {
                      const nodeByMeta = nodes.find(
                        (node) =>
                          (node as { meta?: { variant_id?: string } }).meta
                            ?.variant_id &&
                          node.parentId === expectedVariantParentId &&
                          node.name.includes(variant.name)
                      );
                      const nodeByName = nodes.find(
                        (node) => node.name === `${experimentName}: ${variant.name}`
                      );
                      const node = nodeByMeta || nodeByName;
                      const status = node ? node.status : "pending";
                      const badgeColor =
                        status === "running"
                          ? "var(--ss-warning)"
                          : status === "completed"
                            ? "var(--ss-status-positive)"
                            : "var(--ss-text-subtle)";
                      return (
                        <span
                          className="text-xs font-medium px-2 py-0.5 rounded"
                          style={{
                            color: badgeColor,
                            background: "var(--ss-surface-inset)",
                          }}
                        >
                          {translateVariantStatus(status)}
                        </span>
                      );
                    })()}
                    {(() => {
                      const nodeByMeta = nodes.find(
                        (node) =>
                          (node as { meta?: { variant_id?: string } }).meta
                            ?.variant_id &&
                          node.parentId === expectedVariantParentId &&
                          node.name.includes(variant.name)
                      );
                      const nodeByName = nodes.find(
                        (node) => node.name === `${experimentName}: ${variant.name}`
                      );
                      const node = nodeByMeta || nodeByName;
                      const nodeId = node?.id;
                      if (!nodeId) return null;
                      const logs = nodeLogs[String(nodeId)] || [];
                      return (
                        <div className="mt-2 text-xs" style={{ color: "var(--ss-text-muted)" }}>
                          <div className="flex items-center gap-2">
                            <span
                              className="inline-block w-2 h-2 rounded-full"
                              style={{ background: "var(--ss-success-400)" }}
                            />
                            <span>
                              {t("components.experimentDesignModal.liveLogPreview", {
                                count: Math.min(5, logs.length),
                              })}
                            </span>
                          </div>
                          <div
                            className="mt-2 border rounded p-2 text-[11px] h-20 overflow-auto"
                            style={{
                              background: "var(--ss-surface-inset)",
                              borderColor: "var(--ss-border)",
                            }}
                          >
                            {logs.slice(-5).map((log, index) => {
                              const current = log as {
                                type?: string;
                                event_type?: string;
                                data?: {
                                  action?: string;
                                  message?: string;
                                };
                              };
                              return (
                                <div
                                  key={index}
                                  className="py-0.5 border-b"
                                  style={{ borderColor: "var(--ss-border)" }}
                                >
                                  <div
                                    className="font-mono text-[11px]"
                                    style={{ color: "var(--ss-text-muted)" }}
                                  >
                                    {translateExperimentLogType(
                                      String(
                                        current.type || current.event_type || "evt"
                                      )
                                    )}
                                  </div>
                                  <div style={{ color: "var(--ss-text)" }}>
                                    {String(
                                      (current.data &&
                                        (current.data.action ||
                                          current.data.message ||
                                          JSON.stringify(current.data))) ||
                                        current.data ||
                                        ""
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                            {logs.length === 0 ? (
                              <div style={{ color: "var(--ss-text-subtle)" }}>
                                {t("components.experimentDesignModal.noLogsYet")}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                  <button
                    onClick={() => handleRemoveVariant(variant.id)}
                    className="transition-colors"
                    style={{ color: "var(--ss-text-subtle)" }}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>

                <div className="p-4 space-y-3 min-h-[200px]">
                  {variant.interventions.length === 0 ? (
                    <div
                      className="text-center py-8 text-sm border-2 border-dashed rounded-lg"
                      style={{
                        color: "var(--ss-text-subtle)",
                        borderColor: "var(--ss-border)",
                      }}
                    >
                      {t("components.experimentDesignModal.noInterventions")}
                    </div>
                  ) : (
                    variant.interventions.map((intervention) => (
                      <div
                        key={intervention.id}
                        className="rounded-lg border p-3 text-sm relative"
                        style={{
                          background: "var(--ss-surface-inset)",
                          borderColor: "var(--ss-border)",
                        }}
                      >
                        <div className="flex gap-2 mb-2">
                          <select
                            value={intervention.type}
                            onChange={(event) =>
                              updateIntervention(
                                variant.id,
                                intervention.id,
                                "type",
                                event.target.value
                              )
                            }
                            className="text-[10px] font-bold uppercase border rounded px-1 py-0.5 outline-none"
                            style={{
                              background: "var(--ss-input-bg)",
                              borderColor: "var(--ss-border)",
                              color: "var(--ss-text)",
                            }}
                          >
                            <option value="SCENARIO_PARAMS">
                              {t("components.experimentDesignModal.scenarioParamsType", {
                                defaultValue: "Scenario Parameters",
                              })}
                            </option>
                            <option value="NETWORK_TOPOLOGY">
                              {t(
                                "components.experimentDesignModal.networkTopologyType",
                                { defaultValue: "Network Topology" }
                              )}
                            </option>
                            <option value="INSTRUCTION">
                              {t("components.experimentDesignModal.instructionType")}
                            </option>
                            <option value="AGENT_PROPERTY">
                              {t("components.experimentDesignModal.propertyType")}
                            </option>
                            <option value="ENVIRONMENT">
                              {t("components.experimentDesignModal.environmentType")}
                            </option>
                            {isPolicyCascadeTemplate ? (
                              <option value="FOLLOW_UP_CONDITION">
                                {t(
                                  "components.experimentDesignModal.followUpConditionType",
                                  { defaultValue: "Follow-up condition" }
                                )}
                              </option>
                            ) : null}
                            {isPolicyCascadeTemplate ? (
                              <option value="FOLLOW_UP_THREAD_SEED">
                                {t(
                                  "components.experimentDesignModal.followUpThreadSeedType",
                                  { defaultValue: "Follow-up thread seed" }
                                )}
                              </option>
                            ) : null}
                          </select>

                          {intervention.type === "AGENT_PROPERTY" ||
                          intervention.type === "FOLLOW_UP_THREAD_SEED" ? (
                            <select
                              value={intervention.targetId || ""}
                              onChange={(event) =>
                                updateIntervention(
                                  variant.id,
                                  intervention.id,
                                  "targetId",
                                  event.target.value
                                )
                              }
                              className="text-[10px] border rounded px-1 py-0.5 outline-none max-w-[100px]"
                              style={{
                                background: "var(--ss-input-bg)",
                                borderColor: "var(--ss-border)",
                                color: "var(--ss-text)",
                              }}
                            >
                              <option value="">
                                {t("components.experimentDesignModal.selectAgent")}
                              </option>
                              {agents.map((agent) => (
                                <option key={agent.id} value={agent.id}>
                                  {agent.name}
                                </option>
                              ))}
                            </select>
                          ) : null}
                        </div>

                        {intervention.type === "SCENARIO_PARAMS" ? (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2 text-xs font-semibold">
                              <Settings
                                size={14}
                                style={{ color: "var(--ss-brand-primary)" }}
                              />
                              <span>
                                {t(
                                  "components.experimentDesignModal.configureScenarioParameters",
                                  { defaultValue: "Configure scenario parameters" }
                                )}
                              </span>
                            </div>

                            {(() => {
                              const scenarioId =
                                (
                                  currentSimulation as {
                                    scene_config?: {
                                      scenario_id?: string;
                                      scenarioId?: string;
                                      parameters?: Record<string, unknown>;
                                      description?: string;
                                      round_visibility?: string;
                                    };
                                  } | null
                                )?.scene_config?.scenario_id ||
                                (
                                  currentSimulation as {
                                    scene_config?: {
                                      scenario_id?: string;
                                      scenarioId?: string;
                                      parameters?: Record<string, unknown>;
                                      description?: string;
                                      round_visibility?: string;
                                    };
                                  } | null
                                )?.scene_config?.scenarioId;
                              const scenarioData = scenarioId
                                ? scenarioDataCache[scenarioId]
                                : null;
                              const baseParams =
                                (
                                  currentSimulation as {
                                    scene_config?: {
                                      parameters?: Record<string, unknown>;
                                    };
                                  } | null
                                )?.scene_config?.parameters || {};

                              const schemaProperties =
                                scenarioData?.parameter_schema?.properties || {};
                              if (Object.keys(schemaProperties).length > 0) {
                                return (
                                  <div className="space-y-3">
                                    {Object.entries(schemaProperties).map(
                                      ([key, definition]) => {
                                        const fieldLabel = humanizeBackendLabel(key);
                                        return (
                                          <div key={key} className="space-y-1">
                                            <label
                                              className="text-[11px] font-semibold"
                                              style={{ color: "var(--ss-heading)" }}
                                            >
                                              {fieldLabel}
                                            </label>
                                            <ParameterField
                                              param={{
                                                type: toParameterFieldType(definition.type),
                                                default: definition.default ?? baseParams[key] ?? "",
                                                ui_hint: toParameterUiHint(definition),
                                                min: definition.min,
                                                max: definition.max,
                                                step: definition.step,
                                                options: definition.options,
                                              }}
                                              value={
                                                intervention.parsedParams?.[key] ??
                                                baseParams[key] ??
                                                definition.default ??
                                                ""
                                              }
                                              onChange={(nextValue) =>
                                                updateIntervention(
                                                  variant.id,
                                                  intervention.id,
                                                  "parsedParams",
                                                  {
                                                    ...intervention.parsedParams,
                                                    [key]: nextValue,
                                                  }
                                                )
                                              }
                                            />
                                            {definition.description ? (
                                              <p
                                                className="text-[11px]"
                                                style={{ color: "var(--ss-text-muted)" }}
                                              >
                                                {definition.description}
                                              </p>
                                            ) : null}
                                          </div>
                                        );
                                      }
                                    )}
                                  </div>
                                );
                              }

                              if (scenarioId === "public_goods") {
                                const pgDefaults: Record<string, unknown> = {
                                  resource_name: "tokens",
                                  tokens_per_round: 10,
                                  multiplier: 1.3,
                                  deduction_budget_per_phase: 0,
                                  deduction_cost_ratio: 3,
                                  deduction_anonymous: false,
                                  show_average_contribution: false,
                                };
                                const resourceValues = {
                                  resource_name: String(
                                    (intervention.parsedParams?.resource_name as string)
                                    || (baseParams.resource_name as string)
                                    || pgDefaults.resource_name
                                  ),
                                  tokens_per_round: Number(
                                    (intervention.parsedParams?.tokens_per_round as number)
                                    ?? (baseParams.tokens_per_round as number)
                                    ?? pgDefaults.tokens_per_round
                                  ),
                                  multiplier: Number(
                                    (intervention.parsedParams?.multiplier as number)
                                    ?? (baseParams.multiplier as number)
                                    ?? pgDefaults.multiplier
                                  ),
                                  deduction_budget_per_phase: Number(
                                    (intervention.parsedParams?.deduction_budget_per_phase as number)
                                    ?? (baseParams.deduction_budget_per_phase as number)
                                    ?? pgDefaults.deduction_budget_per_phase
                                  ),
                                  deduction_cost_ratio: Number(
                                    (intervention.parsedParams?.deduction_cost_ratio as number)
                                    ?? (baseParams.deduction_cost_ratio as number)
                                    ?? pgDefaults.deduction_cost_ratio
                                  ),
                                  deduction_anonymous: Boolean(
                                    (intervention.parsedParams?.deduction_anonymous as boolean)
                                    ?? (baseParams.deduction_anonymous as boolean)
                                    ?? pgDefaults.deduction_anonymous
                                  ),
                                  show_average_contribution: Boolean(
                                    (intervention.parsedParams?.show_average_contribution as boolean)
                                    ?? (baseParams.show_average_contribution as boolean)
                                    ?? pgDefaults.show_average_contribution
                                  ),
                                };
                                return (
                                  <ResourceConfig
                                    values={resourceValues}
                                    onChange={(key, value) =>
                                      updateIntervention(
                                        variant.id,
                                        intervention.id,
                                        "parsedParams",
                                        { ...intervention.parsedParams, [key]: value }
                                      )
                                    }
                                  />
                                );
                              }

                              if (scenarioData?.parameters && scenarioData.parameters.length > 0) {
                                return (
                                  <div className="space-y-3">
                                    {scenarioData.parameters.map((param) => {
                                      const fieldLabel = param.label || humanizeBackendLabel(param.key);
                                      return (
                                        <div key={param.key} className="space-y-1">
                                          <label
                                            className="text-[11px] font-semibold"
                                            style={{ color: "var(--ss-heading)" }}
                                          >
                                            {fieldLabel}
                                          </label>
                                          <ParameterField
                                            param={{
                                              type: (param.type === "number" || param.type === "float")
                                                ? "integer"
                                                : (param.type === "text" ? "string" : param.type) as "integer" | "string" | "boolean" | "array",
                                              default: param.default ?? baseParams[param.key] ?? "",
                                              ui_hint: param.ui_hint || "text",
                                              min: param.min,
                                              max: param.max,
                                              step: param.step,
                                              options: param.options,
                                            }}
                                            value={
                                              intervention.parsedParams?.[param.key]
                                              ?? baseParams[param.key]
                                              ?? param.default
                                              ?? ""
                                            }
                                            onChange={(nextValue) =>
                                              updateIntervention(
                                                variant.id,
                                                intervention.id,
                                                "parsedParams",
                                                {
                                                  ...intervention.parsedParams,
                                                  [param.key]: nextValue,
                                                }
                                              )
                                            }
                                          />
                                          {param.description ? (
                                            <p
                                              className="text-[11px]"
                                              style={{ color: "var(--ss-text-muted)" }}
                                            >
                                              {param.description}
                                            </p>
                                          ) : null}
                                        </div>
                                      );
                                    })}
                                  </div>
                                );
                              }

                              return (
                                <textarea
                                  value={intervention.rawParamsText || ""}
                                  onChange={(event) => {
                                    const nextText = event.target.value;
                                    updateIntervention(
                                      variant.id,
                                      intervention.id,
                                      "rawParamsText",
                                      nextText
                                    );
                                    updateIntervention(
                                      variant.id,
                                      intervention.id,
                                      "parsedParams",
                                      parseScenarioParams(nextText)
                                    );
                                  }}
                                  placeholder={t(
                                    "components.experimentDesignModal.scenarioParamsPlaceholder"
                                  )}
                                  className="w-full text-xs border rounded p-2 font-mono h-20"
                                  style={{
                                    background: "var(--ss-input-bg)",
                                    borderColor: "var(--ss-border)",
                                    color: "var(--ss-text)",
                                  }}
                                />
                              );
                            })()}

                            {(() => {
                              const scenarioId =
                                (
                                  currentSimulation as {
                                    scene_config?: { scenario_id?: string; scenarioId?: string };
                                  } | null
                                )?.scene_config?.scenario_id ||
                                (
                                  currentSimulation as {
                                    scene_config?: { scenario_id?: string; scenarioId?: string };
                                  } | null
                                )?.scene_config?.scenarioId;
                              // Public Goods Game uses ResourceConfig with known keys
                              if (scenarioId === 'public_goods') return null;
                              const scenarioData = scenarioId
                                ? scenarioDataCache[scenarioId]
                                : null;
                              const knownKeys = scenarioData?.parameter_schema?.properties
                                ? Object.keys(scenarioData.parameter_schema.properties)
                                : (scenarioData?.parameters || []).map((p) => p.key);
                              const unknownKeys = findUnknownKeys(
                                intervention.parsedParams || {},
                                knownKeys.reduce<Record<string, unknown>>((acc, key) => {
                                  acc[key] = true;
                                  return acc;
                                }, {})
                              );
                              return unknownKeys.length > 0 ? (
                                <div
                                  className="text-xs rounded p-2"
                                  style={{
                                    background: "var(--ss-warning-soft)",
                                    color: "var(--ss-warning)",
                                  }}
                                >
                                  {t("components.experimentDesignModal.unknownKeys", {
                                    keys: unknownKeys.join(", "),
                                  })}
                                </div>
                              ) : null;
                            })()}

                            <div className="space-y-2">
                              <label className="text-xs font-semibold block">
                                {t("experimentBuilder.step2.scenarioDescriptionLabel", {
                                  defaultValue: "Scenario description",
                                })}
                              </label>
                              <textarea
                                value={intervention.scenarioDescription ?? ""}
                                onChange={(event) =>
                                  updateIntervention(
                                    variant.id,
                                    intervention.id,
                                    "scenarioDescription",
                                    event.target.value
                                  )
                                }
                                placeholder={t(
                                  "components.experimentDesignModal.scenarioDescriptionPlaceholder",
                                  { defaultValue: "Optional description override" }
                                )}
                                className="w-full text-xs border rounded p-2 h-16"
                                style={{
                                  background: "var(--ss-input-bg)",
                                  borderColor: "var(--ss-border)",
                                  color: "var(--ss-text)",
                                }}
                              />
                            </div>

                            <div className="space-y-2">
                              <label className="text-xs font-semibold block">
                                {t("experimentBuilder.roundSettings.roundVisibility.label", {
                                  defaultValue: "Round visibility",
                                })}
                              </label>
                              <select
                                value={intervention.roundVisibility || "simultaneous"}
                                onChange={(event) =>
                                  updateIntervention(
                                    variant.id,
                                    intervention.id,
                                    "roundVisibility",
                                    event.target.value
                                  )
                                }
                                className="w-full text-xs border rounded px-2 py-2"
                                style={{
                                  background: "var(--ss-input-bg)",
                                  borderColor: "var(--ss-border)",
                                  color: "var(--ss-text)",
                                }}
                              >
                                <option value="simultaneous">
                                  {t(
                                    "experimentBuilder.roundSettings.roundVisibility.simultaneous",
                                    { defaultValue: "Simultaneous" }
                                  )}
                                </option>
                                <option value="sequential">
                                  {t(
                                    "experimentBuilder.roundSettings.roundVisibility.sequential",
                                    { defaultValue: "Sequential" }
                                  )}
                                </option>
                              </select>
                            </div>
                          </div>
                        ) : null}

                        {intervention.type === "NETWORK_TOPOLOGY" ? (
                          <div className="space-y-2">
                            <div className="flex items-center gap-2 text-xs font-semibold">
                              <Network
                                size={14}
                                style={{ color: "var(--ss-brand-primary)" }}
                              />
                              <span>
                                {t("components.experimentDesignModal.networkTopologyType")}
                              </span>
                            </div>

                            <select
                              value={intervention.networkPreset || "full"}
                              onChange={(event) =>
                                updateIntervention(
                                  variant.id,
                                  intervention.id,
                                  "networkPreset",
                                  event.target.value
                                )
                              }
                              className="w-full text-xs border rounded px-2 py-2"
                              style={{
                                background: "var(--ss-input-bg)",
                                borderColor: "var(--ss-border)",
                                color: "var(--ss-text)",
                              }}
                            >
                              {[
                                "full",
                                "ring",
                                "star",
                                "random",
                                "newman-watts",
                                "core-periphery",
                                "holme-kim",
                                "waxman",
                                "sbm",
                                "custom",
                              ].map((preset) => (
                                <option key={preset} value={preset}>
                                  {translateNetworkPreset(preset)}
                                </option>
                              ))}
                            </select>

                            {intervention.networkPreset === "custom" ? (
                              <textarea
                                value={
                                  intervention.customEdges
                                    ?.map((edge: [string, string]) => edge.join(", "))
                                    .join("\n") || ""
                                }
                                onChange={(event) => {
                                  const edges = event.target.value
                                    .split("\n")
                                    .map((line) => {
                                      const parts = line
                                        .split(",")
                                        .map((item) => item.trim());
                                      return parts.length >= 2
                                        ? ([parts[0], parts[1]] as [string, string])
                                        : null;
                                    })
                                    .filter(
                                      (
                                        edge
                                      ): edge is [string, string] => edge !== null
                                    );
                                  updateIntervention(
                                    variant.id,
                                    intervention.id,
                                    "customEdges",
                                    edges
                                  );
                                }}
                                placeholder={t(
                                  "components.experimentDesignModal.customEdgesPlaceholder"
                                )}
                                className="w-full text-xs border rounded p-2 font-mono h-16"
                                style={{
                                  background: "var(--ss-input-bg)",
                                  borderColor: "var(--ss-border)",
                                  color: "var(--ss-text)",
                                }}
                              />
                            ) : null}

                            {intervention.networkPreset !== "custom" ? (
                              <textarea
                                value={JSON.stringify(intervention.networkParams || {}, null, 2)}
                                onChange={(event) => {
                                  try {
                                    const nextParams = JSON.parse(event.target.value) as Partial<NetworkParams>;
                                    updateIntervention(
                                      variant.id,
                                      intervention.id,
                                      "networkParams",
                                      nextParams
                                    );
                                  } catch {
                                    updateIntervention(
                                      variant.id,
                                      intervention.id,
                                      "networkParams",
                                      intervention.networkParams || {}
                                    );
                                  }
                                }}
                                placeholder='{"random": {"connectionChance": 0.3}}'
                                className="w-full text-xs border rounded p-2 font-mono h-24"
                                style={{
                                  background: "var(--ss-input-bg)",
                                  borderColor: "var(--ss-border)",
                                  color: "var(--ss-text)",
                                }}
                              />
                            ) : null}
                          </div>
                        ) : null}

                        {intervention.type !== "SCENARIO_PARAMS" &&
                        intervention.type !== "NETWORK_TOPOLOGY" ? (
                          <>
                            {intervention.type === "AGENT_PROPERTY" ? (
                              <div className="flex items-center gap-2 text-xs font-semibold mb-2">
                                <UserCog
                                  size={14}
                                  style={{ color: "var(--ss-brand-primary)" }}
                                />
                                <span>
                                  {t("components.experimentDesignModal.propertyType")}
                                </span>
                              </div>
                            ) : null}
                            <textarea
                              value={intervention.description}
                              onChange={(event) =>
                                updateIntervention(
                                  variant.id,
                                  intervention.id,
                                  "description",
                                  event.target.value
                                )
                              }
                              placeholder={
                                intervention.type === "AGENT_PROPERTY"
                                  ? t(
                                      "components.experimentDesignModal.propertyPlaceholder"
                                    )
                                  : intervention.type === "FOLLOW_UP_CONDITION"
                                    ? t(
                                        "components.experimentDesignModal.followUpConditionPlaceholder",
                                        {
                                          defaultValue:
                                            "Example: resource_shortage=0.8, public_opinion_pressure=0.6",
                                        }
                                      )
                                    : intervention.type === "FOLLOW_UP_THREAD_SEED"
                                      ? t(
                                          "components.experimentDesignModal.followUpThreadSeedPlaceholder",
                                          {
                                            defaultValue:
                                              "Example: Agent A messages Agent B with a follow-up request.",
                                          }
                                        )
                                      : t(
                                          "components.experimentDesignModal.descriptionPlaceholder"
                                        )
                              }
                              className="w-full text-xs border rounded p-2 focus:outline-none resize-none h-16"
                              style={{
                                background: "var(--ss-input-bg)",
                                borderColor: "var(--ss-border)",
                                color: "var(--ss-text)",
                              }}
                            />
                            {extractMarkdownImages(intervention.description || "")
                              .length > 0 ? (
                              <div className="mt-2 flex flex-wrap gap-2">
                                {extractMarkdownImages(
                                  intervention.description || ""
                                ).map((url) => (
                                  <div
                                    key={url}
                                    className="w-16 h-16 border rounded overflow-hidden"
                                    style={{
                                      background: "var(--ss-surface-inset)",
                                      borderColor: "var(--ss-border)",
                                    }}
                                  >
                                    <img
                                      src={url}
                                      alt="preview"
                                      className="w-full h-full object-cover"
                                    />
                                  </div>
                                ))}
                              </div>
                            ) : null}
                            <MultimodalInput
                              onUploadComplete={(url) =>
                                handleEmbedInterventionImage(
                                  variant.id,
                                  intervention.id,
                                  url
                                )
                              }
                            />
                          </>
                        ) : null}

                        <button
                          onClick={() =>
                            removeIntervention(variant.id, intervention.id)
                          }
                          className="absolute top-2 right-2"
                          style={{ color: "var(--ss-text-subtle)" }}
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))
                  )}

                  <button
                    onClick={() => addIntervention(variant.id)}
                    className="w-full py-2 border-2 border-dashed rounded-lg text-xs font-bold flex items-center justify-center gap-1 transition-colors"
                    style={{
                      borderColor: "var(--ss-brand-soft)",
                      color: "var(--ss-brand-primary)",
                    }}
                  >
                    <Plus size={14} />
                    {t("components.experimentDesignModal.addIntervention")}
                  </button>
                </div>
              </div>
            ))}

            <button
              onClick={handleAddVariant}
              className="border-2 border-dashed rounded-xl min-h-[200px] flex flex-col items-center justify-center transition-all gap-2"
              style={{
                background: "var(--ss-surface-inset)",
                borderColor: "var(--ss-border)",
                color: "var(--ss-text-subtle)",
              }}
            >
              <div
                className="w-12 h-12 rounded-full border-2 border-current flex items-center justify-center"
                style={{ background: "var(--ss-layer-card)" }}
              >
                <Plus size={24} />
              </div>
              <span className="font-bold text-sm">
                {t("components.experimentDesignModal.addVariant")}
              </span>
            </button>
          </div>

          {showPreview ? (
            <div
              className="fixed inset-0 backdrop-blur-sm z-[150] flex flex-col"
              style={{ background: "var(--ss-surface)" }}
            >
              <div
                className="px-6 py-4 border-b shrink-0"
                style={{
                  background: "var(--ss-brand-soft)",
                  borderColor: "var(--ss-border)",
                }}
              >
                <h3
                  className="text-lg font-bold flex items-center gap-2"
                  style={{ color: "var(--ss-heading)" }}
                >
                  <Sliders size={20} />
                  {t("components.experimentDesignModal.previewTitle")}
                </h3>
              </div>
              <div className="flex-1 overflow-y-auto p-6">
                <div className="space-y-6">
                  {buildPreviewData().map((preview) => (
                    <div
                      key={preview.variantId}
                      className="rounded-lg p-4"
                      style={{ background: "var(--ss-surface-inset)" }}
                    >
                      <h4
                        className="font-bold text-sm mb-3"
                        style={{ color: "var(--ss-heading)" }}
                      >
                        {t("components.experimentDesignModal.previewVariant")}:{" "}
                        {preview.variantName}
                      </h4>

                      {preview.paramChanges.length > 0 ? (
                        <div className="mb-3">
                          <h5
                            className="text-xs font-semibold mb-2"
                            style={{ color: "var(--ss-text-muted)" }}
                          >
                            {t(
                              "components.experimentDesignModal.previewScenarioParams"
                            )}
                            :
                          </h5>
                          <div className="space-y-1">
                            {preview.paramChanges.map((change, index) => (
                              <div
                                key={index}
                                className="text-xs flex items-center gap-2"
                              >
                                <span
                                  className="font-mono"
                                  style={{
                                    color: change.unknown
                                      ? "var(--ss-warning)"
                                      : "var(--ss-text)",
                                  }}
                                >
                                  {change.key}
                                  {change.unknown ? (
                                    <span className="ml-1">
                                      {t(
                                        "components.experimentDesignModal.previewUnknownKey"
                                      )}
                                    </span>
                                  ) : null}
                                </span>
                                <span style={{ color: "var(--ss-text-subtle)" }}>
                                  {"->"}
                                </span>
                                <span
                                  className="font-mono"
                                  style={{ color: "var(--ss-brand-primary)" }}
                                >
                                  {String(change.new)}
                                </span>
                                {change.was !== undefined ? (
                                  <span
                                    className="text-[10px]"
                                    style={{ color: "var(--ss-text-subtle)" }}
                                  >
                                    (
                                    {t(
                                      "components.experimentDesignModal.previewWas"
                                    )}
                                    : {String(change.was)})
                                  </span>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {preview.otherInterventions.length > 0 ? (
                        <div>
                          <h5
                            className="text-xs font-semibold mb-2"
                            style={{ color: "var(--ss-text-muted)" }}
                          >
                            {t("components.experimentDesignModal.interventionCount")}
                            :
                          </h5>
                          <div className="space-y-1">
                            {preview.otherInterventions.map((intervention, index) => (
                              <div
                                key={index}
                                className="text-xs rounded px-2 py-1"
                                style={{ background: "var(--ss-layer-card)" }}
                              >
                                <span
                                  className="font-semibold"
                                  style={{ color: "var(--ss-text-muted)" }}
                                >
                                  {translateInterventionType(intervention.type)}:
                                </span>{" "}
                                <span style={{ color: "var(--ss-text)" }}>
                                  {intervention.description}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {preview.paramChanges.length === 0 &&
                      preview.otherInterventions.length === 0 ? (
                        <div
                          className="text-xs italic"
                          style={{ color: "var(--ss-text-subtle)" }}
                        >
                          {t("components.experimentDesignModal.previewNoChanges")}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
              <div
                className="px-6 py-4 border-t flex justify-end gap-3 shrink-0"
                style={{ borderColor: "var(--ss-border)" }}
              >
                <button
                  onClick={() => setShowPreview(false)}
                  className="px-4 py-2 text-sm font-medium rounded-lg"
                  style={{ color: "var(--ss-text-muted)" }}
                >
                  {t("components.experimentDesignModal.previewBack")}
                </button>
                <button
                  onClick={() => {
                    setShowPreview(false);
                    handleSubmit();
                  }}
                  className="px-6 py-2 text-sm font-medium rounded-lg flex items-center gap-2"
                  style={{
                    background: "var(--ss-brand-primary)",
                    color: "var(--ss-brand-on)",
                  }}
                >
                  <Zap size={16} />
                  {t("components.experimentDesignModal.previewConfirm")}
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <div
        className="px-6 py-4 border-t flex justify-end gap-3 shrink-0"
        style={{ borderColor: "var(--ss-border)" }}
      >
        {onClose ? (
          <button
            onClick={closePanel}
            className="px-4 py-2 text-sm font-medium rounded-lg"
            style={{ color: "var(--ss-text-muted)" }}
          >
            {t("components.experimentDesignModal.cancel")}
          </button>
        ) : null}
        <button
          onClick={() => setShowPreview(true)}
          className="px-6 py-2 text-sm font-medium rounded-lg flex items-center gap-2"
          style={{
            background: "var(--ss-brand-primary)",
            color: "var(--ss-brand-on)",
          }}
        >
          <Sliders size={16} />
          {t("components.experimentDesignModal.startBatch", {
            count: variants.length,
          })}
        </button>
      </div>
    </div>
  );
};

export default ExperimentDesignPanel;
