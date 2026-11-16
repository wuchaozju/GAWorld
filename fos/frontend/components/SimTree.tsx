// This file draws the simulation tree, lets people pick nodes, and provides zoom controls for exploring the tree.
import React, { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import { SimNode } from '../types';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { HelpCircle, Move, ZoomIn, ZoomOut, Maximize, MousePointer2, Trash2, GitFork } from 'lucide-react';
import { EnvironmentSuggestionDialogWrapper } from './EnvironmentSuggestion';
import { Button } from './ui/button';

interface SimTreeProps {
  nodesOverride?: SimNode[];
  alwaysSelectOnClick?: boolean;
  layoutDirection?: 'horizontal' | 'vertical';
}

export const SimTree: React.FC<SimTreeProps> = ({
  nodesOverride,
  alwaysSelectOnClick = false,
  layoutDirection = 'horizontal',
}) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const nodes = useSimulationStore(state => state.nodes);
  const selectedNodeId = useSimulationStore(state => state.selectedNodeId);
  const compareTargetNodeId = useSimulationStore(state => state.compareTargetNodeId);
  const selectNode = useSimulationStore(state => state.selectNode);
  const setCompareTarget = useSimulationStore(state => state.setCompareTarget);
  const toggleHelpModal = useSimulationStore(state => state.toggleHelpModal);
  const isCompareMode = useSimulationStore(state => state.isCompareMode);
  const deleteNode = useSimulationStore(state => state.deleteNode);
  const branchSimulation = useSimulationStore(state => state.branchSimulation);
  const isGenerating = useSimulationStore(state => state.isGenerating);

  // Keep track of zoom behavior to call it programmatically
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const svgRef = useRef<d3.Selection<SVGSVGElement, unknown, null, undefined> | null>(null);
  const selectedNodeIdRef = useRef(selectedNodeId);
  const isCompareModeRef = useRef(isCompareMode);

  const resolvedNodes = nodesOverride || nodes;

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
    isCompareModeRef.current = isCompareMode;
  }, [selectedNodeId, isCompareMode]);

  useEffect(() => {
    if (!containerRef.current || resolvedNodes.length === 0) return;

    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight;
    const safeWidth = width || 1;
    const safeHeight = height || 1;
    
    // Clear previous
    d3.select(containerRef.current).selectAll('*').remove();

    // Setup Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .extent([[0, 0], [safeWidth, safeHeight]])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });
    
    zoomRef.current = zoom;

    const svg = d3.select(containerRef.current)
      .append('svg')
      .attr('width', safeWidth)
      .attr('height', safeHeight)
      .attr('class', 'cursor-grab active:cursor-grabbing')
      .call(zoom)
      .on("dblclick.zoom", null);
    
    svgRef.current = svg;

    const g = svg.append('g');

// Hierarchy
// Filter out nodes with parentIds that don't exist (orphaned/pending experiment nodes)
const nodeIds = new Set(resolvedNodes.map(n => n.id));
const validNodes = resolvedNodes.filter(n => {
  // Root node (no parent) is always valid
  if (!n.parentId) return true;
  // Node with existing parent is valid
  if (nodeIds.has(n.parentId)) return true;
  // Skip orphaned nodes (likely pending experiment placeholders)
  console.warn(`Filtering orphaned node: ${n.id} (parent ${n.parentId} not found)`);
  return false;
});

// Handle edge case where no valid nodes exist
if (validNodes.length === 0) {
  return;
}

const root = d3.stratify<SimNode>()
  .id(d => d.id)
  .parentId(d => d.parentId)
  (validNodes);

    const isVertical = layoutDirection === 'vertical';

    // nodeSize: [x spacing, y spacing]
    const treeLayout = d3.tree<SimNode>()
      .nodeSize(isVertical ? [130, 92] : [60, 120]);

    treeLayout(root);

    // Links
    g.selectAll('.link')
      .data(root.links())
      .enter()
      .append('path')
      .attr('class', 'link')
      .attr('fill', 'none')
      .attr('stroke', 'var(--ss-workspace-topology-link)')
      .attr('stroke-width', 2)
      .attr('d', isVertical
        ? d3.linkVertical<any, any>()
            .x(d => d.x)
            .y(d => d.y)
        : d3.linkHorizontal<any, any>()
            .x(d => d.y)
            .y(d => d.x)
      );

    // Nodes
    const nodeGroup = g.selectAll('.node')
      .data(root.descendants())
      .enter()
      .append('g')
      .attr('class', 'node')
      .attr('data-node-id', d => d.data.id)
      .attr('transform', d => isVertical ? `translate(${d.x},${d.y})` : `translate(${d.y},${d.x})`)
      .on('click', (event, d) => {
        event.stopPropagation();
        const nodeId = d.data.id;

        if (isCompareModeRef.current || event.altKey || event.ctrlKey) {
          if (nodeId !== selectedNodeIdRef.current) {
            setCompareTarget(nodeId);
          }
          return;
        }

        selectNode(nodeId);
      });

    // Node Circle
    nodeGroup.append('circle')
      .attr('class', 'node-circle')
      .attr('r', 16)
      .attr('fill', d => {
        if (d.data.status === 'failed') return 'var(--ss-workspace-node-failed)';
        if (d.data.id === selectedNodeId) return 'var(--ss-workspace-node-selected)';
        if (d.data.id === compareTargetNodeId && isCompareMode) return 'var(--ss-workspace-node-compare)';
        if (d.data.isLeaf) return 'var(--ss-workspace-node-leaf)';
        return 'var(--ss-workspace-surface-strong)';
      })
      .attr('stroke', d => {
        if (d.data.status === 'failed') return 'var(--ss-workspace-node-failed-stroke)';
        if (d.data.id === selectedNodeId) return 'var(--ss-workspace-node-selected-stroke)';
        if (d.data.id === compareTargetNodeId && isCompareMode) return 'var(--ss-workspace-node-compare-stroke)';
        if (d.data.isLeaf) return 'var(--ss-workspace-node-leaf-stroke)';
        return 'var(--ss-workspace-border-strong)';
      })
      .attr('stroke-width', d => {
         if (d.data.id === selectedNodeId) return 3;
         if (d.data.id === compareTargetNodeId && isCompareMode) return 3;
         return d.data.isLeaf ? 2 : 2;
      })
      .attr('stroke-dasharray', d => {
         // Dashed line for comparison target if comparison mode is active
         if (d.data.id === compareTargetNodeId && isCompareMode) return '3 2'; 
         return 'none';
      })
      .style('cursor', isCompareMode ? 'crosshair' : 'pointer');

    // Labels
    nodeGroup.append('text')
      .attr('dy', isVertical ? 34 : 4)
      .attr('x', d => isVertical ? 0 : (d.children ? -24 : 24))
      .style('text-anchor', d => isVertical ? 'middle' : (d.children ? 'end' : 'start'))
      .text(d => d.data.display_id || d.data.id)
      .attr('class', d => `text-xs font-medium pointer-events-none select-none ${d.data.status === 'failed' ? 'fill-red-300' : 'fill-current'}`);

    // Initial positioning
    const initialTransform = isVertical
      ? d3.zoomIdentity.translate(safeWidth / 2, 80).scale(1)
      : d3.zoomIdentity.translate(80, safeHeight / 2).scale(1);
    svg.call(zoom.transform, initialTransform);

  }, [resolvedNodes, selectNode, setCompareTarget, alwaysSelectOnClick, layoutDirection]);

  useEffect(() => {
    if (!svgRef.current) return;

    svgRef.current
      .selectAll<SVGGElement, d3.HierarchyPointNode<SimNode>>('.node')
      .each(function updateNodeVisuals(d) {
        const circle = d3.select(this).select<SVGCircleElement>('circle');

        circle
          .attr('fill', () => {
            if (d.data.status === 'failed') return 'var(--ss-workspace-node-failed)';
            if (d.data.id === selectedNodeId) return 'var(--ss-workspace-node-selected)';
            if (d.data.id === compareTargetNodeId && isCompareMode) return 'var(--ss-workspace-node-compare)';
            if (d.data.isLeaf) return 'var(--ss-workspace-node-leaf)';
            return 'var(--ss-workspace-surface-strong)';
          })
          .attr('stroke', () => {
            if (d.data.status === 'failed') return 'var(--ss-workspace-node-failed-stroke)';
            if (d.data.id === selectedNodeId) return 'var(--ss-workspace-node-selected-stroke)';
            if (d.data.id === compareTargetNodeId && isCompareMode) return 'var(--ss-workspace-node-compare-stroke)';
            if (d.data.isLeaf) return 'var(--ss-workspace-node-leaf-stroke)';
            return 'var(--ss-workspace-border-strong)';
          })
          .attr('stroke-width', () => {
            if (d.data.id === selectedNodeId) return 3;
            if (d.data.id === compareTargetNodeId && isCompareMode) return 3;
            return 2;
          })
          .attr('stroke-dasharray', () => {
            if (d.data.id === compareTargetNodeId && isCompareMode) return '3 2';
            return 'none';
          })
          .style('cursor', isCompareMode ? 'crosshair' : 'pointer');
      });
  }, [selectedNodeId, compareTargetNodeId, isCompareMode]);

  const selectedNodeIsReady = Number.isFinite(Number(selectedNodeId));

  const handleZoomIn = () => {
    if (svgRef.current && zoomRef.current) {
      svgRef.current.transition().duration(300).call(zoomRef.current.scaleBy, 1.2);
    }
  };

  const handleZoomOut = () => {
    if (svgRef.current && zoomRef.current) {
      svgRef.current.transition().duration(300).call(zoomRef.current.scaleBy, 0.8);
    }
  };

  const handleReset = () => {
    if (svgRef.current && zoomRef.current && containerRef.current) {
      const width = containerRef.current.clientWidth;
      const height = containerRef.current.clientHeight;
      const initialTransform = layoutDirection === 'vertical'
        ? d3.zoomIdentity.translate(width / 2, 80).scale(1)
        : d3.zoomIdentity.translate(80, height / 2).scale(1);
      svgRef.current.transition().duration(500).call(zoomRef.current.transform, initialTransform);
    }
  };

  return (
    <>
      <EnvironmentSuggestionDialogWrapper />
      <div className={`ss-workspace__panel ss-workspace__panel--topology h-full relative transition-colors ${isCompareMode ? 'ring-2 ring-[rgba(124,111,168,0.45)]' : ''}`}>
        <div className="ss-workspace__panel-header z-10 relative">
          <div className="flex items-center justify-between gap-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-[var(--ss-workspace-heading)]">
              {isCompareMode ? <MousePointer2 size={16} className="text-[#B7AED9]" /> : <Move size={16} className="text-[var(--ss-workspace-muted)]" />}
              {isCompareMode ? t('components.simTree.selectCompareNode') : t('components.simTree.title')}
            </h3>
            <div className="flex items-center gap-2">
              {!isCompareMode ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void branchSimulation()}
                  disabled={isGenerating || !selectedNodeIsReady}
                >
                  <GitFork size={14} />
                  {t('simPage.branch')}
                </Button>
              ) : null}
              <button
                onClick={() => toggleHelpModal(true)}
                className="inline-flex items-center gap-1 text-xs text-[var(--ss-workspace-link)] transition-colors hover:opacity-80"
              >
                <HelpCircle size={14} />
                <span>{t('components.simTree.legendHelp')}</span>
              </button>
            </div>
          </div>
          <p className="ss-workspace__panel-copy mt-3">
            {isCompareMode
              ? t('components.simTree.clickToCompare')
              : t('components.sidebar.overviewHint')}
          </p>
        </div>
      
      {/* Zoom Controls */}
      <div className="absolute top-20 right-4 z-10 flex flex-col gap-1 rounded-2xl border border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-strong)] p-1 shadow-lg">
        <button onClick={handleZoomIn} className="ss-icon-button square" title={t('components.simTree.zoomIn')}>
          <ZoomIn size={16} />
        </button>
        <button onClick={handleZoomOut} className="ss-icon-button square" title={t('components.simTree.zoomOut')}>
          <ZoomOut size={16} />
        </button>
        <div className="my-0.5 h-px bg-[var(--ss-workspace-border)]"></div>
        <button onClick={handleReset} className="ss-icon-button square" title={t('components.simTree.resetView')}>
          <Maximize size={16} />
        </button>
        <div className="my-0.5 h-px bg-[var(--ss-workspace-border)]"></div>
        <button
          onClick={() => {
            if (selectedNodeId && window.confirm(t('components.simTree.confirmDelete'))) {
              deleteNode();
            }
          }}
          disabled={!selectedNodeId}
          className="ss-icon-button square disabled:cursor-not-allowed disabled:opacity-30"
          title={t('components.simTree.deleteNode')}
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div ref={containerRef} className="flex-1 overflow-hidden relative bg-transparent text-[var(--ss-workspace-muted)]" />
      
      {/* Legend */}
      <div className="z-10 relative flex gap-4 border-t border-[var(--ss-workspace-border)] bg-[var(--ss-workspace-surface-alt)] px-4 py-3 text-xs text-[var(--ss-workspace-muted)]">
        {isCompareMode ? (
          <>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-[var(--ss-workspace-node-selected)]"></div>
              <span>{t('components.simTree.baseline')}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-[var(--ss-workspace-node-compare)] border border-dashed border-[var(--ss-workspace-node-compare-stroke)]"></div>
              <span>{t('components.simTree.compare')}</span>
            </div>
            <div className="ml-auto font-medium text-[#B7AED9]">
               {t('components.simTree.clickToCompare')}
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full border border-[var(--ss-workspace-node-leaf-stroke)] bg-[var(--ss-workspace-node-leaf)]"></div>
              <span>{t('components.simTree.frontier')}</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-[var(--ss-workspace-node-selected)]"></div>
              <span>{t('components.simTree.selected')}</span>
            </div>
             <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full border border-[var(--ss-workspace-node-failed-stroke)] bg-[var(--ss-workspace-node-failed)]"></div>
              <span>{t('components.simTree.failed')}</span>
            </div>
          </>
        )}
        </div>
      </div>
    </>
  );
};
