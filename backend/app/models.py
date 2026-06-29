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
    causal_commits: list[CommitInfo] = []
    before_metrics: SnapshotMetrics | None = None
    after_metrics: SnapshotMetrics | None = None
    delta: dict[str, float] = {}
    shockwave: dict[str, list[str]] = {}


class ArchitecturalFossil(BaseModel):
    title: str
    snapshot_index: int
    timestamp: str
    reason: str
    impact_score: float
    commit: CommitInfo | None = None
    affected_modules: list[str] = []


class Forecast(BaseModel):
    coupling_pressure: str
    churn_pressure: str
    likely_bottlenecks: list[str]
    recommendation: str


class Health(BaseModel):
    evolution_score: int
    stability_trend: list[float]
    summary: str
    archetype: str = "Unknown"
    forecast: Forecast | None = None
    biography: str = ""
    story: list[str] = []
    fossils: list[ArchitecturalFossil] = []
    quality_trend: list[int] = []
    report_markdown: str = ""
    report_html: str = ""


class AnalysisResult(BaseModel):
    repo_id: str
    repo_name: str
    repo_path: str
    snapshots: list[Snapshot]
    events: list[ArchitectureEvent]
    health: Health
