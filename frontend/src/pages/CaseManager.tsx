/**
 * Case Manager (design sample 5) — investigations backed by POST /investigations.
 *
 * Creating a case runs the backend's full pipeline for one device: stored
 * activity, BFS neighbourhood, and ML risk scoring, returned as one case file.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import clsx from "clsx";

import {
  Chip,
  DetailRow,
  EmptyState,
  ErrorState,
  Field,
  Panel,
  QueryState,
  RiskBadge,
  Spinner,
} from "@/components/ui";
import { RankedBars } from "@/components/Charts";
import { api } from "@/lib/api";
import {
  formatBytes,
  formatIsoDateTime,
  formatNumber,
  formatTimestamp,
} from "@/lib/format";

const STATUSES = ["open", "in_review", "closed"];

export function CaseManager() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  // The open case lives in the URL (/cases/:investigationId) so a case file can
  // be linked to and survives a refresh.
  const { investigationId } = useParams();
  const selectedId = investigationId ?? null;
  const selectCase = (id: string | null) =>
    navigate(id ? `/cases/${id}` : "/cases", { replace: false });

  const [device, setDevice] = useState(params.get("device") ?? "");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [depth, setDepth] = useState(2);

  useEffect(() => {
    const fromUrl = params.get("device");
    if (fromUrl) setDevice(fromUrl);
  }, [params]);

  const devices = useQuery({
    queryKey: ["devices", "all"],
    queryFn: () => api.listDevices(500),
  });

  const investigations = useQuery({
    queryKey: ["investigations"],
    queryFn: () => api.listInvestigations({ limit: 100 }),
  });

  const detail = useQuery({
    queryKey: ["investigation", selectedId],
    enabled: !!selectedId,
    queryFn: () => api.getInvestigation(selectedId!),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createInvestigation({
        device: device.trim(),
        title: title.trim() || null,
        notes: notes.trim() || null,
        analyst: "Investigator",
        depth,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
      selectCase(created.investigation_id);
      setTitle("");
      setNotes("");
      setParams({});
    },
  });

  const update = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: { status?: string; notes?: string } }) =>
      api.updateInvestigation(id, changes),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
      queryClient.setQueryData(["investigation", updated.investigation_id], updated);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteInvestigation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["investigations"] });
      selectCase(null);
    },
  });

  const cases = investigations.data?.items ?? [];
  const active = detail.data;

  return (
    <div className="h-full flex min-h-0">
      {/* Case list + new case */}
      <div className="w-[340px] shrink-0 flex flex-col border-r border-outline-variant/50 bg-surface-container-lowest">
        <div className="p-4 border-b border-outline-variant/50 space-y-3">
          <h3 className="text-headline-sm font-headline-sm font-semibold m-0">
            New Investigation
          </h3>
          <Field label="Focus device">
            <input
              className="field w-full font-mono-data"
              list="case-device-list"
              placeholder="Comp431255"
              value={device}
              onChange={(e) => setDevice(e.target.value)}
            />
          </Field>
          <datalist id="case-device-list">
            {(devices.data?.items ?? []).map((d) => (
              <option key={d.device} value={d.device} />
            ))}
          </datalist>
          <Field label="Title (optional)">
            <input
              className="field w-full"
              placeholder="Suspected outbound transfer"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </Field>
          <Field label="Notes (optional)">
            <textarea
              className="field w-full resize-none"
              rows={2}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Field>
          <Field label="Neighbourhood depth">
            <select
              className="field w-full"
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
            >
              {[1, 2, 3].map((d) => (
                <option key={d} value={d}>
                  {d} hop{d === 1 ? "" : "s"}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            className="btn-primary w-full"
            disabled={!device.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            {create.isPending ? "Building case file…" : "Open Investigation"}
          </button>
          {create.isError && (
            <p className="text-body-sm font-body-sm text-red-300 m-0">
              {(create.error as Error).message}
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto">
          <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider px-4 pt-4 pb-2 m-0">
            Cases ({formatNumber(investigations.data?.total ?? 0)})
          </p>
          <QueryState
            isLoading={investigations.isLoading}
            error={investigations.error}
            isEmpty={!cases.length}
            emptyTitle="No investigations yet"
            emptyDetail="Open one for a device to build its case file."
          >
            <ul className="m-0 p-0 px-2 pb-4 list-none space-y-1">
              {cases.map((item) => (
                <li key={item.investigation_id}>
                  <button
                    type="button"
                    onClick={() => selectCase(item.investigation_id)}
                    className={clsx(
                      "w-full text-left px-3 py-2.5 rounded-lg border transition-colors",
                      selectedId === item.investigation_id
                        ? "border-primary/60 bg-primary/5"
                        : "border-transparent hover:bg-surface-container-high"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-body-sm font-body-sm font-semibold text-on-surface truncate">
                        {item.title ?? item.device}
                      </span>
                      <Chip>{item.status}</Chip>
                    </div>
                    <p className="text-body-sm font-mono-data text-on-surface-variant m-0 truncate">
                      {item.device}
                    </p>
                    <div className="flex items-center justify-between gap-2 mt-1.5">
                      <RiskBadge
                        classification={item.classification}
                        score={item.overall_risk_score}
                      />
                      <span className="text-[10px] font-mono-data text-on-surface-variant/60">
                        {formatIsoDateTime(item.created_at).slice(0, 10)}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </QueryState>
        </div>
      </div>

      {/* Case detail */}
      <div className="flex-1 overflow-y-auto min-w-0">
        {!selectedId ? (
          <EmptyState
            icon="folder_open"
            title="No case selected"
            detail="Pick a case from the list, or open a new investigation on a device."
          />
        ) : detail.isLoading ? (
          <Spinner label="Loading case file" />
        ) : detail.error ? (
          <ErrorState error={detail.error} />
        ) : active ? (
          <div className="p-container_padding space-y-gutter">
            {/* Case header */}
            <div className="panel p-5">
              <div className="flex items-start justify-between gap-4 flex-wrap">
                <div className="min-w-0">
                  <h2 className="text-headline-md font-headline-md font-bold text-on-surface m-0">
                    {active.title ?? `Investigation of ${active.device}`}
                  </h2>
                  <p className="text-body-sm font-body-sm text-on-surface-variant m-0 mt-1">
                    <span className="font-mono-data">{active.investigation_id}</span> ·
                    opened {formatIsoDateTime(active.created_at)} by{" "}
                    {active.analyst ?? "unknown"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <RiskBadge
                    classification={active.classification}
                    score={active.overall_risk_score}
                  />
                  <select
                    className="field"
                    value={active.status}
                    onChange={(e) =>
                      update.mutate({
                        id: active.investigation_id,
                        changes: { status: e.target.value },
                      })
                    }
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() =>
                      navigate(`/reports?case=${active.investigation_id}`)
                    }
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      description
                    </span>
                    Report
                  </button>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete investigation ${active.investigation_id}? This cannot be undone.`
                        )
                      ) {
                        remove.mutate(active.investigation_id);
                      }
                    }}
                  >
                    <span className="material-symbols-outlined text-[16px]">delete</span>
                    Delete
                  </button>
                </div>
              </div>
              {active.notes && (
                <p className="text-body-sm font-body-sm text-on-surface-variant mt-3 mb-0 border-l-2 border-outline-variant pl-3">
                  {active.notes}
                </p>
              )}
            </div>

            {active.findings && (
              <>
                {/* Observations — the backend's plain-language findings */}
                <Panel title="Observations" subtitle="Generated from the case data">
                  <ul className="space-y-2 m-0 p-0 list-none">
                    {active.findings.observations.map((note) => (
                      <li
                        key={note}
                        className="flex gap-2 text-body-md font-body-md text-on-surface-variant"
                      >
                        <span className="material-symbols-outlined text-[16px] text-primary mt-0.5 shrink-0">
                          chevron_right
                        </span>
                        {note}
                      </li>
                    ))}
                  </ul>
                </Panel>

                <div className="grid grid-cols-1 xl:grid-cols-2 gap-gutter">
                  <Panel title="Device Summary">
                    <div className="divide-y divide-outline-variant/20">
                      <DetailRow label="Device" mono>
                        {active.findings.device_summary.device}
                      </DetailRow>
                      <DetailRow label="Total events">
                        {formatNumber(active.findings.device_summary.total_events)}
                      </DetailRow>
                      <DetailRow label="Outbound / inbound">
                        {formatNumber(active.findings.device_summary.events_out)} /{" "}
                        {formatNumber(active.findings.device_summary.events_in)}
                      </DetailRow>
                      <DetailRow label="Bytes sent">
                        {formatBytes(active.findings.device_summary.bytes_out)}
                      </DetailRow>
                      <DetailRow label="Bytes received">
                        {formatBytes(active.findings.device_summary.bytes_in)}
                      </DetailRow>
                      <DetailRow label="Distinct destinations">
                        {formatNumber(
                          active.findings.device_summary.unique_destinations
                        )}
                      </DetailRow>
                      <DetailRow label="First seen" mono>
                        {formatTimestamp(active.findings.device_summary.first_seen)}
                      </DetailRow>
                      <DetailRow label="Last seen" mono>
                        {formatTimestamp(active.findings.device_summary.last_seen)}
                      </DetailRow>
                    </div>
                  </Panel>

                  <Panel
                    title="Related Devices"
                    subtitle={`${active.findings.related_devices.length} communication partners`}
                  >
                    <RankedBars
                      data={active.findings.related_devices.slice(0, 8).map((peer) => ({
                        label: `${peer.device} (${peer.direction})`,
                        value: peer.total_bytes,
                      }))}
                      valueFormat={formatBytes}
                    />
                  </Panel>
                </div>

                <Panel
                  title="Risk Summary"
                  subtitle={`${formatNumber(active.findings.risk_summary.flagged_events)} of ${formatNumber(active.findings.risk_summary.analyzed_events)} events reached the review threshold`}
                >
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                    {[
                      {
                        label: "Analyzed",
                        value: formatNumber(active.findings.risk_summary.analyzed_events),
                      },
                      {
                        label: "Flagged",
                        value: formatNumber(active.findings.risk_summary.flagged_events),
                      },
                      {
                        label: "Mean risk",
                        value: active.findings.risk_summary.mean_risk_score.toFixed(3),
                      },
                      {
                        label: "Peak risk",
                        value: active.findings.risk_summary.max_risk_score.toFixed(3),
                      },
                    ].map((stat) => (
                      <div
                        key={stat.label}
                        className="rounded-lg bg-surface-container-high px-3 py-2"
                      >
                        <p className="text-[10px] uppercase tracking-wider text-on-surface-variant m-0">
                          {stat.label}
                        </p>
                        <p className="text-headline-sm font-mono-data text-on-surface m-0">
                          {stat.value}
                        </p>
                      </div>
                    ))}
                  </div>

                  {active.findings.risk_summary.top_reasons.length > 0 && (
                    <div className="mb-4">
                      <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
                        Most common factors
                      </p>
                      <RankedBars
                        data={active.findings.risk_summary.top_reasons.map((r) => ({
                          label: r.reason,
                          value: r.count,
                        }))}
                      />
                    </div>
                  )}

                  <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
                    Highest-risk events
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-body-sm font-body-sm">
                      <thead>
                        <tr className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider border-b border-outline-variant/50">
                          <th className="text-left font-semibold py-2">Time</th>
                          <th className="text-left font-semibold py-2">Destination</th>
                          <th className="text-left font-semibold py-2">Top factor</th>
                          <th className="text-left font-semibold py-2">Risk</th>
                        </tr>
                      </thead>
                      <tbody>
                        {active.findings.risky_events.slice(0, 10).map((risk) => (
                          <tr
                            key={risk.event_id}
                            className="border-b border-outline-variant/20 last:border-0"
                          >
                            <td className="py-2 font-mono-data text-on-surface-variant whitespace-nowrap">
                              {formatTimestamp(risk.timestamp)}
                            </td>
                            <td className="py-2 font-mono-data text-on-surface">
                              {risk.dst_device}
                            </td>
                            <td className="py-2 text-on-surface-variant max-w-[280px] truncate">
                              {risk.reasons[0]}
                            </td>
                            <td className="py-2">
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
                </Panel>
              </>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
