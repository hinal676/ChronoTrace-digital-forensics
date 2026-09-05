/**
 * Hand-rolled SVG charts.
 *
 * Built directly rather than with a chart library so the marks follow the design
 * system exactly: 2px surface gaps between adjacent fills, 4px rounded data-ends
 * anchored to the baseline, recessive axes, and a hover layer on every plot.
 *
 * Series colours come from the validated categorical palette in `format.ts` and
 * are assigned in fixed order — never cycled, never keyed to rank.
 */

import { useMemo, useState } from "react";
import clsx from "clsx";

import { formatCompact, formatNumber, seriesColor } from "@/lib/format";

/** Colour of the panel behind a chart; used to cut the 2px gaps between fills. */
const SURFACE = "#131b2e";

export interface Slice {
  label: string;
  value: number;
  color?: string;
}

/**
 * Donut with a hero total in the middle and a value legend beneath, matching the
 * "Top Event Categories" panel in the dashboard mockup.
 */
export function DonutChart({
  data,
  total,
  totalLabel = "Total",
  unit,
}: {
  data: Slice[];
  total?: number;
  totalLabel?: string;
  unit?: (value: number) => string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  const sum = total ?? data.reduce((acc, slice) => acc + slice.value, 0);
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  // A 2px visual gap between segments, expressed in path units.
  const gap = sum > 0 && data.length > 1 ? 1.5 : 0;

  let offset = 0;
  const segments = data.map((slice, index) => {
    const fraction = sum > 0 ? slice.value / sum : 0;
    const length = Math.max(fraction * circumference - gap, 0);
    const segment = {
      ...slice,
      color: slice.color ?? seriesColor(index),
      dash: `${length} ${circumference - length}`,
      offset: -offset,
      fraction,
      index,
    };
    offset += fraction * circumference;
    return segment;
  });

  const format = unit ?? formatNumber;
  const active = hovered != null ? segments[hovered] : null;

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative w-[180px] h-[180px] shrink-0">
        <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
          <circle
            cx="50"
            cy="50"
            r={radius}
            fill="none"
            stroke="#494454"
            strokeOpacity={0.25}
            strokeWidth={12}
          />
          {segments.map((segment) => (
            <circle
              key={segment.label}
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke={segment.color}
              strokeWidth={hovered === segment.index ? 15 : 12}
              strokeDasharray={segment.dash}
              strokeDashoffset={segment.offset}
              strokeLinecap="butt"
              className="transition-[stroke-width] duration-150 cursor-pointer"
              onMouseEnter={() => setHovered(segment.index)}
              onMouseLeave={() => setHovered(null)}
            >
              <title>{`${segment.label}: ${format(segment.value)}`}</title>
            </circle>
          ))}
        </svg>
        {/* Hero number: text wears text tokens, never a series colour. */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-body-sm font-body-sm text-on-surface-variant">
            {active ? active.label : totalLabel}
          </span>
          <span className="text-headline-md font-headline-md text-on-surface">
            {format(active ? active.value : sum)}
          </span>
          {active && (
            <span className="text-body-sm font-body-sm text-on-surface-variant">
              {(active.fraction * 100).toFixed(1)}%
            </span>
          )}
        </div>
      </div>

      {/* Legend is always present for >= 2 series, and carries the values. */}
      <ul className="w-full space-y-1.5 m-0 p-0 list-none">
        {segments.map((segment) => (
          <li
            key={segment.label}
            className={clsx(
              "flex justify-between items-center gap-3 text-body-sm font-body-sm rounded px-1 py-0.5 cursor-default transition-colors",
              hovered === segment.index && "bg-surface-container-high"
            )}
            onMouseEnter={() => setHovered(segment.index)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="flex items-center gap-2 min-w-0">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: segment.color }}
              />
              <span className="text-on-surface-variant truncate">{segment.label}</span>
            </span>
            <span className="flex gap-2 shrink-0">
              <span className="text-on-surface font-medium">
                {format(segment.value)}
              </span>
              <span className="text-on-surface-variant opacity-60">
                ({(segment.fraction * 100).toFixed(1)}%)
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface Bar {
  label: string;
  value: number;
  /** Optional secondary value shown in the tooltip (e.g. bytes alongside count). */
  secondary?: string;
  color?: string;
}

/**
 * Vertical bar chart with a hover tooltip.
 *
 * Bars carry 4px rounded tops anchored to the baseline and a 2px gap cut between
 * neighbours, so adjacent values never visually merge.
 */
export function BarChart({
  data,
  height = 220,
  color,
  valueFormat = formatCompact,
  emptyLabel = "No data in range",
}: {
  data: Bar[];
  height?: number;
  color?: string;
  valueFormat?: (value: number) => string;
  emptyLabel?: string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);

  const max = useMemo(
    () => Math.max(...data.map((bar) => bar.value), 1),
    [data]
  );

  if (!data.length) {
    return (
      <div
        className="flex items-center justify-center text-body-sm font-body-sm text-on-surface-variant"
        style={{ height }}
      >
        {emptyLabel}
      </div>
    );
  }

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    fraction,
    value: max * fraction,
  }));
  const active = hovered != null ? data[hovered] : null;

  return (
    <div className="relative" style={{ height }}>
      {/* Recessive gridlines + axis labels. */}
      <div className="absolute inset-0 flex flex-col-reverse justify-between pointer-events-none pl-12 pr-2 pb-6">
        {ticks.map((tick) => (
          <div key={tick.fraction} className="relative">
            <div className="border-t border-outline-variant/20" />
            <span className="absolute -left-12 -top-2 w-10 text-right text-[10px] font-mono-data text-on-surface-variant/70">
              {valueFormat(tick.value)}
            </span>
          </div>
        ))}
      </div>

      <div className="absolute inset-0 flex items-end gap-[2px] pl-12 pr-2 pb-6">
        {data.map((bar, index) => {
          const pct = (bar.value / max) * 100;
          return (
            <div
              key={`${bar.label}-${index}`}
              className="flex-1 h-full flex items-end min-w-0 group"
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
            >
              {/* Full-height hit target: easier to hover than the bar itself. */}
              <div className="w-full h-full flex items-end cursor-pointer">
                <div
                  className="w-full rounded-t-[4px] transition-opacity"
                  style={{
                    height: `${Math.max(pct, bar.value > 0 ? 1.5 : 0)}%`,
                    backgroundColor: bar.color ?? color ?? seriesColor(0),
                    opacity: hovered == null || hovered === index ? 1 : 0.45,
                    // 2px surface gap so neighbouring bars stay separable.
                    boxShadow: `0 0 0 1px ${SURFACE}`,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* First/last x labels only — a label on every bar is noise. */}
      <div className="absolute bottom-0 left-12 right-2 flex justify-between text-[10px] font-mono-data text-on-surface-variant/70">
        <span>{data[0]?.label}</span>
        {data.length > 2 && <span>{data[Math.floor(data.length / 2)]?.label}</span>}
        <span>{data[data.length - 1]?.label}</span>
      </div>

      {active && (
        <div className="absolute top-0 right-0 bg-surface-container-highest border border-outline-variant rounded-lg px-3 py-2 shadow-lg pointer-events-none z-10">
          <p className="text-[11px] font-mono-data text-on-surface-variant m-0">
            {active.label}
          </p>
          <p className="text-body-sm font-body-sm text-on-surface m-0 font-semibold">
            {formatNumber(active.value)} events
          </p>
          {active.secondary && (
            <p className="text-[11px] font-body-sm text-on-surface-variant m-0">
              {active.secondary}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Horizontal ranked bars — the right form for "top N by volume", where category
 * labels need room to be read.
 *
 * One measure means one hue: the row label already identifies the category, so
 * giving each bar its own colour would be decoration that implies an encoding
 * which is not there. Callers that genuinely need per-category identity (because
 * a legend elsewhere maps the colours) can still pass `color` per slice.
 */
export function RankedBars({
  data,
  valueFormat = formatNumber,
  max: explicitMax,
}: {
  data: Slice[];
  valueFormat?: (value: number) => string;
  max?: number;
}) {
  const max = explicitMax ?? Math.max(...data.map((d) => d.value), 1);

  if (!data.length) {
    return (
      <p className="text-body-sm font-body-sm text-on-surface-variant py-6 text-center">
        No data
      </p>
    );
  }

  return (
    <ul className="space-y-2.5 m-0 p-0 list-none">
      {data.map((row) => (
        <li key={row.label} className="group">
          <div className="flex justify-between items-baseline gap-3 mb-1">
            <span className="text-body-sm font-body-sm text-on-surface truncate">
              {row.label}
            </span>
            <span className="text-body-sm font-mono-data text-on-surface-variant shrink-0">
              {valueFormat(row.value)}
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-container-high overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.max((row.value / max) * 100, 1)}%`,
                backgroundColor: row.color ?? seriesColor(0),
              }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
