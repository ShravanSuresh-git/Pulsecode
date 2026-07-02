from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from git import Repo

from backend.app.models import ArchitectureDNA, ArchitectureEvent, Snapshot, SnapshotMetrics
from backend.app.timeline import _commit_info, _counterfactuals


class CounterfactualReplayTests(unittest.TestCase):
    def test_merge_commit_replays_with_mainline_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "repo"
            repo_path.mkdir()
            self._git(repo_path, "init")
            self._git(repo_path, "checkout", "-b", "main")
            self._git(repo_path, "config", "user.email", "pulsecode@example.test")
            self._git(repo_path, "config", "user.name", "PulseCode Test")

            (repo_path / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
            self._git(repo_path, "add", "app.py")
            self._git(repo_path, "commit", "-m", "base")
            repo = Repo(repo_path)
            base = _commit_info(repo, repo.head.commit)

            self._git(repo_path, "checkout", "-b", "feature")
            (repo_path / "feature.py").write_text("from app import VALUE\n", encoding="utf-8")
            self._git(repo_path, "add", "feature.py")
            self._git(repo_path, "commit", "-m", "add feature module")

            self._git(repo_path, "checkout", "main")
            (repo_path / "event.py").write_text("from app import VALUE\n", encoding="utf-8")
            self._git(repo_path, "add", "event.py")
            self._git(repo_path, "commit", "-m", "event module")
            repo = Repo(repo_path)
            event_commit = _commit_info(repo, repo.head.commit)

            self._git(repo_path, "merge", "--no-ff", "feature", "-m", "merge feature")
            repo = Repo(repo_path)
            merge_commit = _commit_info(repo, repo.head.commit)

            previous = Snapshot(
                index=0,
                label="t=0",
                timestamp=base.timestamp,
                commits=[base],
                nodes=[],
                edges=[],
                metrics=SnapshotMetrics(
                    churn_score=1,
                    coupling_score=0,
                    module_count=1,
                    dependency_count=0,
                    complexity_proxy=1,
                    entropy=0,
                ),
                dna=self._dna(),
            )
            current = Snapshot(
                index=1,
                label="t=1",
                timestamp=merge_commit.timestamp,
                commits=[event_commit, merge_commit],
                nodes=[],
                edges=[],
                metrics=SnapshotMetrics(
                    churn_score=3,
                    coupling_score=0.5,
                    module_count=3,
                    dependency_count=2,
                    complexity_proxy=2,
                    entropy=0,
                ),
                dna=self._dna(coupling=0.5),
            )
            event = ArchitectureEvent(
                index=1,
                previous_index=0,
                timestamp=merge_commit.timestamp,
                severity="medium",
                explanation="Synthetic event followed by a merge commit.",
                affected_modules=["event.py"],
                causal_commits=[event_commit],
                before_metrics=previous.metrics,
                after_metrics=current.metrics,
                delta={"coupling_score": 0.5, "dependency_count": 2, "complexity_proxy": 1},
            )

            [estimate] = _counterfactuals([event], [previous, current], repo_path)

            self.assertEqual(estimate.replay_status, "exact")
            self.assertIn("Exact git replay", estimate.approximation_note)

    def test_cherry_pick_conflict_returns_approximate_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "repo"
            repo_path.mkdir()
            self._git(repo_path, "init")
            self._git(repo_path, "config", "user.email", "pulsecode@example.test")
            self._git(repo_path, "config", "user.name", "PulseCode Test")

            source_file = repo_path / "app.py"
            source_file.write_text("value = 'base'\n", encoding="utf-8")
            self._git(repo_path, "add", "app.py")
            self._git(repo_path, "commit", "-m", "base")
            repo = Repo(repo_path)
            base = _commit_info(repo, repo.head.commit)

            source_file.write_text("value = 'event'\n", encoding="utf-8")
            self._git(repo_path, "commit", "-am", "event change")
            repo = Repo(repo_path)
            event_commit = _commit_info(repo, repo.head.commit)

            source_file.write_text("value = 'after'\n", encoding="utf-8")
            self._git(repo_path, "commit", "-am", "dependent change")
            repo = Repo(repo_path)
            dependent_commit = _commit_info(repo, repo.head.commit)

            previous = Snapshot(
                index=0,
                label="t=0",
                timestamp=base.timestamp,
                commits=[base],
                nodes=[],
                edges=[],
                metrics=SnapshotMetrics(
                    churn_score=1,
                    coupling_score=0,
                    module_count=1,
                    dependency_count=0,
                    complexity_proxy=1,
                    entropy=0,
                ),
                dna=self._dna(),
            )
            current = Snapshot(
                index=1,
                label="t=1",
                timestamp=dependent_commit.timestamp,
                commits=[event_commit, dependent_commit],
                nodes=[],
                edges=[],
                metrics=SnapshotMetrics(
                    churn_score=2,
                    coupling_score=0.4,
                    module_count=1,
                    dependency_count=1,
                    complexity_proxy=2,
                    entropy=0,
                ),
                dna=self._dna(coupling=0.4),
            )
            event = ArchitectureEvent(
                index=1,
                previous_index=0,
                timestamp=dependent_commit.timestamp,
                severity="medium",
                explanation="Synthetic event with dependent follow-up commit.",
                affected_modules=["app.py"],
                causal_commits=[event_commit],
                before_metrics=previous.metrics,
                after_metrics=current.metrics,
                delta={"coupling_score": 0.4, "dependency_count": 1, "complexity_proxy": 1},
            )

            [estimate] = _counterfactuals([event], [previous, current], repo_path)

            self.assertEqual(estimate.replay_status, "approximate")
            self.assertIn("cherry-picking", estimate.approximation_note)

    @staticmethod
    def _git(cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    @staticmethod
    def _dna(coupling: float = 0) -> ArchitectureDNA:
        return ArchitectureDNA(
            modularity=0,
            coupling=coupling,
            dependency_concentration=0,
            graph_density=coupling,
            average_dependency_depth=0,
            churn_concentration=0,
            hotspot_concentration=0,
            centralization_score=0,
        )


if __name__ == "__main__":
    unittest.main()
