/**
 * Evidence browser (design sample 4).
 *
 * In a network investigation the evidence *is* the event record, so the mockup's
 * file grid becomes a filterable, sortable record browser with grid and list
 * views and a detail pane.
 */

import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";

import {
  Chip,
  DetailRow,
  EmptyState,
  Field,
  QueryState,
  RiskBadge,
} from "@/components/ui";
import { api } from "@/lib/api";
import {
  classifyScore,
  formatBytes,
  formatDuration,
  formatNumber,
  formatTimestamp,
} from "@/lib/format";
import type { NetworkEvent, SortOrder } from "@/types";

const PAGE_SIZE = 24;

const SORTS: { value: string; label: string }[] = [
  { value: "timestamp", label: "Time" },
  { value: "total_bytes", label: "Total bytes" },
  { value: "src_bytes", label: "Bytes sent" },
  { value: "duration", label: "Duration" },
  { value: "total_packets", label: "Packets" },
];

export function Evidence() {
  const navigate = useNavigate();
  const [view, setView] = useState<"grid" | "list">("list");
  const [device, setDevice] = useState("");
  const [protocol, setProtocol] = useState("");
  const [dstPort, setDstPort] = useState("");
  const [minBytes, setMinBytes] = useState("");
  const [sortBy, setSortBy] = useState("timestamp");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [page, setPage] = useState(0);
  const [applied, setApplied] = useState(0);
  const [selected, setSelected] = useState<NetworkEvent | null>(null);

  const query = useMemo(
    () => ({
      device: device.trim() || undefined,
      protocol: protocol ? Number(protocol) : undefined,
      dst_port: dstPort ? Number(dstPort) : undefined,
      min_bytes: minBytes ? Number(minBytes) : undefined,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [applied]
  );

  const events = useQuery({
    queryKey: ["evidence", query, sortBy, order, page],
    // Keeps the previous page on screen while the next loads, so paging doesn't flash.
    placeholderData: keepPreviousData,
    queryFn: () =>
      api.listEvents({
        ...query,
        sort_by: sortBy,
        order,
        limit: PAGE_SIZE,
        skip: page * PAGE_SIZE,
      }),
  });

  const risk = useQuery({
    queryKey: ["evidence", "risk", query],
    retry: false,
    queryFn: () =>
      api.runAnalysis({ ...query, limit: 5000, top_n: 500, persist: false, min_risk_score: 0.5 }),
  });

  const riskByEvent = useMemo(() => {
    const map = new Map<string, number>();
    for (const item of risk.data?.results ?? []) map.set(item.event_id, item.risk_score);
    return map;
  }, [risk.data]);

  const items = events.data?.items ?? [];
  const total = events.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const runSearch = () => {
    setPage(0);
    setApplied((n) => n + 1);
  };

  return (
    <div className="h-full flex min-h-0">
      <div className="flex-1 flex flex-col min-w-0 border-r border-outline-variant/50">
        {/* Search & filters — one row above the results, per the mockup. */}
        <div className="shrink-0 p-4 border-b border-outline-variant/30 bg-surface-container-lowest flex flex-wrap gap-3 items-end">
          <div className="relative flex-1 min-w-[220px] max-w-md">
            <Field label="Search device">
              <div className="relative">
                <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-[18px] pointer-events-none">
                  search
                </span>
                <input
                  className="field w-full pl-9"
                  placeholder="Comp431255 or DNS…"
                  value={device}
                  onChange={(e) => setDevice(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && runSearch()}
                />
              </div>
            </Field>
          </div>

          <Field label="Protocol">
            <select
              className="field w-[115px]"
              value={protocol}
              onChange={(e) => setProtocol(e.target.value)}
            >
              <option value="">All</option>
              <option value="6">TCP</option>
              <option value="17">UDP</option>
            </select>
          </Field>
          <Field label="Dest. port">
            <input
              className="field w-[100px]"
              placeholder="443"
              inputMode="numeric"
              value={dstPort}
              onChange={(e) => setDstPort(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
            />
          </Field>
          <Field label="Min bytes">
            <input
              className="field w-[120px]"
              placeholder="1000000"
              inputMode="numeric"
              value={minBytes}
              onChange={(e) => setMinBytes(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
            />
          </Field>
          <Field label="Sort by">
            <select
              className="field w-[130px]"
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value);
                setPage(0);
              }}
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>

          <button type="button" className="btn-primary" onClick={runSearch}>
            Search
          </button>

          <div className="flex bg-surface-container border border-outline-variant rounded-md overflow-hidden">
            <button
              type="button"
              title="Sort direction"
              aria-label="Toggle sort direction"
              onClick={() => setOrder(order === "desc" ? "asc" : "desc")}
              className="px-2.5 py-2 text-on-surface-variant hover:bg-surface-container-high border-r border-outline-variant/50"
            >
              <span className="material-symbols-outlined text-[18px]">
                {order === "desc" ? "arrow_downward" : "arrow_upward"}
              </span>
            </button>
            {(["list", "grid"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                aria-label={`${mode} view`}
                onClick={() => setView(mode)}
                className={clsx(
                  "px-2.5 py-2",
                  view === mode
                    ? "bg-surface-variant text-on-surface"
                    : "text-on-surface-variant hover:bg-surface-container-high"
                )}
              >
                <span className="material-symbols-outlined text-[18px]">
                  {mode === "grid" ? "grid_view" : "list"}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto">
          <QueryState
            isLoading={events.isLoading}
            error={events.error}
            isEmpty={!items.length}
            emptyTitle="No events match these filters"
            emptyDetail="Clear a filter or widen the byte threshold."
            loadingLabel="Loading evidence"
          >
            {view === "list" ? (
              <table className="w-full text-body-sm font-body-sm">
                <thead className="sticky top-0 bg-surface-container-lowest z-10">
                  <tr className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider border-b border-outline-variant/50">
                    <th className="text-left font-semibold px-4 py-2.5">Time (UTC)</th>
                    <th className="text-left font-semibold px-4 py-2.5">Source</th>
                    <th className="text-left font-semibold px-4 py-2.5">Destination</th>
                    <th className="text-left font-semibold px-4 py-2.5">Service</th>
                    <th className="text-right font-semibold px-4 py-2.5">Volume</th>
                    <th className="text-left font-semibold px-4 py-2.5">Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((event) => {
                    const score = riskByEvent.get(event.event_id);
                    return (
                      <tr
                        key={event.event_id}
                        onClick={() => setSelected(event)}
                        className={clsx(
                          "border-b border-outline-variant/20 cursor-pointer hover:bg-surface-container-high/50",
                          selected?.event_id === event.event_id && "bg-primary/5"
                        )}
                      >
                        <td className="px-4 py-2.5 font-mono-data text-on-surface-variant whitespace-nowrap">
                          {formatTimestamp(event.timestamp)}
                        </td>
                        <td className="px-4 py-2.5 font-mono-data text-on-surface">
                          {event.src_device}:{event.src_port}
                        </td>
                        <td className="px-4 py-2.5 font-mono-data text-on-surface-variant">
                          {event.dst_device}:{event.dst_port}
                        </td>
                        <td className="px-4 py-2.5">
                          <Chip>{event.dst_service ?? event.protocol_name}</Chip>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono-data text-on-surface-variant whitespace-nowrap">
                          {formatBytes(event.total_bytes)}
                        </td>
                        <td className="px-4 py-2.5">
                          {score != null ? (
                            <RiskBadge
                              classification={classifyScore(score)}
                              score={score}
                            />
                          ) : (
                            <span className="text-on-surface-variant/50">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 p-4">
                {items.map((event) => {
                  const score = riskByEvent.get(event.event_id);
                  return (
                    <button
                      key={event.event_id}
                      type="button"
                      onClick={() => setSelected(event)}
                      className={clsx(
                        "panel p-4 text-left transition-colors hover:bg-surface-container",
                        selected?.event_id === event.event_id && "border-primary/60"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <span className="material-symbols-outlined text-primary">
                          {event.protocol === 17 ? "wifi_tethering" : "swap_horiz"}
                        </span>
                        {score != null && (
                          <RiskBadge
                            classification={classifyScore(score)}
                            score={score}
                          />
                        )}
                      </div>
                      <p className="text-body-md font-mono-data text-on-surface m-0 truncate">
                        {event.src_device}
                      </p>
                      <p className="text-body-sm font-body-sm text-on-surface-variant m-0 truncate">
                        → {event.dst_device}:{event.dst_port}
                      </p>
                      <div className="flex flex-wrap gap-1.5 mt-3">
                        <Chip>{event.protocol_name}</Chip>
                        <Chip>{formatBytes(event.total_bytes)}</Chip>
                        <Chip>{formatDuration(event.duration)}</Chip>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </QueryState>
        </div>

        {/* Pagination */}
        <div className="shrink-0 flex items-center justify-between gap-4 px-4 py-2.5 border-t border-outline-variant/50 bg-surface-container-lowest">
          <span className="text-body-sm font-body-sm text-on-surface-variant">
            {formatNumber(total)} events · page {page + 1} of {formatNumber(pageCount)}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-ghost py-1"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn-ghost py-1"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Detail pane */}
      <aside className="w-[340px] shrink-0 flex flex-col bg-surface-container-lowest">
        <div className="px-4 py-3 border-b border-outline-variant/50">
          <h3 className="text-headline-sm font-headline-sm font-semibold m-0">
            Record Detail
          </h3>
        </div>
        {!selected ? (
          <EmptyState
            icon="draft"
            title="No record selected"
            detail="Select an event to see its full normalized record."
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
                <DetailRow label="Epoch" mono>
                  {selected.timestamp}
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
                <DetailRow label="Bytes sent">
                  {formatBytes(selected.src_bytes)}
                </DetailRow>
                <DetailRow label="Bytes received">
                  {formatBytes(selected.dst_bytes)}
                </DetailRow>
                <DetailRow label="Packets">
                  {formatNumber(selected.src_packets)} /{" "}
                  {formatNumber(selected.dst_packets)}
                </DetailRow>
                <DetailRow label="Byte ratio" mono>
                  {selected.byte_ratio.toFixed(4)}
                </DetailRow>
                <DetailRow label="Packet ratio" mono>
                  {selected.packet_ratio.toFixed(4)}
                </DetailRow>
                <DetailRow label="Throughput">
                  {formatBytes(selected.bytes_per_second)}/s
                </DetailRow>
                <DetailRow label="Origin">{selected.source}</DetailRow>
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
                Investigate Source
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
  );
}
