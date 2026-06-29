from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import networkx as nx
import pandas as pd
from git import Commit, Repo

from .models import (
    AnalysisResult,
    ArchitectureEvent,
    CommitInfo,
    GraphEdge,
    GraphNode,
    Health,
    Snapshot,
    SnapshotMetrics,
)


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".swift",
    ".kt",
    ".scala",
    ".vue",
    ".svelte",
}


def analyze_repository(repo_path: Path, snapshot_size: int) -> AnalysisResult:
    repo = Repo(repo_path)
    commits = list(repo.iter_commits("--all", max_count=400))
    commits.reverse()

    commit_infos = [_commit_info(repo, commit) for commit in commits]
    snapshots = _build_snapshots(commit_infos, snapshot_size)
    events = _detect_events(snapshots)
    health = _build_health(snapshots, events)

    fingerprint = hashlib.sha1(f"{repo_path}:{len(commits)}:{datetime.now(timezone.utc)}".encode()).hexdigest()[:12]
    return AnalysisResult(
        repo_id=fingerprint,
        repo_name=repo_path.name,
        repo_path=str(repo_path),
        snapshots=snapshots,
        events=events,
        health=health,
    )


def _commit_info(repo: Repo, commit: Commit) -> CommitInfo:
    stats = commit.stats.total
    files_changed = [path for path in commit.stats.files.keys() if _is_sourceish(path)]
    timestamp = datetime.fromtimestamp(commit.committed_date, timezone.utc).isoformat()
    return CommitInfo(
        sha=commit.hexsha[:10],
        message=commit.message.strip().splitlines()[0][:120] or "(no message)",
        author=str(commit.author),
        timestamp=timestamp,
        files_changed=sorted(files_changed),
        insertions=int(stats.get("insertions", 0)),
        deletions=int(stats.get("deletions", 0)),
    )


