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

export type ArchitectureDNA = {
  modularity: number;
  coupling: number;
  dependency_concentration: number;
  graph_density: number;
  average_dependency_depth: number;
  churn_concentration: number;
  hotspot_concentration: number;
  centralization_score: number;
  hub_dominance: number;
  graph_entropy: number;
  layer_separation: number;
  cyclic_dependency_score: number;
};

export type SpeciesClassification = {
  name: string;
  confidence: number;
  reasons: string[];
};

export type ArchitecturalWeather = {
  condition: string;
  severity: number;
  explanation: string;
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
  dna: ArchitectureDNA | null;
  species: SpeciesClassification | null;
  weather: ArchitecturalWeather | null;
  quality_score: number;
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
    dna: ArchitectureDNA | null;
    species: SpeciesClassification | null;
    weather: ArchitecturalWeather | null;
    quality_score: number;
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
  shockwave: Record<string, string[]>;
  causes: CausalFinding[];
};

export type CausalFinding = {
  cause: string;
  confidence: number;
  affected_modules: string[];
  supporting_commits: CommitInfo[];
  evidence: string[];
  graph_statistics: Record<string, number>;
};

export type InfluenceEdge = {
  source_event: number;
  target_event: number;
  influence_type: string;
  confidence: number;
  explanation: string;
};

export type InfluenceGraph = {
  nodes: Array<Record<string, string | number>>;
  edges: InfluenceEdge[];
};

export type ArchitecturalFossil = {
  title: string;
  snapshot_index: number;
  timestamp: string;
  reason: string;
  impact_score: number;
  commit: CommitInfo | null;
  affected_modules: string[];
};

export type TurningPoint = {
  commit: CommitInfo;
  snapshot_index: number;
  impact_score: number;
  reason: string;
  future_effects: string[];
  evidence: string[];
};

export type CounterfactualEstimate = {
  event_index: number;
  approximation_note: string;
  actual: Record<string, number>;
  alternative: Record<string, number>;
  estimated_delta: Record<string, number>;
  explanation: string;
  actual_timeline: Array<Record<string, number | string>>;
  alternative_timeline: Array<Record<string, number | string>>;
};

export type ArchitecturalMemory = {
  title: string;
  introduced: string;
  still_influences_percent: number;
  influence_score: number;
  reason: string;
  affected_modules: string[];
  supporting_commits: CommitInfo[];
  still_active: boolean;
  dependency_count: number;
  introduced_snapshot: number;
};

export type ButterflyEffect = {
  immediate_impact: number;
  medium_term_impact: number;
  long_term_impact: number;
  influence_radius: number;
  dependency_growth_caused: number;
  future_modules_affected: string[];
  shockwave: Record<string, string[]>;
  explanation: string;
  evidence: string[];
};

export type ArchitecturalDecision = {
  id: string;
  title: string;
  summary: string;
  confidence: number;
  start_commit: CommitInfo | null;
  end_commit: CommitInfo | null;
  start_snapshot: number;
  end_snapshot: number;
  affected_modules: string[];
  architectural_impact_score: number;
  causes: CausalFinding[];
  supporting_commits: CommitInfo[];
  butterfly_effect: ButterflyEffect;
  turning_point_rank: number | null;
};

export type ModuleFamilyNode = {
  id: string;
  label: string;
  introduced_snapshot: number;
  latest_snapshot: number;
  status: string;
  ancestors: string[];
  descendants: string[];
  evidence: string[];
};

export type ModuleFamilyEdge = {
  source: string;
  target: string;
  relationship: string;
  confidence: number;
  explanation: string;
};

export type ModuleFamilyTree = {
  nodes: ModuleFamilyNode[];
  edges: ModuleFamilyEdge[];
};

export type Forecast = {
  coupling_pressure: string;
  churn_pressure: string;
  likely_bottlenecks: string[];
  recommendation: string;
  future_coupling: number | null;
  future_graph_density: number | null;
  future_dependency_concentration: number | null;
  future_hotspot_modules: string[];
  explanations: CausalFinding[];
};

export type Health = {
  evolution_score: number;
  stability_trend: number[];
  summary: string;
  archetype: string;
  forecast: Forecast | null;
  biography: string;
  story: string[];
  fossils: ArchitecturalFossil[];
  influence_graph: InfluenceGraph | null;
  turning_points: TurningPoint[];
  memories: ArchitecturalMemory[];
  counterfactuals: CounterfactualEstimate[];
  decisions: ArchitecturalDecision[];
  decision_influence_graph: InfluenceGraph | null;
  family_tree: ModuleFamilyTree | null;
  quality_trend: number[];
  report_markdown: string;
  report_html: string;
};
