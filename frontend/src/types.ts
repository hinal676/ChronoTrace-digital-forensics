/**
 * TypeScript mirrors of the backend's Pydantic models.
 *
 * Field names match the API's JSON exactly (snake_case) so responses can be used
 * without a translation layer — one less place for the two halves to drift.
 */

export type Classification =
  | "normal"
  | "low_concern"
  | "requires_review"
  | "high_priority";

export type WeightStrategy =
  | "hops"
  | "frequency"
  | "bytes"
  | "duration"
  | "strength";

export type Heuristic = "zero" | "hop_lower_bound";

export type Direction = "outbound" | "inbound" | "both";

export type SortOrder = "asc" | "desc";

export type Algorithm = "bfs" | "dfs" | "dijkstra" | "astar";

export interface Page<T> {
  total: number;
  limit: number;
  skip: number;
  count: number;
  items: T[];
}

export interface NetworkEvent {
  event_id: string;
  timestamp: number;
  event_time: string;
  duration: number;
  src_device: string;
  dst_device: string;
  protocol: number;
  protocol_name: string;
  src_port: number;
  dst_port: number;
  dst_service: string | null;
  src_packets: number;
  dst_packets: number;
  src_bytes: number;
  dst_bytes: number;
  total_packets: number;
  total_bytes: number;
  packet_ratio: number;
  byte_ratio: number;
  bytes_per_second: number;
  src_bytes_per_packet: number;
  dst_bytes_per_packet: number;
  source: string;
}

export interface DeviceSummary {
  device: string;
  events_out: number;
  events_in: number;
  total_events: number;
  bytes_out: number;
  bytes_in: number;
  packets_out: number;
  packets_in: number;
  unique_destinations: number;
  unique_sources: number;
  unique_dst_ports: number;
  protocols: number[];
  first_seen: number | null;
  last_seen: number | null;
}

export interface DeviceListItem {
  device: string;
  events_out: number;
  events_in: number;
  bytes_out: number;
  bytes_in: number;
  total_events: number;
}

export interface RelatedDevice {
  device: string;
  direction: "outbound" | "inbound" | "bidirectional";
  event_count: number;
  total_bytes: number;
  total_packets: number;
  protocols: number[];
  dst_ports: number[];
  first_seen: number | null;
  last_seen: number | null;
}

export interface RelationshipResponse {
  device: string;
  summary: DeviceSummary;
  related: RelatedDevice[];
  recent_events: NetworkEvent[];
}

export interface TimelineBucket {
  bucket_start: number;
  bucket_end: number;
  bucket_time: string;
  event_count: number;
  total_bytes: number;
  total_packets: number;
  unique_src_devices: number;
  unique_dst_devices: number;
}

export interface TimelineResponse {
  interval_seconds: number | null;
  start_time: number | null;
  end_time: number | null;
  total_events: number;
  buckets: TimelineBucket[];
  events: NetworkEvent[];
}

export interface ProtocolBreakdown {
  protocol: number;
  protocol_name: string;
  event_count: number;
  total_bytes: number;
  total_packets: number;
}

export interface PortBreakdown {
  dst_port: number;
  dst_service: string | null;
  event_count: number;
  total_bytes: number;
}

// --- Graph ---------------------------------------------------------------

export interface GraphFilter {
  start_time?: number | null;
  end_time?: number | null;
  protocol?: number | null;
  dst_port?: number | null;
  min_bytes?: number | null;
}

export interface EdgeSummary {
  source: string;
  target: string;
  event_count: number;
  total_bytes: number;
  total_packets: number;
  total_duration: number;
  protocols: number[];
  dst_ports: number[];
  first_seen: number | null;
  last_seen: number | null;
  weight: number | null;
}

export interface NodeAtDepth {
  device: string;
  depth: number;
  discovered_from: string | null;
}

export interface TraversalResponse {
  algorithm: string;
  source: string;
  target: string | null;
  direction: Direction;
  max_depth: number;
  node_count: number;
  nodes: NodeAtDepth[];
  levels: Record<string, string[]>;
  tree_edges: [string, string][];
  order: string[];
  paths_to_target: string[][];
  truncated: boolean;
  graph_stats: Record<string, number>;
}