def _build_snapshots(commits: list[CommitInfo], snapshot_size: int) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    seen_files: set[str] = set()
    cochange: Counter[tuple[str, str]] = Counter()
    file_churn: Counter[str] = Counter()
    file_commits: Counter[str] = Counter()

    for index, end in enumerate(range(snapshot_size, len(commits) + snapshot_size, snapshot_size)):
        group = commits[max(0, end - snapshot_size) : min(end, len(commits))]
        if not group:
            continue

        for commit in group:
            changed = [file for file in commit.files_changed if _is_sourceish(file)]
            seen_files.update(changed)
            churn = commit.insertions + commit.deletions
            for file in changed:
                file_churn[file] += max(1, churn // max(1, len(changed)))
                file_commits[file] += 1
            for left, right in combinations(sorted(set(changed)), 2):
                cochange[(left, right)] += 1

        graph = _graph_from_state(seen_files, cochange)
        nodes = _nodes_from_graph(graph, file_churn, file_commits)
        edges = [
            GraphEdge(source=source, target=target, weight=float(data["weight"]), kind=data["kind"])
            for source, target, data in graph.edges(data=True)
        ]
        metrics = _metrics(group, graph, nodes, edges)
        snapshots.append(
            Snapshot(
                index=index,
                label=f"t={index}",
                timestamp=group[-1].timestamp,
                commits=group,
                nodes=nodes,
                edges=edges,
                metrics=metrics,
            )
        )
        if end >= len(commits):
            break

    return snapshots


def _graph_from_state(files: set[str], cochange: Counter[tuple[str, str]]) -> nx.Graph:
    graph = nx.Graph()
    for file in sorted(files):
        graph.add_node(file)

    for left, right in combinations(sorted(files), 2):
        same_dir = _directory(left) == _directory(right)
        weight = cochange[(left, right)]
        if weight >= 2:
            graph.add_edge(left, right, weight=weight, kind="co-change")
        elif same_dir and _directory(left) != "root":
            graph.add_edge(left, right, weight=0.5, kind="directory")
    return graph


def _nodes_from_graph(graph: nx.Graph, file_churn: Counter[str], file_commits: Counter[str]) -> list[GraphNode]:
    return [
        GraphNode(
            id=node,
            label=Path(node).name,
            directory=_directory(node),
            churn=int(file_churn[node]),
            commits=int(file_commits[node]),
            complexity=round(math.log1p(file_churn[node]) + graph.degree(node) * 0.35, 2),
        )
        for node in graph.nodes
    ]


def _metrics(
    commits: list[CommitInfo],
    graph: nx.Graph,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> SnapshotMetrics:
    churn = sum(commit.insertions + commit.deletions for commit in commits)
    density = nx.density(graph) if graph.number_of_nodes() > 1 else 0
    complexity = sum(node.complexity for node in nodes) / max(1, len(nodes))
    return SnapshotMetrics(
        churn_score=churn,
        coupling_score=round(density, 4),
        module_count=len(nodes),
        dependency_count=len(edges),
        complexity_proxy=round(complexity, 2),
        entropy=round(_entropy([graph.degree(node) for node in graph.nodes]), 3),
    )


def _detect_events(snapshots: list[Snapshot]) -> list[ArchitectureEvent]:
    events: list[ArchitectureEvent] = []
    for previous, current in zip(snapshots, snapshots[1:]):
        reasons: list[str] = []
        density_delta = current.metrics.coupling_score - previous.metrics.coupling_score
        edge_delta = current.metrics.dependency_count - previous.metrics.dependency_count
        churn_spike = _spike_threshold(snapshots, current.index, "churn_score")

        if density_delta >= 0.08:
            reasons.append(f"dependency density rose by {density_delta:.2f}")
        if edge_delta >= max(4, previous.metrics.dependency_count * 0.35):
            reasons.append(f"dependency edges jumped by {edge_delta}")
        if current.metrics.churn_score >= churn_spike and current.metrics.churn_score > 250:
            reasons.append("large refactor-sized churn appeared")
        if current.metrics.complexity_proxy - previous.metrics.complexity_proxy >= 1.2:
            reasons.append("complexity proxy increased sharply")

        if reasons:
            affected = _top_affected_modules(current)
            severity = "high" if len(reasons) >= 2 else "medium"
            events.append(
                ArchitectureEvent(
                    index=current.index,
                    timestamp=current.timestamp,
                    severity=severity,
                    explanation=f"Between {previous.label} and {current.label}, " + "; ".join(reasons) + ".",
                    affected_modules=affected,
                )
            )
    return events


def _build_health(snapshots: list[Snapshot], events: list[ArchitectureEvent]) -> Health:
    if not snapshots:
        return Health(evolution_score=0, stability_trend=[], summary="No commits were available for analysis.")

    frame = pd.DataFrame([snapshot.metrics.model_dump() for snapshot in snapshots])
    coupling = frame["coupling_score"].fillna(0).tolist()
    complexity = frame["complexity_proxy"].fillna(0).tolist()
    stability_trend = [
        round(max(0, 100 - coupling[index] * 80 - complexity[index] * 2), 1)
        for index in range(len(snapshots))
    ]
    event_penalty = min(25, len(events) * 5)
    latest = stability_trend[-1] if stability_trend else 50
    evolution_score = int(max(0, min(100, latest - event_penalty)))
    summary = _summary(snapshots, events)
    return Health(evolution_score=evolution_score, stability_trend=stability_trend, summary=summary)


def _summary(snapshots: list[Snapshot], events: list[ArchitectureEvent]) -> str:
    first = snapshots[0].metrics
    last = snapshots[-1].metrics
    coupling_delta = last.coupling_score - first.coupling_score
    module_delta = last.module_count - first.module_count
    if coupling_delta > 0.08:
        direction = "grew more interconnected, with coupling becoming a larger architectural force"
    elif coupling_delta < -0.05:
        direction = "became more modular as dependency density eased"
    else:
        direction = "kept a relatively steady structural shape"

    event_text = (
        f" {len(events)} architectural shift event{'s' if len(events) != 1 else ''} stood out."
        if events
        else " No abrupt architectural shift was detected."
    )
    return (
        f"The repository {direction} across {len(snapshots)} snapshots. "
        f"Module count changed from {first.module_count} to {last.module_count} "
        f"({module_delta:+d}).{event_text}"
    )


def _top_affected_modules(snapshot: Snapshot) -> list[str]:
    ranked = sorted(snapshot.nodes, key=lambda node: (node.complexity, node.churn, node.commits), reverse=True)
    return [node.id for node in ranked[:6]]


def _spike_threshold(snapshots: list[Snapshot], index: int, field: str) -> float:
    previous = [getattr(snapshot.metrics, field) for snapshot in snapshots[:index]]
    if not previous:
        return float("inf")
    return float(pd.Series(previous).mean() + pd.Series(previous).std(ddof=0) * 1.4)


def _entropy(values: list[int]) -> float:
    total = sum(values)
    if total == 0:
        return 0.0
    return -sum((value / total) * math.log2(value / total) for value in values if value)


def _directory(path: str) -> str:
    parent = str(Path(path).parent)
    return "root" if parent == "." else parent.split("/")[0]


def _is_sourceish(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    ignored = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip"}
    return suffix not in ignored and (suffix in CODE_EXTENSIONS or "/" in path)

