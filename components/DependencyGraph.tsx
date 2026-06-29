"use client";

import { useEffect, useMemo, useRef } from "react";
import * as d3 from "d3";
import type { GraphNode, Snapshot } from "../lib/types";

type SimNode = GraphNode & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode> & { weight: number; kind: string };

export function DependencyGraph({
  snapshot,
  highlighted,
  lens = "directory"
}: {
  snapshot: Snapshot | null;
  highlighted: string[];
  lens?: "directory" | "churn" | "centrality" | "complexity" | "hotspot";
}) {
  const ref = useRef<SVGSVGElement | null>(null);
  const highlightedSet = useMemo(() => new Set(highlighted), [highlighted]);

  useEffect(() => {
    if (!ref.current) return;
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();

    const width = ref.current.clientWidth || 900;
    const height = ref.current.clientHeight || 620;
    const nodes: SimNode[] = (snapshot?.nodes ?? []).slice(0, 120).map((node) => ({ ...node }));
    const nodeIds = new Set(nodes.map((node) => node.id));
    const links: SimLink[] = (snapshot?.edges ?? [])
      .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
      .slice(0, 240)
      .map((edge) => ({ ...edge }));

    const root = svg.attr("viewBox", `0 0 ${width} ${height}`);
    root
      .append("rect")
      .attr("width", width)
      .attr("height", height)
      .attr("rx", 6)
      .attr("fill", "#fbfaf6");

    if (!snapshot || nodes.length === 0) {
      root
        .append("text")
        .attr("x", width / 2)
        .attr("y", height / 2)
        .attr("text-anchor", "middle")
        .attr("fill", "#6d7069")
        .attr("font-size", 16)
        .text("Analyze a Git repository to begin the time-lapse.");
      return;
    }

    const color = d3.scaleOrdinal<string, string>(d3.schemeTableau10);
    const heat = d3
      .scaleSequential(d3.interpolateYlOrRd)
      .domain([0, d3.max(nodes, (node) => lensValue(node, lens)) || 1]);
    const radius = d3
      .scaleSqrt()
      .domain([0, d3.max(nodes, (node) => lensValue(node, lens)) || 1])
      .range([5, 18]);

    const link = root
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("class", (edge) =>
        highlightedSet.has(String(edge.source)) || highlightedSet.has(String(edge.target))
          ? "graph-link highlighted"
          : "graph-link"
      )
      .attr("stroke-width", (edge) => Math.max(1, Math.min(5, edge.weight)))
      .attr("opacity", 0)
      .transition()
      .duration(520)
      .attr("opacity", 1)
      .selection();

    const node = root
      .append("g")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes, (item) => item.id)
      .join("g")
      .attr("class", (item) => (highlightedSet.has(item.id) ? "graph-node highlighted" : "graph-node"))
      .call(drag());

    node
      .append("circle")
      .attr("r", 0)
      .attr("fill", (item) => (lens === "directory" ? color(item.directory) : heat(lensValue(item, lens))))
      .attr("fill-opacity", 0.86)
      .attr("stroke", "#151814")
      .attr("stroke-opacity", 0.2)
      .transition()
      .duration(620)
      .attr("r", (item) => radius(lensValue(item, lens)));

    node
      .filter((item) => highlightedSet.has(item.id))
      .append("circle")
      .attr("class", "graph-shockwave")
      .attr("r", (item) => radius(lensValue(item, lens)) + 8)
      .attr("fill", "none")
      .attr("stroke", "#d39b31")
      .attr("stroke-width", 2);

    node
      .append("title")
      .text(
        (item) =>
          `${item.id}\ncomplexity ${item.complexity}\nchurn ${item.churn}\ncentrality ${item.centrality}\nhotspot ${item.hotspot_score}`
      );

    node
      .filter((item) => highlightedSet.has(item.id) || lensValue(item, lens) > 3 || item.centrality > 0.35)
      .append("text")
      .attr("x", 12)
      .attr("y", 4)
      .attr("font-size", 11)
      .attr("fill", "#151814")
      .text((item) => item.label.slice(0, 22));

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((item) => item.id)
          .distance((edge) => (edge.kind === "co-change" ? 72 : 44))
          .strength((edge) => (edge.kind === "co-change" ? 0.5 : 0.18))
      )
      .force("charge", d3.forceManyBody().strength(-160))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<SimNode>().radius((item) => radius(lensValue(item, lens)) + 8));

    simulation.on("tick", () => {
      link
        .attr("x1", (edge) => (edge.source as SimNode).x ?? 0)
        .attr("y1", (edge) => (edge.source as SimNode).y ?? 0)
        .attr("x2", (edge) => (edge.target as SimNode).x ?? 0)
        .attr("y2", (edge) => (edge.target as SimNode).y ?? 0);

      node.attr("transform", (item) => {
        item.x = Math.max(24, Math.min(width - 24, item.x ?? width / 2));
        item.y = Math.max(24, Math.min(height - 24, item.y ?? height / 2));
        return `translate(${item.x},${item.y})`;
      });
    });

    return () => {
      simulation.stop();
    };

    function drag() {
      function dragstarted(event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, item: SimNode) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        item.fx = item.x;
        item.fy = item.y;
      }
      function dragged(event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, item: SimNode) {
        item.fx = event.x;
        item.fy = event.y;
      }
      function dragended(event: d3.D3DragEvent<SVGGElement, SimNode, SimNode>, item: SimNode) {
        if (!event.active) simulation.alphaTarget(0);
        item.fx = null;
        item.fy = null;
      }
      return d3.drag<SVGGElement, SimNode>().on("start", dragstarted).on("drag", dragged).on("end", dragended);
    }
  }, [snapshot, highlightedSet, lens]);

  return (
    <div className="h-[620px] overflow-hidden rounded-md border border-ink/10 bg-white p-3 shadow-soft">
      <svg ref={ref} className="h-full w-full" role="img" aria-label="Dependency graph visualization" />
    </div>
  );
}

function lensValue(node: SimNode, lens: "directory" | "churn" | "centrality" | "complexity" | "hotspot") {
  if (lens === "churn") return node.churn;
  if (lens === "centrality") return node.centrality;
  if (lens === "hotspot") return node.hotspot_score;
  return node.complexity;
}
