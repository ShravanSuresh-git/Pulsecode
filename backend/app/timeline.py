from __future__ import annotations

import hashlib
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import networkx as nx
from git import Commit, Repo

from .models import (
    AnalysisResult,
    ArchitecturalFossil,
    ArchitecturalWeather,
    ArchitectureDNA,
    ArchitectureEvent,
    CommitInfo,
    Forecast,
    GraphEdge,
    GraphNode,
    Health,
    Snapshot,
    SnapshotMetrics,
    SpeciesClassification,
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
    snapshots = _build_snapshots(repo_path, commit_infos, snapshot_size)
    _enrich_snapshots(snapshots)
    events = _detect_events(snapshots)
    fossils = _detect_fossils(snapshots, events)
    health = _build_health(snapshots, events, fossils)

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
    return ArchitectureDNA(
        modularity=round(modularity, 3),
        coupling=round(min(1, metrics.coupling_score), 3),
        dependency_concentration=round(_gini(degrees), 3),
        graph_density=round(metrics.coupling_score, 3),
        average_dependency_depth=round(avg_depth, 3),
        churn_concentration=round(_gini(churns), 3),
        hotspot_concentration=round(_gini(hotspots), 3),
        centralization_score=round(max(centralities) if centralities else 0, 3),
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
            return ArchitecturalWeather(condition="Sunny", severity=1, explanation="The starting architecture is stable and readable.")
        return ArchitecturalWeather(condition="Cloudy", severity=2, explanation="The starting architecture already shows structural pressure.")

    coupling_delta = snapshot.metrics.coupling_score - previous.metrics.coupling_score
    edge_delta = snapshot.metrics.dependency_count - previous.metrics.dependency_count
    quality_delta = snapshot.quality_score - previous.quality_score
    if coupling_delta > 0.18 or edge_delta > max(12, previous.metrics.dependency_count * 0.6):
        return ArchitecturalWeather(condition="Hurricane", severity=5, explanation="Dependency growth is explosive in this interval.")
    if coupling_delta > 0.08 or quality_delta < -18:
        return ArchitecturalWeather(condition="Storm", severity=4, explanation="Coupling rose quickly and architecture quality dropped.")
    if coupling_delta > 0.03 or edge_delta > 4:
        return ArchitecturalWeather(condition="Cloudy", severity=3, explanation="Dependency pressure is increasing.")
    if quality_delta > 10 or coupling_delta < -0.04:
        return ArchitecturalWeather(condition="Clearing", severity=1, explanation="Coupling pressure is easing.")
    return ArchitecturalWeather(condition="Sunny", severity=1, explanation="Architecture is evolving without a sharp pressure change.")


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
                    previous_index=previous.index,
                    timestamp=current.timestamp,
                    severity=severity,
                    explanation=f"Between {previous.label} and {current.label}, " + "; ".join(reasons) + ".",
                    affected_modules=affected,
                    causal_commits=_causal_commits(current.commits, affected),
                    before_metrics=previous.metrics,
                    after_metrics=current.metrics,
                    delta={
                        "coupling_score": round(density_delta, 4),
                        "dependency_count": float(edge_delta),
                        "churn_score": float(current.metrics.churn_score - previous.metrics.churn_score),
                        "complexity_proxy": round(current.metrics.complexity_proxy - previous.metrics.complexity_proxy, 2),
                    },
                    shockwave=_shockwave(current, affected),
                )
            )
    return events


