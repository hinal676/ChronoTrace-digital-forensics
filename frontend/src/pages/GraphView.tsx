/**
 * Graph View (design sample 3).
 *
 * The mockup's "Traversal Algorithms" panel is wired to the four real backend
 * algorithms — BFS, DFS, Dijkstra and A* — and the results (path, cost, nodes
 * explored) are rendered from the actual response, including A*'s expansion count
 * so the heuristic's benefit over Dijkstra is visible.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams, useNavigate } from "react-router-dom";
import clsx from "clsx";

import { NetworkGraph } from "@/components/NetworkGraph";
import {
  Chip,
  DetailRow,
  EmptyState,
  ErrorState,
  Field,
  QueryState,
  RiskBadge,
  Spinner,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { formatBytes, formatNumber, formatTimestamp } from "@/lib/format";
import type {
  Algorithm,
  Direction,
  PathResponse,
  TraversalResponse,
  WeightStrategy,
} from "@/types";

const ALGORITHMS: { value: Algorithm; label: string; needsTarget: boolean }[] = [
  { value: "bfs", label: "Breadth-First Search (BFS)", needsTarget: false },
  { value: "dfs", label: "Depth-First Search (DFS)", needsTarget: false },
  { value: "dijkstra", label: "Dijkstra (lowest cost)", needsTarget: true },
  { value: "astar", label: "A* (heuristic search)", needsTarget: true },
];

const WEIGHTS: WeightStrategy[] = ["strength", "hops", "frequency", "bytes", "duration"];

type TraversalResult =
  | { kind: "traversal"; data: TraversalResponse }
  | { kind: "path"; data: PathResponse };

export function GraphView() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  const devices = useQuery({
    queryKey: ["devices", "all"],
    queryFn: () => api.listDevices(500),
  });

  const focus = params.get("device") ?? devices.data?.items[0]?.device ?? "";
  const [depth, setDepth] = useState(1);
  const [direction, setDirection] = useState<Direction>("both");
  const [selected, setSelected] = useState<string | null>(null);
  // This dataset is dense (27% graph density), so the full induced subgraph of a
  // 1-hop neighbourhood is a hairball of peer-to-peer edges that say nothing
  // about the focus device. Default to showing only its own links.
  const [directOnly, setDirectOnly] = useState(true);

  const [algorithm, setAlgorithm] = useState<Algorithm>("bfs");
  const [target, setTarget] = useState("");
  const [weight, setWeight] = useState<WeightStrategy>("strength");
  const [result, setResult] = useState<TraversalResult | null>(null);

  // Default the focus device once the device list arrives.
  useEffect(() => {
    if (!params.get("device") && devices.data?.items[0]) {
      setParams({ device: devices.data.items[0].device }, { replace: true });
    }
  }, [devices.data, params, setParams]);

  useEffect(() => {
    setSelected(focus || null);
    setResult(null);
  }, [focus]);

  const neighborhood = useQuery({
    queryKey: ["neighborhood", focus, depth, direction],
    enabled: !!focus,
    queryFn: () => api.neighborhood(focus, depth, direction, 300),
  });

  const detail = useQuery({
    queryKey: ["relationships", selected],
    enabled: !!selected,
    queryFn: () => api.getRelationships(selected!, 12, 5),
  });

  const deviceRisk = useQuery({
    queryKey: ["deviceRisk", selected],
    enabled: !!selected,
    retry: false,
    queryFn: () => api.deviceRisk(selected!),
  });

  const traversal = useMutation({
    mutationFn: async (): Promise<TraversalResult> => {
      const body = { source: focus, direction, max_depth: Math.max(depth, 3) };
      switch (algorithm) {
        case "bfs":
          return {
            kind: "traversal",
            data: await api.bfs({ ...body, target: target || null }),
          };
        case "dfs":
          return {
            kind: "traversal",
            data: await api.dfs({ ...body, target: target || null }),
          };
        case "dijkstra":
          return {
            kind: "path",
            data: await api.dijkstra({ source: focus, target, weight, direction, k: 3 }),
          };
        case "astar":
          return {
            kind: "path",
            data: await api.astar({ source: focus, target, weight, direction }),
          };
      }
    },
    onSuccess: setResult,
  });

  const activeAlgorithm = ALGORITHMS.find((a) => a.value === algorithm)!;
  const canRun = !!focus && (!activeAlgorithm.needsTarget || !!target);

  const highlightPath = useMemo(() => {
    if (!result) return [];
    if (result.kind === "path") return result.data.found ? result.data.path : [];
    return result.data.paths_to_target[0] ?? [];
  }, [result]);

  const deviceOptions = devices.data?.items ?? [];

  const visibleEdges = useMemo(() => {
    const all = neighborhood.data?.edges ?? [];
    if (!directOnly) return all;
    return all.filter((edge) => edge.source === focus || edge.target === focus);
  }, [neighborhood.data, directOnly, focus]);

  return (
    <div className="h-full flex min-h-0">
      {/* Canvas */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="shrink-0 flex flex-wrap items-end gap-4 px-container_padding py-3 border-b border-outline-variant bg-surface-container-lowest">
          <Field label="Focus device">
            <select
              className="field w-[190px]"
              value={focus}
              onChange={(e) => setParams({ device: e.target.value })}
            >
              {deviceOptions.map((d) => (
                <option key={d.device} value={d.device}>
                  {d.device}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Depth">
            <select
              className="field w-[110px]"
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            >
              {[1, 2, 3].map((d) => (
                <option key={d} value={d}>
                  {d} {d === 1 ? "degree" : "degrees"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Direction">
            <select
              className="field w-[130px]"
              value={direction}
              onChange={(e) => setDirection(e.target.value as Direction)}
            >
              <option value="both">Both</option>
              <option value="outbound">Outbound</option>
              <option value="inbound">Inbound</option>
            </select>
          </Field>
          <label className="flex items-center gap-2 cursor-pointer pb-1.5">
            <input
              type="checkbox"
              className="w-4 h-4 rounded accent-primary"
              checked={directOnly}
              onChange={(e) => setDirectOnly(e.target.checked)}
            />
            <span className="text-body-sm font-body-sm text-on-surface-variant">
              Direct links only
            </span>
          </label>
          {neighborhood.data && (
            <span className="ml-auto text-body-sm font-body-sm text-on-surface-variant">
              Showing {formatNumber(neighborhood.data.nodes.length)} devices ·{" "}
              {formatNumber(visibleEdges.length)} of{" "}
              {formatNumber(neighborhood.data.edges.length)} relationships
            </span>
          )}
        </div>

        <div className="flex-1 min-h-0">
          <QueryState
            isLoading={neighborhood.isLoading || devices.isLoading}
            error={neighborhood.error ?? devices.error}
            isEmpty={!neighborhood.data?.nodes.length}
            emptyTitle="No relationships for this device"
            loadingLabel="Building graph"
          >
            <NetworkGraph
              nodes={neighborhood.data?.nodes ?? []}
              edges={visibleEdges}
              focusDevice={focus}
              selected={selected}
              onSelect={setSelected}
              highlightPath={highlightPath}
            />
          </QueryState>
        </div>
      </div>

      {/* Right rail */}
      <aside className="w-[380px] shrink-0 flex flex-col bg-surface-container-lowest border-l border-outline-variant overflow-y-auto">
        <div className="px-4 py-3 border-b border-outline-variant/50 flex items-center gap-2">
          <span className="material-symbols-outlined text-[18px] text-primary">info</span>
          <h3 className="text-headline-sm font-headline-sm font-semibold m-0">
            Node Details
          </h3>
        </div>

        {!selected ? (
          <EmptyState icon="ads_click" title="Select a device" />
        ) : (
          <div className="p-4 space-y-4 border-b border-outline-variant/50">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary/15 border border-primary/40 flex items-center justify-center shrink-0">
                <span className="material-symbols-outlined text-primary">computer</span>
              </div>
              <div className="min-w-0">
                <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0">
                  Device
                </p>
                <p className="text-body-lg font-mono-data text-on-surface m-0 truncate">
                  {selected}
                </p>
              </div>
            </div>

            {detail.isLoading ? (
              <Spinner label="Loading device" />
            ) : detail.error ? (
              <ErrorState error={detail.error} />
            ) : (
              detail.data && (
                <>
                  <div className="divide-y divide-outline-variant/20">
                    <DetailRow label="Total events">
                      {formatNumber(detail.data.summary.total_events)}
                    </DetailRow>
                    <DetailRow label="Outbound / inbound">
                      {formatNumber(detail.data.summary.events_out)} /{" "}
                      {formatNumber(detail.data.summary.events_in)}
                    </DetailRow>
                    <DetailRow label="Bytes sent">
                      {formatBytes(detail.data.summary.bytes_out)}
                    </DetailRow>
                    <DetailRow label="Bytes received">
                      {formatBytes(detail.data.summary.bytes_in)}
                    </DetailRow>
                    <DetailRow label="Distinct peers">
                      {formatNumber(
                        detail.data.summary.unique_destinations +
                          detail.data.summary.unique_sources
                      )}
                    </DetailRow>
                    <DetailRow label="First seen" mono>
                      {formatTimestamp(detail.data.summary.first_seen)}
                    </DetailRow>
                  </div>

                  {deviceRisk.data && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-body-sm font-body-sm text-on-surface-variant">
                        Peak risk
                      </span>
                      <RiskBadge
                        classification={deviceRisk.data.classification}
                        score={deviceRisk.data.max_risk_score}
                      />
                    </div>
                  )}

                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="btn-primary flex-1"
                      onClick={() =>
                        navigate(`/cases?device=${encodeURIComponent(selected)}`)
                      }
                    >
                      Investigate
                    </button>
                    <button
                      type="button"
                      className="btn-ghost flex-1"
                      onClick={() => setParams({ device: selected })}
                    >
                      Focus here
                    </button>
                  </div>

                  <div>
                    <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
                      Top peers
                    </p>
                    <ul className="space-y-1 m-0 p-0 list-none">
                      {detail.data.related.slice(0, 6).map((peer) => (
                        <li key={peer.device}>
                          <button
                            type="button"
                            onClick={() => setSelected(peer.device)}
                            className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-lg hover:bg-surface-container-high text-left"
                          >
                            <span className="font-mono-data text-body-sm text-on-surface truncate">
                              {peer.device}
                            </span>
                            <span className="flex items-center gap-2 shrink-0">
                              <Chip>{peer.direction}</Chip>
                              <span className="text-body-sm font-body-sm text-on-surface-variant">
                                {formatBytes(peer.total_bytes)}
                              </span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                </>
              )
            )}
          </div>
        )}

        {/* Traversal algorithms — the mockup's panel, wired to the real API. */}
        <div className="p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-on-surface-variant">
              route
            </span>
            <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0">
              Traversal Algorithms
            </p>
          </div>

          <select
            className="field w-full"
            value={algorithm}
            onChange={(e) => {
              setAlgorithm(e.target.value as Algorithm);
              setResult(null);
            }}
          >
            {ALGORITHMS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>

          <input
            className="field w-full font-mono-data"
            list="device-list"
            placeholder={
              activeAlgorithm.needsTarget ? "Target device (required)…" : "Target device (optional)…"
            }
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          />
          <datalist id="device-list">
            {deviceOptions.map((d) => (
              <option key={d.device} value={d.device} />
            ))}
          </datalist>

          {activeAlgorithm.needsTarget && (
            <Field label="Edge weight">
              <select
                className="field w-full"
                value={weight}
                onChange={(e) => setWeight(e.target.value as WeightStrategy)}
              >
                {WEIGHTS.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <button
            type="button"
            className="btn-primary w-full"
            disabled={!canRun || traversal.isPending}
            onClick={() => traversal.mutate()}
          >
            <span className="material-symbols-outlined text-[16px]">play_arrow</span>
            {traversal.isPending ? "Running…" : "Execute Traversal"}
          </button>

          {traversal.isError && (
            <p className="text-body-sm font-body-sm text-red-300 m-0">
              {traversal.error instanceof ApiError
                ? traversal.error.message
                : String(traversal.error)}
            </p>
          )}

          {result && <TraversalResult result={result} />}
        </div>
      </aside>
    </div>
  );
}

function TraversalResult({ result }: { result: TraversalResult }) {
  if (result.kind === "path") {
    const path = result.data;
    return (
      <div className="rounded-xl border border-outline-variant/50 bg-surface-container p-3 space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider">
            Algorithm Results
          </span>
          <span
            className={clsx(
              "text-body-sm font-body-sm",
              path.found ? "text-emerald-300" : "text-amber-300"
            )}
          >
            {path.found ? "Path found" : "No path"}
          </span>
        </div>

        {path.found ? (
          <>
            <div>
              <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0 mb-1">
                Path Summary
              </p>
              <p className="text-body-sm font-mono-data text-on-surface m-0 break-all leading-relaxed">
                {path.path.join("  →  ")}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                { label: "Hops", value: formatNumber(path.hops ?? 0) },
                { label: "Cost", value: (path.cost ?? 0).toFixed(4) },
                {
                  label: "Explored",
                  value: path.nodes_explored != null ? formatNumber(path.nodes_explored) : "—",
                },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-lg bg-surface-container-high py-2 px-1"
                >
                  <p className="text-[10px] uppercase tracking-wider text-on-surface-variant m-0">
                    {stat.label}
                  </p>
                  <p className="text-body-md font-mono-data text-on-surface m-0">
                    {stat.value}
                  </p>
                </div>
              ))}
            </div>
            {path.alternative_paths.length > 0 && (
              <div>
                <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0 mb-1">
                  Alternative routes
                </p>
                <ul className="space-y-1 m-0 p-0 list-none">
                  {path.alternative_paths.map((alt) => (
                    <li
                      key={alt.path.join(">")}
                      className="text-body-sm font-mono-data text-on-surface-variant break-all"
                    >
                      {alt.path.join(" → ")}{" "}
                      <span className="opacity-60">({alt.cost.toFixed(4)})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="text-body-sm font-body-sm text-on-surface-variant m-0">
            No directed route exists under the <strong>{path.weight_strategy}</strong>{" "}
            weighting. Five servers in this dataset only receive traffic, so paths out
            of them do not exist.
          </p>
        )}
      </div>
    );
  }

  const traversal = result.data;
  const levels = Object.entries(traversal.levels).sort(
    (a, b) => Number(a[0]) - Number(b[0])
  );

  return (
    <div className="rounded-xl border border-outline-variant/50 bg-surface-container p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider">
          Algorithm Results
        </span>
        <span className="text-body-sm font-body-sm text-emerald-300">
          {traversal.algorithm.toUpperCase()} complete
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: "Nodes", value: formatNumber(traversal.node_count) },
          { label: "Depth", value: String(traversal.max_depth) },
          { label: "Levels", value: String(levels.length) },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg bg-surface-container-high py-2">
            <p className="text-[10px] uppercase tracking-wider text-on-surface-variant m-0">
              {stat.label}
            </p>
            <p className="text-body-md font-mono-data text-on-surface m-0">{stat.value}</p>
          </div>
        ))}
      </div>

      {traversal.truncated && (
        <p className="text-body-sm font-body-sm text-amber-300 m-0">
          Result truncated by the depth or node limit — more devices exist beyond it.
        </p>
      )}

      {traversal.paths_to_target[0] && (
        <div>
          <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0 mb-1">
            Path to target
          </p>
          <p className="text-body-sm font-mono-data text-on-surface m-0 break-all">
            {traversal.paths_to_target[0].join("  →  ")}
          </p>
        </div>
      )}

      <div>
        <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider m-0 mb-1">
          Devices by hop distance
        </p>
        <ul className="space-y-1 m-0 p-0 list-none">
          {levels.map(([level, members]) => (
            <li key={level} className="flex gap-2 items-baseline">
              <span className="text-body-sm font-mono-data text-primary shrink-0">
                {level}
              </span>
              <span className="text-body-sm font-body-sm text-on-surface-variant">
                {members.length} device{members.length === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
