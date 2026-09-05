/**
 * Force-directed device graph (design sample 3).
 *
 * d3-force runs the simulation; rendering is plain SVG so nodes can carry the
 * design's rounded-square + icon treatment and highlight states, which a
 * general-purpose graph library would fight.
 *
 * The simulation runs once per data change and is then stopped — a permanently
 * ticking layout burns CPU and makes nodes impossible to click.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import clsx from "clsx";

import { formatBytes, formatNumber } from "@/lib/format";
import type { EdgeSummary, NeighborhoodNode } from "@/types";

interface GraphNode extends SimulationNodeDatum {
  id: string;
  depth: number;
  bytesOut: number;
  bytesIn: number;
  eventsOut: number;
  eventsIn: number;
  isSink: boolean;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  eventCount: number;
  totalBytes: number;
}

const WIDTH = 1000;
const HEIGHT = 700;

/** Node colour by role, matching the mockup's entity-type legend. */
function nodeColor(node: GraphNode, focus: string): string {
  if (node.id === focus) return "#d0bcff";
  if (node.isSink) return "#059669"; // server / destination-only host
  if (node.depth === 1) return "#3b82f6";
  return "#8b5cf6";
}

export function NetworkGraph({
  nodes,
  edges,
  focusDevice,
  selected,
  onSelect,
  highlightPath = [],
}: {
  nodes: NeighborhoodNode[];
  edges: EdgeSummary[];
  focusDevice: string;
  selected: string | null;
  onSelect: (device: string) => void;
  /** Ordered device list from a path query; drawn as a highlighted route. */
  highlightPath?: string[];
}) {
  const [, forceRerender] = useState(0);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [dragging, setDragging] = useState(false);
  const simulationRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const linksRef = useRef<GraphLink[]>([]);
  const panOrigin = useRef<{ x: number; y: number } | null>(null);

  // Rebuild the simulation only when the underlying data actually changes.
  const dataKey = useMemo(
    () =>
      `${focusDevice}|${nodes.map((n) => n.device).join(",")}|${edges.length}`,
    [focusDevice, nodes, edges.length]
  );

  useEffect(() => {
    const present = new Set(nodes.map((n) => n.device));
    const simNodes: GraphNode[] = nodes.map((n) => ({
      id: n.device,
      depth: n.depth,
      bytesOut: n.bytes_out,
      bytesIn: n.bytes_in,
      eventsOut: n.events_out,
      eventsIn: n.events_in,
      isSink: n.events_out === 0,
    }));
    const simLinks: GraphLink[] = edges
      .filter((e) => present.has(e.source) && present.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        eventCount: e.event_count,
        totalBytes: e.total_bytes,
      }));

    const simulation = forceSimulation<GraphNode, GraphLink>(simNodes)
      .force(
        "link",
        forceLink<GraphNode, GraphLink>(simLinks)
          .id((d) => d.id)
          .distance(110)
          .strength(0.4)
      )
      .force("charge", forceManyBody().strength(-420))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("collide", forceCollide(38))
      .stop();

    // Run the layout synchronously, then render once. Cheaper and steadier than
    // animating every tick, and it keeps nodes still enough to click.
    const ticks = Math.min(300, Math.max(80, simNodes.length * 4));
    for (let i = 0; i < ticks; i += 1) simulation.tick();

    simulationRef.current = simulation;
    nodesRef.current = simNodes;
    linksRef.current = simLinks;
    setTransform({ x: 0, y: 0, k: 1 });
    forceRerender((n) => n + 1);

    return () => {
      simulation.stop();
    };
  }, [dataKey, nodes, edges]);

  const simNodes = nodesRef.current;
  const simLinks = linksRef.current;

  const pathEdges = useMemo(() => {
    const set = new Set<string>();
    for (let i = 0; i < highlightPath.length - 1; i += 1) {
      set.add(`${highlightPath[i]}->${highlightPath[i + 1]}`);
    }
    return set;
  }, [highlightPath]);
  const pathNodes = useMemo(() => new Set(highlightPath), [highlightPath]);

  const zoomBy = (factor: number) =>
    setTransform((t) => ({ ...t, k: Math.min(3, Math.max(0.3, t.k * factor)) }));

  const reset = () => setTransform({ x: 0, y: 0, k: 1 });

  if (!simNodes.length) {
    return (
      <div className="h-full flex items-center justify-center text-body-sm font-body-sm text-on-surface-variant">
        No devices to display.
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-surface-container-lowest">
      {/* Zoom / pan controls, as in the mockup's left toolbar. */}
      <div className="absolute left-4 top-4 z-10 flex flex-col bg-surface-container border border-outline-variant rounded-xl overflow-hidden">
        {[
          { icon: "zoom_in", label: "Zoom in", onClick: () => zoomBy(1.25) },
          { icon: "zoom_out", label: "Zoom out", onClick: () => zoomBy(0.8) },
          { icon: "fit_screen", label: "Reset view", onClick: reset },
        ].map((btn) => (
          <button
            key={btn.icon}
            type="button"
            onClick={btn.onClick}
            title={btn.label}
            aria-label={btn.label}
            className="w-9 h-9 flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
          >
            <span className="material-symbols-outlined text-[18px]">{btn.icon}</span>
          </button>
        ))}
      </div>

      {/* Entity legend — identity is never colour-alone. */}
      <div className="absolute left-4 bottom-4 z-10 bg-surface-container/90 border border-outline-variant rounded-xl px-3 py-2.5 backdrop-blur">
        <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0 mb-2">
          Device Types
        </p>
        <ul className="space-y-1 m-0 p-0 list-none">
          {[
            { color: "#d0bcff", label: "Focus device" },
            { color: "#3b82f6", label: "Direct peer (1 hop)" },
            { color: "#8b5cf6", label: "Indirect (2+ hops)" },
            { color: "#059669", label: "Server (receive only)" },
          ].map((entry) => (
            <li
              key={entry.label}
              className="flex items-center gap-2 text-body-sm font-body-sm text-on-surface-variant"
            >
              <span
                className="w-2.5 h-2.5 rounded-[3px] shrink-0"
                style={{ backgroundColor: entry.color }}
              />
              {entry.label}
            </li>
          ))}
        </ul>
      </div>

      <div className="absolute right-4 top-4 z-10 text-body-sm font-body-sm text-on-surface-variant bg-surface-container/90 border border-outline-variant rounded-lg px-3 py-1.5 backdrop-blur">
        {formatNumber(simNodes.length)} devices · {formatNumber(simLinks.length)} links
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className={clsx("w-full h-full", dragging ? "cursor-grabbing" : "cursor-grab")}
        onMouseDown={(event) => {
          panOrigin.current = {
            x: event.clientX - transform.x,
            y: event.clientY - transform.y,
          };
          setDragging(true);
        }}
        onMouseMove={(event) => {
          if (!dragging || !panOrigin.current) return;
          setTransform((t) => ({
            ...t,
            x: event.clientX - panOrigin.current!.x,
            y: event.clientY - panOrigin.current!.y,
          }));
        }}
        onMouseUp={() => setDragging(false)}
        onMouseLeave={() => setDragging(false)}
        onWheel={(event) => {
          zoomBy(event.deltaY < 0 ? 1.08 : 0.92);
        }}
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#494454" />
          </marker>
          <marker
            id="arrow-path"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#d0bcff" />
          </marker>
        </defs>

        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          {simLinks.map((link, index) => {
            const source = link.source as GraphNode;
            const target = link.target as GraphNode;
            if (source.x == null || target.x == null) return null;
            const key = `${source.id}->${target.id}`;
            const onPath = pathEdges.has(key);
            // Emphasise edges only for a *deliberate* selection. The focus device
            // is selected by default, and highlighting all of its edges would
            // colour the whole canvas — defeating the highlight and making the
            // blue "direct peer" nodes read as violet against it.
            const touchesSelected =
              selected != null &&
              selected !== focusDevice &&
              (source.id === selected || target.id === selected);

            return (
              <line
                key={`${key}-${index}`}
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke={onPath ? "#d0bcff" : touchesSelected ? "#8b5cf6" : "#494454"}
                strokeWidth={onPath ? 2.5 : touchesSelected ? 1.6 : 1}
                strokeOpacity={
                  pathEdges.size > 0 && !onPath ? 0.18 : touchesSelected ? 0.9 : 0.45
                }
                markerEnd={onPath ? "url(#arrow-path)" : "url(#arrow)"}
              />
            );
          })}

          {simNodes.map((node) => {
            const isFocus = node.id === focusDevice;
            const isSelected = node.id === selected;
            const onPath = pathNodes.has(node.id);
            const dimmed = pathNodes.size > 0 && !onPath;
            const size = isFocus ? 34 : 26;
            const color = nodeColor(node, focusDevice);

            return (
              <g
                key={node.id}
                transform={`translate(${node.x ?? 0},${node.y ?? 0})`}
                className="cursor-pointer"
                opacity={dimmed ? 0.25 : 1}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelect(node.id);
                }}
              >
                <title>
                  {`${node.id}\n${formatNumber(node.eventsOut)} out / ${formatNumber(
                    node.eventsIn
                  )} in\n${formatBytes(node.bytesOut)} sent`}
                </title>
                {(isSelected || isFocus) && (
                  <rect
                    x={-size / 2 - 5}
                    y={-size / 2 - 5}
                    width={size + 10}
                    height={size + 10}
                    rx={10}
                    fill="none"
                    stroke={color}
                    strokeWidth={2}
                    strokeOpacity={0.55}
                  />
                )}
                <rect
                  x={-size / 2}
                  y={-size / 2}
                  width={size}
                  height={size}
                  rx={8}
                  fill={color}
                  fillOpacity={0.18}
                  stroke={color}
                  strokeWidth={2}
                />
                <text
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={isFocus ? 16 : 13}
                  fill={color}
                  className="material-symbols-outlined select-none pointer-events-none"
                >
                  {node.isSink ? "dns" : "computer"}
                </text>
                <text
                  y={size / 2 + 15}
                  textAnchor="middle"
                  fontSize={11}
                  fill="#cbc3d7"
                  fontFamily="JetBrains Mono, monospace"
                  className="select-none pointer-events-none"
                >
                  {node.id}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
