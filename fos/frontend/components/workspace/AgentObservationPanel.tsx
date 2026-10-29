/**
 * Agent observation panel for workspace view.
 *
 * Displays agent list with status, latest activity, memory/knowledge counts,
 * and a detail drawer for the selected agent.
 *
 * Exports: AgentObservationPanel (default)
 */
import React from "react";
import { ArrowRight, Brain, BookOpen, ChevronLeft, Sparkles, UserRound, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSimulationStore } from "../../store";
import { getAgentDisplayName, getAgentDisplayRole } from "../../store/helpers";

interface AgentObservationPanelProps {
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string | null) => void;
  onHide: () => void;
}

type AgentStatusTone = "active" | "processing" | "idle" | "complete";

const summarizeText = (text: string, fallback: string) => {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return normalized || fallback;
};

export const AgentObservationPanel: React.FC<AgentObservationPanelProps> = ({
  selectedAgentId,
  onSelectAgent,
  onHide,
}) => {
  const { t } = useTranslation();
  const agents = useSimulationStore((state) => state.agents);
  const logs = useSimulationStore((state) => state.logs);

  const latestByAgent = React.useMemo(() => {
    const map = new Map<string, { content: string; round: number }>();
    for (let index = logs.length - 1; index >= 0; index -= 1) {
      const entry = logs[index];
      if (!entry.agentId || map.has(entry.agentId)) {
        continue;
      }
      map.set(entry.agentId, {
        content: summarizeText(entry.content, t("components.workspace.agentObservation.noRecentActivity")),
        round: entry.round,
      });
    }
    return map;
  }, [t, logs]);

  const activeAgentId = React.useMemo(() => {
    for (let index = logs.length - 1; index >= 0; index -= 1) {
      const entry = logs[index];
      if (entry.agentId) {
        return entry.agentId;
      }
    }
    return null;
  }, [logs]);

  const selectedAgent = React.useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );

  const getAgentStatus = React.useCallback(
    (agentId: string): { label: string; tone: AgentStatusTone } => {
      if (selectedAgentId === agentId) {
        return { label: t("components.workspace.agentObservation.statusFocused"), tone: "active" };
      }
      if (activeAgentId === agentId) {
        return { label: t("components.workspace.agentObservation.statusProcessing"), tone: "processing" };
      }
      if (latestByAgent.has(agentId)) {
        return { label: t("components.workspace.agentObservation.statusComplete"), tone: "complete" };
      }
      return { label: t("components.workspace.agentObservation.statusIdle"), tone: "idle" };
    },
    [activeAgentId, t, latestByAgent, selectedAgentId],
  );

  return (
    <section className="ss-agent-observation" id="workspace-agents">
      <div className="ss-agent-observation__header">
        <div>
          <div className="ss-kicker">{t("components.workspace.agentObservation.title")}</div>
          <h2>{t("components.workspace.agentObservation.subtitle")}</h2>
        </div>
        <div className="ss-agent-observation__header-actions">
          <span className="ss-agent-observation__count">
            {agents.length}
            <small>{t("components.workspace.agentObservation.agentsLabel")}</small>
          </span>
          <button
            type="button"
            className="ss-icon-button"
            onClick={onHide}
            title={t("components.workspace.agentObservation.hideTitle")}
          >
            <ChevronLeft size={16} />
          </button>
        </div>
      </div>

      <div className="ss-agent-observation__list">
        {agents.length ? (
          agents.map((agent) => {
            const latest = latestByAgent.get(agent.id);
            const status = getAgentStatus(agent.id);
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => onSelectAgent(agent.id)}
                className={`ss-agent-observation__card${selectedAgentId === agent.id ? " is-selected" : ""}`}
              >
                <div className="ss-agent-observation__card-top">
                  <div className="ss-agent-observation__identity">
                    <img src={agent.avatarUrl} alt={getAgentDisplayName(agent)} className="ss-agent-observation__avatar" />
                    <div>
                      <strong>{getAgentDisplayName(agent)}</strong>
                      <span>{getAgentDisplayRole(agent)}</span>
                    </div>
                  </div>
                  <span className={`ss-agent-observation__state is-${status.tone}`}>{status.label}</span>
                </div>

                <p className="ss-agent-observation__copy">
                  {latest?.content || summarizeText(agent.profile, t("components.workspace.agentObservation.waitingForOutput"))}
                </p>

                <div className="ss-agent-observation__footer">
                  <span>
                    {t("components.workspace.agentObservation.memory")} {agent.memory.length}
                  </span>
                  <span>
                    {t("components.workspace.agentObservation.knowledge")} {agent.knowledgeBase.length}
                  </span>
                  <span className="ss-agent-observation__detail-link">
                    {t("components.workspace.agentObservation.viewDetails")}
                    <ArrowRight size={14} />
                  </span>
                </div>
              </button>
            );
          })
        ) : (
              <div className="ss-agent-observation__empty">
            {t("components.workspace.agentObservation.emptyHint")}
          </div>
        )}
      </div>

      {selectedAgent ? (
        <div className="ss-agent-drawer">
          <div className="ss-agent-drawer__backdrop" onClick={() => onSelectAgent(null)} />
          <aside className="ss-agent-drawer__panel">
            <div className="ss-agent-drawer__header">
                <div>
                  <div className="ss-kicker">{t("components.workspace.agentObservation.detailsTitle")}</div>
                <h3>{getAgentDisplayName(selectedAgent)}</h3>
                <p>{getAgentDisplayRole(selectedAgent)}</p>
                </div>
              <button type="button" className="ss-icon-button" onClick={() => onSelectAgent(null)}>
                <X size={16} />
              </button>
            </div>

            <div className="ss-agent-drawer__body">
              <div className="ss-agent-drawer__metric-grid">
                <div className="ss-agent-drawer__metric">
                  <UserRound size={15} />
                  <div>
                    <span>{t("components.workspace.agentObservation.state")}</span>
                    <strong>{getAgentStatus(selectedAgent.id).label}</strong>
                  </div>
                </div>
                <div className="ss-agent-drawer__metric">
                  <Brain size={15} />
                  <div>
                    <span>{t("components.workspace.agentObservation.memoryItems")}</span>
                    <strong>{selectedAgent.memory.length}</strong>
                  </div>
                </div>
                <div className="ss-agent-drawer__metric">
                  <BookOpen size={15} />
                  <div>
                    <span>{t("components.workspace.agentObservation.knowledgeItems")}</span>
                    <strong>{selectedAgent.knowledgeBase.length}</strong>
                  </div>
                </div>
                <div className="ss-agent-drawer__metric">
                  <Sparkles size={15} />
                  <div>
                    <span>{t("components.workspace.agentObservation.model")}</span>
                    <strong>{selectedAgent.llmConfig.model || "—"}</strong>
                  </div>
                </div>
              </div>

              <div className="ss-agent-drawer__section">
                <span>{t("components.workspace.agentObservation.roleSummary")}</span>
                <p>{selectedAgent.profile || t("components.workspace.agentObservation.noRoleSummary")}</p>
              </div>

              <div className="ss-agent-drawer__section">
                <span>{t("components.workspace.agentObservation.latestActivity")}</span>
                <p>{latestByAgent.get(selectedAgent.id)?.content || t("components.workspace.agentObservation.noRecentEvent")}</p>
              </div>

              <div className="ss-agent-drawer__section">
                <span>{t("components.workspace.agentObservation.keyProperties")}</span>
                <div className="ss-agent-drawer__property-list">
                  {Object.entries(selectedAgent.properties || {}).slice(0, 6).map(([key, value]) => (
                    <div key={key} className="ss-agent-drawer__property">
                      <strong>{key}</strong>
                      <span>{String(value)}</span>
                    </div>
                  ))}
                  {!Object.keys(selectedAgent.properties || {}).length ? (
                    <div className="ss-agent-drawer__property is-empty">
                      {t("components.workspace.agentObservation.noAdditionalProperties")}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  );
};

export default AgentObservationPanel;