def _build_health(snapshots: list[Snapshot], events: list[ArchitectureEvent], fossils: list[ArchitecturalFossil]) -> Health:
    if not snapshots:
        return Health(evolution_score=0, stability_trend=[], summary="No commits were available for analysis.")

    stability_trend = [float(snapshot.quality_score) for snapshot in snapshots]
    event_penalty = min(25, len(events) * 5)
    latest = stability_trend[-1] if stability_trend else 50
    evolution_score = int(max(0, min(100, latest - event_penalty)))
    summary = _summary(snapshots, events)
    archetype = _archetype(snapshots, events)
    forecast = _forecast(snapshots)
    biography = _biography(snapshots, events, archetype, forecast)
    story = _evolution_story(snapshots, events, fossils)
    report_markdown = _report_markdown(snapshots, events, fossils, evolution_score, summary, archetype, forecast, biography, story)
    report_html = _report_html(snapshots, events, fossils, evolution_score, summary, archetype, forecast, biography, story)
    return Health(
        evolution_score=evolution_score,
        stability_trend=stability_trend,
        summary=summary,
        archetype=archetype,
        forecast=forecast,
        biography=biography,
        story=story,
        fossils=fossils,
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


def _forecast(snapshots: list[Snapshot]) -> Forecast:
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
    if coupling_pressure == "rising":
        recommendation = "Inspect the highlighted bottlenecks before new feature work lands; coupling is trending upward."
    elif churn_pressure == "high":
        recommendation = "Stabilize churn hotspots with tests or boundaries before extending the architecture."
    else:
        recommendation = "The current trajectory looks stable; keep watching high-centrality modules for drift."
    return Forecast(
        coupling_pressure=coupling_pressure,
        churn_pressure=churn_pressure,
        likely_bottlenecks=bottlenecks,
        recommendation=recommendation,
    )


def _biography(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    archetype: str,
    forecast: Forecast,
) -> str:
    first = snapshots[0].metrics
    last = snapshots[-1].metrics
    central = forecast.likely_bottlenecks[:3]
    event_sentence = (
        f"It experienced {len(events)} notable structural shift{'s' if len(events) != 1 else ''}, "
        f"with the largest change around t={events[-1].index}."
        if events
        else "No abrupt structural break dominated the history."
    )
    central_text = ", ".join(central) if central else "no clear bottleneck"
    return (
        f"This codebase follows a {archetype.lower()} arc. It began with {first.module_count} modules "
        f"and now has {last.module_count}, while dependency density moved from {first.coupling_score:.3f} "
        f"to {last.coupling_score:.3f}. {event_sentence} Current architectural gravity centers on {central_text}."
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
        f"with {last.weather.condition if last.weather else 'unknown'} architectural weather."
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
                title=f"Architectural Shockwave at t={event.index}",
                snapshot_index=event.index,
                timestamp=event.timestamp,
                reason=event.explanation,
                impact_score=round(abs(event.delta.get("dependency_count", 0)) + abs(event.delta.get("coupling_score", 0)) * 100, 1),
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
        f"**Latest weather:** {latest.weather.condition if latest and latest.weather else 'Unknown'}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Biography",
        "",
        biography,
        "",
        "## Evolution Story",
        "",
        *[f"- {line}" for line in story],
        "",
        "## Architecture DNA",
        "",
        *(_dna_lines(latest) if latest else ["No DNA available."]),
        "",
        "## Architectural Weather",
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
        "## Shift Events",
        "",
    ]
    if not events:
        lines.append("No architectural shift events were detected.")
    for event in events:
        commits = ", ".join(f"{commit.sha} {commit.message}" for commit in event.causal_commits) or "No direct causal commit isolated"
        lines.extend(
            [
                f"### t={event.index} ({event.severity})",
                "",
                event.explanation,
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
        f"<tr><td>t={event.index}</td><td>{event.severity}</td><td>{event.explanation}</td></tr>"
        for event in events
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
    <span class="pill">{latest.weather.condition if latest and latest.weather else 'Unknown weather'}</span>
  </section>
  <h2>Repository Overview</h2>
  <p>{summary}</p>
  <p>{biography}</p>
  <h2>Architecture DNA</h2>
  <table>{dna_rows}</table>
  <h2>Evolution Timeline</h2>
  <ul>{story_items}</ul>
  <h2>Major Fossils</h2>
  <table><tr><th>Fossil</th><th>Snapshot</th><th>Impact</th><th>Reason</th></tr>{fossil_rows}</table>
  <h2>Architectural Events</h2>
  <table><tr><th>Snapshot</th><th>Severity</th><th>Explanation</th></tr>{event_rows}</table>
  <h2>Dependency Growth</h2>
  <p>Latest dependency count: {latest.metrics.dependency_count if latest else 0}</p>
  <h2>Complexity Growth</h2>
  <p>Latest complexity proxy: {latest.metrics.complexity_proxy if latest else 0}</p>
  <h2>Architectural Weather</h2>
  <p>{forecast.recommendation}</p>
  <h2>Future Risks</h2>
  <p>Likely bottlenecks: {', '.join(forecast.likely_bottlenecks) or 'none'}</p>
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
