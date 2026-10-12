/**
 * This file gives the host one place to guide a running simulation.
 *
 * Each part here does one simple job:
 * - the suggestion block asks for environment suggestions and adopts them,
 * - the broadcast and event blocks send host messages,
 * - the state block edits one agent property,
 * - the event panel block opens saved external events and applies them.
 */

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Check,
  CloudLightning,
  Edit,
  FilePlus,
  Globe,
  Loader2,
  Megaphone,
  Save,
  Settings,
  Sparkles,
} from "lucide-react";

import { useSimulationStore } from "../store";
import { applyEnvironmentEvent, generateSuggestions, type EnvironmentSuggestion } from "../services/environmentSuggestions";
import { type ExternalEventRecord } from "../services/externalEvents";
import { EventPanel } from "./EventPanel";
import { InitialEventsModal } from "./InitialEventsModal";
import { MultimodalInput } from "./MultimodalInput";
import { RuleConfig, type Rule } from "./RuleConfig";

const humanizeBackendLabel = (value: string): string => {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return "";
  }
  return normalized
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
};

export const HostPanel: React.FC = () => {
  const { t } = useTranslation();
  const agents = useSimulationStore((state) => state.agents);
  const currentSimulation = useSimulationStore((state) => state.currentSimulation);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const injectLog = useSimulationStore((state) => state.injectLog);
  const updateAgentProperty = useSimulationStore((state) => state.updateAgentProperty);
  const addNotification = useSimulationStore((state) => state.addNotification);
  const toggleInitialEvents = useSimulationStore(
    (state) => state.toggleInitialEvents as ((open: boolean) => void) | undefined,
  );

  const [broadcastMsg, setBroadcastMsg] = useState("");
  const [envEvent, setEnvEvent] = useState("");
  const [envImage, setEnvImage] = useState<string | null>(null);
  const [broadcastRecipients, setBroadcastRecipients] = useState<string[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState(agents[0]?.id || "");
  const [selectedProp, setSelectedProp] = useState("");
  const [propValue, setPropValue] = useState("");
  const [suggestions, setSuggestions] = useState<EnvironmentSuggestion[]>([]);
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [rules, setRules] = useState<Rule[]>([]);
  const [showEventPanel, setShowEventPanel] = useState(false);
  const [showRuleConfig, setShowRuleConfig] = useState(false);

  const translateSuggestionEventType = (eventType: string) => {
    const key = `components.environmentSuggestion.eventType.${eventType}`;
    const translated = t(key);
    return translated === key ? humanizeBackendLabel(eventType) : translated;
  };

  const translateSuggestionSeverity = (severity: string) => {
    const key = `components.environmentSuggestion.severity.${severity}`;
    const translated = t(key);
    return translated === key ? humanizeBackendLabel(severity) : translated;
  };

  const formatBroadcastLog = (description: string) => {
    const recipients = broadcastRecipients.filter(Boolean);
    const scopeLabel = recipients.length > 0
      ? t("components.hostPanel.privateBroadcastLog", "Private broadcast")
      : t("components.hostPanel.globalBroadcastLog", "Global broadcast");
    const recipientLabel = recipients.length > 0
      ? recipients.join(", ")
      : t("components.hostPanel.allAgentsLog", "All agents");
    return `${scopeLabel}\n${t("components.hostPanel.recipientsLog", "Recipients")}: ${recipientLabel}\n${description}`;
  };

  const pushEnvironmentEvent = async (description: string, eventType: string) => {
    if (!description.trim()) {
      return;
    }
    const recipients = eventType === "broadcast" && broadcastRecipients.length > 0
      ? broadcastRecipients
      : undefined;

    if (currentSimulation?.id) {
      const isPolicyScene = currentSimulation?.scene_type === "policy_cascade_scene";
      const payload: EnvironmentSuggestion & { receivers?: string[]; node_id?: string | number | null } = {
        event_type: eventType,
        description,
        severity: "mild",
        receivers: recipients,
        node_id: selectedNodeId,
      };
      if (isPolicyScene) {
        payload.notice_only = eventType !== "broadcast";
      }
      await applyEnvironmentEvent(currentSimulation.id, payload);
    }

    const logContent = eventType === "broadcast" ? formatBroadcastLog(description) : description;
    injectLog(eventType === "broadcast" ? "SYSTEM" : "ENVIRONMENT", logContent, envImage || undefined);
  };

  const handleBroadcast = async () => {
    if (!broadcastMsg.trim()) {
      return;
    }
    await pushEnvironmentEvent(`${t("components.hostPanel.logPrefixSystemAnnouncement")} ${broadcastMsg}`, "broadcast");
    setBroadcastMsg("");
  };

  const handleEnvEvent = async (text: string = envEvent) => {
    if (!text.trim() && !envImage) {
      return;
    }
    await pushEnvironmentEvent(`${t("components.hostPanel.logPrefixEnvironmentEvent")} ${text}`, "environment");
    if (text === envEvent) {
      setEnvEvent("");
      setEnvImage(null);
    }
  };

  const handleUpdateProp = () => {
    if (!selectedAgentId || !selectedProp) {
      return;
    }
    const parsedValue = Number.isNaN(Number(propValue)) ? propValue : Number(propValue);
    updateAgentProperty(selectedAgentId, selectedProp, parsedValue);
    setPropValue("");
  };

  const handleGetSuggestions = async () => {
    if (!currentSimulation?.id) {
      addNotification("error", t("components.hostPanel.fetchSuggestionsFailed"));
      return;
    }
    setIsSuggesting(true);
    try {
      const result = await generateSuggestions(currentSimulation.id, selectedNodeId);
      setSuggestions(result.suggestions || []);
    } catch (error) {
      console.error("Failed to fetch environment suggestions", error);
      addNotification("error", t("components.hostPanel.fetchSuggestionsFailed"));
    } finally {
      setIsSuggesting(false);
    }
  };

  const handleAdoptSuggestion = (suggestion: EnvironmentSuggestion) => {
    void handleEnvEvent(suggestion.description);
    setSuggestions((previous) => previous.filter((item) => item.description !== suggestion.description));
    addNotification("success", t("components.hostPanel.suggestionAdopted"));
  };

  const handleAppliedExternalEvent = (event: ExternalEventRecord, appliedDescription: string) => {
    injectLog("ENVIRONMENT", appliedDescription);
    addNotification("success", t("components.hostPanel.suggestionAdopted"));
    setSuggestions((previous) => previous.filter((item) => item.description !== event.content));
  };

  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);
  const properties = selectedAgent ? Object.keys(selectedAgent.properties) : [];

  return (
    <div className="flex flex-col h-full" style={{ background: "var(--ss-workspace-surface)" }}>
      <div className="p-3 border-b bg-amber-50/50">
        <p className="text-xs text-amber-800 leading-relaxed">
          <strong>{t("components.hostPanel.godModeTitle")}</strong>: {t("components.hostPanel.godModeDescription")}
        </p>
        <button
          onClick={() => toggleInitialEvents?.(true)}
          className="mt-2 text-[11px] px-2 py-1 border border-amber-200 text-amber-700 rounded flex items-center gap-1"
          style={{ background: "var(--ss-workspace-surface)" }}
        >
          <FilePlus size={12} /> {t("components.hostPanel.initialEventsEditor")}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div className="bg-indigo-50 rounded-lg p-3 border border-indigo-100">
          <div className="flex justify-between items-center mb-2">
            <label className="text-xs font-bold text-indigo-800 flex items-center gap-1">
              <Sparkles size={14} /> {t("components.hostPanel.aiAdvisor")}
            </label>
            <button
              onClick={handleGetSuggestions}
              disabled={isSuggesting}
              className="text-[10px] border border-indigo-200 text-indigo-600 px-2 py-1 rounded hover:bg-indigo-100 disabled:opacity-50"
              style={{ background: "var(--ss-workspace-surface)" }}
            >
              {isSuggesting ? <Loader2 size={10} className="animate-spin inline" /> : t("components.hostPanel.getSuggestions")}
            </button>
          </div>

          {suggestions.length > 0 ? (
            <div className="space-y-2">
              {suggestions.map((suggestion, index) => (
                <div
                  key={`${suggestion.description}-${index}`}
                  className="p-2 rounded border border-indigo-100 text-xs shadow-sm group"
                  style={{ background: "var(--ss-workspace-surface)" }}
                >
                  <p className="font-bold mb-1" style={{ color: "var(--ss-workspace-heading)" }}>
                    {suggestion.description}
                  </p>
                  <p className="text-[10px] mb-2 uppercase tracking-[0.12em]" style={{ color: "var(--ss-workspace-muted)" }}>
                    {translateSuggestionEventType(suggestion.event_type)} · {translateSuggestionSeverity(suggestion.severity)}
                  </p>
                  <button
                    onClick={() => handleAdoptSuggestion(suggestion)}
                    className="w-full py-1 bg-indigo-50 text-indigo-600 font-bold rounded hover:bg-indigo-100 flex items-center justify-center gap-1 opacity-80 hover:opacity-100"
                  >
                    <Check size={12} /> {t("components.hostPanel.adoptEvent")}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-4 text-indigo-300 text-xs italic">
              {t("components.hostPanel.getSuggestionsHint")}
            </div>
          )}
        </div>

        <hr style={{ borderColor: "var(--ss-border)" }} />

        <div className="space-y-2">
          <label className="text-xs font-bold flex items-center gap-1" style={{ color: "var(--ss-workspace-heading)" }}>
            <Megaphone size={14} /> {t("components.hostPanel.systemBroadcast")}
          </label>
          <div className="text-[11px] mb-1" style={{ color: "var(--ss-workspace-muted)" }}>
            {t("components.hostPanel.recipientHint", "Choose recipients, or leave empty for everyone:")}
          </div>
          <div className="flex flex-wrap gap-1 mb-2">
            {agents.map((agent) => {
              const checked = broadcastRecipients.includes(agent.name) || broadcastRecipients.includes(agent.id);
              return (
                <label
                  key={agent.id}
                  className="flex items-center gap-1 text-[11px] px-2 py-1 border rounded cursor-pointer"
                  style={{ borderColor: "var(--ss-workspace-border)", background: "var(--ss-workspace-surface)" }}
                >
                  <input
                    type="checkbox"
                    className="accent-brand-500"
                    checked={checked}
                    onChange={(event) => {
                      setBroadcastRecipients((previous) => {
                        const key = agent.name;
                        if (event.target.checked) {
                          return Array.from(new Set([...previous, key]));
                        }
                        return previous.filter((value) => value !== key);
                      });
                    }}
                  />
                  <span>{agent.name}</span>
                </label>
              );
            })}
          </div>
          <div className="flex gap-2">
            <textarea
              value={broadcastMsg}
              onChange={(event) => setBroadcastMsg(event.target.value)}
              placeholder={t("components.hostPanel.broadcastPlaceholder")}
              className="flex-1 text-sm border rounded p-2 focus:ring-1 focus:ring-brand-500 outline-none resize-none h-20"
            />
          </div>
          <button
            onClick={handleBroadcast}
            disabled={!broadcastMsg}
            className="w-full py-1.5 text-xs text-white rounded disabled:opacity-50"
            style={{ background: "var(--ss-neutral-900)" }}
          >
            {t("components.hostPanel.sendBroadcast")}
          </button>
        </div>

        <hr style={{ borderColor: "var(--ss-border)" }} />

        <div className="space-y-2">
          <label className="text-xs font-bold flex items-center gap-1" style={{ color: "var(--ss-workspace-heading)" }}>
            <CloudLightning size={14} /> {t("components.hostPanel.injectEvent")}
          </label>
          {currentSimulation?.scene_type === "policy_cascade_scene" && (
            <div className="text-[11px] italic" style={{ color: "var(--ss-workspace-muted)" }}>
              {t("components.hostPanel.injectNoticeOnly", "Environment event injection is notice-only here and does not trigger a full system broadcast.")}
            </div>
          )}
          <div className="flex flex-col gap-2">
            <input
              type="text"
              value={envEvent}
              onChange={(event) => setEnvEvent(event.target.value)}
              placeholder={t("components.hostPanel.eventPlaceholder")}
              className="w-full text-sm border rounded px-2 py-1.5 focus:ring-1 focus:ring-emerald-500 outline-none"
            />

            <MultimodalInput
              label={t("components.hostPanel.imageLabel")}
              helperText={t("components.hostPanel.imageHelper")}
              presetUrl={envImage}
              onInsert={(url) => {
                setEnvImage(url);
                addNotification("success", t("components.hostPanel.imageUploaded"));
              }}
            />
          </div>
          <button
            onClick={() => void handleEnvEvent()}
            disabled={!envEvent && !envImage}
            className="w-full py-1.5 text-xs bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50"
          >
            {t("components.hostPanel.triggerEvent")}
          </button>
        </div>

        <hr style={{ borderColor: "var(--ss-border)" }} />

        <div className="space-y-3 p-3 rounded-lg border" style={{ background: "var(--ss-surface-strong)" }}>
          <label className="text-xs font-bold flex items-center gap-1" style={{ color: "var(--ss-workspace-heading)" }}>
            <Edit size={14} /> {t("components.hostPanel.modifyState")}
          </label>

          <select
            value={selectedAgentId}
            onChange={(event) => {
              setSelectedAgentId(event.target.value);
              setSelectedProp("");
              setPropValue("");
            }}
            className="w-full text-xs border rounded px-2 py-1.5"
            style={{ background: "var(--ss-workspace-surface)" }}
          >
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name} ({agent.role})
              </option>
            ))}
          </select>

          <select
            value={selectedProp}
            onChange={(event) => setSelectedProp(event.target.value)}
            disabled={!selectedAgent}
            className="w-full text-xs border rounded px-2 py-1.5 disabled:opacity-50"
            style={{ background: "var(--ss-workspace-surface)" }}
          >
            <option value="">{t("components.hostPanel.selectProperty")}</option>
            {properties.map((property) => (
              <option key={property} value={property}>
                {property}
              </option>
            ))}
          </select>

          <input
            type="text"
            value={propValue}
            onChange={(event) => setPropValue(event.target.value)}
            placeholder={t("components.hostPanel.enterNewValue")}
            disabled={!selectedProp}
            className="w-full text-xs border rounded px-2 py-1.5 focus:ring-1 focus:ring-blue-500 outline-none"
            style={{ background: !selectedProp ? "var(--ss-surface-inset)" : "var(--ss-workspace-surface)" }}
          />

          <button
            onClick={handleUpdateProp}
            disabled={!selectedProp || !propValue}
            className="w-full py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-1"
          >
            <Save size={12} /> {t("components.hostPanel.updateProperty")}
          </button>
        </div>

        <hr style={{ borderColor: "var(--ss-border)" }} />

        <div className="space-y-2">
          <label
            className="text-xs font-bold flex items-center gap-1 cursor-pointer"
            style={{ color: "var(--ss-workspace-heading)" }}
            onClick={() => setShowEventPanel(!showEventPanel)}
          >
            <Globe size={14} /> {t("components.hostPanel.externalEvents")}
            <span className="text-[10px] ml-1 px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-600">
              {t("components.hostPanel.new")}
            </span>
          </label>
          {showEventPanel && (
            <div className="mt-2">
              <EventPanel
                simulationId={currentSimulation?.id}
                nodeId={selectedNodeId}
                onEventApply={handleAppliedExternalEvent}
                onError={(message) => addNotification("error", message)}
              />
            </div>
          )}
        </div>

        <div className="space-y-2">
          <label
            className="text-xs font-bold flex items-center gap-1 cursor-pointer"
            style={{ color: "var(--ss-workspace-heading)" }}
            onClick={() => setShowRuleConfig(!showRuleConfig)}
          >
            <Settings size={14} /> {t("components.hostPanel.ruleConfig")}
            <span className="text-[10px] ml-1 px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-600">
              {t("components.hostPanel.new")}
            </span>
          </label>
          {showRuleConfig && (
            <div className="mt-2">
              <RuleConfig rules={rules} onChange={setRules} simulationId={currentSimulation?.id} />
            </div>
          )}
        </div>
      </div>
      <InitialEventsModal />
    </div>
  );
};
