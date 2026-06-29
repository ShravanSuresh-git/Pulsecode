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


class Snapshot(BaseModel):
    index: int
    label: str
    timestamp: str
    commits: list[CommitInfo]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metrics: SnapshotMetrics


class ArchitectureEvent(BaseModel):
    index: int
    timestamp: str
    severity: str
    explanation: str
    affected_modules: list[str]


class Health(BaseModel):
    evolution_score: int
    stability_trend: list[float]
    summary: str


class AnalysisResult(BaseModel):
    repo_id: str
    repo_name: str
    repo_path: str
    snapshots: list[Snapshot]
    events: list[ArchitectureEvent]
    health: Health

