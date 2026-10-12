/**
 * This file talks to the backend for saved external events.
 *
 * Each function here does one simple job:
 * - `listExternalEvents` loads saved rows.
 * - `createExternalEvent` saves one manual row.
 * - `applyExternalEventRecord` applies one saved row to a simulation node.
 */

import { apiClient } from "./client";

export interface ExternalEventRecord {
  id: string;
  event_type: "policy" | "market" | "news" | "custom" | "manual";
  source: string;
  source_name?: string | null;
  title: string;
  content: string;
  timestamp: string;
  severity: "low" | "medium" | "high" | "critical";
  metadata?: Record<string, unknown>;
  url?: string;
  status?: "pending" | "applied" | "dismissed";
}

export interface CreateExternalEventInput {
  event_type: ExternalEventRecord["event_type"];
  title: string;
  content: string;
  severity: ExternalEventRecord["severity"];
  url?: string;
}

export async function listExternalEvents(
  simulationId?: string,
): Promise<ExternalEventRecord[]> {
  const params = new URLSearchParams();
  if (simulationId) {
    params.set("simulation_id", simulationId);
  }
  const response = await apiClient.get(`/events/external?${params.toString()}`);
  return response.data?.events ?? [];
}

export async function createExternalEvent(
  simulationId: string,
  event: CreateExternalEventInput,
): Promise<{ success: boolean; event_id: string; message: string }> {
  const response = await apiClient.post(
    `/events/external?simulation_id=${encodeURIComponent(simulationId)}`,
    {
      event_type: event.event_type,
      title: event.title,
      content: event.content,
      severity: event.severity,
      url: event.url,
      metadata: {},
    },
  );
  return response.data;
}

export async function applyExternalEventRecord(
  simulationId: string,
  eventId: string,
  nodeId?: string | number | null,
): Promise<{ success: boolean; event_id: string; status: string; description: string }> {
  const suffix = nodeId != null ? `&node_id=${encodeURIComponent(String(nodeId))}` : "";
  const response = await apiClient.post(
    `/events/external/${encodeURIComponent(eventId)}/apply?simulation_id=${encodeURIComponent(simulationId)}${suffix}`,
  );
  return response.data;
}
