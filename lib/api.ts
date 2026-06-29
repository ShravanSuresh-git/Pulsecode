import type {
  AnalyzeResponse,
  ArchitectureDNA,
  ArchitecturalFossil,
  ArchitecturalMemory,
  CounterfactualEstimate,
  Health,
  InfluenceGraph,
  Snapshot,
  Timeline,
  TurningPoint
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function analyzeRepo(repoPath: string, snapshotSize: number) {
  return request<AnalyzeResponse>("/analyze", {
    method: "POST",
    body: JSON.stringify({ repo_path: repoPath, snapshot_size: snapshotSize })
  });
}

export function getTimeline(repoId: string) {
  return request<Timeline>(`/timeline/${repoId}`);
}

export function getSnapshot(repoId: string, index: number) {
  return request<Snapshot>(`/snapshot/${repoId}/${index}`);
}

export function getEvents(repoId: string) {
  return request<{ repo_id: string; events: import("./types").ArchitectureEvent[] }>(`/events/${repoId}`);
}

export function getHealth(repoId: string) {
  return request<Health>(`/health/${repoId}`);
}

export function getSampleRepo() {
  return request<{ repo_path: string; name: string }>("/sample-repo");
}

export function getReport(repoId: string) {
  return request<{ repo_id: string; markdown: string }>(`/report/${repoId}`);
}

export function getReportUrl(repoId: string, format: "html" | "pdf") {
  return `${API_BASE}/report/${repoId}?format=${format}`;
}

export function getDna(repoId: string, index: number) {
  return request<{ repo_id: string; index: number; dna: ArchitectureDNA | null }>(`/dna/${repoId}/${index}`);
}

export function getStory(repoId: string) {
  return request<{ repo_id: string; story: string[]; biography: string }>(`/story/${repoId}`);
}

export function getFossils(repoId: string) {
  return request<{ repo_id: string; fossils: ArchitecturalFossil[] }>(`/fossils/${repoId}`);
}

export function getCausality(repoId: string) {
  return request<{ repo_id: string; influence_graph: InfluenceGraph | null }>(`/causality/${repoId}`);
}

export function getTurningPoints(repoId: string) {
  return request<{ repo_id: string; turning_points: TurningPoint[] }>(`/turning-points/${repoId}`);
}

export function getMemories(repoId: string) {
  return request<{ repo_id: string; memories: ArchitecturalMemory[] }>(`/memories/${repoId}`);
}

export function getCounterfactual(repoId: string, eventIndex: number) {
  return request<{ repo_id: string; counterfactual: CounterfactualEstimate }>(`/counterfactual/${repoId}/${eventIndex}`);
}
