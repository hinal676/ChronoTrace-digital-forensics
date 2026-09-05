/**
 * Timeline (design sample 2): filter bar, chronological event rail, detail panel.
 *
 * The mockup lists raw events; this adds a bucket overview above the rail because
 * a month of network traffic is only legible once aggregated.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";

import { BarChart } from "@/components/Charts";
import {
  Chip,
  DetailRow,
  EmptyState,
  Field,
  Panel,
  QueryState,
  RiskBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import {
  classifyScore,
  formatBytes,
  formatDuration,
  formatNumber,
  formatTime,
  formatTimestamp,
  parseDateTimeLocalInput,
} from "@/lib/format";
import type { NetworkEvent } from "@/types";

export function Timeline() {
  const navigate = useNavigate();
  const [protocol, setProtocol] = useState<string>("");
  const [dstPort, setDstPort] = useState<string>("");
  const [device, setDevice] = useState<string>("");
  const [start, setStart] = useState<string>("");
  const [end, setEnd] = useState<string>("");
  const [applied, setApplied] = useState(0);
  const [selected, setSelected] = useState<NetworkEvent | null>(null);

  // Reading the filters only when Filter is pressed keeps typing from firing a
  // request per keystroke against Atlas.
  const filters = useMemo(
    () => ({
      protocol: protocol ? Number(protocol) : undefined,
      dst_port: dstPort ? Number(dstPort) : undefined,
      device: device.trim() || undefined,
      start_time: parseDateTimeLocalInput(start),
      end_time: parseDateTimeLocalInput(end),
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [applied]
  );

  const buckets = useQuery({
    queryKey: ["timeline", "buckets", filters],
    queryFn: () => api.getTimeline({ ...filters, interval: 21600, limit: 200 }),
  });

  const events = useQuery({
    queryKey: ["timeline", "raw", filters],
    queryFn: () => api.getTimeline({ ...filters, raw: true, limit: 200 }),
  });

  // Risk for the visible page, so the rail can flag events without a second click.
  const risk = useQuery({
    queryKey: ["timeline", "risk", filters],
    enabled: !!events.data?.events.length,
    retry: false,
    queryFn: () =>
      api.runAnalysis({
        ...filters,
        limit: 2000,
        top_n: 500,
        persist: false,
        min_risk_score: 0.5,
      }),
  });

  const riskByEvent = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of risk.data?.results ?? []) map.set(item.event_id, item.risk_score);
    return map;
  }, [risk.data]);

  const bars = useMemo(
    () =>
      (buckets.data?.buckets ?? []).map((bucket) => ({
        label: new Date(bucket.bucket_start * 1000).toISOString().slice(5, 10),
        value: bucket.event_count,
        secondary: formatBytes(bucket.total_bytes),
      })),
    [buckets.data]
  );

  const list = events.data?.events ?? [];

  return (
    <div className="h-full flex flex-col">
      {/* Filter bar */}
      <div className="shrink-0 px-container_padding py-3 border-b border-outline-variant bg-surface-container-lowest flex flex-wrap items-end gap-4">
        <Field label="Start (UTC)">
          <input
            type="datetime-local"
            className="field"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </Field>
        <Field label="End (UTC)">
          <input
            type="datetime-local"
            className="field"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </Field>
        <Field label="Device">
          <input
            className="field w-[170px]"
            placeholder="Comp431255"
            value={device}
            onChange={(e) => setDevice(e.target.value)}
          />
        </Field>
        <Field label="Protocol">
          <select
            className="field w-[120px]"
            value={protocol}
            onChange={(e) => setProtocol(e.target.value)}
          >
            <option value="">All</option>
            <option value="6">TCP (6)</option>
            <option value="17">UDP (17)</option>
          </select>
        </Field>
        <Field label="Dest. port">
          <input
            className="field w-[110px]"
            placeholder="443"
            inputMode="numeric"
            value={dstPort}
            onChange={(e) => setDstPort(e.target.value)}
          />
        </Field>
        <button
          type="button"
          className="btn-primary"
          onClick={() => setApplied((n) => n + 1)}
        >
          Filter
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => {
            setProtocol("");
            setDstPort("");
            setDevice("");
            setStart("");
            setEnd("");
            setApplied((n) => n + 1);
          }}
        >
          Reset
        </button>
        {buckets.data && (
          <span className="ml-auto text-body-sm font-body-sm text-on-surface-variant">
            {formatNumber(buckets.data.total_events)} matching events
          </span>
        )}
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Event rail */}
        <div className="flex-1 flex flex-col min-w-0 border-r border-outline-variant/50">
          <div className="shrink-0 px-container_padding pt-4">
            <Panel title="Volume Over Time" subtitle="6-hour buckets">
              <QueryState
                isLoading={buckets.isLoading}
                error={buckets.error}
                isEmpty={!bars.length}
                emptyTitle="No events match these filters"
              >
                <BarChart data={bars} height={150} />
              </QueryState>
            </Panel>
          </div>

          <div className="flex-1 overflow-y-auto px-container_padding py-4">
            <QueryState
              isLoading={events.isLoading}
              error={events.error}
              isEmpty={!list.length}
              emptyTitle="No events match these filters"
              emptyDetail="Widen the time range or clear a filter."
              loadingLabel="Loading events"
            >
              <ol className="m-0 p-0 list-none">
                {list.map((event) => {
                  const score = riskByEvent.get(event.event_id);
                  const isSelected = selected?.event_id === event.event_id;
                  return (
                    <li key={event.event_id} className="flex gap-4 group">
                      {/* Time gutter + rail, as in the mockup */}
                      <div className="w-[92px] shrink-0 text-right pt-3">
                        <p className="text-mono-data font-mono-data text-on-surface-variant m-0">
                          {formatTime(event.timestamp)}
                        </p>
                        <p className="text-[10px] font-mono-data text-on-surface-variant/60 m-0">
                          {new Date(event.timestamp * 1000).toISOString().slice(0, 10)}
                        </p>
                      </div>
                      <div className="flex flex-col items-center shrink-0">
                        <span
                          className={clsx(
                            "w-8 h-8 rounded-lg border flex items-center justify-center mt-2",
                            score != null && score >= 0.75
                              ? "border-red-500/50 text-red-300 bg-red-500/10"
                              : "border-outline-variant text-on-surface-variant bg-surface-container"
                          )}
                        >
                          <span className="material-symbols-outlined text-[16px]">
                            {event.protocol === 17 ? "wifi_tethering" : "swap_horiz"}
                          </span>
                        </span>
                        <span className="flex-1 w-px bg-outline-variant/30 my-1" />
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelected(event)}
                        className={clsx(
                          "flex-1 min-w-0 text-left mb-3 mt-2 rounded-xl border px-4 py-3 transition-colors",
                          isSelected
                            ? "border-primary/60 bg-primary/5"
                            : "border-outline-variant/40 bg-surface-container-low hover:bg-surface-container"
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-body-md font-body-md font-semibold text-on-surface m-0 truncate">
                              <span className="font-mono-data">{event.src_device}</span>
                              <span className="text-on-surface-variant mx-1.5">→</span>
                              <span className="font-mono-data">{event.dst_device}</span>
                            </p>
                            <p className="text-body-sm font-body-sm text-on-surface-variant m-0 mt-0.5">
                              {event.protocol_name} · port {event.dst_port}
                              {event.dst_service ? ` (${event.dst_service})` : ""} ·{" "}
                              {formatBytes(event.total_bytes)} ·{" "}
                              {formatDuration(event.duration)}
                            </p>
                          </div>
                          {score != null && (
                            <RiskBadge
                              classification={classifyScore(score)}
                              score={score}
                            />
                          )}
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </QueryState>
          </div>
        </div>

        {/* Detail panel */}
        <aside className="w-[360px] shrink-0 flex flex-col bg-surface-container-lowest">
          <div className="px-4 py-3 border-b border-outline-variant/50">
            <h3 className="text-headline-sm font-headline-sm font-semibold m-0">
              Event Details
            </h3>
            <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0">
              Selected event context
            </p>
          </div>

          {!selected ? (
            <EmptyState
              icon="ads_click"
              title="No event selected"
              detail="Choose an event from the timeline to inspect its full record."
            />
          ) : (
            <>
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                <div className="divide-y divide-outline-variant/20">
                  <DetailRow label="Event ID" mono>
                    {selected.event_id}
                  </DetailRow>
                  <DetailRow label="Time (UTC)" mono>
                    {formatTimestamp(selected.timestamp)}
                  </DetailRow>
                  <DetailRow label="Duration">
                    {formatDuration(selected.duration)}
                  </DetailRow>
                  <DetailRow label="Source" mono>
                    {selected.src_device}:{selected.src_port}
                  </DetailRow>
                  <DetailRow label="Destination" mono>
                    {selected.dst_device}:{selected.dst_port}
                  </DetailRow>
                  <DetailRow label="Protocol">
                    {selected.protocol_name} ({selected.protocol})
                  </DetailRow>
                  <DetailRow label="Service">
                    {selected.dst_service ?? "unrecognised"}
                  </DetailRow>
                </div>

                <div>
                  <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
                    Traffic
                  </p>
                  <div className="divide-y divide-outline-variant/20">
                    <DetailRow label="Sent">
                      {formatBytes(selected.src_bytes)} ·{" "}
                      {formatNumber(selected.src_packets)} pkts
                    </DetailRow>
                    <DetailRow label="Received">
                      {formatBytes(selected.dst_bytes)} ·{" "}
                      {formatNumber(selected.dst_packets)} pkts
                    </DetailRow>
                    <DetailRow label="Byte ratio" mono>
                      {selected.byte_ratio.toFixed(3)}
                    </DetailRow>
                    <DetailRow label="Throughput">
                      {formatBytes(selected.bytes_per_second)}/s
                    </DetailRow>
                  </div>
                </div>

                {riskByEvent.has(selected.event_id) && (
                  <div>
                    <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
                      Risk Factors
                    </p>
                    <ul className="space-y-1.5 m-0 p-0 list-none">
                      {(
                        risk.data?.results.find(
                          (r) => r.event_id === selected.event_id
                        )?.reasons ?? []
                      ).map((reason) => (
                        <li
                          key={reason}
                          className="flex gap-2 text-body-sm font-body-sm text-on-surface-variant"
                        >
                          <span className="material-symbols-outlined text-[14px] text-orange-400 mt-0.5">
                            chevron_right
                          </span>
                          {reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="flex flex-wrap gap-1.5">
                  <Chip>{selected.source}</Chip>
                  <Chip>{formatNumber(selected.total_packets)} packets</Chip>
                </div>
              </div>

              <div className="p-4 border-t border-outline-variant/50 space-y-2">
                <button
                  type="button"
                  className="btn-primary w-full"
                  onClick={() =>
                    navigate(`/cases?device=${encodeURIComponent(selected.src_device)}`)
                  }
                >
                  Open Investigation
                </button>
                <button
                  type="button"
                  className="btn-ghost w-full"
                  onClick={() =>
                    navigate(`/graph?device=${encodeURIComponent(selected.src_device)}`)
                  }
                >
                  <span className="material-symbols-outlined text-[16px]">hub</span>
                  View in Graph
                </button>
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
