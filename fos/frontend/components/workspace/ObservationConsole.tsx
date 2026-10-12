import React from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Brain, Crosshair, Search, UserRound, Zap } from "lucide-react";
import { HostPanel } from "../HostPanel";
import { useSimulationStore } from "../../store";
import type { Agent, LogEntry } from "../../types";

type AgentActivity = {
  content: string;
  round: number | null;
};

type AgentIndex = {
  ids: Set<string>;
  names: globalThis.Map<string, string>;
};

type ActivityState = {
  activeAgentId: string | null;
  latestByAgent: globalThis.Map<string, AgentActivity>;
};

type AgentCollection = {
  key: string;
  title: string;
  representative: Agent;
  members: Agent[];
  activeMemberId: string | null;
  latest?: AgentActivity;
};

const summarizeActivity = (content: string) =>
  String(content || "").replace(/\s+/g, " ").trim().slice(0, 108);

const normalizeCollectionTitle = (agent: Agent) => {
  const role = String(agent.role || "").trim();
  if (role) {
    return role;
  }

  return String(agent.name || "")
    .replace(/\s+\d+$/, "")
    .trim();
};

const buildAgentIndex = (agents: Agent[]): AgentIndex => ({
  ids: new Set(agents.map((agent) => agent.id)),
  names: new globalThis.Map(agents.map((agent) => [agent.name, agent.id])),
});

const resolveAgentId = (entry: LogEntry, agentIndex: AgentIndex) =>
  (entry.agentId && agentIndex.ids.has(entry.agentId) && entry.agentId) ||
  agentIndex.names.get(entry.agentId || "") ||
  null;

const buildActivityState = (logs: LogEntry[], agentIndex: AgentIndex): ActivityState => {
  const latestByAgent = new globalThis.Map<string, AgentActivity>();
  let activeAgentId: string | null = null;

  for (let index = logs.length - 1; index >= 0; index -= 1) {
    const entry = logs[index];
    const resolvedAgentId = resolveAgentId(entry, agentIndex);

    if (!resolvedAgentId) {
      continue;
    }

    if (!activeAgentId) {
      activeAgentId = resolvedAgentId;
    }

    if (!latestByAgent.has(resolvedAgentId)) {
      latestByAgent.set(resolvedAgentId, {
        content: summarizeActivity(entry.content),
        round: Number.isFinite(entry.round) ? entry.round : null,
      });
    }

    if (latestByAgent.size === agentIndex.ids.size) {
      break;
    }
  }

  return { activeAgentId, latestByAgent };
};

const applyActivityEntry = (
  current: ActivityState,
  entry: LogEntry,
  agentIndex: AgentIndex,
): ActivityState => {
  const resolvedAgentId = resolveAgentId(entry, agentIndex);
  if (!resolvedAgentId) {
    return current;
  }

  const latestByAgent = new globalThis.Map(current.latestByAgent);
  latestByAgent.set(resolvedAgentId, {
    content: summarizeActivity(entry.content),
    round: Number.isFinite(entry.round) ? entry.round : null,
  });

  return {
    activeAgentId: resolvedAgentId,
    latestByAgent,
  };
};

const FocusMetric: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <div className="ss-observation__metric">
    <span className="ss-observation__metric-label">{label}</span>
    <strong className="ss-observation__metric-value">{value}</strong>
  </div>
);

const CollectionRow: React.FC<{
  collection: AgentCollection;
  latest?: AgentActivity;
  isSelected: boolean;
  isActive: boolean;
  onSelect: () => void;
}> = React.memo(({ collection, latest, isSelected, isActive, onSelect }) => {
  const { t } = useTranslation();

  return (
    <button
      onClick={onSelect}
      className={`ss-observation__directory-row ${isSelected ? "is-selected" : ""}`}
    >
      <img
        src={collection.representative.avatarUrl}
        alt={collection.representative.name}
        className="ss-observation__directory-avatar"
      />
      <div className="min-w-0 flex-1 text-left">
        <div className="ss-observation__directory-topline">
          <span className="ss-observation__directory-name">{collection.title}</span>
          {isActive ? (
            <span className="ss-observation__role-state is-active">
              {t("components.agentPanel.activeNow")}
            </span>
          ) : null}
        </div>
        <div className="ss-observation__directory-role">
          {t("controlRoom.collectionRepresentative")}
          : {collection.representative.name}
        </div>
        <div className="ss-observation__directory-activity">
          {latest?.content || t("components.agentPanel.noRecentActivity")}
        </div>
      </div>
      <div className="ss-observation__directory-meta">
        <span>{collection.members.length}</span>
      </div>
    </button>
  );
});

