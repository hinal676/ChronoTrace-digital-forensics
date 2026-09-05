/** App shell: fixed sidebar + top app bar, matching the design samples. */

import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import clsx from "clsx";

import { api } from "@/lib/api";

interface NavItem {
  to: string;
  label: string;
  icon: string;
}

/** Nav mirrors the mockups, with Graph View added — it is a page in sample 3. */
const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/timeline", label: "Timeline", icon: "timeline" },
  { to: "/graph", label: "Graph View", icon: "hub" },
  { to: "/evidence", label: "Evidence", icon: "inventory_2" },
  { to: "/cases", label: "Case Manager", icon: "cloud_download" },
  { to: "/reports", label: "Reports", icon: "description" },
  { to: "/settings", label: "Settings", icon: "settings" },
];

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Dashboard", subtitle: "Overview of network activity and risk" },
  "/timeline": { title: "Timeline", subtitle: "Visualize events in chronological order" },
  "/graph": { title: "Graph View", subtitle: "Relationships between devices" },
  "/evidence": { title: "Evidence", subtitle: "Browse and analyze collected network events" },
  "/cases": { title: "Case Manager", subtitle: "Investigations and case files" },
  "/reports": { title: "Reports", subtitle: "Create comprehensive investigation reports" },
  "/settings": { title: "Settings", subtitle: "Backend connection, model and system status" },
};

function Sidebar() {
  return (
    <nav className="w-sidebar_width h-full fixed left-0 top-0 bg-surface-dim border-r border-outline-variant flex flex-col py-component_padding_y overflow-y-auto z-20">
      <div className="px-container_padding mb-8 mt-2 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center text-on-primary-container shrink-0">
          <span className="material-symbols-outlined text-[20px]">fingerprint</span>
        </div>
        <div>
          <h1 className="text-headline-sm font-headline-sm font-bold tracking-tight text-on-surface m-0 leading-tight">
            CHRONOTRACE
          </h1>
          <p className="text-label-md font-label-md text-on-surface-variant m-0 uppercase tracking-wider text-[10px]">
            Digital Forensics
          </p>
        </div>
      </div>

      <ul className="flex-1 px-3 space-y-1">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-3 px-3 py-2 rounded-lg transition-colors duration-150",
                  isActive
                    ? "bg-secondary-container text-on-secondary-container font-bold border-l-2 border-primary"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high"
                )
              }
            >
              <span className="material-symbols-outlined">{item.icon}</span>
              <span className="text-label-md font-label-md">{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="px-3 mt-auto pt-4 border-t border-outline-variant/30">
        <div className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-on-surface-variant">
          <div className="w-8 h-8 rounded-full bg-surface-container flex items-center justify-center">
            <span className="material-symbols-outlined text-xl">account_circle</span>
          </div>
          <div className="text-left flex-1">
            <p className="text-label-md font-label-md text-on-surface m-0 leading-tight">
              Investigator
            </p>
            <p className="text-[10px] text-on-surface-variant m-0 uppercase tracking-wider">
              Admin
            </p>
          </div>
        </div>
      </div>
    </nav>
  );
}

/** Live UTC clock — forensic timestamps are UTC throughout the app. */
function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="hidden lg:flex items-center gap-3 bg-surface-container-low border border-outline-variant/50 rounded-lg px-3 py-1.5">
      <span className="text-body-sm font-body-sm text-on-surface-variant">
        {now.toISOString().slice(0, 10)}
      </span>
      <span className="text-mono-data font-mono-data text-on-surface">
        {now.toISOString().slice(11, 19)} UTC
      </span>
    </div>
  );
}

/** Backend reachability indicator, polled so outages surface without a refresh. */
function HealthPill() {
  const { data, isError } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: false,
  });

  const ok = !isError && data?.database.connected;
  const label = isError
    ? "API offline"
    : data?.database.connected
      ? "Connected"
      : "Database down";

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-container-low border border-outline-variant/50"
      title={
        data?.model.trained === false
          ? "Connected, but no risk model is trained"
          : label
      }
    >
      <span
        className={clsx(
          "w-2 h-2 rounded-full",
          ok ? "bg-emerald-500" : "bg-red-500"
        )}
      />
      <span className="text-body-sm font-body-sm text-on-surface-variant">{label}</span>
    </div>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  const meta =
    PAGE_META[pathname] ??
    PAGE_META[`/${pathname.split("/")[1]}`] ?? {
      title: "ChronoTrace",
      subtitle: "",
    };

  return (
    <div className="h-screen overflow-hidden flex bg-background">
      <Sidebar />
      <div className="ml-sidebar_width flex-1 flex flex-col h-full w-[calc(100%-240px)]">
        <header className="h-[64px] bg-surface flex justify-between items-center px-container_padding py-component_padding_y border-b border-outline-variant shrink-0 z-10">
          <div>
            <h2 className="text-headline-md font-headline-md font-bold tracking-tight m-0 leading-tight">
              {meta.title}
            </h2>
            <p className="text-body-sm font-body-sm text-on-surface-variant m-0">
              {meta.subtitle}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Clock />
            <HealthPill />
          </div>
        </header>
        <main className="flex-1 overflow-hidden bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
