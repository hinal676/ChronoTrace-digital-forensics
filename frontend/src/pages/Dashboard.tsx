/**
 * Dashboard (design sample 1), mapped onto network-activity data.
 *
 * The mockup's "event categories" become protocols and destination services; its
 * alert feed becomes the highest-risk events from the anomaly detector.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { BarChart, DonutChart, RankedBars } from "@/components/Charts";
import {
  EmptyState,
  ErrorState,
  Panel,
  QueryState,
  RiskBadge,
  Spinner,
  StatCard,
} from "@/components/ui";
import { api } from "@/lib/api";
import {
  formatBytes,
  formatCompact,
  formatNumber,
  formatTimestamp,
  seriesColor,
} from "@/lib/format";

const RANGES = [
  { label: "6H", seconds: 6 * 3600 },
  { label: "24H", seconds: 24 * 3600 },
  { label: "7D", seconds: 7 * 86400 },
  { label: "All", seconds: 0 },
] as const;

export function Dashboard() {
  const [rangeIndex, setRangeIndex] = useState(3);
  const range = RANGES[rangeIndex];

  const events = useQuery({
    queryKey: ["events", "count"],
    queryFn: () => api.listEvents({ limit: 1 }),
  });
  const graph = useQuery({ queryKey: ["graph", "stats"], queryFn: () => api.graphStats() });
  const protocols = useQuery({ queryKey: ["protocols"], queryFn: api.getProtocols });
  const ports = useQuery({ queryKey: ["ports", 6], queryFn: () => api.getPorts(6) });
  const investigations = useQuery({
    queryKey: ["investigations", "count"],
    queryFn: () => api.listInvestigations({ limit: 1 }),
  });
  const model = useQuery({ queryKey: ["model"], queryFn: api.modelInfo, retry: false });

  // The dataset spans a month, so the window is anchored to the newest event
  // rather than to "now" — otherwise every range would come back empty.
  const latest = useQuery({
    queryKey: ["events", "latest"],
    queryFn: () => api.listEvents({ limit: 1, sort_by: "timestamp", order: "desc" }),
  });
  const latestTs = latest.data?.items[0]?.timestamp;

  const timeline = useQuery({
    queryKey: ["timeline", "dashboard", range.seconds, latestTs],
    enabled: latestTs != null,
    queryFn: () =>
      api.getTimeline({
        interval: range.seconds ? Math.max(range.seconds / 48, 300) : 43200,
        start_time: range.seconds ? latestTs! - range.seconds : undefined,
        limit: 200,
      }),
  });

  const analysis = useQuery({
    queryKey: ["analysis", "dashboard"],
    queryFn: () =>
      api.runAnalysis({ limit: 5000, top_n: 8, persist: false, min_risk_score: 0.5 }),
    retry: false,
  });

  const protocolSlices = useMemo(
    () =>
      (protocols.data ?? []).map((p, index) => ({
        label: p.protocol_name,
        value: p.event_count,
        color: seriesColor(index),
      })),
    [protocols.data]
  );

  const portBars = useMemo(
    () =>
      (ports.data ?? []).map((p) => ({
        label: p.dst_service ? `${p.dst_service} (${p.dst_port})` : `Port ${p.dst_port}`,
        value: p.event_count,
      })),
    [ports.data]
  );

  const timelineBars = useMemo(
    () =>
      (timeline.data?.buckets ?? []).map((bucket) => ({
        label: new Date(bucket.bucket_start * 1000)
          .toISOString()
          .slice(5, 16)
          .replace("T", " "),
        value: bucket.event_count,
        secondary: `${formatBytes(bucket.total_bytes)} · ${bucket.unique_src_devices} sources`,
      })),
    [timeline.data]
  );

  const flagged = analysis.data?.summary.flagged_events ?? 0;
  const analyzed = analysis.data?.summary.analyzed_events ?? 0;

  return (
    <div className="h-full overflow-y-auto p-container_padding space-y-gutter">
      {/* Headline counters */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-gutter">
        <StatCard
          icon="monitoring"
          label="Total Events"
          value={events.isLoading ? "…" : formatNumber(events.data?.total ?? 0)}
          hint={
            graph.data ? `across ${formatNumber(graph.data.node_count)} devices` : undefined
          }
        />
        <StatCard
          icon="warning"
          tone="danger"
          label="Events Requiring Review"
          value={analysis.isLoading ? "…" : analysis.isError ? "—" : formatNumber(flagged)}
          hint={
            analysis.isError
              ? "model unavailable"
              : analyzed
                ? `${((flagged / analyzed) * 100).toFixed(1)}% of ${formatCompact(analyzed)} scored`
                : undefined
          }
        />
        <StatCard
          icon="hub"
          tone="info"
          label="Relationships"
          value={graph.isLoading ? "…" : formatNumber(graph.data?.edge_count ?? 0)}
          hint={
            graph.data
              ? `density ${(graph.data.density * 100).toFixed(1)}% · ${graph.data.weakly_connected_components} component(s)`
              : undefined
          }
        />
        <StatCard
          icon="folder_open"
          tone="success"
          label="Investigations"
          value={
            investigations.isLoading ? "…" : formatNumber(investigations.data?.total ?? 0)
          }
          hint="Active case files"
        />
      </div>

      {/* Activity + distribution */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-gutter">
        <Panel
          className="xl:col-span-2"
          title="Activity Timeline"
          subtitle={
            timeline.data?.interval_seconds
              ? `${formatNumber(timeline.data.total_events)} events · ${Math.round(timeline.data.interval_seconds / 60)}-minute buckets`
              : "Events over time"
          }
          actions={
            <div className="flex bg-surface-container border border-outline-variant rounded-lg overflow-hidden">
              {RANGES.map((option, index) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setRangeIndex(index)}
                  className={
                    index === rangeIndex
                      ? "px-3 py-1 text-body-sm font-body-sm bg-primary/20 text-primary"
                      : "px-3 py-1 text-body-sm font-body-sm text-on-surface-variant hover:bg-surface-container-high"
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>
          }
        >
          <QueryState
            isLoading={timeline.isLoading || latest.isLoading}
            error={timeline.error ?? latest.error}
            isEmpty={!timelineBars.length}
            emptyTitle="No activity in this window"
            emptyDetail="Try a wider range."
          >
            <BarChart data={timelineBars} height={260} />
          </QueryState>
        </Panel>

        <Panel title="Protocol Distribution" subtitle="Share of events by protocol">
          <QueryState
            isLoading={protocols.isLoading}
            error={protocols.error}
            isEmpty={!protocolSlices.length}
            emptyTitle="No protocol data"
          >
            <DonutChart data={protocolSlices} totalLabel="Events" />
          </QueryState>
        </Panel>
      </div>

      {/* Risk feed + top talkers */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-gutter">
        <Panel
          className="xl:col-span-2"
          title="Highest-Risk Activity"
          subtitle="Statistical indicators — each requires analyst review"
          actions={
            <Link
              to="/evidence"
              className="text-body-sm font-body-sm text-primary hover:underline"
            >
              View all
            </Link>
          }
          bodyClassName="p-0"
        >
          {analysis.isLoading ? (
            <Spinner label="Scoring events" />
          ) : analysis.isError ? (
            <ErrorState error={analysis.error} />
          ) : !analysis.data?.results.length ? (
            <EmptyState
              icon="verified"
              title="Nothing above the review threshold"
              detail="No events in the scored window reached a risk score of 0.5."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-body-sm font-body-sm">
                <thead>
                  <tr className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider border-b border-outline-variant/50">
                    <th className="text-left font-semibold px-4 py-2">Time</th>
                    <th className="text-left font-semibold px-4 py-2">Source</th>
                    <th className="text-left font-semibold px-4 py-2">Destination</th>
                    <th className="text-left font-semibold px-4 py-2">Top Factor</th>
                    <th className="text-left font-semibold px-4 py-2">Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.data.results.map((risk) => (
                    <tr
                      key={risk.event_id}
                      className="border-b border-outline-variant/20 last:border-0 hover:bg-surface-container-high/50"
                    >
                      <td className="px-4 py-2.5 font-mono-data text-on-surface-variant whitespace-nowrap">
                        {formatTimestamp(risk.timestamp)}
                      </td>
                      <td className="px-4 py-2.5 font-mono-data text-on-surface">
                        {risk.src_device}
                      </td>
                      <td className="px-4 py-2.5 font-mono-data text-on-surface-variant">
                        {risk.dst_device}
                      </td>
                      <td className="px-4 py-2.5 text-on-surface-variant max-w-[260px] truncate">
                        {risk.reasons[0]}
                      </td>
                      <td className="px-4 py-2.5">
                        <RiskBadge
                          classification={risk.classification}
                          score={risk.risk_score}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <div className="space-y-gutter">
          <Panel title="Top Services" subtitle="Most-contacted destination ports">
            <QueryState
              isLoading={ports.isLoading}
              error={ports.error}
              isEmpty={!portBars.length}
              emptyTitle="No port data"
            >
              <RankedBars data={portBars} />
            </QueryState>
          </Panel>

          <Panel title="System Health">
            <dl className="space-y-2.5 m-0">
              {[
                {
                  label: "Detection model",
                  value: model.data?.trained
                    ? (model.data.model_type ?? "trained")
                    : "not trained",
                  ok: !!model.data?.trained,
                },
                {
                  label: "Training events",
                  value: formatNumber(model.data?.training_events ?? 0),
                  ok: !!model.data?.training_events,
                },
                {
                  label: "Graph cache",
                  value: graph.data
                    ? `${formatNumber(graph.data.node_count)} nodes`
                    : "unavailable",
                  ok: !!graph.data,
                },
                {
                  label: "Total volume",
                  value: formatBytes(graph.data?.total_bytes ?? 0),
                  ok: true,
                },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between gap-3">
                  <dt className="text-body-sm font-body-sm text-on-surface-variant">
                    {row.label}
                  </dt>
                  <dd className="flex items-center gap-2 m-0">
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${row.ok ? "bg-emerald-500" : "bg-amber-500"}`}
                    />
                    <span className="text-body-sm font-body-sm text-on-surface">
                      {row.value}
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </div>
  );
}
