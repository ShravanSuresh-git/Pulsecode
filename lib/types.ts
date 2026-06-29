export type AnalyzeResponse = {
  repo_id: string;
  snapshot_count: number;
  event_count: number;
};

export type Metrics = {
  churn_score: number;
  coupling_score: number;
  module_count: number;
  dependency_count: number;
  complexity_proxy: number;
  entropy: number;
};

export type CommitInfo = {
  sha: string;
  message: string;
  author: string;
  timestamp: string;
  files_changed: string[];
  insertions: number;
  deletions: number;
};

export type GraphNode = {
  id: string;
  label: string;
  directory: string;
  churn: number;
  commits: number;
  complexity: number;
  centrality: number;
  hotspot_score: number;
};

export type GraphEdge = {
  source: string;
  target: string;
  weight: number;
  kind: string;
};

export type Snapshot = {
  index: number;
  label: string;
  timestamp: string;
  commits: CommitInfo[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  metrics: Metrics;
};

export type Timeline = {
  repo_id: string;
  repo_name: string;
  repo_path: string;
  snapshots: Array<{
    index: number;
    label: string;
    timestamp: string;
    commit_count: number;
    metrics: Metrics;
  }>;
};

export type ArchitectureEvent = {
  index: number;
  previous_index: number;
  timestamp: string;
  severity: string;
  explanation: string;
  affected_modules: string[];
  causal_commits: CommitInfo[];
  before_metrics: Metrics | null;
  after_metrics: Metrics | null;
  delta: Record<string, number>;
};

export type Forecast = {
  coupling_pressure: string;
  churn_pressure: string;
  likely_bottlenecks: string[];
  recommendation: string;
};

export type Health = {
  evolution_score: number;
  stability_trend: number[];
  summary: string;
  archetype: string;
  forecast: Forecast | null;
  biography: string;
  report_markdown: string;
};
