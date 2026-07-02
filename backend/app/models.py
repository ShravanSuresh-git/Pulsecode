from __future__ import annotations

from pydantic import BaseModel


class CommitInfo(BaseModel):
    sha: str
    message: str
    author: str
    timestamp: str
    files_changed: list[str]
    insertions: int
    deletions: int
    is_merge: bool = False


class GraphNode(BaseModel):
    id: str
    label: str
    directory: str
    churn: int
    commits: int
    complexity: float
    centrality: float = 0
    hotspot_score: float = 0


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float
    kind: str


class SnapshotMetrics(BaseModel):
    churn_score: int
    coupling_score: float
    module_count: int
    dependency_count: int
    complexity_proxy: float
    entropy: float


class ArchitectureDNA(BaseModel):
    modularity: float
    coupling: float
    dependency_concentration: float
    graph_density: float
    average_dependency_depth: float
    churn_concentration: float
    hotspot_concentration: float
    centralization_score: float
    hub_dominance: float = 0
    graph_entropy: float = 0
    layer_separation: float = 0
    cyclic_dependency_score: float = 0


class SpeciesClassification(BaseModel):
    name: str
    confidence: float
    reasons: list[str]


class ArchitecturalWeather(BaseModel):
    condition: str
    severity: int
    explanation: str


class Snapshot(BaseModel):
    index: int
    label: str
    timestamp: str
    commits: list[CommitInfo]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metrics: SnapshotMetrics
    dna: ArchitectureDNA | None = None
    species: SpeciesClassification | None = None
    weather: ArchitecturalWeather | None = None
    quality_score: int = 0


class ArchitectureEvent(BaseModel):
    index: int
    previous_index: int
    timestamp: str
    severity: str
    explanation: str
    affected_modules: list[str]
    title: str = ""
    influence_score: float = 0
    causal_confidence: float = 0
    causal_signal_note: str = ""
    causal_commits: list[CommitInfo] = []
    before_metrics: SnapshotMetrics | None = None
    after_metrics: SnapshotMetrics | None = None
    delta: dict[str, float] = {}
    shockwave: dict[str, list[str]] = {}
    causes: list["CausalFinding"] = []


class ArchitecturalFossil(BaseModel):
    title: str
    snapshot_index: int
    timestamp: str
    reason: str
    impact_score: float
    commit: CommitInfo | None = None
    affected_modules: list[str] = []


class CausalFinding(BaseModel):
    cause: str
    confidence: float
    affected_modules: list[str]
    supporting_commits: list[CommitInfo]
    evidence: list[str]
    graph_statistics: dict[str, float] = {}


class InfluenceEdge(BaseModel):
    source_event: int
    target_event: int
    influence_type: str
    confidence: float
    explanation: str


class InfluenceGraph(BaseModel):
    nodes: list[dict[str, str | int | float]]
    edges: list[InfluenceEdge]


class TurningPoint(BaseModel):
    commit: CommitInfo
    snapshot_index: int
    impact_score: float
    reason: str
    future_effects: list[str]
    evidence: list[str]


class CounterfactualEstimate(BaseModel):
    event_index: int
    approximation_note: str
    replay_status: str = "approximate"
    causal_confidence: float = 0
    actual: dict[str, float]
    alternative: dict[str, float]
    estimated_delta: dict[str, float]
    explanation: str
    actual_timeline: list[dict[str, float | int | str]] = []
    alternative_timeline: list[dict[str, float | int | str]] = []


class ArchitecturalMemory(BaseModel):
    title: str
    introduced: str
    still_influences_percent: float
    influence_score: float
    reason: str
    affected_modules: list[str]
    supporting_commits: list[CommitInfo]
    still_active: bool = True
    dependency_count: int = 0
    introduced_snapshot: int = 0


class ButterflyEffect(BaseModel):
    immediate_impact: float
    medium_term_impact: float
    long_term_impact: float
    influence_radius: int
    dependency_growth_caused: int
    future_modules_affected: list[str]
    shockwave: dict[str, list[str]]
    explanation: str
    evidence: list[str]


class ArchitecturalDecision(BaseModel):
    id: str
    title: str
    summary: str
    confidence: float
    start_commit: CommitInfo | None = None
    end_commit: CommitInfo | None = None
    start_snapshot: int
    end_snapshot: int
    affected_modules: list[str]
    architectural_impact_score: float
    causes: list[CausalFinding]
    supporting_commits: list[CommitInfo]
    butterfly_effect: ButterflyEffect
    turning_point_rank: int | None = None


class ModuleFamilyNode(BaseModel):
    id: str
    label: str
    introduced_snapshot: int
    latest_snapshot: int
    status: str
    ancestors: list[str] = []
    descendants: list[str] = []
    evidence: list[str] = []


class ModuleFamilyEdge(BaseModel):
    source: str
    target: str
    relationship: str
    confidence: float
    explanation: str


class ModuleFamilyTree(BaseModel):
    nodes: list[ModuleFamilyNode]
    edges: list[ModuleFamilyEdge]


class Forecast(BaseModel):
    coupling_pressure: str
    churn_pressure: str
    likely_bottlenecks: list[str]
    recommendation: str
    future_coupling: float | None = None
    future_graph_density: float | None = None
    future_dependency_concentration: float | None = None
    future_hotspot_modules: list[str] = []
    explanations: list[CausalFinding] = []


class Health(BaseModel):
    evolution_score: int
    stability_trend: list[float]
    summary: str
    archetype: str = "Unknown"
    forecast: Forecast | None = None
    biography: str = ""
    story: list[str] = []
    fossils: list[ArchitecturalFossil] = []
    influence_graph: InfluenceGraph | None = None
    turning_points: list[TurningPoint] = []
    memories: list[ArchitecturalMemory] = []
    counterfactuals: list[CounterfactualEstimate] = []
    decisions: list[ArchitecturalDecision] = []
    decision_influence_graph: InfluenceGraph | None = None
    family_tree: ModuleFamilyTree | None = None
    quality_trend: list[int] = []
    report_markdown: str = ""
    report_html: str = ""


class AnalysisResult(BaseModel):
    repo_id: str
    repo_name: str
    repo_path: str
    snapshots: list[Snapshot]
    events: list[ArchitectureEvent]
    decisions: list[ArchitecturalDecision] = []
    health: Health
