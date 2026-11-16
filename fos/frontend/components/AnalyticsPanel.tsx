
import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { useSimulationStore } from '../store';
import { useTranslation } from 'react-i18next';
import { X, TrendingUp, BarChart2 } from 'lucide-react';

export const AnalyticsPanel: React.FC = () => {
  const { t } = useTranslation();
  const isOpen = useSimulationStore(state => state.isAnalyticsOpen);
  const toggle = useSimulationStore(state => state.toggleAnalytics);
  const agents = useSimulationStore(state => state.agents);
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Extract available metrics from the first agent (assuming homogeneity for now)
  const availableMetrics = agents.length > 0 && agents[0].history 
    ? Object.keys(agents[0].history) 
    : [];
  
  const [selectedMetric, setSelectedMetric] = useState<string>(availableMetrics[0] || '');

  // Update selected metric if available metrics change
  useEffect(() => {
    if (!selectedMetric && availableMetrics.length > 0) {
      setSelectedMetric(availableMetrics[0]);
    }
  }, [availableMetrics, selectedMetric]);

  useEffect(() => {
    if (!isOpen || !svgRef.current || !containerRef.current || !selectedMetric || agents.length === 0) return;

    // Clear previous chart
    d3.select(svgRef.current).selectAll('*').remove();

    const margin = { top: 20, right: 30, bottom: 30, left: 40 };
    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight;
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const svg = d3.select(svgRef.current)
      .attr('width', width)
      .attr('height', height)
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // Prepare Data
    // We assume history is an array of numbers. Round is index + 1.
    const maxRounds = d3.max(agents, a => a.history?.[selectedMetric]?.length || 0) || 10;
    
    // Scales
    const xScale = d3.scaleLinear()
      .domain([1, maxRounds])
      .range([0, innerWidth]);

    const allValues = agents.flatMap(a => a.history?.[selectedMetric] || []);
    const yMax = d3.max(allValues) || 100;
    const yMin = d3.min(allValues) || 0;
    
    // Add some padding to Y domain
    const yScale = d3.scaleLinear()
      .domain([yMin * 0.9, yMax * 1.1])
      .range([innerHeight, 0]);

    // Color scale for agents
    const colorScale = d3.scaleOrdinal(d3.schemeCategory10)
      .domain(agents.map(a => a.id));

    // Axes
    svg.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(d3.axisBottom(xScale).ticks(maxRounds).tickFormat(d => `R${d}`))
      .attr('color', '#94a3b8');

    svg.append('g')
      .call(d3.axisLeft(yScale))
      .attr('color', '#94a3b8');

    // Grid lines
    svg.append('g')
      .attr('class', 'grid')
      .attr('opacity', 0.1)
      .call(d3.axisLeft(yScale).tickSize(-innerWidth).tickFormat(() => ''));

    // Line Generator
    const line = d3.line<{round: number, value: number}>()
      .x(d => xScale(d.round))
      .y(d => yScale(d.value))
      .curve(d3.curveMonotoneX);

    // Draw Lines
    agents.forEach(agent => {
      if (!agent.history?.[selectedMetric]) return;

      const dataPoints = agent.history[selectedMetric].map((val, i) => ({
        round: i + 1,
        value: val
      }));

      // Line path
      svg.append('path')
        .datum(dataPoints)
        .attr('fill', 'none')
        .attr('stroke', colorScale(agent.id) as string)
        .attr('stroke-width', 2.5)
        .attr('d', line)
        .attr('class', 'drop-shadow-sm');

      // Points
      svg.selectAll(`.point-${agent.id}`)
        .data(dataPoints)
        .enter()
        .append('circle')
        .attr('cx', d => xScale(d.round))
        .attr('cy', d => yScale(d.value))
        .attr('r', 4)
        .attr('fill', 'white')
        .attr('stroke', colorScale(agent.id) as string)
        .attr('stroke-width', 2);
    });

    // Tooltip Area (Interaction)
    const tooltip = d3.select(containerRef.current)
      .append('div')
      .attr('class', 'absolute bg-slate-800 text-white text-xs p-2 rounded pointer-events-none opacity-0 transition-opacity z-50')
      .style('top', 0)
      .style('left', 0);

    const mouseGroup = svg.append('g').style('opacity', 0);
    
    // Vertical line cursor
    const cursorLine = mouseGroup.append('line')
      .attr('y1', 0)
      .attr('y2', innerHeight)
      .attr('stroke', '#cbd5e1')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '4 2');

    svg.append('rect')
      .attr('width', innerWidth)
      .attr('height', innerHeight)
      .attr('fill', 'transparent')
      .on('mousemove', (event) => {
        const [mx] = d3.pointer(event);
        const round = Math.round(xScale.invert(mx));
        
        if (round >= 1 && round <= maxRounds) {
          mouseGroup.style('opacity', 1);
          cursorLine.attr('x1', xScale(round)).attr('x2', xScale(round));

          // Build tooltip content
          let html = `<div class="font-bold mb-1">Round ${round}</div>`;
          agents.forEach(agent => {
            const val = agent.history?.[selectedMetric]?.[round-1];
            if (val !== undefined) {
              const color = colorScale(agent.id);
              html += `<div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full" style="background:${color}"></span>
                <span>${agent.name}: ${val}</span>
              </div>`;
            }
          });

          tooltip
            .style('opacity', 1)
            .html(html)
            .style('left', `${event.pageX + 10}px`) // Basic positioning, ideally relative to container
            .style('top', `${event.pageY + 10}px`);
        }
      })
      .on('mouseleave', () => {
        mouseGroup.style('opacity', 0);
        tooltip.style('opacity', 0);
      });

  }, [isOpen, selectedMetric, agents]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/30 backdrop-blur-sm pointer-events-auto">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl h-[600px] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="px-6 py-4 border-b flex justify-between items-center bg-slate-50 shrink-0">
          <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
            <TrendingUp className="text-brand-600" size={20} />
            {t('components.analyticsPanel.title')}
          </h2>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-slate-500">{t('components.analyticsPanel.metricLabel')}</span>
              <select
                value={selectedMetric}
                onChange={(e) => setSelectedMetric(e.target.value)}
                className="text-xs border rounded px-2 py-1 outline-none focus:ring-1 focus:ring-brand-500 bg-white"
              >
                {availableMetrics.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <button onClick={() => toggle(false)} className="text-slate-400 hover:text-slate-600">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="flex-1 p-6 relative flex flex-col">
          {agents.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
              <BarChart2 size={48} className="mb-2 opacity-20" />
              <p>{t('components.analyticsPanel.noAgentData')}</p>
            </div>
          ) : (
             <>
               <div className="flex gap-4 mb-4 flex-wrap justify-center">
                 {agents.map((agent, i) => (
                   <div key={agent.id} className="flex items-center gap-1.5 text-xs bg-slate-50 px-2 py-1 rounded border">
                     <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d3.schemeCategory10[i % 10] }}></span>
                     <span className="font-medium text-slate-700">{agent.name}</span>
                   </div>
                 ))}
               </div>
               <div ref={containerRef} className="flex-1 w-full min-h-0 relative">
                 <svg ref={svgRef} className="w-full h-full overflow-visible"></svg>
               </div>
               <p className="text-center text-[10px] text-slate-400 mt-2">
                 {t('components.analyticsPanel.axisLabel', { metric: selectedMetric })}
               </p>
             </>
          )}
        </div>
      </div>
    </div>
  );
};
