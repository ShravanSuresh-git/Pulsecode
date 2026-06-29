"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, CloudSun, Download, Flame, GitBranch, Layers, Pause, Play, RotateCcw, Search, Sparkles } from "lucide-react";
import {
  Area,
  AreaChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { DependencyGraph } from "../components/DependencyGraph";
import { analyzeRepo, getEvents, getHealth, getReport, getReportUrl, getSampleRepo, getSnapshot, getTimeline } from "../lib/api";
import type { ArchitecturalDecision, ArchitectureEvent, Health, Snapshot, Timeline } from "../lib/types";

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
  const [selectedDecision, setSelectedDecision] = useState<ArchitecturalDecision | null>(null);
  const [beforeSnapshot, setBeforeSnapshot] = useState<Snapshot | null>(null);
  const [lens, setLens] = useState<"directory" | "churn" | "centrality" | "complexity" | "hotspot">("directory");
  const [playing, setPlaying] = useState(false);
  const [loopPlayback, setLoopPlayback] = useState(true);
  const [playbackSpeed, setPlaybackSpeed] = useState(1400);
  const [compareIndex, setCompareIndex] = useState(0);
  const [shockwavePhase, setShockwavePhase] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    setSelectedEvent(null);
    setSelectedDecision(null);
    setBeforeSnapshot(null);
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
      setCompareIndex(Math.max(0, analysis.snapshot_count - 1));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  const moveTo = useCallback(async (index: number) => {
    if (!repoId) return;
    setActiveIndex(index);
    const nextSnapshot = await getSnapshot(repoId, index);
    setSnapshot(nextSnapshot);
  }, [repoId]);

  async function loadSample() {
    setLoading(true);
    setError(null);
    try {
      const sample = await getSampleRepo();
      setRepoPath(sample.repo_path);
      setSnapshotSize(2);
      const analysis = await analyzeRepo(sample.repo_path, 2);
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
      setCompareIndex(Math.max(0, analysis.snapshot_count - 1));
      setSelectedEvent(null);
      setSelectedDecision(null);
      setBeforeSnapshot(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sample analysis failed");
    } finally {
      setLoading(false);
    }
  }

  async function selectEvent(event: ArchitectureEvent) {
    setSelectedEvent(event);
    setSelectedDecision(null);
    setShockwavePhase(0);
    if (repoId) {
      const [before, after] = await Promise.all([
        getSnapshot(repoId, event.previous_index),
        getSnapshot(repoId, event.index)
      ]);
      setBeforeSnapshot(before);
      setSnapshot(after);
      setActiveIndex(event.index);
    }
  }

  async function selectDecision(decision: ArchitecturalDecision) {
    setSelectedDecision(decision);
    setShockwavePhase(0);
    const matchingEvent = events.find((event) => event.index === decision.end_snapshot) ?? null;
    setSelectedEvent(matchingEvent);
    if (repoId) {
      const [before, after] = await Promise.all([
        getSnapshot(repoId, Math.max(0, decision.start_snapshot)),
        getSnapshot(repoId, decision.end_snapshot)
      ]);
      setBeforeSnapshot(before);
      setSnapshot(after);
      setActiveIndex(decision.end_snapshot);
    }
  }

  async function exportReport() {
    if (!repoId) return;
    const report = await getReport(repoId);
    const blob = new Blob([report.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${timeline?.repo_name ?? "pulsecode"}-evolution-report.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function exportReportAs(format: "markdown" | "html" | "pdf") {
    if (!repoId) return;
    if (format === "markdown") {
      await exportReport();
      return;
    }
    window.open(getReportUrl(repoId, format), "_blank");
  }

  const maxIndex = Math.max(0, (timeline?.snapshots.length ?? 1) - 1);

  useEffect(() => {
    if (!playing || !timeline || maxIndex === 0) return;
    const timer = window.setInterval(() => {
      const next = activeIndex >= maxIndex ? (loopPlayback ? 0 : maxIndex) : activeIndex + 1;
      if (!loopPlayback && activeIndex >= maxIndex) {
        setPlaying(false);
        return;
      }
      moveTo(next);
    }, playbackSpeed);
    return () => window.clearInterval(timer);
  }, [activeIndex, loopPlayback, maxIndex, moveTo, playbackSpeed, playing, timeline]);

  useEffect(() => {
    if (!selectedEvent && !selectedDecision) return;
    const timer = window.setInterval(() => {
      setShockwavePhase((phase) => (phase >= 3 ? 0 : phase + 1));
    }, 900);
    return () => window.clearInterval(timer);
  }, [selectedDecision, selectedEvent]);

  const chartData = useMemo(
    () =>
      timeline?.snapshots.map((item) => ({
        index: item.index,
        coupling: item.metrics.coupling_score,
        churn: item.metrics.churn_score,
        complexity: item.metrics.complexity_proxy,
        quality: item.quality_score,
        dependency: item.metrics.dependency_count
      })) ?? [],
    [timeline]
  );

  const compareSnapshot = timeline?.snapshots[compareIndex] ?? null;
  const dnaData = useMemo(() => {
    if (!snapshot?.dna || !compareSnapshot?.dna) return [];
    return Object.entries(snapshot.dna).map(([key, value]) => ({
      axis: key.replaceAll("_", " "),
      current: Number(value),
      compare: Number(compareSnapshot.dna?.[key as keyof typeof compareSnapshot.dna] ?? 0)
    }));
  }, [compareSnapshot, snapshot]);

  const shockwaveNodes = useMemo(() => {
    const shockwave = selectedDecision?.butterfly_effect.shockwave ?? selectedEvent?.shockwave;
    if (!shockwave) return [];
    const rings = ["changed_files", "neighbor_modules", "graph"] as const;
    return rings.slice(0, shockwavePhase + 1).flatMap((ring) => shockwave[ring] ?? []);
  }, [selectedDecision, selectedEvent, shockwavePhase]);
  const highlighted = shockwaveNodes.length ? shockwaveNodes : selectedDecision?.affected_modules ?? selectedEvent?.affected_modules ?? health?.forecast?.likely_bottlenecks ?? [];

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
            <button
              onClick={loadSample}
              disabled={loading}
              className="inline-flex h-11 items-center gap-2 rounded-md border border-ink/15 bg-white px-4 text-sm font-semibold text-ink transition hover:border-cobalt/50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Sparkles size={18} />
              Demo
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
            <div className="flex items-center gap-3">
              <button
                onClick={() => setPlaying((value) => !value)}
                disabled={!timeline || maxIndex === 0}
                className="flex h-9 w-9 items-center justify-center rounded-md border border-ink/15 bg-[#fbfaf6] text-ink disabled:opacity-40"
                title={playing ? "Pause replay" : "Play replay"}
              >
                {playing ? <Pause size={17} /> : <Play size={17} />}
              </button>
              <input
                aria-label="Time slider"
                type="range"
                min={0}
                max={maxIndex}
                value={activeIndex}
                disabled={!timeline}
                onChange={(event) => {
                  setPlaying(false);
                  moveTo(Number(event.target.value));
                }}
                className="h-2 flex-1 accent-rust"
              />
            </div>
            <div className="mt-2 flex justify-between text-xs text-ink/50">
              <span>origin</span>
              <span>{timeline ? `${timeline.snapshots.length} snapshots` : "waiting for analysis"}</span>
              <span>latest</span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-cobalt/10 px-2 py-1 text-xs font-semibold text-cobalt">
                {snapshot?.species?.name ?? "Unclassified"}
              </span>
              <span className="rounded-md bg-amber/15 px-2 py-1 text-xs font-semibold text-ink/70">
                {snapshot?.weather?.condition ?? "No weather"} · score {snapshot?.quality_score ?? "--"}
              </span>
              <label className="ml-auto flex items-center gap-2 text-xs text-ink/55">
                Speed
                <select
                  value={playbackSpeed}
                  onChange={(event) => setPlaybackSpeed(Number(event.target.value))}
                  className="rounded-md border border-ink/15 bg-white px-2 py-1"
                >
                  <option value={2200}>Slow</option>
                  <option value={1400}>Normal</option>
                  <option value={800}>Fast</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs text-ink/55">
                <input type="checkbox" checked={loopPlayback} onChange={(event) => setLoopPlayback(event.target.checked)} />
                Loop
              </label>
            </div>
          </div>

          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-ink/10 bg-white p-3 shadow-soft">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink/70">
              <Layers size={16} className="text-cobalt" />
              Hotspot Lens
            </div>
            <div className="flex flex-wrap gap-2">
              {(["directory", "churn", "centrality", "complexity", "hotspot"] as const).map((option) => (
                <button
                  key={option}
                  onClick={() => setLens(option)}
                  className={`rounded-md border px-3 py-1.5 text-xs font-semibold capitalize ${
                    lens === option ? "border-rust bg-rust/10 text-rust" : "border-ink/10 bg-[#fbfaf6] text-ink/65"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          <DependencyGraph snapshot={snapshot} highlighted={highlighted} lens={lens} />
          <DecisionReplay
            decisions={health?.decisions ?? []}
            selected={selectedDecision}
            onSelect={selectDecision}
          />
          <DnaPanel
            snapshot={snapshot}
            compareIndex={compareIndex}
            maxIndex={maxIndex}
            onCompareIndex={setCompareIndex}
            data={dnaData}
          />
          {selectedEvent && beforeSnapshot ? (
            <TimePortal before={beforeSnapshot} after={snapshot} event={selectedEvent} shockwavePhase={shockwavePhase} />
          ) : null}
        </div>

        <aside className="flex flex-col gap-5">
          <WeatherPanel health={health} snapshot={snapshot} onExport={exportReportAs} canExport={Boolean(repoId)} />
          <WhyPanel health={health} selectedEvent={selectedEvent} selectedDecision={selectedDecision} />
          <FamilyTreePanel health={health} />
          <MetricsPanel snapshot={snapshot} />
          <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
            <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Evolution Signal</h2>
            <div className="mt-3 h-44">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData}>
                  <XAxis dataKey="index" tickLine={false} axisLine={false} />
                  <YAxis hide />
                  <Tooltip />
                  <Area type="monotone" dataKey="quality" stroke="#536b49" fill="#536b49" fillOpacity={0.12} />
                  <Area type="monotone" dataKey="coupling" stroke="#355c9a" fill="#355c9a" fillOpacity={0.16} />
                  <Area type="monotone" dataKey="complexity" stroke="#a75736" fill="#a75736" fillOpacity={0.12} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
          <EventsPanel
            events={events}
            selected={selectedEvent}
            onSelect={selectEvent}
          />
          <SummaryPanel health={health} />
        </aside>
      </section>
    </main>
  );
}

function DecisionReplay({
  decisions,
  selected,
  onSelect
}: {
  decisions: ArchitecturalDecision[];
  selected: ArchitecturalDecision | null;
  onSelect: (decision: ArchitecturalDecision) => void;
}) {
  return (
    <div className="mt-4 rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Decision Replay</h2>
          <p className="mt-1 text-sm text-ink/60">Architectural decisions become the timeline landmarks.</p>
        </div>
        <span className="rounded-md bg-cobalt/10 px-2 py-1 text-xs font-semibold text-cobalt">
          {decisions.length} decisions
        </span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_260px]">
        <div className="flex gap-3 overflow-x-auto pb-2">
          {decisions.length === 0 ? (
            <div className="min-h-24 flex-1 rounded-md border border-dashed border-ink/20 bg-[#fbfaf6] p-4 text-sm text-ink/55">
              Analyze a repository to isolate architectural decisions.
            </div>
          ) : (
            decisions.slice(0, 12).map((decision) => (
              <button
                key={decision.id}
                onClick={() => onSelect(decision)}
                className={`min-w-64 rounded-md border p-3 text-left transition ${
                  selected?.id === decision.id
                    ? "border-rust bg-rust/10"
                    : "border-ink/10 bg-[#fbfaf6] hover:border-cobalt/40"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-ink/50">t={decision.end_snapshot}</span>
                  <span className="rounded bg-amber/15 px-2 py-0.5 text-xs font-semibold text-ink/65">
                    {decision.architectural_impact_score.toFixed(1)}
                  </span>
                </div>
                <div className="mt-2 text-sm font-semibold text-ink">{decision.title}</div>
                <div className="mt-1 line-clamp-3 text-xs leading-5 text-ink/60">{decision.summary}</div>
              </button>
            ))
          )}
        </div>
        <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">Butterfly Effect</div>
          {selected ? (
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <MiniMetric label="Immediate" value={selected.butterfly_effect.immediate_impact.toFixed(1)} />
              <MiniMetric label="Long-term" value={selected.butterfly_effect.long_term_impact.toFixed(1)} />
              <MiniMetric label="Radius" value={selected.butterfly_effect.influence_radius.toString()} />
              <MiniMetric label="Deps" value={`+${selected.butterfly_effect.dependency_growth_caused}`} />
            </div>
          ) : (
            <p className="mt-2 text-sm leading-5 text-ink/60">Select a decision to watch its simulated shockwave through future graph structure.</p>
          )}
          {selected?.butterfly_effect.evidence.length ? (
            <p className="mt-3 text-xs leading-5 text-ink/60">{selected.butterfly_effect.evidence[0]}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-ink/10 bg-white p-2">
      <div className="text-[11px] text-ink/45">{label}</div>
      <div className="mt-1 font-semibold text-ink">{value}</div>
    </div>
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

function DnaPanel({
  snapshot,
  compareIndex,
  maxIndex,
  onCompareIndex,
  data
}: {
  snapshot: Snapshot | null;
  compareIndex: number;
  maxIndex: number;
  onCompareIndex: (index: number) => void;
  data: Array<{ axis: string; current: number; compare: number }>;
}) {
  return (
    <div className="mt-4 rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Architecture DNA</h2>
          <p className="mt-1 text-sm text-ink/60">Compare the current fingerprint with another snapshot.</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-ink/55">
          Compare t={compareIndex}
          <input
            type="range"
            min={0}
            max={maxIndex}
            value={compareIndex}
            onChange={(event) => onCompareIndex(Number(event.target.value))}
            className="w-40 accent-cobalt"
          />
        </label>
      </div>
      <div className="mt-3 grid gap-4 lg:grid-cols-[1fr_260px]">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={data}>
              <PolarGrid />
              <PolarAngleAxis dataKey="axis" tick={{ fontSize: 10 }} />
              <Radar name="Current" dataKey="current" stroke="#a75736" fill="#a75736" fillOpacity={0.22} />
              <Radar name="Compare" dataKey="compare" stroke="#355c9a" fill="#355c9a" fillOpacity={0.14} />
              <Tooltip />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3 text-sm">
          <div className="font-semibold text-ink">{snapshot?.species?.name ?? "Unclassified"}</div>
          <div className="mt-1 text-xs text-ink/50">
            Confidence {snapshot?.species ? Math.round(snapshot.species.confidence * 100) : 0}%
          </div>
          <div className="mt-3 flex flex-col gap-2 text-ink/65">
            {(snapshot?.species?.reasons ?? ["Analyze a repository to classify its software species."]).slice(0, 3).map((reason) => (
              <span key={reason}>{reason}</span>
            ))}
          </div>
        </div>
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
              {event.causes.length > 0 ? (
                <div className="mt-2 rounded-md bg-cobalt/10 p-2 text-xs text-ink/70">
                  Why: {event.causes[0].cause} ({Math.round(event.causes[0].confidence * 100)}%)
                </div>
              ) : null}
              {event.causal_commits.length > 0 ? (
                <div className="mt-2 border-t border-ink/10 pt-2 text-xs text-ink/55">
                  {event.causal_commits.slice(0, 2).map((commit) => (
                    <div key={commit.sha}>
                      {commit.sha} · {commit.message}
                    </div>
                  ))}
                </div>
              ) : null}
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
        {health?.biography || health?.summary ||
          "Load a repository to watch its architectural shape emerge across Git history."}
      </p>
    </div>
  );
}

function WeatherPanel({
  health,
  snapshot,
  onExport,
  canExport
}: {
  health: Health | null;
  snapshot: Snapshot | null;
  onExport: (format: "markdown" | "html" | "pdf") => void;
  canExport: boolean;
}) {
  const forecast = health?.forecast;
  return (
    <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Architectural Weather</h2>
          <div className="mt-1 text-lg font-semibold text-ink">{health?.archetype ?? "No archetype yet"}</div>
        </div>
        <div className="flex gap-1">
          {(["markdown", "html", "pdf"] as const).map((format) => (
            <button
              key={format}
              onClick={() => onExport(format)}
              disabled={!canExport}
              className="flex h-9 min-w-9 items-center justify-center rounded-md border border-ink/15 bg-[#fbfaf6] px-2 text-xs font-semibold uppercase text-ink disabled:opacity-40"
              title={`Export ${format} report`}
            >
              {format === "markdown" ? <Download size={15} /> : format}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 rounded-md bg-[#fbfaf6] p-3 text-sm">
        <CloudSun size={17} className="text-amber" />
        <span className="font-semibold">{snapshot?.weather?.condition ?? "No weather"}</span>
        <span className="text-ink/55">{snapshot?.weather?.explanation ?? "Analyze a snapshot to see architectural weather."}</span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
          <div className="text-xs text-ink/50">Coupling</div>
          <div className="mt-1 font-semibold capitalize">{forecast?.coupling_pressure ?? "-"}</div>
        </div>
        <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
          <div className="text-xs text-ink/50">Churn</div>
          <div className="mt-1 font-semibold capitalize">{forecast?.churn_pressure ?? "-"}</div>
        </div>
      </div>
      <div className="mt-3 flex items-start gap-2 rounded-md bg-cobalt/10 p-3 text-sm leading-5 text-ink/75">
        <Flame size={16} className="mt-0.5 shrink-0 text-rust" />
        <span>{forecast?.recommendation ?? "Analyze a repository to generate the forecast."}</span>
      </div>
      {forecast?.likely_bottlenecks.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {forecast.likely_bottlenecks.slice(0, 4).map((module) => (
            <span key={module} className="rounded-md bg-amber/15 px-2 py-1 text-xs font-semibold text-ink/70">
              {module.split("/").slice(-2).join("/")}
            </span>
          ))}
        </div>
      ) : null}
      {health?.story.length ? (
        <div className="mt-4 border-t border-ink/10 pt-3">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">Evolution Story</div>
          <div className="mt-2 flex flex-col gap-2 text-sm leading-5 text-ink/70">
            {health.story.slice(0, 4).map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
        </div>
      ) : null}
      {health?.fossils.length ? (
        <div className="mt-4 border-t border-ink/10 pt-3">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">Architectural Fossils</div>
          <div className="mt-2 flex flex-col gap-2">
            {health.fossils.slice(0, 3).map((fossil) => (
              <div key={`${fossil.title}-${fossil.snapshot_index}`} className="rounded-md bg-amber/10 p-2 text-sm">
                <div className="font-semibold text-ink">{fossil.title}</div>
                <div className="text-xs text-ink/60">t={fossil.snapshot_index} · impact {fossil.impact_score.toFixed(1)}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FamilyTreePanel({ health }: { health: Health | null }) {
  const tree = health?.family_tree;
  const edges = tree?.edges.slice(0, 5) ?? [];
  return (
    <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Family Tree</h2>
        <span className="text-xs font-semibold text-ink/50">{tree?.nodes.length ?? 0} modules</span>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {edges.length ? (
          edges.map((edge) => (
            <div key={`${edge.source}-${edge.target}-${edge.relationship}`} className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3 text-sm">
              <div className="font-semibold text-ink">{edge.relationship}</div>
              <div className="mt-1 text-xs leading-5 text-ink/60">
                {edge.source.split("/").slice(-2).join("/")} → {edge.target.split("/").slice(-2).join("/")}
              </div>
              <div className="mt-1 text-xs text-ink/45">confidence {Math.round(edge.confidence * 100)}%</div>
            </div>
          ))
        ) : (
          <p className="text-sm leading-5 text-ink/55">Module genealogy will appear when PulseCode detects splits, renames, abstractions, or responsibility inheritance.</p>
        )}
      </div>
    </div>
  );
}

function WhyPanel({
  health,
  selectedEvent,
  selectedDecision
}: {
  health: Health | null;
  selectedEvent: ArchitectureEvent | null;
  selectedDecision: ArchitecturalDecision | null;
}) {
  const topTurningPoint = health?.turning_points[0];
  const topMemory = health?.memories[0];
  const counterfactual = selectedEvent
    ? health?.counterfactuals.find((item) => item.event_index === selectedEvent.index)
    : health?.counterfactuals[0];
  const influence = health?.decision_influence_graph?.edges[0] ?? health?.influence_graph?.edges[0];
  return (
    <div className="rounded-md border border-ink/10 bg-white p-4 shadow-soft">
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Why Engine</h2>
      <div className="mt-3 flex flex-col gap-3">
        <ResearchCard
          title="Decision"
          value={selectedDecision?.title ?? health?.decisions[0]?.title ?? "No decision isolated"}
          detail={selectedDecision?.summary ?? health?.decisions[0]?.summary ?? "PulseCode stores decisions independently from commits."}
        />
        <ResearchCard
          title="Likely Cause"
          value={selectedDecision?.causes[0]?.cause ?? selectedEvent?.causes[0]?.cause ?? "Select an event"}
          detail={selectedDecision?.causes[0]?.evidence[0] ?? selectedEvent?.causes[0]?.evidence[0] ?? "PulseCode infers causal mechanisms for each architectural event."}
        />
        <ResearchCard
          title="Turning Point"
          value={topTurningPoint ? `${topTurningPoint.commit.sha} · ${topTurningPoint.impact_score.toFixed(1)}` : "No turning point yet"}
          detail={topTurningPoint?.reason ?? "Commits are ranked by long-term architectural influence."}
        />
        <ResearchCard
          title="Architectural Memory"
          value={topMemory?.title ?? "No persistent memory yet"}
          detail={topMemory?.reason ?? "Persistent decisions appear when modules keep shaping the latest graph."}
        />
        <ResearchCard
          title="Counterfactual"
          value={counterfactual ? `Without t=${counterfactual.event_index}` : "No counterfactual yet"}
          detail={counterfactual?.explanation ?? "Counterfactuals approximate graph metrics without rewriting Git history."}
        />
        <ResearchCard
          title="Influence Chain"
          value={influence ? `t=${influence.source_event} → t=${influence.target_event}` : "No chain isolated"}
          detail={influence?.explanation ?? "Event DAG edges appear when causes or affected modules persist into future events."}
        />
        {health?.forecast?.explanations[0] ? (
          <ResearchCard
            title="Forecast Evidence"
            value={`Future coupling ${health.forecast.future_coupling}`}
            detail={health.forecast.explanations[0].evidence[0]}
          />
        ) : null}
      </div>
    </div>
  );
}

function ResearchCard({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">{title}</div>
      <div className="mt-1 text-sm font-semibold text-ink">{value}</div>
      <div className="mt-1 text-xs leading-5 text-ink/60">{detail}</div>
    </div>
  );
}

function TimePortal({
  before,
  after,
  event,
  shockwavePhase
}: {
  before: Snapshot;
  after: Snapshot | null;
  event: ArchitectureEvent;
  shockwavePhase: number;
}) {
  const beforeEdges = new Set(before.edges.map((edge) => edgeKey(edge.source, edge.target)));
  const afterEdges = new Set((after?.edges ?? []).map((edge) => edgeKey(edge.source, edge.target)));
  const newEdges = [...afterEdges].filter((edge) => !beforeEdges.has(edge));
  const removedEdges = [...beforeEdges].filter((edge) => !afterEdges.has(edge));
  const phaseLabels = ["Commit", "Changed files", "Neighbor modules", "Whole graph"];
  const rows = [
    ["Coupling", before.metrics.coupling_score.toFixed(3), after?.metrics.coupling_score.toFixed(3) ?? "-"],
    ["Dependencies", before.metrics.dependency_count.toString(), after?.metrics.dependency_count.toString() ?? "-"],
    ["Complexity", before.metrics.complexity_proxy.toFixed(2), after?.metrics.complexity_proxy.toFixed(2) ?? "-"],
    ["Modules", before.metrics.module_count.toString(), after?.metrics.module_count.toString() ?? "-"]
  ];
  return (
    <div className="mt-4 rounded-md border border-amber/40 bg-white p-4 shadow-soft">
      <h2 className="text-sm font-semibold uppercase tracking-[0.14em] text-ink/55">Before / After Portal</h2>
      <p className="mt-2 text-sm leading-6 text-ink/70">{event.explanation}</p>
      <div className="mt-4 grid gap-2 md:grid-cols-4">
        {phaseLabels.map((label, index) => (
          <div
            key={label}
            className={`rounded-md border p-3 text-center text-xs font-semibold transition ${
              index <= shockwavePhase ? "border-rust bg-rust/10 text-rust" : "border-ink/10 bg-[#fbfaf6] text-ink/45"
            }`}
          >
            {label}
          </div>
        ))}
      </div>
      <div className="mt-4 grid gap-2 md:grid-cols-4">
        {rows.map(([label, beforeValue, afterValue]) => (
          <div key={label} className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
            <div className="text-xs text-ink/50">{label}</div>
            <div className="mt-1 text-sm font-semibold">
              {beforeValue} → {afterValue}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <CommitList title="Causal Commits" commits={event.causal_commits} />
        <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">Affected Modules</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {event.affected_modules.map((module) => (
              <span key={module} className="rounded-md bg-amber/15 px-2 py-1 text-xs font-semibold text-ink/70">
                {module.split("/").slice(-2).join("/")}
              </span>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <DiffList title="New Edges" items={newEdges.slice(0, 8)} empty="No new edges isolated." />
        <DiffList title="Removed Edges" items={removedEdges.slice(0, 8)} empty="No removed edges isolated." />
      </div>
      <div className="mt-4 rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
        <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">Causal Inference</div>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {event.causes.slice(0, 4).map((cause) => (
            <div key={cause.cause} className="rounded-md bg-white p-2 text-sm">
              <div className="font-semibold text-ink">
                {cause.cause} · {Math.round(cause.confidence * 100)}%
              </div>
              <div className="mt-1 text-xs text-ink/60">{cause.evidence[0]}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DiffList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">{title}</div>
      <div className="mt-2 flex flex-col gap-1 text-xs text-ink/65">
        {items.length ? items.map((item) => <span key={item}>{item}</span>) : <span>{empty}</span>}
      </div>
    </div>
  );
}

function edgeKey(source: string, target: string) {
  return [source, target].sort().map((item) => item.split("/").slice(-2).join("/")).join(" ↔ ");
}

function CommitList({ title, commits }: { title: string; commits: ArchitectureEvent["causal_commits"] }) {
  return (
    <div className="rounded-md border border-ink/10 bg-[#fbfaf6] p-3">
      <div className="text-xs font-semibold uppercase tracking-[0.12em] text-ink/45">{title}</div>
      <div className="mt-2 flex flex-col gap-2">
        {commits.length === 0 ? (
          <span className="text-sm text-ink/55">No direct causal commit isolated.</span>
        ) : (
          commits.map((commit) => (
            <div key={commit.sha} className="text-sm">
              <span className="font-semibold text-cobalt">{commit.sha}</span>
              <span className="text-ink/70"> · {commit.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
