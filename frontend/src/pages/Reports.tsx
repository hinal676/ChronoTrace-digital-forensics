/**
 * Report generation (design sample 6): configuration on the left, a live
 * printable preview on the right.
 *
 * The preview is composed entirely from real case data. "Export PDF" uses the
 * browser's own print-to-PDF via a print stylesheet rather than bundling a PDF
 * library — fewer moving parts, and the output matches what is on screen.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { EmptyState, Field, QueryState } from "@/components/ui";
import { api } from "@/lib/api";
import {
  CLASSIFICATION_LABEL,
  formatBytes,
  formatIsoDateTime,
  formatNumber,
  formatTimestamp,
} from "@/lib/format";

const SECTIONS = [
  { id: "summary", label: "Executive Summary" },
  { id: "timeline", label: "Timeline of Events" },
  { id: "evidence", label: "Evidence Summary" },
  { id: "analysis", label: "Analysis Results" },
  { id: "conclusion", label: "Conclusion" },
] as const;

type SectionId = (typeof SECTIONS)[number]["id"];

export function Reports() {
  // The selected case lives in the query string (/reports?case=inv_...) so a
  // report can be linked to directly — including from the Case Manager.
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case") ?? "";
  const setCaseId = (id: string) => setParams(id ? { case: id } : {});
  const [enabled, setEnabled] = useState<Record<SectionId, boolean>>({
    summary: true,
    timeline: true,
    evidence: true,
    analysis: true,
    conclusion: true,
  });

  const investigations = useQuery({
    queryKey: ["investigations"],
    queryFn: () => api.listInvestigations({ limit: 100 }),
  });

  const report = useQuery({
    queryKey: ["investigation", caseId],
    enabled: !!caseId,
    queryFn: () => api.getInvestigation(caseId),
  });

  const cases = investigations.data?.items ?? [];
  const active = report.data;
  const findings = active?.findings;

  const generatedAt = useMemo(() => new Date().toISOString().slice(0, 19).replace("T", " "), []);

  return (
    <div className="h-full flex min-h-0">
      {/* Configuration */}
      <div className="w-[330px] shrink-0 flex flex-col border-r border-outline-variant/50 bg-surface-container-lowest p-4 gap-4 print:hidden">
        <h3 className="text-headline-sm font-headline-sm font-semibold m-0">
          Report Configuration
        </h3>

        <Field label="Target case">
          <select
            className="field w-full"
            value={caseId}
            onChange={(e) => setCaseId(e.target.value)}
          >
            <option value="">Select an investigation…</option>
            {cases.map((item) => (
              <option key={item.investigation_id} value={item.investigation_id}>
                {item.investigation_id} — {item.title ?? item.device}
              </option>
            ))}
          </select>
        </Field>

        <div>
          <p className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider mb-2">
            Include sections
          </p>
          <div className="panel p-3 space-y-2">
            {SECTIONS.map((section) => (
              <label
                key={section.id}
                className="flex items-center gap-3 cursor-pointer text-body-md font-body-md text-on-surface"
              >
                <input
                  type="checkbox"
                  className="w-4 h-4 rounded accent-primary"
                  checked={enabled[section.id]}
                  onChange={(e) =>
                    setEnabled((prev) => ({ ...prev, [section.id]: e.target.checked }))
                  }
                />
                {section.label}
              </label>
            ))}
          </div>
        </div>

        {cases.length === 0 && !investigations.isLoading && (
          <p className="text-body-sm font-body-sm text-on-surface-variant">
            No investigations exist yet. Open one in Case Manager first.
          </p>
        )}

        <button
          type="button"
          className="btn-primary w-full mt-auto"
          disabled={!active}
          onClick={() => window.print()}
        >
          <span className="material-symbols-outlined text-[16px]">print</span>
          Print / Export PDF
        </button>
      </div>

      {/* Preview */}
      <div className="flex-1 overflow-y-auto bg-surface-container-lowest p-container_padding">
        {!caseId ? (
          <EmptyState
            icon="description"
            title="No case selected"
            detail="Choose an investigation to preview its report."
          />
        ) : (
          <QueryState
            isLoading={report.isLoading}
            error={report.error}
            loadingLabel="Building report"
          >
            {active && findings && (
              <article
                className="mx-auto max-w-[820px] bg-white text-slate-900 rounded-xl shadow-2xl p-12 print:shadow-none print:rounded-none print:p-0 print:max-w-none"
                id="report"
              >
                <header className="flex justify-between items-start gap-8 border-b-2 border-slate-800 pb-4 mb-8">
                  <div>
                    <h1 className="text-[28px] leading-tight font-bold m-0 font-headline-lg text-slate-900">
                      Investigation Report
                    </h1>
                    <p className="m-0 mt-1 font-mono-data text-slate-600 text-[13px]">
                      {active.investigation_id}
                    </p>
                  </div>
                  <div className="text-right font-mono-data text-[11px] text-slate-600 leading-relaxed">
                    <p className="m-0">Generated: {generatedAt} UTC</p>
                    <p className="m-0">Investigator: {active.analyst ?? "—"}</p>
                    <p className="m-0">
                      Classification: {CLASSIFICATION_LABEL[active.classification]}
                    </p>
                  </div>
                </header>

                {enabled.summary && (
                  <Section number={1} title="Executive Summary">
                    <p>
                      This report covers network activity associated with device{" "}
                      <strong className="font-mono-data">{active.device}</strong>. A total
                      of{" "}
                      <strong>
                        {formatNumber(findings.risk_summary.analyzed_events)}
                      </strong>{" "}
                      events were analyzed, of which{" "}
                      <strong>{formatNumber(findings.risk_summary.flagged_events)}</strong>{" "}
                      reached the review threshold. The highest observed risk score was{" "}
                      <strong>{findings.risk_summary.max_risk_score.toFixed(3)}</strong>,
                      placing this case in the{" "}
                      <strong>{CLASSIFICATION_LABEL[active.classification]}</strong> band.
                    </p>
                    <h3 className="text-[14px] font-bold mt-4 mb-2">Key Findings</h3>
                    <ul className="list-disc pl-5 space-y-1 m-0">
                      {findings.observations.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  </Section>
                )}

                {enabled.timeline && (
                  <Section number={2} title="Timeline of Events">
                    <table className="w-full text-[12px] border-collapse">
                      <thead>
                        <tr className="border-b border-slate-300 text-left">
                          <th className="py-1.5 pr-3 font-semibold">Time (UTC)</th>
                          <th className="py-1.5 pr-3 font-semibold">Source</th>
                          <th className="py-1.5 pr-3 font-semibold">Destination</th>
                          <th className="py-1.5 pr-3 font-semibold">Service</th>
                          <th className="py-1.5 font-semibold text-right">Volume</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findings.notable_events.map((event) => (
                          <tr key={event.event_id} className="border-b border-slate-200">
                            <td className="py-1.5 pr-3 font-mono-data whitespace-nowrap">
                              {formatTimestamp(event.timestamp)}
                            </td>
                            <td className="py-1.5 pr-3 font-mono-data">
                              {event.src_device}
                            </td>
                            <td className="py-1.5 pr-3 font-mono-data">
                              {event.dst_device}:{event.dst_port}
                            </td>
                            <td className="py-1.5 pr-3">
                              {event.dst_service ?? event.protocol_name}
                            </td>
                            <td className="py-1.5 text-right font-mono-data whitespace-nowrap">
                              {formatBytes(event.total_bytes)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!findings.notable_events.length && (
                      <p className="text-slate-500 m-0">No events recorded.</p>
                    )}
                  </Section>
                )}

                {enabled.evidence && (
                  <Section number={3} title="Evidence Summary">
                    <table className="w-full text-[12px] border-collapse mb-4">
                      <tbody>
                        {[
                          ["Focus device", findings.device_summary.device],
                          [
                            "Total events",
                            formatNumber(findings.device_summary.total_events),
                          ],
                          [
                            "Outbound / inbound",
                            `${formatNumber(findings.device_summary.events_out)} / ${formatNumber(findings.device_summary.events_in)}`,
                          ],
                          ["Bytes sent", formatBytes(findings.device_summary.bytes_out)],
                          [
                            "Bytes received",
                            formatBytes(findings.device_summary.bytes_in),
                          ],
                          [
                            "Distinct destinations",
                            formatNumber(findings.device_summary.unique_destinations),
                          ],
                          [
                            "First seen",
                            formatTimestamp(findings.device_summary.first_seen),
                          ],
                          [
                            "Last seen",
                            formatTimestamp(findings.device_summary.last_seen),
                          ],
                        ].map(([label, value]) => (
                          <tr key={label} className="border-b border-slate-200">
                            <td className="py-1.5 pr-4 text-slate-600 w-[200px]">
                              {label}
                            </td>
                            <td className="py-1.5 font-mono-data">{value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    <h3 className="text-[14px] font-bold mb-2">Communication Partners</h3>
                    <table className="w-full text-[12px] border-collapse">
                      <thead>
                        <tr className="border-b border-slate-300 text-left">
                          <th className="py-1.5 pr-3 font-semibold">Device</th>
                          <th className="py-1.5 pr-3 font-semibold">Direction</th>
                          <th className="py-1.5 pr-3 font-semibold text-right">Events</th>
                          <th className="py-1.5 font-semibold text-right">Volume</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findings.related_devices.slice(0, 12).map((peer) => (
                          <tr key={peer.device} className="border-b border-slate-200">
                            <td className="py-1.5 pr-3 font-mono-data">{peer.device}</td>
                            <td className="py-1.5 pr-3">{peer.direction}</td>
                            <td className="py-1.5 pr-3 text-right font-mono-data">
                              {formatNumber(peer.event_count)}
                            </td>
                            <td className="py-1.5 text-right font-mono-data">
                              {formatBytes(peer.total_bytes)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Section>
                )}

                {enabled.analysis && (
                  <Section number={4} title="Analysis Results">
                    <p className="m-0 mb-3">
                      Events were scored by an unsupervised anomaly-detection model.
                      Scores are statistical indicators of unusual traffic — they are not
                      determinations of malicious activity.
                    </p>
                    <table className="w-full text-[12px] border-collapse">
                      <thead>
                        <tr className="border-b border-slate-300 text-left">
                          <th className="py-1.5 pr-3 font-semibold">Time (UTC)</th>
                          <th className="py-1.5 pr-3 font-semibold">Destination</th>
                          <th className="py-1.5 pr-3 font-semibold">Contributing factors</th>
                          <th className="py-1.5 font-semibold text-right">Score</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findings.risky_events.slice(0, 12).map((risk) => (
                          <tr key={risk.event_id} className="border-b border-slate-200">
                            <td className="py-1.5 pr-3 font-mono-data whitespace-nowrap">
                              {formatTimestamp(risk.timestamp)}
                            </td>
                            <td className="py-1.5 pr-3 font-mono-data">
                              {risk.dst_device}
                            </td>
                            <td className="py-1.5 pr-3">{risk.reasons.join("; ")}</td>
                            <td className="py-1.5 text-right font-mono-data">
                              {risk.risk_score.toFixed(3)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Section>
                )}

                {enabled.conclusion && (
                  <Section number={5} title="Conclusion">
                    <p className="m-0">
                      {findings.risk_summary.flagged_events > 0 ? (
                        <>
                          {formatNumber(findings.risk_summary.flagged_events)} event
                          {findings.risk_summary.flagged_events === 1 ? "" : "s"}{" "}
                          associated with{" "}
                          <strong className="font-mono-data">{active.device}</strong>{" "}
                          deviate from the learned baseline and warrant analyst review.
                          This case is currently marked <strong>{active.status}</strong>.
                        </>
                      ) : (
                        <>
                          No events associated with{" "}
                          <strong className="font-mono-data">{active.device}</strong>{" "}
                          reached the review threshold. No further action is indicated by
                          the current model.
                        </>
                      )}
                    </p>
                    <p className="mt-4 mb-0 text-[11px] text-slate-500 border-t border-slate-300 pt-3">
                      Generated by ChronoTrace on {generatedAt} UTC. Risk scores are
                      statistical indicators produced by an unsupervised model and do not
                      constitute proof of malicious activity. Case opened{" "}
                      {formatIsoDateTime(active.created_at)}.
                    </p>
                  </Section>
                )}
              </article>
            )}
          </QueryState>
        )}
      </div>
    </div>
  );
}

function Section({
  number,
  title,
  children,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-8 break-inside-avoid">
      <h2 className="text-[16px] font-bold uppercase tracking-wide border-b border-slate-300 pb-1.5 mb-3 m-0 font-headline-sm">
        {number}. {title}
      </h2>
      <div className="text-[13px] leading-relaxed">{children}</div>
    </section>
  );
}
