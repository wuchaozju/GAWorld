/**
 * This file figures out simple step progress from logs people can already see.
 *
 * `isAgentOutputLog` checks whether one log line counts as visible output from an agent.
 * `countAgentsWithOutput` counts how many different agents produced visible output in one step.
 * `buildRoundProgressMap` prepares a quick lookup so the UI can show progress for each step.
 * `getLatestRoundProgress` returns progress for the newest visible step.
 */

import type { LogEntry } from "../types";

export interface LogGroupProgress {
  round: number;
  finishedAgents: number;
  totalAgents: number;
}

export interface LogGroupLike {
  round: number;
  entries: LogEntry[];
}

// This checks whether a log line is a visible agent output we can use as step progress.
export const isAgentOutputLog = (entry: LogEntry): boolean => {
  if (!entry.agentId) {
    return false;
  }

  return entry.type === "AGENT_ACTION" || entry.type === "AGENT_SAY";
};

// This counts how many different agents produced visible output in one step.
export const countAgentsWithOutput = (entries: LogEntry[]): number => {
  const agentIds = new Set<string>();

  entries.forEach((entry) => {
    if (!isAgentOutputLog(entry) || !entry.agentId) {
      return;
    }

    agentIds.add(entry.agentId);
  });

  return agentIds.size;
};

// This builds one progress summary per step so the UI can reuse it in multiple places.
export const buildRoundProgressMap = (
  groups: LogGroupLike[],
  totalAgents: number,
): Map<number, LogGroupProgress> => {
  return new Map(
    groups.map((group) => [
      group.round,
      {
        round: group.round,
        finishedAgents: countAgentsWithOutput(group.entries),
        totalAgents,
      },
    ]),
  );
};

// This returns progress for the newest visible step.
export const getLatestRoundProgress = (
  groups: LogGroupLike[],
  totalAgents: number,
): LogGroupProgress | null => {
  const latestGroup = groups.at(-1);

  if (!latestGroup) {
    return null;
  }

  return {
    round: latestGroup.round,
    finishedAgents: countAgentsWithOutput(latestGroup.entries),
    totalAgents,
  };
};
