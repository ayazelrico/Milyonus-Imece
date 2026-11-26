export function DecayForecastSvg({
  curve,
  demoteFloor,
}: {
  curve: { day: number; avg_trust: number; surviving_active: number }[];
  demoteFloor: number;
}) {
  if (curve.length === 0) return null;
  const w = 520;
  const h = 165;
  const pad = 28;
  const maxDay = Math.max(1, curve[curve.length - 1].day);
  const toX = (d: number) => pad + (d / maxDay) * (w - pad * 2);
  const toY = (v: number) => h - pad - Math.max(0, Math.min(1, v)) * (h - pad * 2);
  const pts = curve.map((c) => `${toX(c.day)},${toY(c.avg_trust)}`).join(" ");
  const floorY = toY(demoteFloor);

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-40 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="Memory Trust Decay Forecast"
    >
      <line x1={pad} y1={floorY} x2={w - pad} y2={floorY} stroke="#f87171" strokeDasharray="5 4" />
      <text x={w - pad} y={floorY - 4} textAnchor="end" fill="#fca5a5" fontSize="9">
        quarantine floor ({Math.round(demoteFloor * 100)}%)
      </text>
      <polyline fill="none" stroke="#5CC8FF" strokeWidth="2.4" points={pts} />
      {curve.map((c) => (
        <g key={c.day}>
          <circle cx={toX(c.day)} cy={toY(c.avg_trust)} r={3.5} fill="#5CC8FF" />
          <text x={toX(c.day)} y={h - 8} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize="9">
            +{c.day}d
          </text>
        </g>
      ))}
    </svg>
  );
}

export function DagWavesSvg({
  waves,
  criticalPath,
}: {
  waves: string[][];
  criticalPath: string[];
}) {
  if (waves.length === 0) return null;
  const crit = new Set(criticalPath);
  const w = 540;
  const h = 175;
  const colW = w / Math.max(1, waves.length);

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-44 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="DAG Topological Waves"
    >
      {waves.map((wave, wi) => {
        const x = colW * wi + colW / 2;
        const rowH = h / Math.max(1, wave.length + 1);
        return (
          <g key={wi}>
            <text x={x} y={14} textAnchor="middle" fill="rgba(255,255,255,0.4)" fontSize="9">
              Wave {wi}
            </text>
            {wave.map((nid, ni) => {
              const y = rowH * (ni + 1) + 8;
              const isCrit = crit.has(nid);
              return (
                <g key={nid}>
                  <rect
                    x={x - 46}
                    y={y - 14}
                    width={92}
                    height={26}
                    rx={8}
                    fill={isCrit ? "rgba(46,107,255,0.35)" : "rgba(255,255,255,0.08)"}
                    stroke={isCrit ? "#5CC8FF" : "rgba(255,255,255,0.2)"}
                  />
                  <text x={x} y={y + 3} textAnchor="middle" fill="#fff" fontSize="9">
                    {nid.slice(0, 14)}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

export function EconomyScalesSvg({
  scales,
}: {
  scales: {
    agents: number;
    hybrid_cost_usd: number;
    frontier_baseline_usd: number;
    savings_pct: number;
  }[];
}) {
  if (scales.length === 0) return null;
  const w = 520;
  const h = 165;
  const pad = 28;
  const maxUsd = Math.max(0.01, ...scales.map((s) => s.frontier_baseline_usd));
  const groupW = (w - pad * 2) / scales.length;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="w-full h-44 rounded-xl bg-black/50 border border-white/10"
      role="img"
      aria-label="Collective Scale Economy Comparison"
    >
      {scales.map((s, i) => {
        const x0 = pad + i * groupW + 10;
        const bw = Math.max(12, groupW / 3);
        const hFront = Math.max(4, (s.frontier_baseline_usd / maxUsd) * (h - pad * 2));
        const hHyb = Math.max(4, (s.hybrid_cost_usd / maxUsd) * (h - pad * 2));
        return (
          <g key={s.agents}>
            <rect
              x={x0}
              y={h - pad - hFront}
              width={bw}
              height={hFront}
              rx={3}
              fill="rgba(255,255,255,0.2)"
            />
            <rect
              x={x0 + bw + 4}
              y={h - pad - hHyb}
              width={bw}
              height={hHyb}
              rx={3}
              fill="#34d399"
            />
            <text
              x={x0 + bw}
              y={h - 9}
              textAnchor="middle"
              fill="rgba(255,255,255,0.65)"
              fontSize="9"
            >
              {s.agents.toLocaleString()}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
