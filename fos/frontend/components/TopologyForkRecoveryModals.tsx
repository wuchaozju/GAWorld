/**
 * Fork-from-checkpoint and failure-recovery dialogs for the topology explorer.
 *
 * - ForkFromCheckpointModal: pick a fork-capable checkpoint day (from node
 *   meta.checkpoint), optionally add an intervention text and per-agent LLM
 *   reassignment rows, then fork sibling branches sharing that checkpoint.
 * - RecoveryModal: offered when a node's runtime_status is "failed" —
 *   Retry, Fix and retry (repaired runtime config JSON), or Substitute an
 *   explicit provider/model for one affected agent. Wording makes clear the
 *   failed day reruns from the last completed checkpoint into a fresh
 *   attempt directory.
 */

import React from "react";
import { useTranslation } from "react-i18next";
import {
  forkFromCheckpoint,
  retryNode,
  fixAndRetryNode,
  substituteProvider,
  type CheckpointRef,
} from "../services/simulationTree";
import type { SimNode } from "../types";

type Base = { endpoint: string; token?: string };

const readCheckpoint = (node: SimNode | null): CheckpointRef | null => {
  const meta = (node?.meta || {}) as Record<string, unknown>;
  const ref = meta.checkpoint as CheckpointRef | undefined;
  if (!ref || typeof ref.checkpoint_path !== "string") return null;
  return ref;
};

const cardStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.45)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
};

const panelStyle: React.CSSProperties = {
  background: "var(--surface, #fff)",
  color: "inherit",
  borderRadius: 12,
  padding: 20,
  width: 460,
  maxWidth: "92vw",
  maxHeight: "86vh",
  overflowY: "auto",
};

const rowStyle: React.CSSProperties = { display: "flex", gap: 8, marginBottom: 10 };

const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: "6px 8px",
  border: "1px solid var(--border, #ccc)",
  borderRadius: 6,
  background: "transparent",
  color: "inherit",
};