CollectionRow.displayName = "CollectionRow";

interface ObservationConsoleProps {
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string | null) => void;
  forcedTab?: "observe" | "host";
  showTabs?: boolean;
}

export const ObservationConsole: React.FC<ObservationConsoleProps> = ({
  selectedAgentId,
  onSelectAgent,
  forcedTab,
  showTabs = true,
}) => {
  const { t } = useTranslation();
  const agents = useSimulationStore((state) => state.agents);
  const logCount = useSimulationStore((state) => state.logs.length);
  const lastLog = useSimulationStore((state) => state.logs[state.logs.length - 1] || null);
  const selectedNodeId = useSimulationStore((state) => state.selectedNodeId);
  const isCompareMode = useSimulationStore((state) => state.isCompareMode);
  const [activeTab, setActiveTab] = React.useState<"observe" | "host">(forcedTab ?? "observe");
  const [directoryQuery, setDirectoryQuery] = React.useState("");
  const [selectedCollectionKey, setSelectedCollectionKey] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (forcedTab) {
      setActiveTab(forcedTab);
    }
  }, [forcedTab]);

  const agentIndex = React.useMemo(() => buildAgentIndex(agents), [agents]);
  const agentSignature = React.useMemo(() => agents.map((agent) => agent.id).join("|"), [agents]);
  const previousNodeIdRef = React.useRef<string | null>(selectedNodeId);
  const previousLogCountRef = React.useRef(logCount);
  const previousAgentSignatureRef = React.useRef(agentSignature);
  const [activityState, setActivityState] = React.useState<ActivityState>(() =>
    buildActivityState(useSimulationStore.getState().logs, buildAgentIndex(useSimulationStore.getState().agents)),
  );

  React.useEffect(() => {
    const nodeChanged = previousNodeIdRef.current !== selectedNodeId;
    const logsReset = logCount < previousLogCountRef.current;
    const agentsChanged = previousAgentSignatureRef.current !== agentSignature;

    if (nodeChanged || logsReset || agentsChanged) {
      setActivityState(buildActivityState(useSimulationStore.getState().logs, agentIndex));
    } else if (logCount > previousLogCountRef.current && lastLog) {
      setActivityState((current) => applyActivityEntry(current, lastLog, agentIndex));
    } else if (logCount === 0) {
      setActivityState(buildActivityState([], agentIndex));
    }

    previousNodeIdRef.current = selectedNodeId;
    previousLogCountRef.current = logCount;
    previousAgentSignatureRef.current = agentSignature;
  }, [agentIndex, agentSignature, lastLog, logCount, selectedNodeId]);

  const { activeAgentId, latestByAgent } = activityState;
  const selectedAgent = React.useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );
  const agentCollections = React.useMemo(() => {
    const groups = new globalThis.Map<string, { title: string; members: Agent[] }>();

    agents.forEach((agent) => {
      const title = normalizeCollectionTitle(agent) || agent.name;
      const key = title.toLowerCase();
      const current = groups.get(key);
      if (current) {
        current.members.push(agent);
        return;
      }

      groups.set(key, {
        title,
        members: [agent],
      });
    });

    return Array.from(groups.entries())
      .map(([key, value]) => {
        const members = [...value.members].sort((left, right) =>
          left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: "base" })
        );
        const activeMember = members.find((member) => member.id === activeAgentId) || null;
        const latest =
          members
            .map((member) => latestByAgent.get(member.id) || null)
            .filter(Boolean)
            .sort((left, right) => (right!.round || 0) - (left!.round || 0))[0] || undefined;

        return {
          key,
          title: value.title,
          representative: members[0],
          members,
          activeMemberId: activeMember?.id || null,
          latest,
        };
      })
      .sort((left, right) => {
        const leftSelected = left.members.some((member) => member.id === selectedAgentId) ? 1 : 0;
        const rightSelected = right.members.some((member) => member.id === selectedAgentId) ? 1 : 0;
        if (leftSelected !== rightSelected) {
          return rightSelected - leftSelected;
        }

        const leftActive = left.activeMemberId ? 1 : 0;
        const rightActive = right.activeMemberId ? 1 : 0;
        if (leftActive !== rightActive) {
          return rightActive - leftActive;
        }

        return left.title.localeCompare(right.title, undefined, { sensitivity: "base" });
      });
  }, [activeAgentId, agents, latestByAgent, selectedAgentId]);

  const latestMemory = selectedAgent?.memory[selectedAgent.memory.length - 1] || null;

  const directoryCollections = React.useMemo(() => {
    const query = directoryQuery.trim().toLowerCase();
    return agentCollections.filter((collection) => {
      if (!query) {
        return true;
      }

      const haystack = [
        collection.title,
        collection.representative.name,
        collection.representative.role || "",
        collection.latest?.content || "",
        ...collection.members.map((member) => member.name),
      ]
        .join(" ")
        .toLowerCase();

      return haystack.includes(query);
    });
  }, [agentCollections, directoryQuery]);
  const selectedCollection = React.useMemo(
    () =>
      directoryCollections.find((collection) => collection.key === selectedCollectionKey) ||
      agentCollections.find((collection) => collection.key === selectedCollectionKey) ||
      agentCollections.find((collection) => collection.members.some((member) => member.id === selectedAgentId)) ||
      directoryCollections[0] ||
      agentCollections[0] ||
      null,
    [agentCollections, directoryCollections, selectedAgentId, selectedCollectionKey]
  );

  React.useEffect(() => {
    if (!selectedCollection) {
      setSelectedCollectionKey(null);
      return;
    }
    if (selectedCollection.key !== selectedCollectionKey) {
      setSelectedCollectionKey(selectedCollection.key);
    }
  }, [selectedCollection, selectedCollectionKey]);

  const handleSelectCollection = React.useCallback(
    (collection: AgentCollection) => {
      setSelectedCollectionKey(collection.key);
      const nextAgent =
        collection.members.find((member) => member.id === selectedAgentId) ||
        collection.members.find((member) => member.id === collection.activeMemberId) ||
        collection.representative;
      onSelectAgent(nextAgent.id);
    },
    [onSelectAgent, selectedAgentId]
  );

  const handleSelectMember = React.useCallback(
    (agentId: string) => {
      onSelectAgent(agentId === selectedAgentId ? null : agentId);
    },
    [onSelectAgent, selectedAgentId]
  );

  const isHostTab = activeTab === "host";
  const panelKicker = isHostTab
    ? t("controlRoom.hostIntervention")
    : t("controlRoom.roleObservation");
  const panelTitle = isHostTab
    ? t("controlRoom.hostInterventionDesk")
    : t("controlRoom.focusedAgent");
  const panelCopy = isHostTab
    ? t("controlRoom.hostInterventionCopy")
    : isCompareMode
      ? t("controlRoom.compareHint")
      : t("components.sidebar.overviewHint");

  return (
    <aside className="ss-workspace__panel ss-workspace__panel--observation ss-observation">
      <div className="ss-workspace__panel-header">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="ss-kicker">{panelKicker}</div>
            <h2 className="ss-workspace__panel-title mt-2">{panelTitle}</h2>
            <p className="ss-workspace__panel-copy">{panelCopy}</p>
          </div>
          {isCompareMode ? (
            <span className="ss-observation__compare-chip">{t("controlRoom.compareActive")}</span>
          ) : null}
        </div>

        {showTabs ? (
          <div className="ss-observation__tabs">
            <button
              onClick={() => setActiveTab("observe")}
              className={`ss-observation__tab ${activeTab === "observe" ? "is-active" : ""}`}
            >
              <UserRound size={15} />
              {t("controlRoom.roleObservation")}
            </button>
            <button
              onClick={() => setActiveTab("host")}
              className={`ss-observation__tab ${activeTab === "host" ? "is-active" : ""}`}
            >
              <Zap size={15} />
              {t("controlRoom.hostIntervention")}
            </button>
          </div>
        ) : null}
      </div>

      {activeTab === "host" ? (
        <div className="ss-observation__host-wrap">
          <HostPanel />
        </div>
      ) : (
        <div className="ss-observation__body">
          <section className={`ss-observation__focus-card ${selectedAgent ? "is-selected" : ""}`}>
            <div className="ss-observation__section-label">{t("controlRoom.focusedAgent")}</div>

            {selectedAgent ? (
              <>
                <div className="ss-observation__focus-main">
                  <img
                    src={selectedAgent.avatarUrl}
                    alt={selectedAgent.name}
                    className="ss-observation__avatar"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="ss-observation__focus-name">{selectedAgent.name}</div>
                    <div className="ss-observation__focus-role">
                      {selectedAgent.role || t("common.none")}
                    </div>
                  </div>
                  <button onClick={() => onSelectAgent(null)} className="ss-button-secondary">
                    {t("controlRoom.clearFocus")}
                  </button>
                </div>

                <div className="ss-observation__metrics">
                  <FocusMetric label={t("controlRoom.memoryCount")} value={selectedAgent.memory.length} />
                  <FocusMetric
                    label={t("controlRoom.knowledgeCount")}
                    value={selectedAgent.knowledgeBase.length}
                  />
                  <FocusMetric
                    label={t("controlRoom.propertyCount")}
                    value={Object.keys(selectedAgent.properties || {}).length}
                  />
                </div>

                <div className="ss-observation__latest">
                  <div className="ss-observation__latest-label">{t("controlRoom.lastObserved")}</div>
                  <p className="ss-observation__latest-copy">
                    {latestByAgent.get(selectedAgent.id)?.content ||
                      latestMemory?.content ||
                      t("components.agentPanel.noRecentActivity")}
                  </p>
                </div>
              </>
            ) : (
              <div className="ss-observation__empty-focus">
                <div className="ss-observation__empty-title">{t("controlRoom.noFocusedAgent")}</div>
                <p className="ss-observation__empty-copy">{t("controlRoom.noFocusedAgentHint")}</p>
                {activeAgentId ? (
                  <button onClick={() => onSelectAgent(activeAgentId)} className="ss-button">
                    <Crosshair size={15} />
                    {t("controlRoom.observeRole")}
                  </button>
                ) : null}
              </div>
            )}
          </section>

          <section className="ss-observation__secondary ss-observation__secondary--directory">
            <div className="ss-observation__section-header">
              <div className="ss-observation__section-label">
                {t("controlRoom.roleCollections")}
              </div>
              <span className="ss-observation__count">
                {directoryCollections.length}/{agentCollections.length}
              </span>
            </div>

            <div className="ss-observation__directory-toolbar">
              <label className="ss-observation__directory-search">
                <Search size={14} />
                <input
                  value={directoryQuery}
                  onChange={(event) => setDirectoryQuery(event.target.value)}
                  placeholder={t("controlRoom.roleDirectorySearch")}
                />
              </label>
            </div>

            <div className="ss-observation__directory-list">
              {directoryCollections.length > 0 ? (
                directoryCollections.map((collection) => (
                  <CollectionRow
                    key={collection.key}
                    collection={collection}
                    latest={collection.latest}
                    isSelected={selectedCollection?.key === collection.key}
                    isActive={Boolean(collection.activeMemberId)}
                    onSelect={() => handleSelectCollection(collection)}
                  />
                ))
              ) : (
                <div className="ss-path__empty">
                  {t("controlRoom.noDirectoryResults")}
                </div>
              )}
            </div>
          </section>

          {selectedCollection && selectedCollection.members.length > 1 ? (
            <section className="ss-observation__secondary">
              <div className="ss-observation__section-header">
                <div className="ss-observation__section-label">
                  {t("controlRoom.memberRoster")}
                </div>
                <span className="ss-observation__count">
                  {selectedCollection.members.length}
                </span>
              </div>

              <div className="ss-observation__member-grid">
                {selectedCollection.members.map((member) => (
                  <button
                    key={member.id}
                    type="button"
                    onClick={() => handleSelectMember(member.id)}
                    className={`ss-observation__member-chip ${
                      member.id === selectedAgentId ? "is-selected" : ""
                    }`}
                  >
                    <img
                      src={member.avatarUrl}
                      alt={member.name}
                      className="ss-observation__member-avatar"
                    />
                    <div className="min-w-0 flex-1 text-left">
                      <div className="ss-observation__member-name">{member.name}</div>
                      <div className="ss-observation__member-copy">
                        {latestByAgent.get(member.id)?.content ||
                          t("components.agentPanel.noRecentActivity")}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          <section className="ss-observation__support">
            <div className="ss-observation__support-item">
              <Brain size={15} />
              <span>{t("controlRoom.memoryCount")}</span>
            </div>
            <div className="ss-observation__support-item">
              <BookOpen size={15} />
              <span>{t("controlRoom.knowledgeCount")}</span>
            </div>
          </section>
        </div>
      )}
    </aside>
  );
};

export default ObservationConsole;
