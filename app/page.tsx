"use client";

import { useMemo, useState } from "react";
import { Activity, GitBranch, Play, RotateCcw, Search } from "lucide-react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { DependencyGraph } from "../components/DependencyGraph";
import { analyzeRepo, getEvents, getHealth, getSnapshot, getTimeline } from "../lib/api";
import type { ArchitectureEvent, Health, Snapshot, Timeline } from "../lib/types";

const samplePath = "/Users/shravan/Documents/Pulsecode";

export default function Home() {
  const [repoPath, setRepoPath] = useState(samplePath);
  const [snapshotSize, setSnapshotSize] = useState(8);
  const [repoId, setRepoId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<ArchitectureEvent[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [selectedEvent, setSelectedEvent] = useState<ArchitectureEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    setSelectedEvent(null);
    try {
      const analysis = await analyzeRepo(repoPath, snapshotSize);
      const [nextTimeline, nextEvents, nextHealth] = await Promise.all([
        getTimeline(analysis.repo_id),
        getEvents(analysis.repo_id),
        getHealth(analysis.repo_id)
      ]);
      const firstSnapshot = analysis.snapshot_count > 0 ? await getSnapshot(analysis.repo_id, 0) : null;
      setRepoId(analysis.repo_id);
      setTimeline(nextTimeline);
      setEvents(nextEvents.events);
      setHealth(nextHealth);
      setSnapshot(firstSnapshot);
      setActiveIndex(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  async function moveTo(index: number) {
    if (!repoId) return;
    setActiveIndex(index);
    const nextSnapshot = await getSnapshot(repoId, index);
    setSnapshot(nextSnapshot);
  }

  const chartData = useMemo(
    () =>
      timeline?.snapshots.map((item) => ({
        index: item.index,
        coupling: item.metrics.coupling_score,
        churn: item.metrics.churn_score,
        complexity: item.metrics.complexity_proxy
      })) ?? [],
    [timeline]
  );

  const highlighted = selectedEvent?.affected_modules ?? [];
  const maxIndex = Math.max(0, (timeline?.snapshots.length ?? 1) - 1);

  return (
    <main className="min-h-screen bg-paper">
      <section className="border-b border-ink/10 bg-[#ece7dc]">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 px-5 py-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-rust">
                <Activity size={16} />
                PulseCode
              </div>
              <h1 className="mt-2 text-3xl font-semibold tracking-normal text-ink">
                Software Evolution Time Machine
              </h1>
            </div>
            <button
              onClick={runAnalysis}
              disabled={loading}
              className="inline-flex h-11 items-center gap-2 rounded-md bg-ink px-5 text-sm font-semibold text-white transition hover:bg-moss disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? <RotateCcw className="animate-spin" size={18} /> : <Play size={18} />}
              {loading ? "Analyzing" : "Analyze"}
            </button>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
            <label className="flex h-12 items-center gap-3 rounded-md border border-ink/15 bg-white px-3">
              <Search size={18} className="text-moss" />
              <input
                value={repoPath}
                onChange={(event) => setRepoPath(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                placeholder="/absolute/path/to/git/repo"
              />
            </label>
            <label className="flex h-12 items-center justify-between gap-3 rounded-md border border-ink/15 bg-white px-3 text-sm">
              <span className="font-medium text-ink/70">Commits per snapshot</span>
              <input
                type="number"
                min={2}
                max={50}
                value={snapshotSize}
                onChange={(event) => setSnapshotSize(Number(event.target.value))}
                className="w-16 rounded border border-ink/15 px-2 py-1 text-right outline-none"
              />
            </label>
          </div>
          {error ? <p className="rounded-md bg-rust/10 px-3 py-2 text-sm text-rust">{error}</p> : null}
        </div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-5 px-5 py-5 xl:grid-cols-[1fr_360px]">
        <div className="min-w-0">
          <div className="mb-4 rounded-md border border-ink/10 bg-white p-4 shadow-soft">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 font-semibold">
                <GitBranch size={18} className="text-cobalt" />
                {timeline?.repo_name ?? "Choose a repository"}
              </div>
              <div className="text-sm text-ink/60">
                {snapshot ? `${snapshot.label} · ${new Date(snapshot.timestamp).toLocaleString()}` : "No timeline loaded"}
              </div>
            </div>
            <input
              aria-label="Time slider"
              type="range"
              min={0}
              max={maxIndex}
              value={activeIndex}
              disabled={!timeline}
              onChange={(event) => moveTo(Number(event.target.value))}
              className="h-2 w-full accent-rust"
            />
            <div className="mt-2 flex justify-between text-xs text-ink/50">
              <span>origin</span>
              <span>{timeline ? `${timeline.snapshots.length} snapshots` : "waiting for analysis"}</span>
              <span>latest</span>
            </div>
          </div>

          <DependencyGraph snapshot={snapshot} highlighted={highlighted} />
        </div>

        <aside className="flex flex-col gap-5">
          <MetricsPanel snapshot={snapshot} />
          <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
            <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Evolution Signal</h2>
            <div className="mt-3 h-44">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData}>
                  <XAxis dataKey="index" tickLine={false} axisLine={false} />
                  <YAxis hide />
                  <Tooltip />
                  <Area type="monotone" dataKey="coupling" stroke="#355c9a" fill="#355c9a" fillOpacity={0.16} />
                  <Area type="monotone" dataKey="complexity" stroke="#a75736" fill="#a75736" fillOpacity={0.12} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
          <EventsPanel
            events={events}
            selected={selectedEvent}
            onSelect={(event) => {
              setSelectedEvent(event);
              moveTo(event.index);
            }}
          />
          <SummaryPanel health={health} />
        </aside>
      </section>
    </main>
  );
}

function MetricsPanel({ snapshot }: { snapshot: Snapshot | null }) {
  const metrics = snapshot?.metrics;
  const rows = [
    ["Coupling", metrics?.coupling_score.toFixed(3) ?? "-"],
    ["Churn", metrics?.churn_score.toLocaleString() ?? "-"],
    ["Complexity", metrics?.complexity_proxy.toFixed(2) ?? "-"],
    ["Modules", metrics?.module_count.toString() ?? "-"],
    ["Dependencies", metrics?.dependency_count.toString() ?? "-"]
  ];
  return (
    <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Snapshot Metrics</h2>
      <div className="mt-4 grid grid-cols-2 gap-3">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
            <div className="text-xs text-ink/50">{label}</div>
            <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EventsPanel({
  events,
  selected,
  onSelect
}: {
  events: ArchitectureEvent[];
  selected: ArchitectureEvent | null;
  onSelect: (event: ArchitectureEvent) => void;
}) {
  return (
    <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Architectural Shifts</h2>
      <div className="mt-3 flex max-h-64 flex-col gap-2 overflow-auto">
        {events.length === 0 ? (
          <p className="text-sm text-ink/55">No structural shift has been flagged yet.</p>
        ) : (
          events.map((event) => (
            <button
              key={`${event.index}-${event.explanation}`}
              onClick={() => onSelect(event)}
              className={`rounded-md border p-3 text-left text-sm transition ${
                selected?.index === event.index
                  ? "border-amber bg-amber/10"
                  : "border-ink/10 bg-[#fbfaf6] hover:border-cobalt/40"
              }`}
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="font-semibold">t={event.index}</span>
                <span className="rounded bg-rust/10 px-2 py-0.5 text-xs font-semibold text-rust">
                  {event.severity}
                </span>
              </div>
              <span className="text-ink/70">{event.explanation}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function SummaryPanel({ health }: { health: Health | null }) {
  return (
    <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Evolution Summary</h2>
        <span className="text-2xl font-semibold text-moss">{health?.evolution_score ?? "--"}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-ink/70">
        {health?.summary ??
          "Load a repository to watch its architectural shape emerge across Git history."}
      </p>
    </div>
  );
}
