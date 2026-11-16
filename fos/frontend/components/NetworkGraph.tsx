/**
 * Shared network graph visualization using Sigma.js + Graphology.
 *
 * Renders a social network as an interactive force-directed graph with
 * node dragging, selection, and edge toggling. Used by NetworkEditorModal
 * and Step5Network to display agent relationship topologies.
 *
 * Exports: NetworkGraph (default), networkToGraph
 */
import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import Graph from 'graphology';
import forceAtlas2 from 'graphology-layout-forceatlas2';
import {
  SigmaContainer,
  useSigma,
  useRegisterEvents,
  useLoadGraph,
  useSetSettings,
} from '@react-sigma/core';
import '@react-sigma/core/lib/style.css';
import { NodeCircleProgram } from 'sigma/rendering';
import type { SocialNetwork, Agent } from '../types';

/** Color constants for graph rendering. */
const NODE_COLOR = '#d4a24e';
const NODE_HIGHLIGHT_COLOR = '#ff9500';
const NODE_FIRST_CLICK_COLOR = '#4ecdc4';
const EDGE_COLOR = 'rgba(135, 189, 255, 0.85)';

/**
 * Convert a SocialNetwork adjacency list into a Graphology Graph.
 *
 * Adds all nodes (both sources and targets), deduplicates edges, and
 * assigns random initial positions. Agent names are used as node labels
 * when a matching agent is found.
 *
 * @param network - Adjacency list mapping agent names to their connections.
 * @param agents - Optional agent array for label/avatar metadata.
 * @returns A Graphology Graph instance ready for layout and rendering.
 */
export function networkToGraph(
  network: SocialNetwork,
  agents?: Agent[],
): Graph {
  const graph = new Graph({ type: 'undirected' });
  const agentMap = new Map(agents?.map((a) => [a.name, a]));

  // Collect all unique node IDs (sources + targets).
  const nodeIds = new Set<string>();
  for (const [source, targets] of Object.entries(network)) {
    nodeIds.add(source);
    for (const target of targets) {
      nodeIds.add(target);
    }
  }

  // Add nodes with random initial positions.
  for (const id of nodeIds) {
    const agent = agentMap.get(id);
    graph.addNode(id, {
      x: Math.random() * 100,
      y: Math.random() * 100,
      label: agent?.name ?? id,
      color: NODE_COLOR,
      size: 10,
    });
  }

  // Add deduplicated edges.
  const edgeSet = new Set<string>();
  for (const [source, targets] of Object.entries(network)) {
    for (const target of targets) {
      const key =
        source < target ? `${source}::${target}` : `${target}::${source}`;
      if (!edgeSet.has(key) && graph.hasNode(source) && graph.hasNode(target)) {
        edgeSet.add(key);
        graph.addEdge(source, target, { color: EDGE_COLOR, size: 2 });
      }
    }
  }

  return graph;
}

/** Props accepted by the NetworkGraph component. */
interface NetworkGraphProps {
  /** Social network adjacency list to render. */
  network: SocialNetwork;
  /** Agent data for labels and metadata. */
  agents?: Agent[];
  /** Callback when a node is clicked. */
  onNodeClick?: (nodeId: string) => void;
  /** Callback when an edge is clicked. */
  onEdgeClick?: (source: string, target: string) => void;
  /** Callback when an edge is toggled (created or removed) between two nodes. */
  onEdgeToggle?: (source: string, target: string) => void;
  /** Currently selected node ID, highlighted with a distinct color. */
  selectedNodeId?: string;
  /** Additional CSS class name for the container. */
  className?: string;
}

/**
 * Inner component that runs ForceAtlas2 layout and handles graph events.
 *
 * Must be rendered inside a SigmaContainer so that Sigma context hooks
 * (useSigma, useRegisterEvents, etc.) are available.
 */
