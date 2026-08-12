"use client";

import { useMemo } from "react";

type GraphNode = {
  id: string;
  label: string;
  kind: "entity" | "neighbor" | "claim" | "topic";
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

export function buildGraphViz(
  entities: Record<string, unknown>[],
  neighbors: Record<string, unknown>[],
  claims: Record<string, unknown>[],
  topics: Record<string, unknown>[],
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];

  for (const item of entities) {
    const id = asString(item.entity_id || item.node_id || item.id);
    if (!id) continue;
    nodes.set(id, {
      id,
      label: asString(item.name || item.normalized_name || id.slice(0, 8)),
      kind: "entity",
    });
  }

  for (const item of neighbors) {
    const id = asString(item.node_id || item.entity_id || item.id);
    if (!id) continue;
    if (!nodes.has(id)) {
      nodes.set(id, {
        id,
        label: asString(item.name || item.label || id.slice(0, 8)),
        kind: "neighbor",
      });
    }
    const source = asString(item.source_node_id || item.from_id);
    const target = asString(item.target_node_id || item.to_id || id);
    if (source && target && source !== target) {
      edges.push({
        id: `${source}-${target}-${edges.length}`,
        source,
        target,
        label: asString(item.relationship_type || item.type),
      });
      if (!nodes.has(source)) {
        nodes.set(source, { id: source, label: source.slice(0, 8), kind: "neighbor" });
      }
    }
  }

  for (const item of claims) {
    const id = asString(item.claim_id || item.id);
    const subject = asString(item.subject);
    const object = asString(item.object);
    if (id) {
      nodes.set(id, {
        id,
        label: asString(item.statement || id.slice(0, 8)).slice(0, 48),
        kind: "claim",
      });
    }
    if (subject && object) {
      const sid = `subj:${subject}`;
      const oid = `obj:${object}`;
      nodes.set(sid, { id: sid, label: subject, kind: "entity" });
      nodes.set(oid, { id: oid, label: object, kind: "entity" });
      edges.push({
        id: `claim-${edges.length}`,
        source: sid,
        target: oid,
        label: asString(item.predicate || "claim"),
      });
    }
  }

  for (const item of topics) {
    const id = asString(item.topic_id || item.id || item.name);
    if (!id) continue;
    nodes.set(id, {
      id,
      label: asString(item.name || item.label || id.slice(0, 8)),
      kind: "topic",
    });
  }

  return { nodes: [...nodes.values()], edges };
}

const KIND_COLOR: Record<GraphNode["kind"], string> = {
  entity: "#0d7377",
  neighbor: "#3d5a80",
  claim: "#b5651d",
  topic: "#5a6b76",
};

export function GraphNetworkViz({
  entities,
  neighbors,
  claims,
  topics,
}: {
  entities: Record<string, unknown>[];
  neighbors: Record<string, unknown>[];
  claims: Record<string, unknown>[];
  topics: Record<string, unknown>[];
}) {
  const { nodes, edges } = useMemo(
    () => buildGraphViz(entities, neighbors, claims, topics),
    [entities, neighbors, claims, topics],
  );

  if (!nodes.length) {
    return (
      <p className="rounded-lg border border-border bg-surface px-5 py-8 text-sm text-muted">
        No graph nodes to visualize for this search.
      </p>
    );
  }

  const width = 720;
  const height = 420;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.36;
  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / nodes.length - Math.PI / 2;
    positions.set(node.id, {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    });
  });

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface p-3 shadow-sm">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full min-w-[20rem]"
        role="img"
        aria-label="Knowledge graph visualization"
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="18"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#9aa8b2" />
          </marker>
        </defs>
        {edges.map((edge) => {
          const from = positions.get(edge.source);
          const to = positions.get(edge.target);
          if (!from || !to) return null;
          return (
            <g key={edge.id}>
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke="#c9d4dc"
                strokeWidth={1.5}
                markerEnd="url(#arrow)"
              />
              {edge.label ? (
                <text
                  x={(from.x + to.x) / 2}
                  y={(from.y + to.y) / 2 - 4}
                  textAnchor="middle"
                  className="fill-[var(--muted)]"
                  fontSize={9}
                >
                  {edge.label}
                </text>
              ) : null}
            </g>
          );
        })}
        {nodes.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          return (
            <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
              <circle r={14} fill={KIND_COLOR[node.kind]} opacity={0.92} />
              <text
                y={28}
                textAnchor="middle"
                fontSize={11}
                className="fill-[var(--foreground)]"
              >
                {node.label.length > 22
                  ? `${node.label.slice(0, 20)}…`
                  : node.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 px-1 font-mono text-[11px] text-muted">
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#0d7377]" />
          entity
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#3d5a80]" />
          neighbor
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#b5651d]" />
          claim
        </span>
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#5a6b76]" />
          topic
        </span>
        <span>
          {nodes.length} nodes · {edges.length} edges
        </span>
      </div>
    </div>
  );
}
