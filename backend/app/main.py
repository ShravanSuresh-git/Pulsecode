from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .models import AnalysisResult
from .sample_repo import ensure_sample_repo
from .storage import analyses
from .timeline import analyze_repository


class AnalyzeRequest(BaseModel):
    repo_path: str = Field(..., min_length=1)
    snapshot_size: int = Field(default=8, ge=2, le=50)


app = FastAPI(title="PulseCode API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "PulseCode", "status": "ready"}


@app.get("/sample-repo")
def sample_repo() -> dict[str, str]:
    path = ensure_sample_repo()
    return {"repo_path": str(path), "name": path.name}


@app.post("/analyze")
def analyze(payload: AnalyzeRequest) -> dict[str, str | int]:
    repo_path = Path(payload.repo_path).expanduser().resolve()
    if not repo_path.exists():
        raise HTTPException(status_code=400, detail="Repository path does not exist")
    if not (repo_path / ".git").exists():
        raise HTTPException(status_code=400, detail="Path must point to a Git repository")

    try:
        result = analyze_repository(repo_path, payload.snapshot_size)
    except Exception as exc:  # pragma: no cover - returned to UI as actionable feedback
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    analyses[result.repo_id] = result
    return {
        "repo_id": result.repo_id,
        "snapshot_count": len(result.snapshots),
        "event_count": len(result.events),
    }


@app.get("/timeline/{repo_id}")
def timeline(repo_id: str) -> dict:
    analysis = _get_analysis(repo_id)
    return {
        "repo_id": analysis.repo_id,
        "repo_name": analysis.repo_name,
        "repo_path": analysis.repo_path,
        "snapshots": [
            {
                "index": snapshot.index,
                "label": snapshot.label,
                "timestamp": snapshot.timestamp,
                "commit_count": len(snapshot.commits),
                "metrics": snapshot.metrics.model_dump(),
            }
            for snapshot in analysis.snapshots
        ],
    }


@app.get("/snapshot/{repo_id}/{index}")
def snapshot(repo_id: str, index: int) -> dict:
    analysis = _get_analysis(repo_id)
    if index < 0 or index >= len(analysis.snapshots):
        raise HTTPException(status_code=404, detail="Snapshot index is out of range")
    return analysis.snapshots[index].model_dump()


@app.get("/events/{repo_id}")
def events(repo_id: str) -> dict:
    analysis = _get_analysis(repo_id)
    return {"repo_id": repo_id, "events": [event.model_dump() for event in analysis.events]}


@app.get("/health/{repo_id}")
def health(repo_id: str) -> dict:
    analysis = _get_analysis(repo_id)
    return analysis.health.model_dump()


@app.get("/report/{repo_id}")
def report(repo_id: str) -> dict[str, str]:
    analysis = _get_analysis(repo_id)
    return {"repo_id": repo_id, "markdown": analysis.health.report_markdown}


def _get_analysis(repo_id: str) -> AnalysisResult:
    analysis = analyses.get(repo_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Unknown repo_id. Run /analyze first.")
    return analysis