export interface PathResponse {
  algorithm: string;
  source: string;
  target: string;
  weight_strategy: WeightStrategy;
  heuristic: Heuristic | null;
  found: boolean;
  cost: number | null;
  hops: number | null;
  path: string[];
  edges: EdgeSummary[];
  alternative_paths: { path: string[]; cost: number; hops: number }[];
  nodes_explored: number | null;
  graph_stats: Record<string, number>;
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  event_count: number;
  density: number;
  is_weakly_connected: boolean;
  weakly_connected_components: number;
  strongly_connected_components: number;
  average_out_degree: number;
  total_bytes: number;
  top_talkers: { device: string; bytes_out: number; events_out: number }[];
  top_receivers: { device: string; bytes_in: number; events_in: number }[];
  busiest_edges: EdgeSummary[];
  built_at: number | null;
}

export interface NeighborhoodNode {
  device: string;
  depth: number;
  events_out: number;
  events_in: number;
  bytes_out: number;
  bytes_in: number;
}

export interface NeighborhoodResponse {
  device: string;
  depth: number;
  nodes: NeighborhoodNode[];
  edges: EdgeSummary[];
}

// --- Analysis ------------------------------------------------------------

export interface EventRisk {
  event_id: string;
  src_device: string | null;
  dst_device: string | null;
  timestamp: number | null;
  risk_score: number;
  classification: Classification;
  reasons: string[];
  anomaly_score: number | null;
  contributing_features: Record<string, number>;
}

export interface AnalysisSummary {
  analyzed_events: number;
  flagged_events: number;
  mean_risk_score: number;
  max_risk_score: number;
  classification_counts: Partial<Record<Classification, number>>;
  top_risk_devices: {
    device: string;
    event_count: number;
    mean_risk_score: number;
    max_risk_score: number;
    flagged_events: number;
  }[];
  top_reasons: { reason: string; count: number }[];
}

export interface AnalysisRequest {
  src_device?: string | null;
  dst_device?: string | null;
  device?: string | null;
  protocol?: number | null;
  dst_port?: number | null;
  start_time?: number | null;
  end_time?: number | null;
  min_bytes?: number | null;
  limit?: number;
  top_n?: number;
  min_risk_score?: number;
  persist?: boolean;
}

export interface AnalysisResponse {
  analysis_id: string | null;
  created_at: string | null;
  model_version: string | null;
  request: AnalysisRequest | null;
  summary: AnalysisSummary;
  results: EventRisk[];
}

export interface DeviceRisk {
  device: string;
  event_count: number;
  mean_risk_score: number;
  max_risk_score: number;
  flagged_events: number;
  classification: Classification;
  top_reasons: string[];
}

export interface ModelInfo {
  trained: boolean;
  model_type: string | null;
  model_version: string | null;
  trained_at: string | null;
  training_events: number | null;
  contamination: number | null;
  features: string[];
  thresholds: Record<string, number>;
}

// --- Investigations ------------------------------------------------------

export interface InvestigationRequest {
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
}

export interface InvestigationFindings {
  device_summary: DeviceSummary;
  related_devices: RelatedDevice[];
  neighborhood_levels: Record<string, string[]>;
  neighborhood_edges: EdgeSummary[];
  risk_summary: AnalysisSummary;
  risky_events: EventRisk[];
  notable_events: NetworkEvent[];
  observations: string[];
}

export interface Investigation {
  investigation_id: string;
  device: string;
  title: string | null;
  notes: string | null;
  analyst: string | null;
  status: string;
  created_at: string;
  updated_at: string | null;
  overall_risk_score: number;
  classification: Classification;
  request: InvestigationRequest | null;
  findings: InvestigationFindings | null;
}

export interface HealthResponse {
  status: string;
  database: { connected: boolean; database?: string; error?: string };
  model: { trained: boolean; version: string | null };
}

export interface IngestResult {
  received: number;
  inserted: number;
  duplicates: number;
  rejected: number;
  errors: Record<string, unknown>[];
  event_ids: string[];
}

export interface EventQuery {
  src_device?: string;
  dst_device?: string;
  device?: string;
  protocol?: number;
  src_port?: number;
  dst_port?: number;
  start_time?: number;
  end_time?: number;
  min_duration?: number;
  max_duration?: number;
  min_bytes?: number;
  max_bytes?: number;
  source?: string;
  limit?: number;
  skip?: number;
  sort_by?: string;
  order?: SortOrder;
}
