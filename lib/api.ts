import type { AnalyzeResponse, Health, Snapshot, Timeline } from "./types";

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

