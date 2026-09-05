/** Formatting helpers shared across pages, so units read identically everywhere. */

import type { Classification } from "@/types";

/** Bytes as a human-readable size. Network volumes here reach hundreds of MB. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const exponent = Math.min(
    Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / 1024 ** exponent;
  // Big units earn a decimal; bytes and KB do not.
  return `${value.toFixed(exponent > 1 ? 2 : 0)} ${units[exponent]}`;
}

export function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US");
}

export function formatCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Seconds as a duration. Events in this dataset run to several hours. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** Epoch seconds -> UTC. Forensic timestamps stay in UTC to avoid ambiguity. */
export function formatTimestamp(epochSeconds: number | null | undefined): string {
  if (epochSeconds == null) return "—";
  return new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 19);
}

export function formatTime(epochSeconds: number | null | undefined): string {
  if (epochSeconds == null) return "—";
  return new Date(epochSeconds * 1000).toISOString().slice(11, 19);
}

export function formatDate(epochSeconds: number | null | undefined): string {
  if (epochSeconds == null) return "—";
  return new Date(epochSeconds * 1000).toISOString().slice(0, 10);
}

export function formatDateTimeLocalInput(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().slice(0, 16);
}

export function parseDateTimeLocalInput(value: string): number | undefined {
  if (!value) return undefined;
  const ms = Date.parse(`${value}:00Z`);
  return Number.isNaN(ms) ? undefined : Math.floor(ms / 1000);
}

export function formatIsoDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  return new Date(ms).toISOString().replace("T", " ").slice(0, 19);
}

/** Human label for a risk band. */
export const CLASSIFICATION_LABEL: Record<Classification, string> = {
  normal: "Normal",
  low_concern: "Low Concern",
  requires_review: "Requires Review",
  high_priority: "High Priority",
};

/**
 * Status colours for risk bands. Reserved — never reused as a chart series.
 * Always paired with a label and icon so meaning is never colour-alone.
 */
export const CLASSIFICATION_STYLE: Record<
  Classification,
  { text: string; bg: string; border: string; dot: string; icon: string }
> = {
  normal: {
    text: "text-emerald-300",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/40",
    dot: "#059669",
    icon: "check_circle",
  },
  low_concern: {
    text: "text-amber-300",
    bg: "bg-amber-500/10",
    border: "border-amber-500/40",
    dot: "#d97706",
    icon: "info",
  },
  requires_review: {
    text: "text-orange-300",
    bg: "bg-orange-500/10",
    border: "border-orange-500/40",
    dot: "#f97316",
    icon: "warning",
  },
  high_priority: {
    text: "text-red-300",
    bg: "bg-red-500/10",
    border: "border-red-500/40",
    dot: "#ef4444",
    icon: "e911_emergency",
  },
};

/**
 * Categorical chart palette — validated for colour-vision deficiency.
 * Assign in this fixed order; never cycle. A 7th category folds into "Other".
 */
export const SERIES_COLORS = [
  "#3b82f6",
  "#ea580c",
  "#059669",
  "#8b5cf6",
  "#0891b2",
  "#ec4899",
] as const;

export const OTHER_COLOR = "#64748b";

/** Colour for the nth category, with everything past the palette as "Other". */
export function seriesColor(index: number): string {
  return index < SERIES_COLORS.length ? SERIES_COLORS[index] : OTHER_COLOR;
}

export function riskColor(score: number): string {
  if (score >= 0.9) return "#ef4444";
  if (score >= 0.75) return "#f97316";
  if (score >= 0.5) return "#d97706";
  return "#059669";
}

export function classifyScore(score: number): Classification {
  if (score >= 0.9) return "high_priority";
  if (score >= 0.75) return "requires_review";
  if (score >= 0.5) return "low_concern";
  return "normal";
}

export function protocolLabel(protocol: number, name?: string | null): string {
  return name ?? (protocol === 6 ? "TCP" : protocol === 17 ? "UDP" : `PROTO-${protocol}`);
}
