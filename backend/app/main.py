from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
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
                "dna": snapshot.dna.model_dump() if snapshot.dna else None,
                "species": snapshot.species.model_dump() if snapshot.species else None,
                "weather": snapshot.weather.model_dump() if snapshot.weather else None,
                "quality_score": snapshot.quality_score,
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


@app.get("/dna/{repo_id}/{index}")
def dna(repo_id: str, index: int) -> dict:
    analysis = _get_analysis(repo_id)
    if index < 0 or index >= len(analysis.snapshots):
        raise HTTPException(status_code=404, detail="Snapshot index is out of range")
    snapshot = analysis.snapshots[index]
    return {
        "repo_id": repo_id,
        "index": index,
        "dna": snapshot.dna.model_dump() if snapshot.dna else None,
        "species": snapshot.species.model_dump() if snapshot.species else None,
        "weather": snapshot.weather.model_dump() if snapshot.weather else None,
        "quality_score": snapshot.quality_score,
    }


@app.get("/story/{repo_id}")
def story(repo_id: str) -> dict:
    analysis = _get_analysis(repo_id)
    return {"repo_id": repo_id, "story": analysis.health.story, "biography": analysis.health.biography}


@app.get("/fossils/{repo_id}")
def fossils(repo_id: str) -> dict:
    analysis = _get_analysis(repo_id)
    return {"repo_id": repo_id, "fossils": [fossil.model_dump() for fossil in analysis.health.fossils]}


@app.get("/health/{repo_id}")
def health(repo_id: str) -> dict:
    analysis = _get_analysis(repo_id)
    return analysis.health.model_dump()


@app.get("/report/{repo_id}")
def report(repo_id: str, format: str = Query(default="markdown", pattern="^(markdown|html|pdf)$")):
    analysis = _get_analysis(repo_id)
    if format == "html":
        return Response(analysis.health.report_html, media_type="text/html")
    if format == "pdf":
        return Response(_simple_pdf(analysis.health.report_markdown), media_type="application/pdf")
    return {
        "repo_id": repo_id,
        "markdown": analysis.health.report_markdown,
        "html": analysis.health.report_html,
    }


def _get_analysis(repo_id: str) -> AnalysisResult:
    analysis = analyses.get(repo_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Unknown repo_id. Run /analyze first.")
    return analysis


def _simple_pdf(text: str) -> bytes:
    # Minimal text-only PDF writer for local report export without adding a heavy dependency.
    safe_lines = [line[:95].replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in text.splitlines()[:52]]
    commands = ["BT", "/F1 10 Tf", "50 780 Td", "14 TL"]
    for line in safe_lines:
        commands.append(f"({line}) Tj")
        commands.append("T*")
    commands.append("ET")
    stream = "\n".join(commands).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in pdf))
        pdf.append(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = sum(len(part) for part in pdf)
    pdf.append(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.append(f"{offset:010d} 00000 n \n".encode())
    pdf.append(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return b"".join(pdf)
