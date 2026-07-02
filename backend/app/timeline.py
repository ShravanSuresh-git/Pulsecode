from __future__ import annotations

import hashlib
import math
import re
import statistics
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import networkx as nx
from git import Commit, Repo

from .models import (
    AnalysisResult,
    ArchitecturalFossil,
    ArchitecturalMemory,
    ArchitecturalWeather,
    ArchitectureDNA,
    ArchitectureEvent,
    ArchitecturalDecision,
    ButterflyEffect,
    CausalFinding,
    CounterfactualEstimate,
    CommitInfo,
    Forecast,
    GraphEdge,
    GraphNode,
    Health,
    InfluenceEdge,
    InfluenceGraph,
    ModuleFamilyEdge,
    ModuleFamilyNode,
    ModuleFamilyTree,
    Snapshot,
    SnapshotMetrics,
    SpeciesClassification,
    TurningPoint,
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

_IMPORT_EDGE_CACHE: dict[tuple[str, tuple[str, ...]], set[tuple[str, str]]] = {}


@dataclass
class CounterfactualReplay:
    status: str
    alternative: dict[str, float]
    explanation: str
    note: str
    replayed_commits: list[str]
    git_backed: bool = False


def analyze_repository(repo_path: Path, snapshot_size: int) -> AnalysisResult:
    repo = Repo(repo_path)
    commits = list(repo.iter_commits("--all", max_count=400))
    commits.reverse()

    commit_infos = [_commit_info(repo, commit) for commit in commits]
    snapshots = _build_snapshots(repo_path, commit_infos, snapshot_size)
    _enrich_snapshots(snapshots)
    events = _detect_events(snapshots)
    _attach_event_causes(events, snapshots)
    _attach_causal_confidence(events, snapshots)
    fossils = _detect_fossils(snapshots, events)
    turning_points = _turning_points(snapshots)
    decisions = _architectural_decisions(snapshots, events, turning_points)
    memories = _architectural_memories(snapshots, events)
    counterfactuals = _counterfactuals(events, snapshots, repo_path)
    influence_graph = _influence_graph(events)
    decision_influence_graph = _decision_influence_graph(decisions)
    family_tree = _module_family_tree(snapshots)
    health = _build_health(
        snapshots,
        events,
        fossils,
        turning_points,
        memories,
        counterfactuals,
        influence_graph,
        decisions,
        decision_influence_graph,
        family_tree,
    )

    fingerprint = hashlib.sha1(f"{repo_path}:{len(commits)}:{datetime.now(timezone.utc)}".encode()).hexdigest()[:12]
    return AnalysisResult(
        repo_id=fingerprint,
        repo_name=repo_path.name,
        repo_path=str(repo_path),
        snapshots=snapshots,
        events=events,
        decisions=decisions,
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
        is_merge=len(commit.parents) > 1,
    )


def _build_snapshots(repo_path: Path, commits: list[CommitInfo], snapshot_size: int) -> list[Snapshot]:
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

        graph = _graph_from_state(repo_path, seen_files, cochange)
        nodes = _nodes_from_graph(graph, file_churn, file_commits)
        edges = [
            GraphEdge(source=source, target=target, weight=float(data["weight"]), kind=data["kind"])
            for source, target, data in graph.edges(data=True)
        ]
        metrics = _metrics(group, graph, nodes, edges)
        dna = _dna(metrics, graph, nodes)
        species = _species(metrics, nodes, edges, dna)
        snapshots.append(
            Snapshot(
                index=index,
                label=f"t={index}",
                timestamp=group[-1].timestamp,
                commits=group,
                nodes=nodes,
                edges=edges,
                metrics=metrics,
                dna=dna,
                species=species,
                quality_score=_quality_score(metrics, dna),
            )
        )
        if end >= len(commits):
            break

    return snapshots


def _enrich_snapshots(snapshots: list[Snapshot]) -> None:
    for index, snapshot in enumerate(snapshots):
        previous = snapshots[index - 1] if index else None
        snapshot.weather = _weather(snapshot, previous)


def _graph_from_state(repo_path: Path, files: set[str], cochange: Counter[tuple[str, str]]) -> nx.Graph:
    graph = nx.Graph()
    for file in sorted(files):
        graph.add_node(file)

    import_edges = _import_edges(repo_path, files)
    for source, target in import_edges:
        graph.add_edge(source, target, weight=2.5, kind="import")

    for left, right in combinations(sorted(files), 2):
        same_dir = _directory(left) == _directory(right)
        weight = cochange[(left, right)]
        if graph.has_edge(left, right):
            if weight:
                graph[left][right]["weight"] = float(graph[left][right]["weight"]) + weight
                graph[left][right]["kind"] = "import+co-change"
        elif weight >= 2:
            graph.add_edge(left, right, weight=weight, kind="co-change")
        elif same_dir and _directory(left) != "root":
            graph.add_edge(left, right, weight=0.5, kind="directory")
    return graph


def _nodes_from_graph(graph: nx.Graph, file_churn: Counter[str], file_commits: Counter[str]) -> list[GraphNode]:
    centrality = nx.degree_centrality(graph) if graph.number_of_nodes() > 1 else {node: 0 for node in graph.nodes}
    return [
        GraphNode(
            id=node,
            label=Path(node).name,
            directory=_directory(node),
            churn=int(file_churn[node]),
            commits=int(file_commits[node]),
            complexity=round(math.log1p(file_churn[node]) + graph.degree(node) * 0.35, 2),
            centrality=round(float(centrality.get(node, 0)), 3),
            hotspot_score=round(math.log1p(file_churn[node]) + centrality.get(node, 0) * 5 + file_commits[node] * 0.4, 2),
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


def _dna(metrics: SnapshotMetrics, graph: nx.Graph, nodes: list[GraphNode]) -> ArchitectureDNA:
    degrees = [degree for _, degree in graph.degree()]
    centralities = [node.centrality for node in nodes]
    churns = [node.churn for node in nodes]
    hotspots = [node.hotspot_score for node in nodes]
    modularity = _modularity(graph)
    avg_depth = _average_dependency_depth(graph)
    top_directory_edges = sum(1 for source, target in graph.edges if _directory(source) == _directory(target))
    cross_directory_edges = graph.number_of_edges() - top_directory_edges
    cyclic_pressure = 0.0
    if graph.number_of_nodes() > 0:
        cyclic_pressure = max(0, graph.number_of_edges() - graph.number_of_nodes() + nx.number_connected_components(graph)) / max(1, graph.number_of_edges())
    return ArchitectureDNA(
        modularity=round(modularity, 3),
        coupling=round(min(1, metrics.coupling_score), 3),
        dependency_concentration=round(_gini(degrees), 3),
        graph_density=round(metrics.coupling_score, 3),
        average_dependency_depth=round(avg_depth, 3),
        churn_concentration=round(_gini(churns), 3),
        hotspot_concentration=round(_gini(hotspots), 3),
        centralization_score=round(max(centralities) if centralities else 0, 3),
        hub_dominance=round(max(degrees) / max(1, sum(degrees)) if degrees else 0, 3),
        graph_entropy=round(metrics.entropy, 3),
        layer_separation=round(cross_directory_edges / max(1, graph.number_of_edges()), 3),
        cyclic_dependency_score=round(cyclic_pressure, 3),
    )


def _quality_score(metrics: SnapshotMetrics, dna: ArchitectureDNA) -> int:
    raw = (
        100
        - dna.coupling * 26
        - dna.dependency_concentration * 18
        - dna.hotspot_concentration * 16
        - dna.centralization_score * 18
        - min(1, metrics.complexity_proxy / 12) * 12
        + dna.modularity * 18
        + min(1, metrics.entropy / 4) * 10
    )
    return int(max(0, min(100, round(raw))))


def _species(
    metrics: SnapshotMetrics,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    dna: ArchitectureDNA,
) -> SpeciesClassification:
    max_centrality = dna.centralization_score
    import_ratio = sum(1 for edge in edges if "import" in edge.kind) / max(1, len(edges))
    root_dirs = len({node.directory for node in nodes})
    churny = metrics.churn_score > max(200, metrics.module_count * 30)
    reasons: list[str] = []

    if churny and metrics.module_count <= 5:
        species = "Rewrite Phase"
        confidence = 0.72
        reasons.append("High churn is concentrated in a small module set.")
    elif dna.coupling > 0.68 and max_centrality > 0.58:
        species = "Distributed Monolith"
        confidence = 0.78
        reasons.append("Dense dependencies and high centralization suggest distributed tight coupling.")
    elif max_centrality > 0.72:
        species = "Dependency Hub"
        confidence = 0.82
        reasons.append("One module dominates graph centrality.")
    elif root_dirs <= 2 and metrics.module_count >= 8 and dna.coupling > 0.34:
        species = "Modular Monolith"
        confidence = 0.74
        reasons.append("Many modules live inside a small number of top-level areas.")
    elif import_ratio > 0.55 and dna.modularity > 0.45:
        species = "Layered Architecture"
        confidence = 0.7
        reasons.append("Explicit import edges dominate while modules remain clustered.")
    elif dna.churn_concentration > 0.64 and metrics.module_count > 8:
        species = "Feature Factory"
        confidence = 0.68
        reasons.append("Churn is concentrated while module count keeps growing.")
    elif max_centrality > 0.48 and dna.coupling < 0.35:
        species = "Platform Core"
        confidence = 0.66
        reasons.append("A central core exists without overwhelming dependency density.")
    elif metrics.module_count > 15 and dna.hotspot_concentration > 0.5:
        species = "Legacy Accretion"
        confidence = 0.65
        reasons.append("Growth and hotspot concentration indicate accumulated complexity.")
    elif any("util" in node.id.lower() or "shared" in node.id.lower() or "core" in node.id.lower() for node in nodes) and max_centrality > 0.35:
        species = "Utility Core"
        confidence = 0.62
        reasons.append("Core/shared modules are becoming graph anchors.")
    else:
        species = "Healthy Modular"
        confidence = 0.76
        reasons.append("Coupling and concentration remain within a stable modular range.")

    reasons.append(f"DNA coupling={dna.coupling:.2f}, modularity={dna.modularity:.2f}, centralization={dna.centralization_score:.2f}.")
    return SpeciesClassification(name=species, confidence=round(confidence, 2), reasons=reasons)


def _weather(snapshot: Snapshot, previous: Snapshot | None) -> ArchitecturalWeather:
    if previous is None:
        if snapshot.quality_score >= 70:
            return ArchitecturalWeather(condition="Stable", severity=1, explanation="The starting architecture is readable, with no early structural pressure spike.")
        return ArchitecturalWeather(condition="Growing", severity=2, explanation="The starting architecture already shows measurable coupling or complexity pressure.")

    coupling_delta = snapshot.metrics.coupling_score - previous.metrics.coupling_score
    edge_delta = snapshot.metrics.dependency_count - previous.metrics.dependency_count
    quality_delta = snapshot.quality_score - previous.quality_score
    if coupling_delta > 0.18 or edge_delta > max(12, previous.metrics.dependency_count * 0.6):
        return ArchitecturalWeather(condition="High Risk", severity=5, explanation="Dependency growth is explosive in this interval and may create long-lived coupling.")
    if coupling_delta > 0.08 or quality_delta < -18:
        return ArchitecturalWeather(condition="Accelerating", severity=4, explanation="Coupling rose quickly while architecture quality dropped.")
    if coupling_delta > 0.03 or edge_delta > 4:
        return ArchitecturalWeather(condition="Growing", severity=3, explanation="Dependency pressure is increasing but has not crossed the high-risk range.")
    if quality_delta > 10 or coupling_delta < -0.04:
        return ArchitecturalWeather(condition="Consolidating", severity=1, explanation="Coupling pressure is easing and quality is improving.")
    if (snapshot.dna.layer_separation if snapshot.dna else 0) > 0.62:
        return ArchitecturalWeather(condition="Fragmenting", severity=3, explanation="Cross-directory dependencies dominate this snapshot, suggesting responsibility spread.")
    return ArchitecturalWeather(condition="Stable", severity=1, explanation="Architecture is evolving without a sharp pressure change.")


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
            delta = {
                "coupling_score": round(density_delta, 4),
                "dependency_count": float(edge_delta),
                "churn_score": float(current.metrics.churn_score - previous.metrics.churn_score),
                "complexity_proxy": round(current.metrics.complexity_proxy - previous.metrics.complexity_proxy, 2),
            }
            title = _event_title(previous, current, affected, delta)
            influence_score = _event_influence_score(delta, affected)
            events.append(
                ArchitectureEvent(
                    index=current.index,
                    previous_index=previous.index,
                    timestamp=current.timestamp,
                    severity=severity,
                    explanation=f"Between {previous.label} and {current.label}, " + "; ".join(reasons) + ".",
                    affected_modules=affected,
                    title=title,
                    influence_score=influence_score,
                    causal_commits=_causal_commits(current.commits, affected),
                    before_metrics=previous.metrics,
                    after_metrics=current.metrics,
                    delta=delta,
                    shockwave=_shockwave(current, affected),
                )
            )
    return events


def _build_health(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    fossils: list[ArchitecturalFossil],
    turning_points: list[TurningPoint],
    memories: list[ArchitecturalMemory],
    counterfactuals: list[CounterfactualEstimate],
    influence_graph: InfluenceGraph,
    decisions: list[ArchitecturalDecision],
    decision_influence_graph: InfluenceGraph,
    family_tree: ModuleFamilyTree,
) -> Health:
    if not snapshots:
        return Health(evolution_score=0, stability_trend=[], summary="No commits were available for analysis.")

    stability_trend = [float(snapshot.quality_score) for snapshot in snapshots]
    event_penalty = min(25, len(events) * 5)
    latest = stability_trend[-1] if stability_trend else 50
    evolution_score = int(max(0, min(100, latest - event_penalty)))
    summary = _summary(snapshots, events)
    archetype = _archetype(snapshots, events)
    forecast = _forecast(snapshots, turning_points)
    biography = _biography(snapshots, events, archetype, forecast)
    story = _evolution_story(snapshots, events, fossils)
    report_markdown = _report_markdown(
        snapshots,
        events,
        fossils,
        turning_points,
        memories,
        influence_graph,
        decisions,
        decision_influence_graph,
        family_tree,
        evolution_score,
        summary,
        archetype,
        forecast,
        biography,
        story,
    )
    report_html = _report_html(
        snapshots,
        events,
        fossils,
        turning_points,
        memories,
        influence_graph,
        decisions,
        decision_influence_graph,
        family_tree,
        evolution_score,
        summary,
        archetype,
        forecast,
        biography,
        story,
    )
    return Health(
        evolution_score=evolution_score,
        stability_trend=stability_trend,
        summary=summary,
        archetype=archetype,
        forecast=forecast,
        biography=biography,
        story=story,
        fossils=fossils,
        influence_graph=influence_graph,
        turning_points=turning_points,
        memories=memories,
        counterfactuals=counterfactuals,
        decisions=decisions,
        decision_influence_graph=decision_influence_graph,
        family_tree=family_tree,
        quality_trend=[snapshot.quality_score for snapshot in snapshots],
        report_markdown=report_markdown,
        report_html=report_html,
    )


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
    ranked = sorted(snapshot.nodes, key=lambda node: (node.hotspot_score, node.complexity, node.churn), reverse=True)
    return [node.id for node in ranked[:6]]


def _causal_commits(commits: list[CommitInfo], affected: list[str]) -> list[CommitInfo]:
    affected_set = set(affected)
    ranked = sorted(
        commits,
        key=lambda commit: (
            len(affected_set.intersection(commit.files_changed)),
            commit.insertions + commit.deletions,
            len(commit.files_changed),
        ),
        reverse=True,
    )
    return [commit for commit in ranked if affected_set.intersection(commit.files_changed)][:5]


def _event_title(previous: Snapshot, current: Snapshot, affected: list[str], delta: dict[str, float]) -> str:
    lead = Path(affected[0]).stem.replace("_", " ").replace("-", " ").title() if affected else "Architecture"
    coupling_delta = delta.get("coupling_score", 0)
    dependency_delta = delta.get("dependency_count", 0)
    complexity_delta = delta.get("complexity_proxy", 0)
    module_delta = current.metrics.module_count - previous.metrics.module_count
    hub = next((module for module in affected if (current.dna and current.dna.centralization_score > 0.45)), None)
    if hub and coupling_delta > 0.05:
        return f"{Path(hub).stem.replace('_', ' ').title()} becomes dependency hub"
    if module_delta >= 3 and coupling_delta <= 0.04:
        return "Architecture modularization"
    if dependency_delta >= 8:
        return f"{lead} dependency expansion"
    if any(token in lead.lower() for token in ["util", "shared", "core", "common"]):
        return "Large-scale utility extraction"
    if complexity_delta > 1:
        return f"{lead} complexity surge"
    if coupling_delta < -0.03:
        return f"{lead} coupling reduction"
    return f"{lead} architectural shift"


def _event_influence_score(delta: dict[str, float], affected: list[str]) -> float:
    score = (
        abs(delta.get("coupling_score", 0)) * 140
        + abs(delta.get("dependency_count", 0)) * 2.4
        + abs(delta.get("complexity_proxy", 0)) * 9
        + min(12, len(affected) * 1.8)
    )
    return round(max(1, min(100, score)), 1)


def _attach_event_causes(events: list[ArchitectureEvent], snapshots: list[Snapshot]) -> None:
    for event in events:
        current = snapshots[event.index]
        previous = snapshots[event.previous_index]
        event.causes = _infer_causes(event, previous, current)


def _attach_causal_confidence(events: list[ArchitectureEvent], snapshots: list[Snapshot]) -> None:
    """Attach a within-repo causal signal from lagged commit features to DNA metric shifts.

    This uses Granger causality on the repository's own snapshot time-series when statsmodels
    is available and there are enough observations. It is temporal evidence inside one repo,
    not proof of general causality across repositories.
    """
    signals, signal_note = _within_repo_causal_signals(snapshots)
    for event in events:
        if event.previous_index < 0 or event.index >= len(snapshots):
            event.causal_signal_note = signal_note
            continue
        previous = snapshots[event.previous_index]
        current = snapshots[event.index]
        event_features = _commit_feature_vector(event.causal_commits or current.commits)
        metric_deltas = _dna_metric_deltas(previous, current)
        best_confidence = 0.0
        best_metric = ""
        best_feature = ""
        for metric, delta in sorted(metric_deltas.items(), key=lambda item: abs(item[1]), reverse=True):
            if abs(delta) < 0.005:
                continue
            for feature, value in event_features.items():
                if value <= 0:
                    continue
                confidence = signals.get(metric, {}).get(feature, 0.0)
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_metric = metric
                    best_feature = feature
        event.causal_confidence = round(best_confidence, 2)
        if best_confidence:
            event.causal_signal_note = (
                f"Within-repo causal signal: lagged {best_feature} precedes {best_metric} shifts "
                f"with confidence {best_confidence:.2f}. This is not cross-repo causal proof."
            )
        else:
            event.causal_signal_note = signal_note


def _within_repo_causal_signals(snapshots: list[Snapshot]) -> tuple[dict[str, dict[str, float]], str]:
    if len(snapshots) < 6:
        return {}, "Insufficient within-repo time-series length for Granger causal signal; at least 6 snapshots are preferred."
    try:
        from statsmodels.tsa.stattools import grangercausalitytests
    except Exception:
        return {}, "Statsmodels is unavailable; within-repo Granger causal signal was not computed."

    feature_rows = [_commit_feature_vector(snapshot.commits) for snapshot in snapshots[:-1]]
    metric_delta_rows = [_dna_metric_deltas(previous, current) for previous, current in zip(snapshots, snapshots[1:])]
    signals: dict[str, dict[str, float]] = defaultdict(dict)
    feature_names = ["churn", "files_changed", "is_merge", "directory_spread"]
    metric_names = list(metric_delta_rows[0].keys()) if metric_delta_rows else []
    for metric in metric_names:
        target = [row.get(metric, 0.0) for row in metric_delta_rows]
        if _series_is_flat(target):
            continue
        for feature in feature_names:
            predictor = [row.get(feature, 0.0) for row in feature_rows]
            if _series_is_flat(predictor):
                continue
            try:
                # statsmodels tests whether the second column helps predict the first.
                result = grangercausalitytests(list(zip(target, predictor)), maxlag=1, verbose=False)
                p_value = float(result[1][0]["ssr_ftest"][1])
            except Exception:
                continue
            signals[metric][feature] = round(max(0.0, min(1.0, 1.0 - p_value)), 3)
    if not signals:
        return {}, "Within-repo Granger causal signal was inconclusive for this snapshot sequence."
    return dict(signals), "Within-repo causal signal computed from lagged commit features and following snapshot DNA shifts."


def _commit_feature_vector(commits: list[CommitInfo]) -> dict[str, float]:
    files = [file for commit in commits for file in commit.files_changed if _is_sourceish(file)]
    directories = {_directory(file) for file in files}
    return {
        "churn": float(sum(commit.insertions + commit.deletions for commit in commits)),
        "files_changed": float(len(set(files))),
        "is_merge": float(sum(1 for commit in commits if commit.is_merge)),
        "directory_spread": float(len(directories)),
    }


def _dna_metric_deltas(previous: Snapshot, current: Snapshot) -> dict[str, float]:
    if not previous.dna or not current.dna:
        return {}
    previous_dna = previous.dna.model_dump()
    current_dna = current.dna.model_dump()
    return {
        key: float(current_dna.get(key, 0)) - float(previous_dna.get(key, 0))
        for key in [
            "coupling",
            "dependency_concentration",
            "modularity",
            "centralization_score",
            "layer_separation",
            "cyclic_dependency_score",
            "hotspot_concentration",
        ]
    }


def _series_is_flat(values: list[float]) -> bool:
    return len(values) < 4 or max(values) == min(values)


def _infer_causes(event: ArchitectureEvent, previous: Snapshot, current: Snapshot) -> list[CausalFinding]:
    causes: list[CausalFinding] = []
    edge_delta = current.metrics.dependency_count - previous.metrics.dependency_count
    module_delta = current.metrics.module_count - previous.metrics.module_count
    centrality_delta = (current.dna.centralization_score if current.dna else 0) - (previous.dna.centralization_score if previous.dna else 0)
    churn_delta = (current.dna.churn_concentration if current.dna else 0) - (previous.dna.churn_concentration if previous.dna else 0)
    shared_modules = [module for module in event.affected_modules if any(token in module.lower() for token in ["core", "shared", "util", "common"])]

    def add(cause: str, confidence: float, evidence: list[str], modules: list[str] | None = None) -> None:
        causes.append(
            CausalFinding(
                cause=cause,
                confidence=round(max(0.1, min(0.99, confidence)), 2),
                affected_modules=modules or event.affected_modules[:6],
                supporting_commits=event.causal_commits,
                evidence=evidence,
                graph_statistics={
                    "edge_delta": float(edge_delta),
                    "module_delta": float(module_delta),
                    "coupling_delta": float(event.delta.get("coupling_score", 0)),
                    "centrality_delta": round(centrality_delta, 3),
                    "churn_concentration_delta": round(churn_delta, 3),
                },
            )
        )

    if module_delta > 0 and event.delta.get("coupling_score", 0) <= 0:
        add("module extraction", 0.62 + min(0.2, module_delta * 0.04), [f"Module count increased by {module_delta} while coupling did not rise sharply."])
    if edge_delta > 0:
        add("dependency introduction", 0.58 + min(0.28, edge_delta / 40), [f"Dependency count increased by {edge_delta}."])
    if shared_modules:
        add("utility expansion", 0.7, [f"Shared/core modules are in the affected set: {', '.join(shared_modules[:3])}."], shared_modules)
    if churn_delta > 0.12 or current.metrics.churn_score > previous.metrics.churn_score * 1.8:
        add("high churn concentration", 0.68, [f"Churn rose from {previous.metrics.churn_score} to {current.metrics.churn_score}."])
    if any("co-change" in edge.kind for edge in current.edges):
        add("repeated co-change", 0.55, ["Co-change edges participate in the resulting dependency graph."])
    if current.metrics.churn_score > max(120, previous.metrics.churn_score * 2):
        add("architectural refactor", 0.64, ["Snapshot churn crossed a refactor-sized threshold."])
    if len({node.directory for node in current.nodes}) - len({node.directory for node in previous.nodes}) >= 2:
        add("directory restructuring", 0.6, ["Top-level directory count expanded quickly."])
    if centrality_delta > 0.12 or (current.dna and current.dna.centralization_score > 0.65):
        add("dependency hub formation", 0.74, [f"Centralization changed by {centrality_delta:.3f}."])

    return sorted(causes or [CausalFinding(
        cause="compound architectural drift",
        confidence=0.5,
        affected_modules=event.affected_modules,
        supporting_commits=event.causal_commits,
        evidence=["No single heuristic dominated; multiple weak signals contributed."],
        graph_statistics={"coupling_delta": float(event.delta.get("coupling_score", 0))},
    )], key=lambda item: item.confidence, reverse=True)[:5]


def _influence_graph(events: list[ArchitectureEvent]) -> InfluenceGraph:
    nodes = [
        {
            "id": event.index,
            "label": f"t={event.index}",
            "severity": event.severity,
            "primary_cause": event.causes[0].cause if event.causes else "unknown",
            "impact": round(abs(event.delta.get("dependency_count", 0)) + abs(event.delta.get("coupling_score", 0)) * 100, 2),
        }
        for event in events
    ]
    edges: list[InfluenceEdge] = []
    for source, target in combinations(events, 2):
        if source.index >= target.index:
            continue
        shared_modules = set(source.affected_modules).intersection(target.affected_modules)
        shared_causes = {cause.cause for cause in source.causes}.intersection(cause.cause for cause in target.causes)
        if shared_modules or shared_causes:
            confidence = min(0.95, 0.42 + len(shared_modules) * 0.08 + len(shared_causes) * 0.12)
            edges.append(
                InfluenceEdge(
                    source_event=source.index,
                    target_event=target.index,
                    influence_type="module-continuity" if shared_modules else "cause-continuity",
                    confidence=round(confidence, 2),
                    explanation=(
                        f"Shared affected modules: {', '.join(sorted(shared_modules)[:4])}."
                        if shared_modules
                        else f"Shared causal mechanism: {', '.join(sorted(shared_causes))}."
                    ),
                )
            )
    return InfluenceGraph(nodes=nodes, edges=edges)


def _turning_points(snapshots: list[Snapshot]) -> list[TurningPoint]:
    points: list[TurningPoint] = []
    for snapshot in snapshots:
        future = snapshots[snapshot.index + 1 :]
        if not future:
            continue
        future_last = future[-1]
        future_coupling = future_last.metrics.coupling_score - snapshot.metrics.coupling_score
        future_dependency = future_last.metrics.dependency_count - snapshot.metrics.dependency_count
        future_concentration = (future_last.dna.dependency_concentration if future_last.dna else 0) - (snapshot.dna.dependency_concentration if snapshot.dna else 0)
        future_hotspot = (future_last.dna.hotspot_concentration if future_last.dna else 0) - (snapshot.dna.hotspot_concentration if snapshot.dna else 0)
        base = abs(future_coupling) * 45 + abs(future_concentration) * 22 + abs(future_hotspot) * 18 + max(0, future_dependency) * 1.5
        for commit in snapshot.commits:
            churn_weight = math.log1p(commit.insertions + commit.deletions)
            file_weight = len(commit.files_changed) * 0.8
            impact = base + churn_weight + file_weight
            effects = []
            if future_coupling > 0.03:
                effects.append(f"Future coupling increased by {future_coupling:.3f}.")
            elif future_coupling < -0.03:
                effects.append(f"Future coupling decreased by {abs(future_coupling):.3f}.")
            if future_dependency > 0:
                effects.append(f"Future dependency count grew by {future_dependency}.")
            if future_concentration > 0.03:
                effects.append(f"Dependency concentration rose by {future_concentration:.3f}.")
            if future_hotspot > 0.03:
                effects.append(f"Hotspot concentration rose by {future_hotspot:.3f}.")
            points.append(
                TurningPoint(
                    commit=commit,
                    snapshot_index=snapshot.index,
                    impact_score=round(impact, 1),
                    reason=f"Commit changed {len(commit.files_changed)} files before a measurable trajectory shift.",
                    future_effects=effects or ["Future architecture remained comparatively stable."],
                    evidence=[
                        f"Commit churn: {commit.insertions + commit.deletions}",
                        f"Snapshot quality: {snapshot.quality_score}",
                        f"Future dependency delta: {future_dependency}",
                    ],
                )
            )
    return sorted(points, key=lambda item: item.impact_score, reverse=True)[:20]


def _architectural_decisions(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    turning_points: list[TurningPoint],
) -> list[ArchitecturalDecision]:
    decisions: list[ArchitecturalDecision] = []
    turning_by_sha = {point.commit.sha: rank + 1 for rank, point in enumerate(turning_points)}
    if events:
        for event in events:
            current = snapshots[event.index]
            previous = snapshots[event.previous_index]
            primary = event.causes[0] if event.causes else None
            commits = event.causal_commits or current.commits[:3]
            dependency_growth = max(0, current.metrics.dependency_count - previous.metrics.dependency_count)
            medium = _future_delta(snapshots, event.index, 2)
            long = _future_delta(snapshots, event.index, len(snapshots))
            impact = (
                abs(event.delta.get("coupling_score", 0)) * 120
                + abs(event.delta.get("dependency_count", 0)) * 2.2
                + abs(event.delta.get("complexity_proxy", 0)) * 8
                + len(event.affected_modules) * 1.5
                + long * 42
            )
            title = _decision_title(primary.cause if primary else "architectural shift", event.affected_modules)
            decisions.append(
                ArchitecturalDecision(
                    id=f"decision-{event.index}",
                    title=title,
                    summary=(
                        f"{title} around {current.label}. {event.explanation} "
                        f"PulseCode links this to {primary.cause if primary else 'compound architectural drift'}."
                    ),
                    confidence=round(primary.confidence if primary else 0.52, 2),
                    start_commit=commits[0] if commits else None,
                    end_commit=commits[-1] if commits else None,
                    start_snapshot=previous.index,
                    end_snapshot=current.index,
                    affected_modules=event.affected_modules,
                    architectural_impact_score=round(min(100, impact), 1),
                    causes=event.causes,
                    supporting_commits=commits,
                    butterfly_effect=ButterflyEffect(
                        immediate_impact=round(abs(event.delta.get("coupling_score", 0)) * 100 + dependency_growth, 2),
                        medium_term_impact=round(medium * 100, 2),
                        long_term_impact=round(long * 100, 2),
                        influence_radius=len(set(sum(event.shockwave.values(), []))) if event.shockwave else len(event.affected_modules),
                        dependency_growth_caused=dependency_growth,
                        future_modules_affected=_future_modules_affected(snapshots, event.index, event.affected_modules),
                        shockwave=event.shockwave,
                        explanation=(
                            "Immediate impact comes from the event delta; medium and long-term impact compare later "
                            "coupling, dependency concentration, and complexity against the decision snapshot."
                        ),
                        evidence=[
                            f"Dependency delta: {event.delta.get('dependency_count', 0):.0f}",
                            f"Coupling delta: {event.delta.get('coupling_score', 0):.3f}",
                            f"Supporting commits: {', '.join(commit.sha for commit in commits[:4]) or 'none isolated'}",
                        ],
                    ),
                    turning_point_rank=min((turning_by_sha.get(commit.sha, 999) for commit in commits), default=None),
                )
            )

    if not decisions:
        for point in turning_points[:8]:
            snapshot = snapshots[point.snapshot_index]
            modules = _commit_modules(point.commit, snapshot)
            impact = min(100, point.impact_score)
            cause = CausalFinding(
                cause="lasting architectural impact",
                confidence=0.55,
                affected_modules=modules,
                supporting_commits=[point.commit],
                evidence=point.evidence + point.future_effects,
                graph_statistics={"impact_score": point.impact_score},
            )
            decisions.append(
                ArchitecturalDecision(
                    id=f"decision-{point.snapshot_index}-{point.commit.sha}",
                    title=_decision_title("turning point", modules),
                    summary=f"{point.commit.message} became a measurable architectural decision because future graph shape changed after it.",
                    confidence=0.55,
                    start_commit=point.commit,
                    end_commit=point.commit,
                    start_snapshot=point.snapshot_index,
                    end_snapshot=point.snapshot_index,
                    affected_modules=modules,
                    architectural_impact_score=round(impact, 1),
                    causes=[cause],
                    supporting_commits=[point.commit],
                    butterfly_effect=ButterflyEffect(
                        immediate_impact=round(point.impact_score / 3, 2),
                        medium_term_impact=round(_future_delta(snapshots, point.snapshot_index, 2) * 100, 2),
                        long_term_impact=round(_future_delta(snapshots, point.snapshot_index, len(snapshots)) * 100, 2),
                        influence_radius=len(modules),
                        dependency_growth_caused=max(0, snapshots[-1].metrics.dependency_count - snapshot.metrics.dependency_count),
                        future_modules_affected=_future_modules_affected(snapshots, point.snapshot_index, modules),
                        shockwave={"changed_files": modules, "neighbor_modules": [], "graph": []},
                        explanation="Derived from a high-ranking turning point in the absence of a discrete event spike.",
                        evidence=point.evidence,
                    ),
                    turning_point_rank=turning_by_sha.get(point.commit.sha),
                )
            )
    return sorted(decisions, key=lambda item: item.architectural_impact_score, reverse=True)[:24]


def _decision_influence_graph(decisions: list[ArchitecturalDecision]) -> InfluenceGraph:
    nodes = [
        {
            "id": decision.id,
            "label": decision.title,
            "impact": decision.architectural_impact_score,
            "confidence": decision.confidence,
            "snapshot": decision.end_snapshot,
        }
        for decision in decisions
    ]
    edges: list[InfluenceEdge] = []
    for source, target in combinations(sorted(decisions, key=lambda item: item.end_snapshot), 2):
        if source.end_snapshot >= target.end_snapshot:
            continue
        shared_modules = set(source.affected_modules).intersection(target.affected_modules)
        shared_causes = {cause.cause for cause in source.causes}.intersection(cause.cause for cause in target.causes)
        if not shared_modules and not shared_causes:
            continue
        confidence = min(0.95, 0.38 + len(shared_modules) * 0.1 + len(shared_causes) * 0.14)
        edges.append(
            InfluenceEdge(
                source_event=source.end_snapshot,
                target_event=target.end_snapshot,
                influence_type="decision-memory" if shared_modules else "causal-pattern",
                confidence=round(confidence, 2),
                explanation=(
                    f"{source.title} influenced {target.title}; shared modules: {', '.join(sorted(shared_modules)[:4])}."
                    if shared_modules
                    else f"{source.title} and {target.title} share causal pattern: {', '.join(sorted(shared_causes))}."
                ),
            )
        )
    return InfluenceGraph(nodes=nodes, edges=edges)


def _counterfactuals(
    events: list[ArchitectureEvent],
    snapshots: list[Snapshot] | None = None,
    repo_path: Path | None = None,
) -> list[CounterfactualEstimate]:
    estimates: list[CounterfactualEstimate] = []
    snapshots = snapshots or []
    for event in events:
        after = event.after_metrics
        if not after:
            continue
        after_snapshot = snapshots[event.index] if 0 <= event.index < len(snapshots) else None
        actual = _counterfactual_metric_dict(after, after_snapshot.dna if after_snapshot else None)
        replay = _replay_counterfactual(repo_path, event, snapshots, actual) if repo_path and snapshots else _failed_replay(actual, "Counterfactual replay requires the repository path and analyzed snapshots.")
        actual_timeline = _actual_timeline(snapshots)
        if replay.git_backed:
            alternative_timeline = _timeline_with_replay(actual_timeline, event.index, replay.alternative, replay.status)
        else:
            _, alternative_timeline = _simulated_timelines(event, snapshots)
        causal_note = (
            f"Within-repo causal signal confidence is {event.causal_confidence:.2f}. "
            "This is temporal evidence inside one repository, not cross-repo causal proof."
        )
        estimates.append(
            CounterfactualEstimate(
                event_index=event.index,
                approximation_note=f"{replay.note} {causal_note}",
                replay_status=replay.status,
                causal_confidence=event.causal_confidence,
                actual=actual,
                alternative=replay.alternative,
                estimated_delta={key: round(replay.alternative.get(key, actual[key]) - actual[key], 4) for key in actual},
                explanation=replay.explanation,
                actual_timeline=actual_timeline,
                alternative_timeline=alternative_timeline,
            )
        )
    return estimates


def _replay_counterfactual(
    repo_path: Path | None,
    event: ArchitectureEvent,
    snapshots: list[Snapshot],
    actual: dict[str, float],
) -> CounterfactualReplay:
    if repo_path is None or event.previous_index < 0 or event.index >= len(snapshots):
        return _failed_replay(actual, "Counterfactual replay could not locate the event snapshot range.")

    current = snapshots[event.index]
    previous = snapshots[event.previous_index]
    skipped = event.causal_commits or current.commits
    skip_shas = {commit.sha for commit in skipped}
    kept_interval = [commit for commit in current.commits if commit.sha not in skip_shas]
    if not previous.commits or not skip_shas:
        return _failed_replay(actual, "Counterfactual replay needs a parent snapshot and at least one target commit to remove.")

    source_repo = Repo(repo_path)
    base_sha = _resolve_full_sha(source_repo, previous.commits[-1].sha)
    prior_commits = _commits_through_snapshot(snapshots, event.previous_index)
    replayed_shas: list[str] = []
    applied_interval: list[CommitInfo] = []
    skipped_merge_reasons: list[str] = []

    try:
        with tempfile.TemporaryDirectory(prefix="pulsecode-counterfactual-") as temp_dir:
            replay_path = Path(temp_dir) / "repo"
            _run_git(["clone", "--no-hardlinks", "--quiet", str(repo_path), str(replay_path)])
            _run_git(["checkout", "--quiet", base_sha], cwd=replay_path)
            for commit in kept_interval:
                full_sha = _resolve_full_sha(source_repo, commit.sha)
                is_merge = len(source_repo.commit(full_sha).parents) > 1
                cherry_pick_args = ["cherry-pick", "--quiet"]
                if is_merge:
                    cherry_pick_args.extend(["-m", "1"])
                cherry_pick_args.append(full_sha)
                try:
                    _run_git(cherry_pick_args, cwd=replay_path)
                    replayed_shas.append(commit.sha)
                    applied_interval.append(commit)
                except subprocess.CalledProcessError as exc:
                    reason = _git_failure_reason(exc, replay_path)
                    if _is_empty_cherry_pick(reason):
                        _skip_cherry_pick(replay_path)
                        continue
                    _abort_cherry_pick(replay_path)
                    if is_merge:
                        skipped_merge_reasons.append(f"{commit.sha}: {reason}")
                        continue
                    raise RuntimeError(f"commit {commit.sha} failed to cherry-pick: {reason}") from exc

            metrics, dna = _state_metrics(replay_path, prior_commits + applied_interval, applied_interval)
            alternative = _counterfactual_metric_dict(metrics, dna)
            skipped_note = ""
            status = "exact"
            if skipped_merge_reasons:
                status = "approximate"
                skipped_note = (
                    f" {len(skipped_merge_reasons)} merge commit(s) still conflicted after `git cherry-pick -m 1` "
                    f"and were omitted from the temporary replay: {'; '.join(skipped_merge_reasons[:3])}."
                )
            return CounterfactualReplay(
                status=status,
                alternative=alternative,
                explanation=(
                    f"PulseCode replayed the event range from {previous.label} to {current.label}, skipped "
                    f"{len(skip_shas)} event commit(s), and rebuilt dependency metrics from the resulting file tree."
                    f"{skipped_note}"
                ),
                note=(
                    "Exact git replay: non-event commits were cherry-picked onto the pre-event snapshot and graph/DNA metrics "
                    "were rebuilt from that alternate file-tree state."
                    if not skipped_merge_reasons
                    else (
                        "Git-backed approximate replay: non-event commits were replayed onto the pre-event snapshot, "
                        "but some merge commits were omitted after `git cherry-pick -m 1` still conflicted."
                        f"{skipped_note}"
                    )
                ),
                replayed_commits=replayed_shas,
                git_backed=True,
            )
    except Exception as exc:
        return _approximate_replay(event, actual, f"Exact replay fell back because cherry-picking without the target commits failed: {exc}")


def _approximate_replay(event: ArchitectureEvent, actual: dict[str, float], reason: str) -> CounterfactualReplay:
    coupling_delta = float(event.delta.get("coupling_score", 0))
    dependency_delta = float(event.delta.get("dependency_count", 0))
    complexity_delta = float(event.delta.get("complexity_proxy", 0))
    alternative = dict(actual)
    alternative.update(
        {
            "coupling": round(max(0.0, actual.get("coupling", 0) - coupling_delta * 0.7), 4),
            "density": round(max(0.0, actual.get("density", 0) - coupling_delta * 0.7), 4),
            "centralization": round(max(0.0, actual.get("centralization", 0) * 0.35), 4),
            "complexity": round(max(0.0, actual.get("complexity", 0) - complexity_delta * 0.55), 2),
            "entropy": round(max(0.0, actual.get("entropy", 0) - abs(coupling_delta) * 0.35), 3),
            "dependency_count": round(max(0.0, actual.get("dependency_count", 0) - dependency_delta * 0.7), 2),
        }
    )
    return CounterfactualReplay(
        status="approximate",
        alternative=alternative,
        explanation=(
            f"{reason}. The displayed alternative is an explicitly labeled fallback based on observed event deltas, "
            "not an exact alternate Git history."
        ),
        note=f"Approximate mode: {reason}.",
        replayed_commits=[],
    )


def _failed_replay(actual: dict[str, float], reason: str) -> CounterfactualReplay:
    return CounterfactualReplay(
        status="failed",
        alternative=dict(actual),
        explanation=f"{reason} PulseCode therefore does not report a structural difference for this counterfactual.",
        note=f"Replay failed: {reason}",
        replayed_commits=[],
    )


def _counterfactual_metric_dict(metrics: SnapshotMetrics, dna: ArchitectureDNA | None) -> dict[str, float]:
    return {
        "coupling": metrics.coupling_score,
        "density": metrics.coupling_score,
        "centralization": dna.centralization_score if dna else 0.0,
        "complexity": metrics.complexity_proxy,
        "entropy": metrics.entropy,
        "dependency_count": float(metrics.dependency_count),
        "modularity": dna.modularity if dna else 0.0,
        "dependency_concentration": dna.dependency_concentration if dna else 0.0,
    }


def _state_metrics(
    repo_path: Path,
    commits: list[CommitInfo],
    interval_commits: list[CommitInfo],
) -> tuple[SnapshotMetrics, ArchitectureDNA]:
    cochange: Counter[tuple[str, str]] = Counter()
    file_churn: Counter[str] = Counter()
    file_commits: Counter[str] = Counter()
    for commit in commits:
        changed = [file for file in commit.files_changed if _is_sourceish(file)]
        churn = commit.insertions + commit.deletions
        for file in changed:
            file_churn[file] += max(1, churn // max(1, len(changed)))
            file_commits[file] += 1
        for left, right in combinations(sorted(set(changed)), 2):
            cochange[(left, right)] += 1

    files = _tracked_source_files(repo_path)
    graph = _graph_from_state(repo_path, files, cochange)
    nodes = _nodes_from_graph(graph, file_churn, file_commits)
    edges = [
        GraphEdge(source=source, target=target, weight=float(data["weight"]), kind=data["kind"])
        for source, target, data in graph.edges(data=True)
    ]
    metrics = _metrics(interval_commits, graph, nodes, edges)
    return metrics, _dna(metrics, graph, nodes)


def _tracked_source_files(repo_path: Path) -> set[str]:
    try:
        result = _run_git(["ls-files"], cwd=repo_path)
    except Exception:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip() and _is_sourceish(line.strip())}


def _commits_through_snapshot(snapshots: list[Snapshot], index: int) -> list[CommitInfo]:
    commits: list[CommitInfo] = []
    for snapshot in snapshots[: index + 1]:
        commits.extend(snapshot.commits)
    return commits


def _actual_timeline(snapshots: list[Snapshot]) -> list[dict[str, float | int | str]]:
    return [
        {
            "snapshot": snapshot.index,
            "label": snapshot.label,
            "coupling": snapshot.metrics.coupling_score,
            "density": snapshot.metrics.coupling_score,
            "centrality": snapshot.dna.centralization_score if snapshot.dna else 0,
            "entropy": snapshot.metrics.entropy,
            "complexity": snapshot.metrics.complexity_proxy,
            "dependency_count": snapshot.metrics.dependency_count,
        }
        for snapshot in snapshots
    ]


def _timeline_with_replay(
    actual_timeline: list[dict[str, float | int | str]],
    event_index: int,
    alternative: dict[str, float],
    replay_status: str,
) -> list[dict[str, float | int | str]]:
    timeline = [dict(item) for item in actual_timeline]
    for item in timeline:
        if item.get("snapshot") == event_index:
            item.update(alternative)
            item["replay_status"] = replay_status
    return timeline


def _resolve_full_sha(repo: Repo, sha: str) -> str:
    return repo.commit(sha).hexsha


def _git_failure_reason(exc: subprocess.CalledProcessError, cwd: Path) -> str:
    detail = "\n".join(part.strip() for part in [exc.stderr, exc.stdout] if part and part.strip())
    unmerged = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    conflict_files = [line.strip() for line in unmerged.stdout.splitlines() if line.strip()]
    reason = detail or str(exc)
    if conflict_files:
        reason = f"{reason} Conflicted files: {', '.join(conflict_files[:6])}."
    return " ".join(reason.split())


def _is_empty_cherry_pick(reason: str) -> bool:
    lowered = reason.lower()
    return "previous cherry-pick is now empty" in lowered or "nothing to commit" in lowered


def _skip_cherry_pick(cwd: Path) -> None:
    subprocess.run(["git", "cherry-pick", "--skip"], cwd=cwd, text=True, capture_output=True, check=False, timeout=10)


def _abort_cherry_pick(cwd: Path) -> None:
    subprocess.run(["git", "cherry-pick", "--abort"], cwd=cwd, text=True, capture_output=True, check=False, timeout=10)


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=True,
        timeout=45,
    )


def _architectural_memories(snapshots: list[Snapshot], events: list[ArchitectureEvent]) -> list[ArchitecturalMemory]:
    memories: list[ArchitecturalMemory] = []
    latest_nodes = {node.id for node in snapshots[-1].nodes} if snapshots else set()
    for snapshot in snapshots:
        for node in sorted(snapshot.nodes, key=lambda item: item.hotspot_score, reverse=True)[:4]:
            is_memory_candidate = any(token in node.id.lower() for token in ["core", "shared", "util", "auth", "billing", "cache", "event"])
            if not is_memory_candidate or node.id not in latest_nodes:
                continue
            latest = next((candidate for candidate in snapshots[-1].nodes if candidate.id == node.id), node)
            influence = min(100.0, latest.centrality * 100 + latest.hotspot_score * 4)
            if influence < 25:
                continue
            commits = [commit for commit in snapshot.commits if node.id in commit.files_changed][:3]
            memories.append(
                ArchitecturalMemory(
                    title=f"{Path(node.id).stem.title()} Architectural Memory",
                    introduced=snapshot.timestamp,
                    still_influences_percent=round(min(100, latest.centrality * 100), 1),
                    influence_score=round(influence, 1),
                    reason=f"{node.id} persisted from t={snapshot.index} and remains central/hot in the latest graph.",
                    affected_modules=[node.id],
                    supporting_commits=commits,
                    still_active=node.id in latest_nodes,
                    dependency_count=int(latest.centrality * max(1, len(latest_nodes))),
                    introduced_snapshot=snapshot.index,
                )
            )
    unique: dict[str, ArchitecturalMemory] = {}
    for memory in memories:
        unique.setdefault(memory.title, memory)
    return sorted(unique.values(), key=lambda item: item.influence_score, reverse=True)[:10]


def _module_family_tree(snapshots: list[Snapshot]) -> ModuleFamilyTree:
    if not snapshots:
        return ModuleFamilyTree(nodes=[], edges=[])

    first_seen: dict[str, int] = {}
    last_seen: dict[str, int] = {}
    directories_by_snapshot: list[dict[str, set[str]]] = []
    for snapshot in snapshots:
        directories: dict[str, set[str]] = defaultdict(set)
        for node in snapshot.nodes:
            first_seen.setdefault(node.id, snapshot.index)
            last_seen[node.id] = snapshot.index
            directories[_directory(node.id)].add(node.id)
        directories_by_snapshot.append(directories)

    latest_ids = {node.id for node in snapshots[-1].nodes}
    nodes = [
        ModuleFamilyNode(
            id=module,
            label=Path(module).stem,
            introduced_snapshot=first_seen[module],
            latest_snapshot=last_seen[module],
            status="active" if module in latest_ids else "retired",
            evidence=[
                f"First seen at t={first_seen[module]}",
                f"Last seen at t={last_seen[module]}",
            ],
        )
        for module in sorted(first_seen)
    ]
    edges: list[ModuleFamilyEdge] = []
    for previous, current in zip(snapshots, snapshots[1:]):
        previous_modules = {node.id for node in previous.nodes}
        current_modules = {node.id for node in current.nodes}
        introduced = current_modules - previous_modules
        retired = previous_modules - current_modules

        for new_module in introduced:
            candidates = sorted(previous_modules, key=lambda item: _module_similarity(item, new_module), reverse=True)[:2]
            for candidate in candidates:
                score = _module_similarity(candidate, new_module)
                if score >= 0.32:
                    relationship = "rename" if Path(candidate).stem == Path(new_module).stem else "abstraction"
                    edges.append(
                        ModuleFamilyEdge(
                            source=candidate,
                            target=new_module,
                            relationship=relationship,
                            confidence=round(score, 2),
                            explanation=f"{new_module} appeared after {candidate}; path/name similarity suggests {relationship}.",
                        )
                    )

        previous_dirs = directories_by_snapshot[previous.index]
        current_dirs = directories_by_snapshot[current.index]
        for directory, current_members in current_dirs.items():
            previous_members = previous_dirs.get(directory, set())
            added = current_members - previous_members
            if len(added) >= 2 and previous_members:
                parent = sorted(previous_members, key=lambda item: len(item))[0]
                for child in sorted(added)[:4]:
                    edges.append(
                        ModuleFamilyEdge(
                            source=parent,
                            target=child,
                            relationship="module split",
                            confidence=0.58,
                            explanation=f"{directory} expanded by multiple modules at t={current.index}, suggesting responsibility split.",
                        )
                    )

        for retired_module in retired:
            successors = sorted(introduced, key=lambda item: _module_similarity(retired_module, item), reverse=True)[:1]
            if successors and _module_similarity(retired_module, successors[0]) >= 0.28:
                edges.append(
                    ModuleFamilyEdge(
                        source=retired_module,
                        target=successors[0],
                        relationship="responsibility inheritance",
                        confidence=round(_module_similarity(retired_module, successors[0]), 2),
                        explanation=f"{successors[0]} appeared as {retired_module} disappeared.",
                    )
                )

    by_id = {node.id: node for node in nodes}
    unique_edges: dict[tuple[str, str, str], ModuleFamilyEdge] = {}
    for edge in edges:
        unique_edges.setdefault((edge.source, edge.target, edge.relationship), edge)
    for edge in unique_edges.values():
        if edge.source in by_id:
            by_id[edge.source].descendants.append(edge.target)
        if edge.target in by_id:
            by_id[edge.target].ancestors.append(edge.source)
    ranked_nodes = sorted(by_id.values(), key=lambda node: (len(node.descendants), node.latest_snapshot), reverse=True)[:80]
    kept = {node.id for node in ranked_nodes}
    ranked_edges = [edge for edge in unique_edges.values() if edge.source in kept and edge.target in kept][:120]
    return ModuleFamilyTree(nodes=ranked_nodes, edges=ranked_edges)


def _simulated_timelines(event: ArchitectureEvent, snapshots: list[Snapshot]) -> tuple[list[dict[str, float | int | str]], list[dict[str, float | int | str]]]:
    actual: list[dict[str, float | int | str]] = []
    alternative: list[dict[str, float | int | str]] = []
    coupling_delta = float(event.delta.get("coupling_score", 0))
    dependency_delta = float(event.delta.get("dependency_count", 0))
    complexity_delta = float(event.delta.get("complexity_proxy", 0))
    for snapshot in snapshots:
        item = {
            "snapshot": snapshot.index,
            "label": snapshot.label,
            "coupling": snapshot.metrics.coupling_score,
            "density": snapshot.metrics.coupling_score,
            "centrality": snapshot.dna.centralization_score if snapshot.dna else 0,
            "entropy": snapshot.metrics.entropy,
            "complexity": snapshot.metrics.complexity_proxy,
        }
        actual.append(item)
        decay = 0 if snapshot.index < event.index else max(0.18, 0.78 - (snapshot.index - event.index) * 0.12)
        alternative.append(
            {
                **item,
                "coupling": round(max(0, snapshot.metrics.coupling_score - coupling_delta * decay), 4),
                "density": round(max(0, snapshot.metrics.coupling_score - coupling_delta * decay), 4),
                "centrality": round(max(0, (snapshot.dna.centralization_score if snapshot.dna else 0) - abs(coupling_delta) * decay), 4),
                "entropy": round(max(0, snapshot.metrics.entropy - abs(coupling_delta) * decay), 4),
                "complexity": round(max(0, snapshot.metrics.complexity_proxy - complexity_delta * decay), 2),
                "dependency_count": round(max(0, snapshot.metrics.dependency_count - dependency_delta * decay), 2),
            }
        )
    return actual, alternative


def _future_delta(snapshots: list[Snapshot], index: int, horizon: int) -> float:
    if index >= len(snapshots) - 1:
        return 0.0
    current = snapshots[index]
    target = snapshots[min(len(snapshots) - 1, index + max(1, horizon))]
    concentration_delta = (target.dna.dependency_concentration if target.dna else 0) - (current.dna.dependency_concentration if current.dna else 0)
    return abs(target.metrics.coupling_score - current.metrics.coupling_score) + abs(target.metrics.complexity_proxy - current.metrics.complexity_proxy) / 10 + abs(concentration_delta)


def _future_modules_affected(snapshots: list[Snapshot], index: int, modules: list[str]) -> list[str]:
    if not snapshots or index >= len(snapshots):
        return modules[:8]
    current_modules = set(modules)
    future: Counter[str] = Counter()
    for snapshot in snapshots[index + 1 :]:
        graph = nx.Graph()
        for node in snapshot.nodes:
            graph.add_node(node.id)
        for edge in snapshot.edges:
            graph.add_edge(edge.source, edge.target)
        for module in current_modules:
            if module in graph:
                future.update(graph.neighbors(module))
    return [module for module, _ in future.most_common(12)]


def _commit_modules(commit: CommitInfo, snapshot: Snapshot) -> list[str]:
    snapshot_modules = {node.id for node in snapshot.nodes}
    modules = [file for file in commit.files_changed if file in snapshot_modules]
    return modules[:8] or [node.id for node in sorted(snapshot.nodes, key=lambda item: item.hotspot_score, reverse=True)[:4]]


def _decision_title(cause: str, modules: list[str]) -> str:
    target = Path(modules[0]).stem.replace("_", " ").replace("-", " ").title() if modules else "Architecture"
    if "utility" in cause or "shared" in cause:
        return f"Introduced Shared {target}"
    if "hub" in cause:
        return f"Formed {target} Dependency Hub"
    if "module extraction" in cause:
        return f"Extracted {target} Module Boundary"
    if "refactor" in cause:
        return f"Refactored {target} Architecture"
    if "directory" in cause:
        return f"Restructured {target} Directory"
    if "turning point" in cause:
        return f"Committed {target} Turning Point"
    return f"Changed {target} Architecture"


def _module_similarity(left: str, right: str) -> float:
    left_parts = set(Path(left).with_suffix("").parts)
    right_parts = set(Path(right).with_suffix("").parts)
    overlap = len(left_parts.intersection(right_parts)) / max(1, len(left_parts.union(right_parts)))
    stem_bonus = 0.25 if Path(left).stem == Path(right).stem else 0
    directory_bonus = 0.2 if _directory(left) == _directory(right) else 0
    return min(1.0, overlap + stem_bonus + directory_bonus)


def _archetype(snapshots: list[Snapshot], events: list[ArchitectureEvent]) -> str:
    if len(snapshots) < 2:
        return "Seed Architecture"
    first = snapshots[0].metrics
    last = snapshots[-1].metrics
    mid = snapshots[len(snapshots) // 2].metrics
    coupling_delta = last.coupling_score - first.coupling_score
    module_delta = last.module_count - first.module_count
    if module_delta > max(3, first.module_count * 0.5) and coupling_delta < -0.04:
        return "Extraction and Stabilization"
    if mid.coupling_score > first.coupling_score and last.coupling_score < mid.coupling_score:
        return "Coupling Spike then Recovery"
    if coupling_delta > 0.12 and len(events) >= 2:
        return "Dependency Collapse"
    if module_delta > 4 and coupling_delta > 0:
        return "Feature Accretion"
    if last.module_count <= first.module_count and last.churn_score > first.churn_score * 2:
        return "Rewrite Pressure"
    return "Steady Modular Growth"


def _forecast(snapshots: list[Snapshot], turning_points: list[TurningPoint] | None = None) -> Forecast:
    if not snapshots:
        return Forecast(
            coupling_pressure="unknown",
            churn_pressure="unknown",
            likely_bottlenecks=[],
            recommendation="Analyze a repository with commits to build an architectural forecast.",
        )
    recent = snapshots[-3:] if len(snapshots) >= 3 else snapshots
    first = recent[0].metrics
    last = recent[-1].metrics
    coupling_delta = last.coupling_score - first.coupling_score
    churn_avg = sum(snapshot.metrics.churn_score for snapshot in recent) / max(1, len(recent))
    coupling_pressure = "rising" if coupling_delta > 0.04 else "falling" if coupling_delta < -0.04 else "stable"
    churn_pressure = "high" if churn_avg > 500 else "moderate" if churn_avg > 120 else "low"
    bottlenecks = [node.id for node in sorted(snapshots[-1].nodes, key=lambda node: node.hotspot_score, reverse=True)[:5]]
    future_coupling = _linear_forecast([snapshot.metrics.coupling_score for snapshot in snapshots])
    future_density = _linear_forecast([snapshot.dna.graph_density if snapshot.dna else snapshot.metrics.coupling_score for snapshot in snapshots])
    future_dependency_concentration = _linear_forecast([snapshot.dna.dependency_concentration if snapshot.dna else 0 for snapshot in snapshots])
    future_hotspots = [node.id for node in sorted(snapshots[-1].nodes, key=lambda node: (node.hotspot_score, node.centrality), reverse=True)[:5]]
    if coupling_pressure == "rising":
        recommendation = "Inspect the highlighted bottlenecks before new feature work lands; coupling is trending upward."
    elif churn_pressure == "high":
        recommendation = "Stabilize churn hotspots with tests or boundaries before extending the architecture."
    else:
        recommendation = "The current trajectory looks stable; keep watching high-centrality modules for drift."
    supporting = [point.commit for point in (turning_points or [])[:3]]
    explanations = [
        CausalFinding(
            cause="linear evolution forecast",
            confidence=0.67 if len(snapshots) >= 4 else 0.48,
            affected_modules=future_hotspots,
            supporting_commits=supporting,
            evidence=[
                f"Observed coupling series: {[snapshot.metrics.coupling_score for snapshot in snapshots][-5:]}",
                f"Recent churn average: {churn_avg:.1f}",
                f"Latest dependency concentration: {(snapshots[-1].dna.dependency_concentration if snapshots[-1].dna else 0):.3f}",
            ],
            graph_statistics={
                "future_coupling": future_coupling,
                "future_graph_density": future_density,
                "future_dependency_concentration": future_dependency_concentration,
            },
        )
    ]
    return Forecast(
        coupling_pressure=coupling_pressure,
        churn_pressure=churn_pressure,
        likely_bottlenecks=bottlenecks,
        recommendation=recommendation,
        future_coupling=future_coupling,
        future_graph_density=future_density,
        future_dependency_concentration=future_dependency_concentration,
        future_hotspot_modules=future_hotspots,
        explanations=explanations,
    )


def _linear_forecast(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 4)
    xs = list(range(len(values)))
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(values)
    denominator = sum((x - x_mean) ** 2 for x in xs) or 1
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denominator
    return round(max(0.0, min(1.0, values[-1] + slope)), 4)


def _biography(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    archetype: str,
    forecast: Forecast,
) -> str:
    first = snapshots[0].metrics
    last = snapshots[-1].metrics
    midpoint = snapshots[len(snapshots) // 2].metrics
    central = forecast.likely_bottlenecks[:2]
    opening = "a tightly coupled application" if first.coupling_score > 0.45 else "a compact modular application"
    if last.coupling_score - first.coupling_score > 0.08:
        density_story = "Dependency density increased steadily before stabilizing around the latest snapshot."
    elif last.coupling_score < midpoint.coupling_score:
        density_story = "Dependency pressure rose during the middle of the lifecycle, then eased after later consolidation."
    else:
        density_story = "Dependency density stayed comparatively steady across the observed lifecycle."
    event_story = (
        f"{events[0].title} became the first major architectural turning point."
        if events
        else "No single architectural event permanently dominated the timeline."
    )
    central_text = ", ".join(central) if central else "no dominant subsystem"
    return (
        f"The repository began as {opening}. {event_story} "
        f"Module count moved from {first.module_count} to {last.module_count}, while complexity moved from "
        f"{first.complexity_proxy:.2f} to {last.complexity_proxy:.2f}. {density_story} "
        f"Today, architectural gravity centers on {central_text}, and the current shape most closely resembles {archetype.lower()}."
    )


def _evolution_story(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    fossils: list[ArchitecturalFossil],
) -> list[str]:
    if not snapshots:
        return ["No commits were available, so PulseCode could not infer an evolution story."]
    story = []
    first = snapshots[0]
    last = snapshots[-1]
    story.append(
        f"The system began as {first.species.name if first.species else 'an unclassified architecture'} "
        f"with {first.metrics.module_count} modules and {first.metrics.dependency_count} dependencies."
    )
    for previous, current in zip(snapshots, snapshots[1:]):
        coupling_delta = current.metrics.coupling_score - previous.metrics.coupling_score
        module_delta = current.metrics.module_count - previous.metrics.module_count
        if module_delta >= 3:
            story.append(f"At {current.label}, the architecture expanded by {module_delta} modules, indicating feature or boundary growth.")
        if coupling_delta > 0.08:
            hub = _top_affected_modules(current)[:2]
            story.append(f"At {current.label}, dependency pressure increased around {', '.join(hub)}.")
        elif coupling_delta < -0.05:
            story.append(f"At {current.label}, coupling eased, suggesting extraction or boundary repair.")
        if current.species and previous.species and current.species.name != previous.species.name:
            story.append(f"The system shifted from {previous.species.name} to {current.species.name} around {current.label}.")
    if fossils:
        story.append(f"{fossils[0].title} became the strongest architectural fossil with impact {fossils[0].impact_score:.1f}.")
    if events:
        story.append(f"{len(events)} architectural shockwave{'s' if len(events) != 1 else ''} changed the graph shape.")
    story.append(
        f"By the latest snapshot, the system is {last.species.name if last.species else 'unclassified'} "
        f"with {last.weather.condition if last.weather else 'unknown'} evolution outlook."
    )
    return story


def _detect_fossils(snapshots: list[Snapshot], events: list[ArchitectureEvent]) -> list[ArchitecturalFossil]:
    fossils: list[ArchitecturalFossil] = []
    if not snapshots:
        return fossils

    hub_snapshot = max(snapshots, key=lambda snapshot: snapshot.dna.centralization_score if snapshot.dna else 0)
    hub_node = _top_affected_modules(hub_snapshot)[:1]
    if hub_node and hub_snapshot.dna and hub_snapshot.dna.centralization_score > 0.25:
        fossils.append(
            _fossil(
                "First Dependency Hub",
                hub_snapshot,
                f"{hub_node[0]} became a central architectural gravity point.",
                hub_snapshot.dna.centralization_score * 100,
                hub_node,
            )
        )

    if len(snapshots) > 1:
        largest_coupling = max(
            zip(snapshots, snapshots[1:]),
            key=lambda pair: pair[1].metrics.coupling_score - pair[0].metrics.coupling_score,
        )
        delta = largest_coupling[1].metrics.coupling_score - largest_coupling[0].metrics.coupling_score
        if delta > 0:
            fossils.append(
                _fossil(
                    "Largest Coupling Increase",
                    largest_coupling[1],
                    f"Coupling increased by {delta:.3f} from {largest_coupling[0].label} to {largest_coupling[1].label}.",
                    delta * 100,
                    _top_affected_modules(largest_coupling[1])[:4],
                )
            )

        largest_reduction = max(
            zip(snapshots, snapshots[1:]),
            key=lambda pair: pair[0].metrics.complexity_proxy - pair[1].metrics.complexity_proxy,
        )
        reduction = largest_reduction[0].metrics.complexity_proxy - largest_reduction[1].metrics.complexity_proxy
        if reduction > 0:
            fossils.append(
                _fossil(
                    "Largest Complexity Reduction",
                    largest_reduction[1],
                    f"Complexity dropped by {reduction:.2f}, suggesting cleanup or extraction.",
                    reduction * 12,
                    _top_affected_modules(largest_reduction[1])[:4],
                )
            )

    refactor_snapshot = max(snapshots, key=lambda snapshot: snapshot.metrics.churn_score)
    if refactor_snapshot.metrics.churn_score > 0:
        fossils.append(
            _fossil(
                "Largest Refactor",
                refactor_snapshot,
                f"Snapshot churn reached {refactor_snapshot.metrics.churn_score} changed lines.",
                min(100, refactor_snapshot.metrics.churn_score / 10),
                _top_affected_modules(refactor_snapshot)[:4],
            )
        )

    shared = next(
        (
            snapshot
            for snapshot in snapshots
            if any("shared" in node.id.lower() or "core" in node.id.lower() or "util" in node.id.lower() for node in snapshot.nodes)
        ),
        None,
    )
    if shared:
        fossils.append(
            _fossil(
                "Introduction of Shared Module",
                shared,
                "A core/shared utility surface appeared and began shaping dependencies.",
                54,
                [node.id for node in shared.nodes if "shared" in node.id.lower() or "core" in node.id.lower() or "util" in node.id.lower()][:4],
            )
        )

    for event in events:
        fossils.append(
            ArchitecturalFossil(
                title=event.title or f"Architectural Shockwave at t={event.index}",
                snapshot_index=event.index,
                timestamp=event.timestamp,
                reason=event.explanation,
                impact_score=event.influence_score or round(abs(event.delta.get("dependency_count", 0)) + abs(event.delta.get("coupling_score", 0)) * 100, 1),
                commit=event.causal_commits[0] if event.causal_commits else None,
                affected_modules=event.affected_modules,
            )
        )

    unique: dict[str, ArchitecturalFossil] = {}
    for fossil in fossils:
        key = f"{fossil.title}:{fossil.snapshot_index}"
        unique[key] = fossil
    return sorted(unique.values(), key=lambda fossil: fossil.impact_score, reverse=True)[:8]


def _fossil(title: str, snapshot: Snapshot, reason: str, impact: float, modules: list[str]) -> ArchitecturalFossil:
    commit = max(snapshot.commits, key=lambda item: item.insertions + item.deletions, default=None)
    return ArchitecturalFossil(
        title=title,
        snapshot_index=snapshot.index,
        timestamp=snapshot.timestamp,
        reason=reason,
        impact_score=round(float(impact), 1),
        commit=commit,
        affected_modules=modules,
    )


def _report_markdown(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    fossils: list[ArchitecturalFossil],
    turning_points: list[TurningPoint],
    memories: list[ArchitecturalMemory],
    influence_graph: InfluenceGraph,
    decisions: list[ArchitecturalDecision],
    decision_influence_graph: InfluenceGraph,
    family_tree: ModuleFamilyTree,
    evolution_score: int,
    summary: str,
    archetype: str,
    forecast: Forecast,
    biography: str,
    story: list[str],
) -> str:
    latest = snapshots[-1] if snapshots else None
    lines = [
        "# PulseCode Evolution Report",
        "",
        f"**Evolution score:** {evolution_score}/100",
        f"**Archetype:** {archetype}",
        f"**Snapshots:** {len(snapshots)}",
        f"**Latest species:** {latest.species.name if latest and latest.species else 'Unknown'}",
        f"**Evolution outlook:** {latest.weather.condition if latest and latest.weather else 'Unknown'}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Biography",
        "",
        biography,
        "",
        "## Architectural Decisions",
        "",
        *(_decision_lines(decisions)),
        "",
        "## Architectural Butterfly Effects",
        "",
        *(_butterfly_lines(decisions)),
        "",
        "## Architectural Family Tree",
        "",
        f"- Modules tracked: {len(family_tree.nodes)}",
        f"- Genealogy links: {len(family_tree.edges)}",
        *[f"- {edge.source} → {edge.target}: {edge.relationship} ({edge.confidence:.2f})" for edge in family_tree.edges[:8]],
        "",
        "## Evolution Story",
        "",
        *[f"- {line}" for line in story],
        "",
        "## Architecture DNA",
        "",
        *(_dna_lines(latest) if latest else ["No DNA available."]),
        "",
        "## Evolution Outlook",
        "",
        f"- Coupling pressure: {forecast.coupling_pressure}",
        f"- Churn pressure: {forecast.churn_pressure}",
        f"- Likely bottlenecks: {', '.join(forecast.likely_bottlenecks) or 'none'}",
        f"- Recommendation: {forecast.recommendation}",
        "",
        "## Major Fossils",
        "",
        *(_fossil_lines(fossils)),
        "",
        "## Architectural Memories",
        "",
        *(_memory_lines(memories)),
        "",
        "## Turning Points",
        "",
        *(_turning_point_lines(turning_points)),
        "",
        "## Major Causal Chains",
        "",
        *(_influence_lines(influence_graph)),
        "",
        "## Decision Influence Chains",
        "",
        *(_influence_lines(decision_influence_graph)),
        "",
        "## Forecast",
        "",
        f"- Future coupling: {forecast.future_coupling}",
        f"- Future graph density: {forecast.future_graph_density}",
        f"- Future dependency concentration: {forecast.future_dependency_concentration}",
        f"- Future hotspot modules: {', '.join(forecast.future_hotspot_modules) or 'none'}",
        "",
        "## Coupling Growth",
        "",
        f"- Coupling moved from {snapshots[0].metrics.coupling_score if snapshots else 0} to {latest.metrics.coupling_score if latest else 0}.",
        f"- Dependency count moved from {snapshots[0].metrics.dependency_count if snapshots else 0} to {latest.metrics.dependency_count if latest else 0}.",
        "",
        "## Complexity Trends",
        "",
        f"- Complexity proxy moved from {snapshots[0].metrics.complexity_proxy if snapshots else 0} to {latest.metrics.complexity_proxy if latest else 0}.",
        f"- Hotspot modules: {', '.join(forecast.future_hotspot_modules[:5]) or 'none'}",
        "",
        "## Recommendations",
        "",
        *(_suggested_refactors(forecast, memories, turning_points)),
        "",
        "## Major Architectural Events",
        "",
    ]
    if not events:
        lines.append("No architectural shift events were detected.")
    for event in events:
        commits = ", ".join(f"{commit.sha} {commit.message}" for commit in event.causal_commits) or "No direct causal commit isolated"
        lines.extend(
            [
                f"### {event.title or f't={event.index}'} ({event.severity})",
                "",
                event.explanation,
                "",
                f"**Influence score:** {event.influence_score:.1f}",
                "",
                f"**Likely causes:** {', '.join(cause.cause for cause in event.causes) or 'Unknown'}",
                "",
                f"**Affected modules:** {', '.join(event.affected_modules)}",
                "",
                f"**Causal commits:** {commits}",
                "",
            ]
        )
    return "\n".join(lines)


def _report_html(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    fossils: list[ArchitecturalFossil],
    turning_points: list[TurningPoint],
    memories: list[ArchitecturalMemory],
    influence_graph: InfluenceGraph,
    decisions: list[ArchitecturalDecision],
    decision_influence_graph: InfluenceGraph,
    family_tree: ModuleFamilyTree,
    evolution_score: int,
    summary: str,
    archetype: str,
    forecast: Forecast,
    biography: str,
    story: list[str],
) -> str:
    latest = snapshots[-1] if snapshots else None
    dna_rows = "".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in (latest.dna.model_dump().items() if latest and latest.dna else []))
    fossil_rows = "".join(
        f"<tr><td>{fossil.title}</td><td>t={fossil.snapshot_index}</td><td>{fossil.impact_score:.1f}</td><td>{fossil.reason}</td></tr>"
        for fossil in fossils
    )
    event_rows = "".join(
        f"<tr><td>{event.title or f't={event.index}'}</td><td>{event.influence_score:.1f}</td><td>{event.explanation}<br><strong>Causes:</strong> {', '.join(cause.cause for cause in event.causes)}</td></tr>"
        for event in events
    )
    memory_rows = "".join(
        f"<tr><td>{memory.title}</td><td>{memory.influence_score:.1f}</td><td>{memory.reason}</td></tr>"
        for memory in memories
    )
    turning_rows = "".join(
        f"<tr><td>{point.commit.sha}</td><td>{point.impact_score:.1f}</td><td>{point.reason}</td></tr>"
        for point in turning_points[:12]
    )
    influence_rows = "".join(
        f"<tr><td>t={edge.source_event} → t={edge.target_event}</td><td>{edge.influence_type}</td><td>{edge.explanation}</td></tr>"
        for edge in influence_graph.edges
    )
    decision_rows = "".join(
        f"<tr><td>{decision.title}</td><td>{decision.architectural_impact_score:.1f}</td><td>{decision.summary}</td></tr>"
        for decision in decisions[:12]
    )
    decision_influence_rows = "".join(
        f"<tr><td>t={edge.source_event} → t={edge.target_event}</td><td>{edge.influence_type}</td><td>{edge.explanation}</td></tr>"
        for edge in decision_influence_graph.edges
    )
    family_rows = "".join(
        f"<tr><td>{edge.source}</td><td>{edge.target}</td><td>{edge.relationship}</td><td>{edge.explanation}</td></tr>"
        for edge in family_tree.edges[:20]
    )
    story_items = "".join(f"<li>{line}</li>" for line in story)
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>PulseCode Evolution Report</title>
  <style>
    body {{ font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #151814; margin: 48px; line-height: 1.5; }}
    h1, h2 {{ letter-spacing: 0; }}
    .hero {{ border-bottom: 1px solid #ddd6c8; padding-bottom: 24px; margin-bottom: 28px; }}
    .score {{ font-size: 44px; font-weight: 800; color: #536b49; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 28px; }}
    th, td {{ border: 1px solid #ddd6c8; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f5f2ea; }}
    .pill {{ display: inline-block; background: #f5f2ea; border: 1px solid #ddd6c8; padding: 6px 10px; border-radius: 6px; margin-right: 8px; }}
    @media print {{ body {{ margin: 28px; }} }}
  </style>
</head>
<body>
  <section class="hero">
    <div class="score">{evolution_score}/100</div>
    <h1>PulseCode Evolution Report</h1>
    <span class="pill">{archetype}</span>
    <span class="pill">{latest.species.name if latest and latest.species else 'Unknown species'}</span>
    <span class="pill">{latest.weather.condition if latest and latest.weather else 'Unknown outlook'}</span>
  </section>
  <h2>Repository Overview</h2>
  <p>{summary}</p>
  <p>{biography}</p>
  <h2>Architectural Decisions</h2>
  <table><tr><th>Decision</th><th>Impact</th><th>Summary</th></tr>{decision_rows}</table>
  <h2>Architectural Family Tree</h2>
  <p>Modules tracked: {len(family_tree.nodes)}; genealogy links: {len(family_tree.edges)}.</p>
  <table><tr><th>From</th><th>To</th><th>Relationship</th><th>Evidence</th></tr>{family_rows}</table>
  <h2>Architecture DNA</h2>
  <table>{dna_rows}</table>
  <h2>Evolution Timeline</h2>
  <ul>{story_items}</ul>
  <h2>Major Fossils</h2>
  <table><tr><th>Fossil</th><th>Snapshot</th><th>Impact</th><th>Reason</th></tr>{fossil_rows}</table>
  <h2>Architectural Memories</h2>
  <table><tr><th>Memory</th><th>Influence</th><th>Reason</th></tr>{memory_rows}</table>
  <h2>Turning Points</h2>
  <table><tr><th>Commit</th><th>Impact</th><th>Reason</th></tr>{turning_rows}</table>
  <h2>Major Causal Chains</h2>
  <table><tr><th>Chain</th><th>Type</th><th>Evidence</th></tr>{influence_rows}</table>
  <h2>Decision Influence Chains</h2>
  <table><tr><th>Chain</th><th>Type</th><th>Evidence</th></tr>{decision_influence_rows}</table>
  <h2>Major Architectural Events</h2>
  <table><tr><th>Event</th><th>Influence</th><th>Explanation</th></tr>{event_rows}</table>
  <h2>Coupling Growth</h2>
  <p>Latest dependency count: {latest.metrics.dependency_count if latest else 0}</p>
  <h2>Complexity Trends</h2>
  <p>Latest complexity proxy: {latest.metrics.complexity_proxy if latest else 0}</p>
  <h2>Evolution Outlook</h2>
  <p>{forecast.recommendation}</p>
  <h2>Future Risks</h2>
  <p>Likely bottlenecks: {', '.join(forecast.likely_bottlenecks) or 'none'}</p>
  <p>Future coupling: {forecast.future_coupling}; future density: {forecast.future_graph_density}; future dependency concentration: {forecast.future_dependency_concentration}.</p>
  <h2>Recommendations</h2>
  <ul>{"".join(f"<li>{item}</li>" for item in _suggested_refactors(forecast, memories, turning_points))}</ul>
</body>
</html>"""


def _dna_lines(snapshot: Snapshot) -> list[str]:
    if not snapshot.dna:
        return ["No DNA available."]
    return [f"- {key.replace('_', ' ').title()}: {value}" for key, value in snapshot.dna.model_dump().items()]


def _fossil_lines(fossils: list[ArchitecturalFossil]) -> list[str]:
    if not fossils:
        return ["No architectural fossils were detected."]
    return [f"- **{fossil.title}** at t={fossil.snapshot_index}: {fossil.reason} Impact {fossil.impact_score:.1f}." for fossil in fossils]


def _memory_lines(memories: list[ArchitecturalMemory]) -> list[str]:
    if not memories:
        return ["No persistent architectural memories were detected."]
    return [
        f"- **{memory.title}**: influence {memory.influence_score:.1f}, still influences {memory.still_influences_percent:.1f}% of the latest graph signal. {memory.reason}"
        for memory in memories
    ]


def _decision_lines(decisions: list[ArchitecturalDecision]) -> list[str]:
    if not decisions:
        return ["No architectural decisions were isolated."]
    lines = []
    for decision in decisions[:12]:
        commits = ", ".join(commit.sha for commit in decision.supporting_commits[:4]) or "none isolated"
        lines.append(
            f"- **{decision.title}** ({decision.architectural_impact_score:.1f}, confidence {decision.confidence:.2f}): "
            f"{decision.summary} Supporting commits: {commits}."
        )
    return lines


def _butterfly_lines(decisions: list[ArchitecturalDecision]) -> list[str]:
    if not decisions:
        return ["No butterfly effects were isolated."]
    return [
        f"- **{decision.title}**: immediate {decision.butterfly_effect.immediate_impact:.1f}, "
        f"medium {decision.butterfly_effect.medium_term_impact:.1f}, long {decision.butterfly_effect.long_term_impact:.1f}; "
        f"radius {decision.butterfly_effect.influence_radius}; future modules {', '.join(decision.butterfly_effect.future_modules_affected[:5]) or 'none'}."
        for decision in decisions[:10]
    ]


def _turning_point_lines(turning_points: list[TurningPoint]) -> list[str]:
    if not turning_points:
        return ["No turning points were detected."]
    return [
        f"- **{point.commit.sha}** ({point.impact_score:.1f}): {point.reason} {' '.join(point.future_effects[:2])}"
        for point in turning_points[:12]
    ]


def _influence_lines(influence_graph: InfluenceGraph) -> list[str]:
    if not influence_graph.edges:
        return ["No event-to-event influence chain was strong enough to isolate."]
    return [
        f"- t={edge.source_event} → t={edge.target_event} ({edge.confidence:.2f}): {edge.explanation}"
        for edge in influence_graph.edges
    ]


def _suggested_refactors(
    forecast: Forecast,
    memories: list[ArchitecturalMemory],
    turning_points: list[TurningPoint],
) -> list[str]:
    suggestions = []
    if forecast.future_coupling and forecast.future_coupling > 0.55:
        suggestions.append("Introduce an explicit boundary around the forecast hotspot modules before coupling crosses the high-risk range.")
    if forecast.future_dependency_concentration and forecast.future_dependency_concentration > 0.45:
        suggestions.append("Split or document dependency hub responsibilities; dependency concentration is forecast to remain high.")
    for memory in memories[:2]:
        suggestions.append(f"Review {memory.title}: it still exerts architectural memory and may need a clearer ownership boundary.")
    if turning_points:
        suggestions.append(f"Use {turning_points[0].commit.sha} as a case study for future refactors; it had the highest long-term influence.")
    return suggestions or ["No urgent refactor is suggested; continue monitoring forecast hotspots."]


def _shockwave(snapshot: Snapshot, affected: list[str]) -> dict[str, list[str]]:
    graph = nx.Graph()
    for node in snapshot.nodes:
        graph.add_node(node.id)
    for edge in snapshot.edges:
        graph.add_edge(edge.source, edge.target)

    commit_files: set[str] = set()
    for commit in snapshot.commits:
        commit_files.update(file for file in commit.files_changed if file in graph)
    changed = [file for file in commit_files if file in affected or not affected][:8]
    if not changed:
        changed = affected[:4]

    neighbors: set[str] = set()
    outer: set[str] = set()
    for file in changed:
        if file not in graph:
            continue
        first_ring = set(graph.neighbors(file))
        neighbors.update(first_ring)
        for neighbor in first_ring:
            outer.update(graph.neighbors(neighbor))
    return {
        "commit": [commit.sha for commit in snapshot.commits[:3]],
        "changed_files": changed,
        "neighbor_modules": sorted(neighbors.difference(changed))[:12],
        "graph": sorted(outer.difference(neighbors).difference(changed))[:18],
    }


def _modularity(graph: nx.Graph) -> float:
    if graph.number_of_nodes() < 3 or graph.number_of_edges() == 0:
        return 0.0
    try:
        communities = list(nx.community.greedy_modularity_communities(graph))
        return max(0.0, nx.community.modularity(graph, communities))
    except Exception:
        return 0.0


def _average_dependency_depth(graph: nx.Graph) -> float:
    if graph.number_of_nodes() < 2 or graph.number_of_edges() == 0:
        return 0.0
    lengths: list[int] = []
    for component in nx.connected_components(graph):
        subgraph = graph.subgraph(component)
        if subgraph.number_of_nodes() < 2:
            continue
        path_lengths = dict(nx.all_pairs_shortest_path_length(subgraph, cutoff=6))
        for source, targets in path_lengths.items():
            lengths.extend(distance for target, distance in targets.items() if target != source)
    return sum(lengths) / max(1, len(lengths))


def _gini(values: list[float] | list[int]) -> float:
    cleaned = sorted(float(value) for value in values if value >= 0)
    if not cleaned or sum(cleaned) == 0:
        return 0.0
    total = sum(cleaned)
    weighted = sum((index + 1) * value for index, value in enumerate(cleaned))
    count = len(cleaned)
    return (2 * weighted) / (count * total) - (count + 1) / count


def _spike_threshold(snapshots: list[Snapshot], index: int, field: str) -> float:
    previous = [getattr(snapshot.metrics, field) for snapshot in snapshots[:index]]
    if not previous:
        return float("inf")
    mean = statistics.fmean(previous)
    deviation = statistics.pstdev(previous) if len(previous) > 1 else 0
    return float(mean + deviation * 1.4)


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


def _import_edges(repo_path: Path, files: set[str]) -> set[tuple[str, str]]:
    cache_key = (str(repo_path), tuple(sorted(files)))
    if cache_key in _IMPORT_EDGE_CACHE:
        return _IMPORT_EDGE_CACHE[cache_key]
    edges: set[tuple[str, str]] = set()
    module_map = {_module_name(file): file for file in files}
    basename_map: dict[str, list[str]] = defaultdict(list)
    for file in files:
        basename_map[Path(file).stem].append(file)

    for file in files:
        try:
            content = (repo_path / file).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        imports = _python_imports(content) if Path(file).suffix == ".py" else _js_ts_imports(content)
        for imported in imports:
            target = _resolve_import(imported, file, module_map, basename_map)
            if target and target != file:
                edges.add(tuple(sorted((file, target))))
    _IMPORT_EDGE_CACHE[cache_key] = edges
    return edges


def _python_imports(content: str) -> set[str]:
    imports: set[str] = set()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("import "):
            for name in stripped.replace("import ", "", 1).split(","):
                imports.add(name.strip().split(" as ")[0])
        elif stripped.startswith("from ") and " import " in stripped:
            imports.add(stripped.split(" import ", 1)[0].replace("from ", "", 1).strip())
    return imports


def _js_ts_imports(content: str) -> set[str]:
    imports = set(re.findall(r"(?:from\s+|import\s*\(?\s*)[\"']([^\"']+)[\"']", content))
    return {item for item in imports if item.startswith(".") or "/" in item}


def _resolve_import(
    imported: str,
    source_file: str,
    module_map: dict[str, str],
    basename_map: dict[str, list[str]],
) -> str | None:
    normalized = imported.strip(".").replace("/", ".")
    if imported.startswith("."):
        source_parts = Path(source_file).with_suffix("").parts[:-1]
        normalized = ".".join((*source_parts, normalized))
    if normalized in module_map:
        return module_map[normalized]
    candidates = [path for module, path in module_map.items() if module.endswith(f".{normalized}") or module == normalized]
    if len(candidates) == 1:
        return candidates[0]
    basename = normalized.split(".")[-1]
    if len(basename_map.get(basename, [])) == 1:
        return basename_map[basename][0]
    return None


def _module_name(path: str) -> str:
    return str(Path(path).with_suffix("")).replace("/", ".")