export const ForkFromCheckpointModal: React.FC<{
  node: SimNode | null;
  base: Base;
  simulationId: string;
  onClose: () => void;
  onForked: (children: number[]) => void;
  onError: (message: string) => void;
}> = ({ node, base, simulationId, onClose, onForked, onError }) => {
  const { t } = useTranslation();
  const checkpoint = readCheckpoint(node);
  const [day, setDay] = React.useState<string>(checkpoint ? String(checkpoint.day) : "");
  const [interventions, setInterventions] = React.useState("");
  const [agentId, setAgentId] = React.useState("");
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  if (!checkpoint) return null;

  const submit = async () => {
    setBusy(true);
    try {
      const ref: Record<string, unknown> = { ...checkpoint, day: Number(day || checkpoint.day) };
      const agentLlmMap: Record<string, { provider: string; model?: string }> = {};
      if (agentId.trim() && provider.trim()) {
        agentLlmMap[agentId.trim()] = { provider: provider.trim(), model: model.trim() || undefined };
      }
      // Fork via the dedicated endpoint: children share the source checkpoint.
      const result = await forkFromCheckpoint(
        base.endpoint,
        simulationId,
        Number(node!.id),
        ref,
        base.token,
        interventions.trim() || undefined,
        Object.keys(agentLlmMap).length ? agentLlmMap : undefined,
      );
      onForked(result?.children || []);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={cardStyle} role="dialog" aria-modal="true" onClick={onClose}>
      <div style={panelStyle} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{t("topologyExplorer.forkDialog.title", { day: checkpoint.day })}</h3>
        <p>{t("topologyExplorer.forkDialog.hint")}</p>
        <div style={rowStyle}>
          <label style={{ flex: 1 }}>
            {t("topologyExplorer.forkDialog.day")}
            <input style={inputStyle} value={day} onChange={(e) => setDay(e.target.value)} inputMode="numeric" />
          </label>
        </div>
        <div style={rowStyle}>
          <label style={{ flex: 1 }}>
            {t("topologyExplorer.forkDialog.interventions")}
            <textarea
              style={{ ...inputStyle, minHeight: 60 }}
              value={interventions}
              onChange={(e) => setInterventions(e.target.value)}
              placeholder={t("topologyExplorer.forkDialog.interventionsPlaceholder")}
            />
          </label>
        </div>
        <div style={rowStyle}>
          <label>
            {t("topologyExplorer.forkDialog.agentId")}
            <input style={inputStyle} value={agentId} onChange={(e) => setAgentId(e.target.value)} inputMode="numeric" />
          </label>
          <label>
            {t("topologyExplorer.forkDialog.provider")}
            <input style={inputStyle} value={provider} onChange={(e) => setProvider(e.target.value)} />
          </label>
          <label>
            {t("topologyExplorer.forkDialog.model")}
            <input style={inputStyle} value={model} onChange={(e) => setModel(e.target.value)} />
          </label>
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="ss-button-secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
          <button className="ss-button-secondary" onClick={() => void submit()} disabled={busy}>
            {t("topologyExplorer.forkDialog.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
};

export const RecoveryModal: React.FC<{
  node: SimNode | null;
  base: Base;
  simulationId: string;
  onClose: () => void;
  onRecovered: (child: number) => void;
  onError: (message: string) => void;
}> = ({ node, base, simulationId, onClose, onRecovered, onError }) => {
  const { t } = useTranslation();
  const [action, setAction] = React.useState<"retry" | "fix_and_retry" | "substitute">("retry");
  const [runtimeConfig, setRuntimeConfig] = React.useState("");
  const [agentId, setAgentId] = React.useState("");
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  if (!node) return null;
  const numericNode = Number(node.id);

  const submit = async () => {
    setBusy(true);
    try {
      let result: { child: number };
      if (action === "retry") {
        result = await retryNode(base.endpoint, simulationId, numericNode, base.token);
      } else if (action === "fix_and_retry") {
        let parsed: Record<string, unknown> = {};
        try {
          parsed = runtimeConfig.trim() ? JSON.parse(runtimeConfig) : {};
        } catch {
          onError(t("topologyExplorer.recoveryDialog.badJson"));
          setBusy(false);
          return;
        }
        result = await fixAndRetryNode(base.endpoint, simulationId, numericNode, parsed, base.token);
      } else {
        result = await substituteProvider(
          base.endpoint,
          simulationId,
          numericNode,
          Number(agentId),
          provider.trim(),
          model.trim(),
          base.token,
        );
      }
      onRecovered(result?.child);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const actions: Array<{ id: typeof action; label: string; hint: string }> = [
    { id: "retry", label: t("topologyExplorer.recoveryDialog.retry"), hint: t("topologyExplorer.recoveryDialog.retryHint") },
    { id: "fix_and_retry", label: t("topologyExplorer.recoveryDialog.fixAndRetry"), hint: t("topologyExplorer.recoveryDialog.fixAndRetryHint") },
    { id: "substitute", label: t("topologyExplorer.recoveryDialog.substitute"), hint: t("topologyExplorer.recoveryDialog.substituteHint") },
  ];

  return (
    <div style={cardStyle} role="dialog" aria-modal="true" onClick={onClose}>
      <div style={panelStyle} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>{t("topologyExplorer.recoveryDialog.title")}</h3>
        <p>{t("topologyExplorer.recoveryDialog.checkpointHint")}</p>
        {actions.map((entry) => (
          <label key={entry.id} style={{ display: "block", marginBottom: 8 }}>
            <input
              type="radio"
              name="recovery-action"
              checked={action === entry.id}
              onChange={() => setAction(entry.id)}
            />{" "}
            <strong>{entry.label}</strong>
            <div style={{ opacity: 0.75, fontSize: 12 }}>{entry.hint}</div>
          </label>
        ))}
        {action === "fix_and_retry" && (
          <div style={rowStyle}>
            <label style={{ flex: 1 }}>
              {t("topologyExplorer.recoveryDialog.runtimeConfig")}
              <textarea
                style={{ ...inputStyle, minHeight: 60, fontFamily: "monospace" }}
                value={runtimeConfig}
                onChange={(e) => setRuntimeConfig(e.target.value)}
                placeholder='{"sim_days": 6}'
              />
            </label>
          </div>
        )}
        {action === "substitute" && (
          <>
            <div style={rowStyle}>
              <label>
                {t("topologyExplorer.forkDialog.agentId")}
                <input style={inputStyle} value={agentId} onChange={(e) => setAgentId(e.target.value)} inputMode="numeric" />
              </label>
            </div>
            <div style={rowStyle}>
              <label>
                {t("topologyExplorer.forkDialog.provider")}
                <input style={inputStyle} value={provider} onChange={(e) => setProvider(e.target.value)} />
              </label>
              <label>
                {t("topologyExplorer.forkDialog.model")}
                <input style={inputStyle} value={model} onChange={(e) => setModel(e.target.value)} />
              </label>
            </div>
          </>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="ss-button-secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
          <button className="ss-button-secondary" onClick={() => void submit()} disabled={busy}>
            {t("topologyExplorer.recoveryDialog.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
};
