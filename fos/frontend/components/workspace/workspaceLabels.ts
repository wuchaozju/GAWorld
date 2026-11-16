import type { SimNode } from "../../types";

const GENERIC_NODE_PATTERN = /^(Node \d+|节点 \d+)$/;

export const getWorkspaceNodeLabel = (
  node: SimNode | null,
  t: (key: string, options?: Record<string, unknown>) => string,
) => {
  if (!node) return "—";
  if (node.depth === 0) return "起始";
  if (node.name && !GENERIC_NODE_PATTERN.test(node.name)) return node.name;
  return t("controlRoom.roundNodeLabel", { round: node.depth });
};

export const buildWorkspacePath = (
  selectedNode: SimNode | null,
  nodeLookup: Map<string, SimNode>,
) => {
  const ordered: SimNode[] = [];
  let current = selectedNode;

  while (current) {
    ordered.unshift(current);
    current = current.parentId ? nodeLookup.get(current.parentId) || null : null;
  }

  return ordered;
};
