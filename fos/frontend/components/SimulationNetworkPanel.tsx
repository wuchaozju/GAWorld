/**
 * This file shows the editable network area inside a running simulation.
 *
 * SimulationNetworkPanel lets people pick a network preset, add or
 * remove manual links, click links on the graph, and save each change
 * back to the current simulation.
 */

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, Settings2 } from "lucide-react";

import { useSimulationStore } from "../store";
import type { Agent, SocialNetwork } from "../types";
import NetworkGraph from "./NetworkGraph";
import {
  buildPresetNetwork,
  cloneNetwork,
  connectPair,
  NewmanWattsParams,
  RandomParams,
  removePair,
  SimulationPresetType,
  simulationPresetIcons,
} from "./network/simulationNetworkHelpers";

interface SimulationNetworkPanelProps {
  className?: string;
}

export const SimulationNetworkPanel: React.FC<SimulationNetworkPanelProps> = ({
  className = "",
}) => {
  const { t } = useTranslation();
  const agents = useSimulationStore((state) => state.agents);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const updateSocialNetwork = useSimulationStore(
    (state) => state.updateSocialNetwork
  );

  const [selectedPreset, setSelectedPreset] = useState<SimulationPresetType>("full");
  const [randomParams, setRandomParams] = useState<RandomParams>({
    connectionChance: 0.3,
  });
  const [newmanWattsParams, setNewmanWattsParams] = useState<NewmanWattsParams>({
    neighborsEachSide: 2,
    shortcutChance: 0.1,
  });
  const [linkFrom, setLinkFrom] = useState("");
  const [linkTo, setLinkTo] = useState("");
  const [draftNetwork, setDraftNetwork] = useState<SocialNetwork>({});

  const agentNames = useMemo(() => agents.map((agent) => agent.name), [agents]);

  const socialNetwork = useMemo(
    () => cloneNetwork(currentSimulation?.socialNetwork ?? {}, agentNames),
    [agentNames, currentSimulation]
  );

  useEffect(() => {
    setDraftNetwork(socialNetwork);
  }, [socialNetwork]);

  useEffect(() => {
    if (agentNames.length === 0) return;
    if (!agentNames.includes(linkFrom)) {
      setLinkFrom(agentNames[0]);
    }
    if (!agentNames.includes(linkTo)) {
      setLinkTo(agentNames[Math.min(1, agentNames.length - 1)]);
    }
  }, [agentNames, linkFrom, linkTo]);

  const edges = useMemo(() => {
    const list: Array<{ key: string; source: string; target: string }> = [];
    const seen = new Set<string>();
    Object.entries(draftNetwork).forEach(([source, targets]) => {
      targets.forEach((target) => {
        const key = source < target ? `${source}|${target}` : `${target}|${source}`;
        if (seen.has(key)) return;
        seen.add(key);
        list.push({ key, source, target });
      });
    });
    return list.sort((left, right) => left.key.localeCompare(right.key));
  }, [draftNetwork]);

  const graphAgents: Agent[] = useMemo(
    () =>
      agents.map((agent, index) => ({
        ...agent,
        id: agent.id || `agent-${index}`,
      })),
    [agents]
  );

  const saveNetwork = (next: SocialNetwork): void => {
    setDraftNetwork(next);
    void updateSocialNetwork(next);
  };

  const applyPreset = (preset: SimulationPresetType): void => {
    const next = buildPresetNetwork(
      preset,
      agentNames,
      randomParams,
      newmanWattsParams
    );
    setSelectedPreset(preset);
    saveNetwork(next);
  };

  const addManualLink = (): void => {
    if (!linkFrom || !linkTo || linkFrom === linkTo) return;
    const next = cloneNetwork(draftNetwork, agentNames);
    connectPair(next, linkFrom, linkTo);
    saveNetwork(next);
  };

  const removeManualLink = (key: string): void => {
    const [source, target] = key.split("|");
    const next = cloneNetwork(draftNetwork, agentNames);
    removePair(next, source, target);
    saveNetwork(next);
  };

  const toggleGraphLink = (source: string, target: string): void => {
    const key = source < target ? `${source}|${target}` : `${target}|${source}`;
    const exists = edges.some((edge) => edge.key === key);
    const next = cloneNetwork(draftNetwork, agentNames);
    if (exists) {
      removePair(next, source, target);
    } else {
      connectPair(next, source, target);
    }
    saveNetwork(next);
  };

  if (agentNames.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div
          className="rounded-2xl border px-8 py-10 text-center"
          style={{
            background: "var(--ss-workspace-bg)",
            borderColor: "var(--ss-workspace-border)",
            color: "var(--ss-workspace-text)",
          }}
        >
          {t("experimentBuilder.step5.noAgentsConfigured", {
            defaultValue: "Add agents first to edit the network.",
          })}
        </div>
      </div>
    );
  }

  return (
    <div className={`h-full flex flex-col lg:flex-row ${className}`}>
      <div
        className="w-full lg:w-80 shrink-0 border-r p-4 space-y-4 overflow-y-auto"
        style={{
          background: "var(--ss-workspace-surface)",
          borderColor: "var(--ss-workspace-border)",
        }}
      >
        <div>
          <label
            className="text-xs font-bold uppercase tracking-wide"
            style={{ color: "var(--ss-text-muted)" }}
          >
            {t("experimentBuilder.step5.networkPresets", {
              defaultValue: "Network presets",
            })}
          </label>
          <p
            className="text-[10px] mt-0.5 mb-3"
            style={{ color: "var(--ss-text-subtle)" }}
          >
            {t("experimentBuilder.step5.chooseTopology", {
              defaultValue: "Start from a common social structure, then refine it.",
            })}
          </p>

          <div className="space-y-1.5">
            {Object.entries(simulationPresetIcons).map(([key, { icon: Icon, translationKey }]) => {
              const isSelected = selectedPreset === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => applyPreset(key as SimulationPresetType)}
                  className={`w-full p-2 rounded-lg border text-left transition-all ${
                    isSelected ? "ring-1" : ""
                  }`}
                  style={
                    isSelected
                      ? {
                          background: "var(--ss-accent-warm-soft)",
                          borderColor: "var(--ss-brand-primary)",
                          boxShadow: "0 0 0 1px var(--ss-brand-soft)",
                        }
                      : {
                          background: "var(--ss-page-surface)",
                          borderColor: "var(--ss-border)",
                        }
                  }
                >
                  <div className="flex items-center gap-2">
                    <div
                      className="p-1.5 rounded"
                      style={{
                        background: isSelected
                          ? "var(--ss-brand-soft)"
                          : "var(--ss-surface-strong)",
                        color: isSelected
                          ? "var(--ss-brand-primary)"
                          : "var(--ss-text-subtle)",
                      }}
                    >
                      <Icon size={14} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <span
                        className="text-xs font-medium block"
                        style={{
                          color: isSelected
                            ? "var(--ss-brand-primary)"
                            : "var(--ss-text)",
                        }}
                      >
                        {t(`experimentBuilder.step5.presets.${translationKey}.name`, {
                          defaultValue: key,
                        })}
                      </span>
                      <p
                        className="text-[10px] truncate"
                        style={{ color: "var(--ss-text-subtle)" }}
                      >
                        {t(`experimentBuilder.step5.presets.${translationKey}.description`, {
                          defaultValue: "",
                        })}
                      </p>
                    </div>
                    <div className={isSelected ? "rotate-90 transition-transform" : "transition-transform"}>
                      <ChevronRight
                        size={14}
                        style={{ color: "var(--ss-text-subtle)" }}
                      />
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <div
          className="p-3 border rounded-lg shadow-sm space-y-3"
          style={{
            background: "var(--ss-page-surface)",
            borderColor: "var(--ss-border)",
          }}
        >
          <div
            className="text-xs font-semibold flex items-center gap-1.5"
            style={{ color: "var(--ss-text)" }}
          >
            <Settings2 size={12} />
            {t("experimentBuilder.step5.manualLinks", {
              defaultValue: "Manual links",
            })}
          </div>

          <div className="flex items-center gap-2 text-[11px]">
            <select
              value={linkFrom}
              onChange={(event) => setLinkFrom(event.target.value)}
              className="flex-1 border rounded px-2 py-1"
              style={{
                background: "var(--ss-page-surface-muted)",
                borderColor: "var(--ss-border)",
              }}
            >
              {agentNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <span style={{ color: "var(--ss-text-subtle)" }}>{"->"}</span>
            <select
              value={linkTo}
              onChange={(event) => setLinkTo(event.target.value)}
              className="flex-1 border rounded px-2 py-1"
              style={{
                background: "var(--ss-page-surface-muted)",
                borderColor: "var(--ss-border)",
              }}
            >
              {agentNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            onClick={addManualLink}
            disabled={!linkFrom || !linkTo || linkFrom === linkTo}
            className="w-full py-2 rounded text-xs font-medium"
            style={{
              background: "var(--ss-brand-primary)",
              color: "var(--ss-brand-on)",
              opacity: !linkFrom || !linkTo || linkFrom === linkTo ? 0.6 : 1,
            }}
          >
            {t("experimentBuilder.step5.addLink", { defaultValue: "Add link" })}
          </button>

          {edges.length > 0 ? (
            <div
              className="max-h-60 overflow-y-auto pt-2 space-y-1 text-[11px]"
              style={{
                borderTop: "1px solid var(--ss-border)",
                color: "var(--ss-text-muted)",
              }}
            >
              {edges.map(({ key, source, target }) => (
                <div
                  key={key}
                  className="flex items-center justify-between px-2 py-1 rounded"
                  style={{ background: "var(--ss-page-surface-muted)" }}
                >
                  <span className="truncate">
                    {source} {"<->"} {target}
                  </span>
                  <button type="button" onClick={() => removeManualLink(key)}>
                    {t("common.remove", { defaultValue: "Remove" })}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div
              className="text-[10px] pt-2"
              style={{
                color: "var(--ss-text-subtle)",
                borderTop: "1px solid var(--ss-border)",
              }}
            >
              {t("experimentBuilder.step5.noLinks", {
                defaultValue: "No links yet",
              })}
            </div>
          )}
        </div>

        <div
          className="text-xs leading-relaxed pt-3 border-t"
          style={{
            color: "var(--ss-text-subtle)",
            borderColor: "var(--ss-border)",
          }}
        >
          <strong style={{ color: "var(--ss-text-muted)" }}>
            {t("experimentBuilder.step5.instructions", {
              defaultValue: "Instructions",
            })}
            :
          </strong>
          <ul className="list-decimal pl-4 space-y-0.5 mt-1 text-[10px]">
            <li>
              {t("experimentBuilder.step5.instructionSelect", {
                defaultValue: "Pick a preset to rebuild the network.",
              })}
            </li>
            <li>
              {t("experimentBuilder.step5.instructionDrag", {
                defaultValue: "Click two nodes in the graph by toggling edges directly.",
              })}
            </li>
            <li>
              {t("experimentBuilder.step5.instructionZoom", {
                defaultValue: "Scroll to zoom and drag to pan.",
              })}
            </li>
          </ul>
        </div>
      </div>

      <div
        className="flex-1 relative overflow-hidden min-h-[420px]"
        style={{ background: "var(--ss-workspace-bg)" }}
      >
        <NetworkGraph
          network={draftNetwork}
          agents={graphAgents}
          onEdgeToggle={toggleGraphLink}
          className="w-full h-full"
        />

        <div
          className="absolute bottom-4 left-4 backdrop-blur-sm border rounded-lg px-3 py-2 text-[10px]"
          style={{
            background: "var(--ss-page-surface)",
            borderColor: "var(--ss-border)",
            color: "var(--ss-text-muted)",
          }}
        >
          <div className="flex items-center gap-3">
            <span>
              <strong style={{ color: "var(--ss-text)" }}>{agentNames.length}</strong>{" "}
              {t("experimentBuilder.step5.nodes", {
                count: agentNames.length,
                defaultValue: "nodes",
              })}
            </span>
            <span>
              <strong style={{ color: "var(--ss-text)" }}>{edges.length * 2}</strong>{" "}
              {t("experimentBuilder.step5.edges", {
                count: edges.length * 2,
                defaultValue: "edges",
              })}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SimulationNetworkPanel;
