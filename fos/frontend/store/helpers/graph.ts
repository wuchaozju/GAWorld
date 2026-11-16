import type { Graph } from '../../services/simulationTree';
import type { SimNode } from '../../types';
import { getLocale, isZh } from './time';

export const generateNodes = (): SimNode[] => {
  return [
    {
      id: 'root',
      display_id: '0',
      parentId: null,
      name: 'Start',
      depth: 0,
      isLeaf: true,
      status: 'pending',
      timestamp: new Date().toISOString(),
      worldTime: new Date().toISOString(),
    },
  ];
};

export const mapGraphToNodes = (graph: Graph): SimNode[] => {
  const parentMap = new Map<number, number | null>();
  const childrenSet = new Set<number>();
  for (const edge of graph.edges) {
    parentMap.set(edge.to, edge.from);
    childrenSet.add(edge.from);
  }
  const root = graph.root;
  if (root != null && !parentMap.has(root)) {
    parentMap.set(root, null);
  }
  const running = new Set(graph.running || []);
  const nowIso = new Date().toISOString();
  const locale = getLocale();

  return graph.nodes.map((node) => {
    const parentId = parentMap.has(node.id) ? parentMap.get(node.id)! : null;
    const isLeaf = !childrenSet.has(node.id);
    const displayName = isZh() ? `节点 ${node.id}` : `Node ${node.id}`;
    return {
      id: String(node.id),
      display_id: String(node.id),
      parentId: parentId == null ? null : String(parentId),
      name: displayName,
      depth: node.depth,
      isLeaf,
      status: running.has(node.id) ? 'running' : 'completed',
      timestamp: new Date().toLocaleTimeString(locale),
      worldTime: nowIso,
      meta: (node as any).meta || null,
    };
  });
};