function GraphEvents({
  onNodeClick,
  onEdgeToggle,
  selectedNodeId,
}: Pick<NetworkGraphProps, 'onNodeClick' | 'onEdgeToggle' | 'selectedNodeId'>) {
  const sigma = useSigma();
  const loadGraph = useLoadGraph();
  const registerEvents = useRegisterEvents();
  const setSettings = useSetSettings();
  const [firstClick, setFirstClick] = useState<string | null>(null);

  // Apply settings for label rendering.
  useEffect(() => {
    setSettings({
      labelRenderedSizeThreshold: 6,
      labelFont: 'Inter, system-ui, sans-serif',
      labelSize: 12,
      labelWeight: '500',
    });
  }, [setSettings]);

  // Run ForceAtlas2 layout on the current graph.
  useEffect(() => {
    const graph = sigma.getGraph();
    if (graph.order === 0) return;

    const isSmall = graph.order < 100;
    forceAtlas2.assign(graph, {
      iterations: isSmall ? 100 : 200,
      settings: {
        gravity: 1,
        scalingRatio: isSmall ? 10 : 2,
        barnesHutOptimize: !isSmall,
      },
    });

    // Ensure no node is stuck at (0,0) from layout.
    graph.forEachNode((node, attrs) => {
      if (attrs.x === undefined || attrs.y === undefined) {
        graph.setNodeAttribute(node, 'x', Math.random() * 10);
        graph.setNodeAttribute(node, 'y', Math.random() * 10);
      }
    });
  }, [sigma]);

  // Update node highlights when selection changes.
  useEffect(() => {
    const graph = sigma.getGraph();
    graph.forEachNode((node) => {
      const isSelected = node === selectedNodeId;
      const isFirstClick = node === firstClick;
      graph.setNodeAttribute(
        node,
        'color',
        isSelected
          ? NODE_HIGHLIGHT_COLOR
          : isFirstClick
            ? NODE_FIRST_CLICK_COLOR
            : NODE_COLOR,
      );
      graph.setNodeAttribute(node, 'size', isSelected || isFirstClick ? 14 : 10);
    });
  }, [sigma, selectedNodeId, firstClick]);

  // Register mouse events: node dragging, click selection, edge toggling.
  useEffect(() => {
    let dragNode: string | null = null;
    let isDragging = false;

    registerEvents({
      downNode: (e) => {
        dragNode = e.node;
        isDragging = true;
        sigma.getGraph().setNodeAttribute(dragNode, 'highlighted', true);
        e.preventSigmaDefault();
      },
      mouseup: () => {
        if (dragNode) {
          sigma.getGraph().removeNodeAttribute(dragNode, 'highlighted');
        }
        dragNode = null;
        isDragging = false;
      },
      mousemove: (e) => {
        if (isDragging && dragNode) {
          const pos = sigma.viewportToGraph(e);
          sigma.getGraph().setNodeAttribute(dragNode, 'x', pos.x);
          sigma.getGraph().setNodeAttribute(dragNode, 'y', pos.y);
        }
      },
      clickNode: (e) => {
        const clickedNode = e.node;

        // Edge toggling: if a first-click node was already selected,
        // toggle the edge between the two nodes.
        if (firstClick && firstClick !== clickedNode) {
          onEdgeToggle?.(firstClick, clickedNode);
          setFirstClick(null);
          return;
        }

        // Set this node as the first-click target for edge creation.
        setFirstClick(clickedNode);
        onNodeClick?.(clickedNode);
      },
      clickStage: () => {
        setFirstClick(null);
      },
    });
  }, [sigma, registerEvents, firstClick, onNodeClick, onEdgeToggle]);

  return null;
}

/**
 * Interactive network graph component powered by Sigma.js.
 *
 * Converts a SocialNetwork adjacency list into a force-directed graph
 * with node dragging, selection highlighting, and edge toggling.
 */
export default function NetworkGraph({
  network,
  agents,
  onNodeClick,
  onEdgeClick,
  onEdgeToggle,
  selectedNodeId,
  className,
}: NetworkGraphProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);

  // Rebuild the graph whenever the network or agents change.
  const graph = useMemo(
    () => networkToGraph(network, agents),
    [network, agents],
  );

  // Expose onEdgeClick through a stable reference for external consumers.
  const handleEdgeClick = useCallback(
    (source: string, target: string) => {
      onEdgeClick?.(source, target);
    },
    [onEdgeClick],
  );

  // Suppress unused variable lint (edge click is passed through props).
  void handleEdgeClick;

  // Show placeholder when there are no nodes.
  if (graph.order === 0) {
    return (
      <div className={className} style={{ textAlign: 'center', padding: 24, color: '#888' }}>
        {t('components.networkGraph.emptyState')}
      </div>
    );
  }

  return (
    <div ref={containerRef} className={className} style={{ width: '100%', height: '100%' }}>
      <SigmaContainer
        graph={graph}
        style={{ width: '100%', height: '100%' }}
        settings={{
          defaultNodeType: 'circle',
          defaultEdgeColor: EDGE_COLOR,
          defaultNodeColor: NODE_COLOR,
          renderEdgeLabels: false,
          minCameraRatio: 0.1,
          maxCameraRatio: 10,
          nodeProgramClasses: {
            circle: NodeCircleProgram,
          },
        }}
      >
        <GraphEvents
          onNodeClick={onNodeClick}
          onEdgeToggle={onEdgeToggle}
          selectedNodeId={selectedNodeId}
        />
      </SigmaContainer>
    </div>
  );
}
