/**
 * Typed client for the ChronoTrace REST API.
 *
 * Every backend endpoint is reachable from here, so components never build URLs
 * or handle transport concerns themselves.
 */

import type {
  AnalysisRequest,
  AnalysisResponse,
  DeviceListItem,
  DeviceRisk,
  DeviceSummary,
  Direction,
  EventQuery,
  GraphFilter,
  GraphStats,
  HealthResponse,
  Heuristic,
  Investigation,
  ModelInfo,
  NeighborhoodResponse,
  NetworkEvent,
  Page,
  PathResponse,
  PortBreakdown,
  ProtocolBreakdown,
  RelationshipResponse,
  TimelineResponse,
  TraversalResponse,
  WeightStrategy,
} from "@/types";

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(
  /\/$/,
  ""
);

/** An API error carrying the HTTP status, so callers can branch on 404 vs 503. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** 503 means MongoDB is down or no model is trained — both are recoverable. */
  get isUnavailable(): boolean {
    return this.status === 503;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

function buildQuery(params: object | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    // `0` and `false` are meaningful filter values; only skip absent ones.
    if (value === undefined || value === null || value === "") continue;
    search.append(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch (cause) {
    // Network-level failure: the API isn't running or is unreachable.
    throw new ApiError(
      0,
      "Cannot reach the ChronoTrace API. Is the backend running?",
      cause
    );
  }

  if (!response.ok) {
    let detail: unknown;
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body?.detail ?? body;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail) && detail[0]?.msg) {
        // FastAPI validation errors arrive as a list of {loc, msg}.
        message = detail
          .map((d: { loc?: unknown[]; msg?: string }) =>
            `${d.loc?.slice(1).join(".") ?? "input"}: ${d.msg}`
          )
          .join("; ");
      }
    } catch {
      /* response had no JSON body; keep the status line */
    }
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  // --- meta ---
  health: () => request<HealthResponse>("/health"),

  // --- events ---
  listEvents: (query?: EventQuery) =>
    request<Page<NetworkEvent>>(`/events${buildQuery(query)}`),
  getEvent: (eventId: string) => request<NetworkEvent>(`/events/${eventId}`),
  deleteEvent: (eventId: string) =>
    request<{ status: string }>(`/events/${eventId}`, { method: "DELETE" }),

  // --- devices & relationships ---
  listDevices: (limit = 500, skip = 0) =>
    request<Page<DeviceListItem>>(`/devices${buildQuery({ limit, skip })}`),
  getDevice: (device: string) =>
    request<DeviceSummary>(`/devices/${encodeURIComponent(device)}`),
  getRelationships: (device: string, limit = 100, recent = 10) =>
    request<RelationshipResponse>(
      `/relationships/${encodeURIComponent(device)}${buildQuery({ limit, recent })}`
    ),
  getProtocols: () => request<ProtocolBreakdown[]>("/protocols"),
  getPorts: (limit = 20) =>
    request<PortBreakdown[]>(`/ports${buildQuery({ limit })}`),

  // --- timeline ---
  getTimeline: (params: {
    device?: string;
    src_device?: string;
    dst_device?: string;
    protocol?: number;
    dst_port?: number;
    start_time?: number;
    end_time?: number;
    min_bytes?: number;
    interval?: number;
    raw?: boolean;
    limit?: number;
  }) => request<TimelineResponse>(`/timeline${buildQuery(params)}`),

  // --- graph ---
  graphStats: (filter?: GraphFilter) =>
    request<GraphStats>(`/graph/stats${buildQuery(filter)}`),
  neighborhood: (
    device: string,
    depth = 1,
    direction: Direction = "both",
    maxNodes = 200
  ) =>
    request<NeighborhoodResponse>(
      `/graph/neighborhood/${encodeURIComponent(device)}${buildQuery({
        depth,
        direction,
        max_nodes: maxNodes,
      })}`
    ),
  bfs: (body: {
    source: string;
    target?: string | null;
    max_depth?: number;
    max_nodes?: number;
    direction?: Direction;
    filter?: GraphFilter;
  }) => post<TraversalResponse>("/graph/bfs", body),
  dfs: (body: {
    source: string;
    target?: string | null;
    max_depth?: number;
    max_nodes?: number;
    direction?: Direction;
    filter?: GraphFilter;
  }) => post<TraversalResponse>("/graph/dfs", body),
  dijkstra: (body: {
    source: string;
    target: string;
    weight?: WeightStrategy;
    direction?: Direction;
    k?: number;
    filter?: GraphFilter;
  }) => post<PathResponse>("/graph/dijkstra", body),
  astar: (body: {
    source: string;
    target: string;
    weight?: WeightStrategy;
    heuristic?: Heuristic;
    direction?: Direction;
    filter?: GraphFilter;
  }) => post<PathResponse>("/graph/astar", body),
  rebuildGraph: () =>
    post<{ status: string; node_count: number; edge_count: number }>(
      "/graph/rebuild",
      {}
    ),

  // --- analysis ---
  runAnalysis: (body: AnalysisRequest) =>
    post<AnalysisResponse>("/analysis", body),
  getAnalysis: (id: string) => request<AnalysisResponse>(`/analysis/${id}`),
  listAnalyses: (limit = 20, skip = 0) =>
    request<Page<AnalysisResponse>>(`/analysis${buildQuery({ limit, skip })}`),
  modelInfo: () => request<ModelInfo>("/analysis/model"),
  reloadModel: () => post<{ status: string }>("/analysis/model/reload", {}),
  deviceRisk: (device: string, limit = 1000) =>
    request<DeviceRisk>(
      `/analysis/device/${encodeURIComponent(device)}${buildQuery({ limit })}`
    ),

  // --- investigations ---
  createInvestigation: (body: {
    device: string;
    title?: string | null;
    notes?: string | null;
    analyst?: string | null;
    depth?: number;
    start_time?: number | null;
    end_time?: number | null;
    max_events?: number;
    top_n?: number;
    weight?: WeightStrategy;
    persist?: boolean;
  }) => post<Investigation>("/investigations", body),
  listInvestigations: (params?: {
    device?: string;
    status?: string;
    limit?: number;
    skip?: number;
  }) => request<Page<Investigation>>(`/investigations${buildQuery(params)}`),
  getInvestigation: (id: string) => request<Investigation>(`/investigations/${id}`),
  updateInvestigation: (
    id: string,
    changes: { title?: string; notes?: string; analyst?: string; status?: string }
  ) =>
    request<Investigation>(`/investigations/${id}`, {
      method: "PATCH",
      body: JSON.stringify(changes),
    }),
  deleteInvestigation: (id: string) =>
    request<{ status: string }>(`/investigations/${id}`, { method: "DELETE" }),
};
