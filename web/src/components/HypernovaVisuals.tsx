type GraphNode = {
  id: string;
  kind: string;
  label: string;
  trust_tier?: string | null;
  centrality: number;
};

type GraphEdge = {
  source: string;
  target: string;
  relation: string;
};

export function EpistemicGraphSvg({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const shown = nodes.slice(0, 16);
  if (shown.length === 0) {
    return (
      <div className="rounded-xl bg-black/40 border border-white/10 p-6 text-center text-xs text-white/45">
        No verified memories yet — start a conversation or stage a branch to populate the belief graph.
      </div>
    );
  }
  const cx = 280;
  const cy = 125;
  const rx = 210;
  const ry = 88;
  const coords = new Map<string, { x: number; y: number }>();
  shown.forEach((n, idx) => {
    const angle = (2 * Math.PI * idx) / shown.length - Math.PI / 2;
    coords.set(n.id, {
      x: cx + Math.cos(angle) * rx,
      y: cy + Math.sin(angle) * ry,
    });
  });

  return (
    <svg
      viewBox="0 0 560 250"
      className="w-full h-56 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="Epistemic Knowledge Graph"
    >
      {edges.map((e, i) => {
        const a = coords.get(e.source);
        const b = coords.get(e.target);
        if (!a || !b) return null;
        const isConflict = e.relation === "contradicts";
        return (
          <line
            key={`${e.source}-${e.target}-${i}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke={isConflict ? "#f87171" : "rgba(92,200,255,0.35)"}
            strokeWidth={isConflict ? 2.2 : 1.1}
            strokeDasharray={isConflict ? "5 4" : undefined}
          />
        );
      })}
      {shown.map((n) => {
        const pt = coords.get(n.id)!;
        const fill =
          n.kind === "memory"
            ? "#2E6BFF"
            : n.kind === "source"
              ? "#10b981"
              : "#38bdf8";
        return (
          <g key={n.id}>
            <circle cx={pt.x} cy={pt.y} r={11} fill={fill} fillOpacity={0.85} />
            <text
              x={pt.x}
              y={pt.y + 22}
              textAnchor="middle"
              fill="rgba(255,255,255,0.8)"
              fontSize="9"
            >
              {n.label.slice(0, 18)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function EvolutionCurveSvg({
  curve,
}: {
  curve: { generation: number; best_fitness: number; avg_fitness: number }[];
}) {
  if (curve.length === 0) return null;
  const w = 520;
  const h = 160;
  const pad = 28;
  const maxG = Math.max(1, curve.length - 1);
  const toX = (i: number) => pad + (i / maxG) * (w - pad * 2);
  const toY = (v: number) => h - pad - Math.max(0, Math.min(1, v)) * (h - pad * 2);

  const bestPts = curve.map((c, i) => `${toX(i)},${toY(c.best_fitness)}`).join(" ");
  const avgPts = curve.map((c, i) => `${toX(i)},${toY(c.avg_fitness)}`).join(" ");

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-40 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="Swarm DNA Fitness Curve"
    >
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="rgba(255,255,255,0.15)" />
      <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="rgba(255,255,255,0.15)" />
      <polyline fill="none" stroke="rgba(92,200,255,0.45)" strokeWidth="2" points={avgPts} />
      <polyline fill="none" stroke="#34d399" strokeWidth="2.6" points={bestPts} />
      {curve.map((c, i) => (
        <g key={c.generation}>
          <circle cx={toX(i)} cy={toY(c.best_fitness)} r={3.5} fill="#34d399" />
          <text
            x={toX(i)}
            y={h - 10}
            textAnchor="middle"
            fill="rgba(255,255,255,0.5)"
            fontSize="9"
          >
            G{c.generation}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function ParetoScatterSvg({
  catalog,
  frontierIds,
  selectedId,
}: {
  catalog: {
    model_id: string;
    label: string;
    effective_quality: number;
    cost_per_1m_usd: number;
  }[];
  frontierIds: Set<string>;
  selectedId?: string;
}) {
  if (catalog.length === 0) return null;
  const w = 520;
  const h = 190;
  const pad = 34;
  const maxCost = Math.max(1, ...catalog.map((m) => m.cost_per_1m_usd));
  const toX = (cost: number) => pad + (cost / maxCost) * (w - pad * 2);
  const toY = (q: number) => h - pad - Math.max(0, Math.min(1, (q - 0.5) / 0.5)) * (h - pad * 2);

  const frontierPts = catalog
    .filter((m) => frontierIds.has(m.model_id))
    .sort((a, b) => a.cost_per_1m_usd - b.cost_per_1m_usd)
    .map((m) => `${toX(m.cost_per_1m_usd)},${toY(m.effective_quality)}`)
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-48 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="Cost vs Quality Pareto Frontier"
    >
      <line x1={pad} y1={h - pad} x2={w - pad} y2={h - pad} stroke="rgba(255,255,255,0.18)" />
      <line x1={pad} y1={pad} x2={pad} y2={h - pad} stroke="rgba(255,255,255,0.18)" />
      <text x={w / 2} y={h - 8} textAnchor="middle" fill="rgba(255,255,255,0.45)" fontSize="9">
        USD / 1M tokens →
      </text>
      <text x={14} y={h / 2} textAnchor="middle" fill="rgba(255,255,255,0.45)" fontSize="9">
        Q
      </text>
      {frontierPts && (
        <polyline
          fill="none"
          stroke="#5CC8FF"
          strokeWidth="1.8"
          strokeDasharray="4 3"
          points={frontierPts}
        />
      )}
      {catalog.map((m) => {
        const x = toX(m.cost_per_1m_usd);
        const y = toY(m.effective_quality);
        const isSel = m.model_id === selectedId;
        const isOpt = frontierIds.has(m.model_id);
        return (
          <g key={m.model_id}>
            <circle
              cx={x}
              cy={y}
              r={isSel ? 7 : isOpt ? 5 : 4}
              fill={isSel ? "#34d399" : isOpt ? "#5CC8FF" : "rgba(255,255,255,0.35)"}
            />
            <text
              x={x}
              y={y - 10}
              textAnchor="middle"
              fill={isSel ? "#6ee7b7" : "rgba(255,255,255,0.75)"}
              fontSize="9"
            >
              {m.label.slice(0, 15)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function MeshTopologySvg({
  peers,
}: {
  peers: {
    node_id: string;
    label: string;
    reputation: number;
    quarantined: boolean;
  }[];
}) {
  if (peers.length === 0) return null;
  const cx = 260;
  const cy = 100;
  const r = 70;
  const coords = peers.map((p, i) => {
    const a = (2 * Math.PI * i) / peers.length - Math.PI / 2;
    return { p, x: cx + Math.cos(a) * r * 1.9, y: cy + Math.sin(a) * r };
  });

  return (
    <svg
      viewBox="0 0 520 200"
      className="w-full h-44 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="Federated İmece Mesh Topology"
    >
      {coords.map((a, i) =>
        coords.slice(i + 1).map((b) => (
          <line
            key={`${a.p.node_id}-${b.p.node_id}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke={
              a.p.quarantined || b.p.quarantined
                ? "rgba(248,113,113,0.25)"
                : "rgba(92,200,255,0.4)"
            }
            strokeDasharray={a.p.quarantined || b.p.quarantined ? "4 4" : undefined}
          />
        )),
      )}
      {coords.map(({ p, x, y }) => (
        <g key={p.node_id}>
          <circle
            cx={x}
            cy={y}
            r={16}
            fill={p.quarantined ? "#ef4444" : "#2E6BFF"}
            fillOpacity={0.85}
          />
          <text x={x} y={y + 3} textAnchor="middle" fill="#fff" fontSize="9" fontWeight="600">
            {Math.round(p.reputation * 100)}%
          </text>
          <text x={x} y={y + 28} textAnchor="middle" fill="rgba(255,255,255,0.8)" fontSize="9">
            {p.node_id}
          </text>
        </g>
      ))}
    </svg>
  );
}
