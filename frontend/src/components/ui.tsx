/** Small shared presentational pieces used across every page. */

import clsx from "clsx";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { CLASSIFICATION_LABEL, CLASSIFICATION_STYLE } from "@/lib/format";
import type { Classification } from "@/types";

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={clsx("panel flex flex-col min-h-0", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-4 px-4 py-3 border-b border-outline-variant/50 shrink-0">
          <div className="min-w-0">
            {title && (
              <h3 className="text-headline-sm font-headline-sm font-semibold text-on-surface m-0 truncate">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="text-body-sm font-body-sm text-on-surface-variant m-0 truncate">
                {subtitle}
              </p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </header>
      )}
      <div className={clsx("flex-1 min-h-0", bodyClassName ?? "p-4")}>{children}</div>
    </section>
  );
}

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "primary",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon: string;
  tone?: "primary" | "danger" | "success" | "info";
}) {
  const tones = {
    primary: "bg-primary/10 text-primary",
    danger: "bg-red-500/10 text-red-300",
    success: "bg-emerald-500/10 text-emerald-300",
    info: "bg-sky-500/10 text-sky-300",
  } as const;

  return (
    <div className="panel p-4 flex items-start gap-4">
      <div
        className={clsx(
          "w-11 h-11 rounded-xl flex items-center justify-center shrink-0",
          tones[tone]
        )}
      >
        <span className="material-symbols-outlined">{icon}</span>
      </div>
      <div className="min-w-0">
        <p className="text-body-sm font-body-sm text-on-surface-variant m-0">{label}</p>
        <p className="text-headline-lg font-headline-lg text-on-surface m-0 leading-tight truncate">
          {value}
        </p>
        {hint && (
          <p className="text-body-sm font-body-sm text-on-surface-variant m-0 mt-0.5">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Risk band chip. Always renders an icon and the band name alongside the colour,
 * so the state is never communicated by colour alone.
 */
export function RiskBadge({
  classification,
  score,
  className,
}: {
  classification: Classification;
  score?: number;
  className?: string;
}) {
  const style = CLASSIFICATION_STYLE[classification];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg border text-[11px] font-semibold uppercase tracking-wider whitespace-nowrap",
        style.bg,
        style.border,
        style.text,
        className
      )}
    >
      <span className="material-symbols-outlined text-[13px] leading-none">
        {style.icon}
      </span>
      {CLASSIFICATION_LABEL[classification]}
      {score !== undefined && (
        <span className="font-mono-data font-normal opacity-80">
          {score.toFixed(2)}
        </span>
      )}
    </span>
  );
}

export function Chip({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded-lg bg-surface-container-high border border-outline-variant/50 text-[11px] font-medium text-on-surface-variant whitespace-nowrap",
        className
      )}
    >
      {children}
    </span>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-10 text-on-surface-variant">
      <span className="w-4 h-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      <span className="text-body-sm font-body-sm">{label}…</span>
    </div>
  );
}

export function EmptyState({
  icon = "search_off",
  title,
  detail,
  action,
}: {
  icon?: string;
  title: string;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
      <span className="material-symbols-outlined text-[40px] text-on-surface-variant/40">
        {icon}
      </span>
      <p className="text-body-lg font-body-lg text-on-surface mt-3 mb-1">{title}</p>
      {detail && (
        <p className="text-body-sm font-body-sm text-on-surface-variant max-w-md">
          {detail}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/**
 * Error state that explains what to actually do. A 503 from this backend has two
 * distinct causes — MongoDB unreachable, or no trained model — and the fix
 * differs, so the message names the command rather than saying "try again".
 */
export function ErrorState({ error }: { error: unknown }) {
  const apiError = error instanceof ApiError ? error : null;
  const message = error instanceof Error ? error.message : String(error);

  let hint: ReactNode = null;
  if (apiError?.status === 0) {
    hint = (
      <>
        Start the API from the <code className="font-mono-data">backend/</code>{" "}
        folder:{" "}
        <code className="font-mono-data text-primary">
          uvicorn app.main:app --reload
        </code>
      </>
    );
  } else if (apiError?.isUnavailable) {
    hint = /model/i.test(message) ? (
      <>
        Train the anomaly detector:{" "}
        <code className="font-mono-data text-primary">python -m app.ml.train</code>
      </>
    ) : (
      <>
        Check <code className="font-mono-data">CHRONOTRACE_MONGO_URI</code> in{" "}
        <code className="font-mono-data">backend/.env</code> and that the database
        is reachable.
      </>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center py-12 px-6 text-center">
      <span className="material-symbols-outlined text-[40px] text-red-400/70">
        error
      </span>
      <p className="text-body-lg font-body-lg text-on-surface mt-3 mb-1">
        {apiError?.isNotFound ? "Not found" : "Something went wrong"}
      </p>
      <p className="text-body-sm font-body-sm text-on-surface-variant max-w-lg">
        {message}
      </p>
      {hint && (
        <p className="text-body-sm font-body-sm text-on-surface-variant/80 max-w-lg mt-3">
          {hint}
        </p>
      )}
    </div>
  );
}

/** Wraps the loading / error / empty triad so pages don't repeat it. */
export function QueryState({
  isLoading,
  error,
  isEmpty,
  emptyTitle = "No results",
  emptyDetail,
  loadingLabel,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDetail?: ReactNode;
  loadingLabel?: string;
  children: ReactNode;
}) {
  if (isLoading) return <Spinner label={loadingLabel} />;
  if (error) return <ErrorState error={error} />;
  if (isEmpty) return <EmptyState title={emptyTitle} detail={emptyDetail} />;
  return <>{children}</>;
}

export function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={clsx("flex flex-col gap-1.5", className)}>
      <span className="text-label-md font-label-md text-on-surface-variant uppercase tracking-wider">
        {label}
      </span>
      {children}
    </label>
  );
}

/** Key/value row used by every detail panel. */
export function DetailRow({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-body-sm font-body-sm text-on-surface-variant shrink-0">
        {label}
      </span>
      <span
        className={clsx(
          "text-body-sm text-on-surface text-right break-all",
          mono ? "font-mono-data" : "font-body-sm font-medium"
        )}
      >
        {children}
      </span>
    </div>
  );
}
