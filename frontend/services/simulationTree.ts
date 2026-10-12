/**
 * Simulation tree WebSocket and API services.
 *
 * Provides functions for connecting to simulation event streams via WebSocket,
 * and API calls for tree manipulation (advance, branch, delete).
 *
 * WebSocket connections are tracked in auth store for proactive token refresh.
 *
 * Exports: connectTreeEvents, connectNodeEvents, getTreeGraph, treeAdvanceChain, etc.
 */

import { httpGet, httpPost, httpDelete } from "./client";
import { useAuthStore } from "../store/auth";

export type GraphNode = { id: number; depth: number; meta?: Record<string, unknown> | null };
export type GraphEdge = { from: number; to: number; type: string; ops?: unknown[] };

export type Graph = {
  root: number | null;
  frontier: number[];
  running?: number[];
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type SimEvent = { type: string; data?: Record<string, unknown> | null; node?: number };

// Track active WebSocket connections count
let activeWsConnections = 0;

function toWsUrl(base: string, path: string, token?: string): string {
  const b = base.replace(/\/$/, "");
  const url = new URL(b, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const full = new URL(path.replace(/^\//, "/"), url);
  if (token) full.searchParams.set("token", token);
  return full.toString();
}

/**
 * Notify auth store of WebSocket connection state change.
 * Called when any WebSocket connects or disconnects.
 */
function notifyWsStateChange(connected: boolean): void {
  if (connected) {
    activeWsConnections++;
    if (activeWsConnections === 1) {
      // First connection - notify auth store
      useAuthStore.getState().setWebSocketConnected(true);
    }
  } else {
    activeWsConnections = Math.max(0, activeWsConnections - 1);
    if (activeWsConnections === 0) {
      // Last connection closed - notify auth store
      useAuthStore.getState().setWebSocketConnected(false);
    }
  }
}

export async function getTreeGraph(base: string, id: string, token?: string): Promise<Graph | null> {
  try {
    return await httpGet<Graph>(base, `/simulations/${id}/tree/graph`, token);
  } catch (e) {
    console.error('[getTreeGraph] Failed to fetch tree graph:', e);
    return null;
  }
}

export function connectTreeEvents(base: string, id: string, token: string | undefined, onMessage: (event: SimEvent) => void): WebSocket {
  const ws = new WebSocket(toWsUrl(base, `/simulations/${id}/tree/events`, token));

  ws.onopen = () => {
    notifyWsStateChange(true);
    ws.send("ready");
  };

  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));

  ws.onclose = () => {
    notifyWsStateChange(false);
  };

  return ws;
}

export function connectNodeEvents(base: string, id: string, node: number, token: string | undefined, onMessage: (event: SimEvent) => void): WebSocket {
  const ws = new WebSocket(toWsUrl(base, `/simulations/${id}/tree/${node}/events`, token));

  ws.onopen = () => {
    notifyWsStateChange(true);
    ws.send("ready");
  };

  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));

  ws.onclose = () => {
    notifyWsStateChange(false);
  };

  return ws;
}

export async function treeAdvanceFrontier(base: string, id: string, turns: number, onlyMaxDepth = false, token?: string): Promise<{ children: number[] }> {
  return await httpPost<{ children: number[] }>(base, `/simulations/${id}/tree/advance_frontier`, { turns, only_max_depth: onlyMaxDepth }, token);
}

export async function treeAdvanceMulti(base: string, id: string, parent: number, turns: number, count: number, token?: string): Promise<{ children: number[] }> {
  return await httpPost<{ children: number[] }>(base, `/simulations/${id}/tree/advance_multi`, { parent, turns, count }, token);
}

export async function treeAdvanceChain(base: string, id: string, parent: number, turns: number, token?: string): Promise<{ child: number }> {
  return await httpPost<{ child: number }>(base, `/simulations/${id}/tree/advance_chain`, { parent, turns }, token);
}

export async function treeBranch(base: string, id: string, parent: number, ops: Array<Record<string, unknown>>, token?: string): Promise<{ child: number }> {
  return await httpPost<{ child: number }>(base, `/simulations/${id}/tree/branch`, { parent, ops }, token);
}

export async function treeBranchPublic(base: string, id: string, parent: number, text: string, token?: string): Promise<{ child: number }> {
  return await httpPost<{ child: number }>(base, `/simulations/${id}/tree/branch`, { parent, ops: [{ op: "public_broadcast", text }] }, token);
}

export async function treeDeleteSubtree(base: string, id: string, node: number, token?: string): Promise<{ ok: boolean }> {
  return await httpDelete<{ ok: boolean }>(base, `/simulations/${id}/tree/node/${node}`, token);
}

export async function getSimEvents(base: string, id: string, node: number, token?: string): Promise<any[]> {
  return await httpGet<any[]>(base, `/simulations/${id}/tree/sim/${node}/events`, token);
}

export async function getSimState(base: string, id: string, node: number, token?: string): Promise<any> {
  return await httpGet<any>(base, `/simulations/${id}/tree/sim/${node}/state`, token);
}

export async function getRehydrate(base: string, id: string, token?: string): Promise<any> {
  return await httpGet<any>(base, `/simulations/${id}/rehydrate`, token);
}

export async function applyNodeOverrides(
  base: string,
  id: string,
  node: number,
  overrides: Array<{
    name: string;
    language?: string;
    llm_config?: Record<string, unknown>;
    knowledge_base?: any[];
    documents?: Record<string, unknown>;
    properties?: Record<string, unknown>;
  }>,
  token?: string,
): Promise<{ ok: boolean }> {
  return await httpPost<{ ok: boolean }>(base, `/simulations/${id}/tree/sim/${node}/overrides`, { overrides }, token);
}

export async function injectHostMessage(
  base: string,
  id: string,
  node: number,
  message: string,
  token?: string,
): Promise<{ status: string; message: string }> {
  return await httpPost<{ status: string; message: string }>(base, `/simulations/${id}/tree/sim/${node}/inject-message`, { message }, token);
}
