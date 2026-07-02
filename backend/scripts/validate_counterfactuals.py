from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.timeline import analyze_repository


DEFAULT_REPOS = [
    "https://github.com/pallets/itsdangerous.git",
    "https://github.com/pallets/markupsafe.git",
    "https://github.com/theskumar/python-dotenv.git",
    "https://github.com/corydolphin/flask-cors.git",
    "https://github.com/jazzband/prettytable.git",
]

BASELINE_COMPARABLE_EVENTS = 30
BASELINE_EXACT_COMPARABLE_EVENTS = 3
BASELINE_CORRECT_EVENTS = 17


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PulseCode counterfactual replay on a small public corpus.")
    parser.add_argument("--workdir", default="/tmp/pulsecode-counterfactual-validation")
    parser.add_argument("--max-repos", type=int, default=5)
    parser.add_argument("--events", type=int, default=10)
    parser.add_argument("--snapshot-size", type=int, default=8)
    parser.add_argument("--output", default=str(ROOT / "backend/scripts/validation_results.md"))
    parser.add_argument("--repos", nargs="*", default=DEFAULT_REPOS)
    parser.add_argument(
        "--debug-replay-failures",
        action="store_true",
        help="Print replay fallback reasons without changing validation scoring.",
    )
    args = parser.parse_args()

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []

    for url in args.repos[: args.max_repos]:
        repo_path = workdir / repo_slug(url)
        try:
            ensure_repo(url, repo_path)
            result = analyze_repository(repo_path, args.snapshot_size)
            counterfactuals = {item.event_index: item for item in result.health.counterfactuals}
            for event in result.events[: args.events]:
                estimate = counterfactuals.get(event.index)
                if estimate is None:
                    continue
                if args.debug_replay_failures and estimate.replay_status != "exact":
                    print(
                        "REPLAY_DIAGNOSTIC"
                        f" repo={result.repo_name}"
                        f" snapshot={event.index}"
                        f" status={estimate.replay_status}"
                        f" event={event.title!r}"
                        f" reason={estimate.approximation_note}",
                        file=sys.stderr,
                    )
                predicted = contribution_direction(estimate)
                nearby = nearby_real_history_direction(result.snapshots, event.index)
                match = "unknown" if nearby == "unknown" or predicted == "steady" else str(predicted == nearby)
                rows.append(
                    {
                        "repo": result.repo_name,
                        "event": event.title or f"t={event.index}",
                        "predicted_direction": predicted,
                        "nearby_real_history_direction": nearby,
                        "match": match,
                        "replay_status": estimate.replay_status,
                        "causal_confidence": f"{estimate.causal_confidence:.2f}",
                    }
                )
        except Exception as exc:
            rows.append(
                {
                    "repo": repo_slug(url),
                    "event": "analysis failed",
                    "predicted_direction": "unknown",
                    "nearby_real_history_direction": "unknown",
                    "match": "unknown",
                    "replay_status": "failed",
                    "causal_confidence": "0.00",
                    "error": str(exc)[:140],
                }
            )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(output_path, rows)
    write_csv(output_path.with_suffix(".csv"), rows)
    print(f"Wrote {output_path}")
    return 0


def ensure_repo(url: str, path: Path) -> None:
    if (path / ".git").exists():
        subprocess.run(["git", "fetch", "--quiet", "--depth", "500", "origin"], cwd=path, check=False)
        return
    subprocess.run(["git", "clone", "--quiet", "--depth", "500", url, str(path)], check=True, timeout=120)


def repo_slug(url: str) -> str:
    return url.rstrip("/").removesuffix(".git").split("/")[-1]


def contribution_direction(estimate) -> str:
    # This is a sanity signal, not proof: it asks whether the counterfactual says the event contributed
    # upward or downward pressure relative to the actual measured snapshot.
    actual = estimate.actual.get("coupling", 0)
    alternative = estimate.alternative.get("coupling", actual)
    delta = actual - alternative
    if delta > 0.01:
        return "coupling_up"
    if delta < -0.01:
        return "coupling_down"
    return "steady"


def nearby_real_history_direction(snapshots, event_index: int) -> str:
    if event_index <= 0 or event_index >= len(snapshots):
        return "unknown"
    event_churn = snapshots[event_index].metrics.churn_score
    candidates = []
    for previous, current in zip(snapshots, snapshots[1:]):
        if current.index == event_index:
            continue
        delta = current.metrics.coupling_score - previous.metrics.coupling_score
        if abs(delta) < 0.01:
            continue
        candidates.append((abs(current.metrics.churn_score - event_churn), delta))
    if not candidates:
        return "unknown"
    _, delta = min(candidates, key=lambda item: item[0])
    return "coupling_up" if delta > 0 else "coupling_down"


def write_markdown(path: Path, rows: list[dict[str, str]]) -> None:
    known = [row for row in rows if row.get("match") in {"True", "False"}]
    correct = sum(1 for row in known if row["match"] == "True")
    accuracy = correct / len(known) if known else 0
    exact_known = [row for row in known if row.get("replay_status") == "exact"]
    exact_rate = len(exact_known) / len(known) if known else 0
    baseline_accuracy = BASELINE_CORRECT_EVENTS / BASELINE_COMPARABLE_EVENTS
    baseline_exact_rate = BASELINE_EXACT_COMPARABLE_EVENTS / BASELINE_COMPARABLE_EVENTS
    lines = [
        "# PulseCode Counterfactual Validation Results",
        "",
        "This is a small-corpus sanity check for counterfactual replay. It compares the replay-predicted direction of coupling pressure with a nearby real-history interval of similar churn. It is useful engineering evidence, not proof of causality.",
        "",
        "## Before/After Summary",
        "",
        f"- Exact replay rate before: {BASELINE_EXACT_COMPARABLE_EVENTS}/{BASELINE_COMPARABLE_EVENTS} ({baseline_exact_rate:.0%}), after: {len(exact_known)}/{len(known)} ({exact_rate:.0%})",
        f"- Sign agreement before: {BASELINE_CORRECT_EVENTS}/{BASELINE_COMPARABLE_EVENTS} ({baseline_accuracy:.0%}), after: {correct}/{len(known)} ({accuracy:.0%})",
        "- What changed: merge commits are now attempted with `git cherry-pick -m 1`, which increased exact replay coverage.",
        "- Outcome: sign agreement did not improve meaningfully and remains below 65%, so the corpus-stats endpoint is intentionally skipped for this milestone.",
        "",
        "## Current Results",
        "",
        f"- Repositories/events evaluated: {len(rows)}",
        f"- Comparable events: {len(known)}",
        f"- Sign agreement: {correct}/{len(known)} ({accuracy:.0%})",
        "",
        "| repo | event | predicted_direction | nearby_real_history_direction | match | replay_status | causal_confidence |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {repo} | {event} | {predicted_direction} | {nearby_real_history_direction} | {match} | {replay_status} | {causal_confidence} |".format(
                **{key: escape_md(str(value)) for key, value in row.items()}
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "repo",
        "event",
        "predicted_direction",
        "nearby_real_history_direction",
        "match",
        "replay_status",
        "causal_confidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
