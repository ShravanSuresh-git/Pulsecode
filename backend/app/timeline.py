from __future__ import annotations

import hashlib
import math
import re
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
    Forecast,
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
    snapshots = _build_snapshots(repo_path, commit_infos, snapshot_size)
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
    archetype = _archetype(snapshots, events)
    forecast = _forecast(snapshots)
    biography = _biography(snapshots, events, archetype, forecast)
    return Health(
        evolution_score=evolution_score,
        stability_trend=stability_trend,
        summary=summary,
        archetype=archetype,
        forecast=forecast,
        biography=biography,
        report_markdown=_report_markdown(snapshots, events, evolution_score, summary, archetype, forecast, biography),
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


def _report_markdown(
    snapshots: list[Snapshot],
    events: list[ArchitectureEvent],
    evolution_score: int,
    summary: str,
    archetype: str,
    forecast: Forecast,
    biography: str,
) -> str:
    lines = [
        "# PulseCode Evolution Report",
        "",
        f"**Evolution score:** {evolution_score}/100",
        f"**Archetype:** {archetype}",
        f"**Snapshots:** {len(snapshots)}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Biography",
        "",
        biography,
        "",
        "## Architectural Weather",
        "",
        f"- Coupling pressure: {forecast.coupling_pressure}",
        f"- Churn pressure: {forecast.churn_pressure}",
        f"- Likely bottlenecks: {', '.join(forecast.likely_bottlenecks) or 'none'}",
        f"- Recommendation: {forecast.recommendation}",
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
