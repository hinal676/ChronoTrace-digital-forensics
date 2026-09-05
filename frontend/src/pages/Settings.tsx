/**
 * Settings: backend connection, model status and graph cache controls.
 *
 * This page is where a broken deployment is diagnosed, so it shows raw state
 * (URLs, versions, error strings) rather than a friendly summary.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Chip, DetailRow, Panel, QueryState } from "@/components/ui";
import { api } from "@/lib/api";
import { formatIsoDateTime, formatNumber } from "@/lib/format";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export function Settings() {
  const queryClient = useQueryClient();

  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: false,
    refetchInterval: 15_000,
  });
  const model = useQuery({ queryKey: ["model"], queryFn: api.modelInfo, retry: false });
  const graph = useQuery({ queryKey: ["graph", "stats"], queryFn: () => api.graphStats() });

  const rebuild = useMutation({
    mutationFn: api.rebuildGraph,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["graph"] }),
  });

  const reload = useMutation({
    mutationFn: api.reloadModel,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["model"] }),
  });

  return (
    <div className="h-full overflow-y-auto p-container_padding">
      <div className="max-w-4xl space-y-gutter">
        <Panel title="Backend Connection" subtitle="Where this UI sends its requests">
          <div className="divide-y divide-outline-variant/20">
            <DetailRow label="API base URL" mono>
              {API_BASE}
            </DetailRow>
            <DetailRow label="Status">
              {health.isLoading ? (
                "checking…"
              ) : health.isError ? (
                <span className="text-red-300">unreachable</span>
              ) : (
                <span className="text-emerald-300">{health.data?.status}</span>
              )}
            </DetailRow>
            <DetailRow label="Database">
              {health.data?.database.connected ? (
                <span className="text-emerald-300">
                  connected · {health.data.database.database}
                </span>
              ) : (
                <span className="text-red-300">
                  {health.data?.database.error ?? "not connected"}
                </span>
              )}
            </DetailRow>
          </div>
          {health.isError && (
            <p className="text-body-sm font-body-sm text-on-surface-variant mt-3 mb-0">
              Start the API from <code className="font-mono-data">backend/</code>:{" "}
              <code className="font-mono-data text-primary">
                uvicorn app.main:app --reload
              </code>
            </p>
          )}
        </Panel>

        <Panel
          title="Detection Model"
          subtitle="Unsupervised anomaly detection"
          actions={
            <button
              type="button"
              className="btn-ghost py-1"
              disabled={reload.isPending || !model.data?.trained}
              onClick={() => reload.mutate()}
            >
              {reload.isPending ? "Reloading…" : "Reload from disk"}
            </button>
          }
        >
          <QueryState isLoading={model.isLoading} error={model.error}>
            {model.data?.trained ? (
              <>
                <div className="divide-y divide-outline-variant/20">
                  <DetailRow label="Type">{model.data.model_type}</DetailRow>
                  <DetailRow label="Version" mono>
                    {model.data.model_version}
                  </DetailRow>
                  <DetailRow label="Trained at" mono>
                    {formatIsoDateTime(model.data.trained_at)}
                  </DetailRow>
                  <DetailRow label="Training events">
                    {formatNumber(model.data.training_events ?? 0)}
                  </DetailRow>
                  <DetailRow label="Features">
                    {model.data.features.length}
                  </DetailRow>
                </div>

                <div className="mt-4">
                  <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
                    Risk thresholds
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(model.data.thresholds).map(([band, value]) => (
                      <Chip key={band}>
                        {band.replace(/_/g, " ")} ≥ {value}
                      </Chip>
                    ))}
                  </div>
                </div>

                <details className="mt-4">
                  <summary className="text-body-sm font-body-sm text-on-surface-variant cursor-pointer hover:text-on-surface">
                    Show {model.data.features.length} model features
                  </summary>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {model.data.features.map((feature) => (
                      <Chip key={feature} className="font-mono-data">
                        {feature}
                      </Chip>
                    ))}
                  </div>
                </details>
              </>
            ) : (
              <p className="text-body-sm font-body-sm text-on-surface-variant m-0">
                No model is trained. Run{" "}
                <code className="font-mono-data text-primary">python -m app.ml.train</code>{" "}
                in <code className="font-mono-data">backend/</code>, then reload.
              </p>
            )}
          </QueryState>
        </Panel>

        <Panel
          title="Relationship Graph"
          subtitle="Cached in the API process and rebuilt on ingestion"
          actions={
            <button
              type="button"
              className="btn-ghost py-1"
              disabled={rebuild.isPending}
              onClick={() => rebuild.mutate()}
            >
              {rebuild.isPending ? "Rebuilding…" : "Rebuild now"}
            </button>
          }
        >
          <QueryState isLoading={graph.isLoading} error={graph.error}>
            {graph.data && (
              <div className="divide-y divide-outline-variant/20">
                <DetailRow label="Devices (nodes)">
                  {formatNumber(graph.data.node_count)}
                </DetailRow>
                <DetailRow label="Relationships (edges)">
                  {formatNumber(graph.data.edge_count)}
                </DetailRow>
                <DetailRow label="Events folded in">
                  {formatNumber(graph.data.event_count)}
                </DetailRow>
                <DetailRow label="Density">
                  {(graph.data.density * 100).toFixed(2)}%
                </DetailRow>
                <DetailRow label="Weakly connected">
                  {graph.data.is_weakly_connected ? "yes" : "no"} ·{" "}
                  {graph.data.weakly_connected_components} component(s)
                </DetailRow>
                <DetailRow label="Strongly connected components">
                  {formatNumber(graph.data.strongly_connected_components)}
                </DetailRow>
              </div>
            )}
          </QueryState>
        </Panel>

        <Panel title="About">
          <p className="text-body-sm font-body-sm text-on-surface-variant m-0 leading-relaxed">
            ChronoTrace analyses authorized network activity logs. Risk scores are
            produced by an unsupervised anomaly-detection model and indicate that traffic
            is <em>statistically unusual</em> relative to a learned baseline — not that it
            is malicious. Every flagged event requires analyst review.
          </p>
        </Panel>
      </div>
    </div>
  );
}
