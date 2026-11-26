import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useUi } from "../store";

type ImeceRunRow = {
  id: string;
  task: string;
  agents: number;
  mode: string;
  state: string;
  current_phase: string;
  created_at: number;
};

type ImeceRunDetail = ImeceRunRow & {
  report?: {
    status?: string;
    deliverable?: string;
    rounds?: number;
    tokens?: number;
    allocation?: Record<string, number>;
    proof?: { merkle_root: string; bundle_sha256: string };
  } | null;
  error?: string | null;
};

type PhaseEvent = {
  seq: number;
  type: string;
  phase?: string;
  elapsed_s?: number;
  accepted?: boolean;
  proof_merkle_root?: string;
  message?: string;
};

type LeaderboardRow = {
  contender_id: string;
  label: string;
  rating: number;
  wins: number;
  losses: number;
  draws: number;
};

type ArenaMatchResp = {
  match_id: string;
  winner: string;
  reason: string;
  rating_changes: Record<string, { before: number; after: number; delta: number }>;
};

const AGENT_SCALES = [17, 50, 250, 1000, 10000];

export function WarRoomModal() {
  const qc = useQueryClient();
  const { warRoomOpen, setWarRoomOpen } = useUi();
  const [tab, setTab] = useState<"warroom" | "arena">("warroom");

  // M3 War Room state
  const [task, setTask] = useState("");
  const [agents, setAgents] = useState(17);
  const [dryRun, setDryRun] = useState(true);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<PhaseEvent[]>([]);
  const [detail, setDetail] = useState<ImeceRunDetail | null>(null);
  const [warError, setWarError] = useState("");
  const esRef = useRef<EventSource | null>(null);

  // M5 Arena state
  const [arenaTask, setArenaTask] = useState("");
  const [contenderA, setContenderA] = useState("direct");
  const [contenderB, setContenderB] = useState("structured");
  const [arenaResult, setArenaResult] = useState<ArenaMatchResp | null>(null);
  const [arenaBusy, setArenaBusy] = useState(false);

  const runs = useQuery({
    queryKey: ["imece-runs"],
    queryFn: () => api<ImeceRunRow[]>("/v1/imece/runs"),
    enabled: warRoomOpen && tab === "warroom",
  });

  const arena = useQuery({
    queryKey: ["arena-leaderboard"],
    queryFn: () => api<{ leaderboard: LeaderboardRow[] }>("/v1/arena/leaderboard"),
    enabled: warRoomOpen && tab === "arena",
  });

  useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  if (!warRoomOpen) return null;

  function attachRunStream(runId: string) {
    esRef.current?.close();
    setActiveRunId(runId);
    setEvents([]);
    setDetail(null);
    const es = new EventSource(`/v1/imece/runs/${runId}/stream`, { withCredentials: true });
    esRef.current = es;

    const pushEv = (ev: MessageEvent) => {
      const data = JSON.parse(ev.data) as PhaseEvent;
      setEvents((prev) => [...prev, data]);
      if (
        data.type === "imece.completed" ||
        data.type === "imece.stopped" ||
        data.type === "imece.error"
      ) {
        es.close();
        esRef.current = null;
        void api<ImeceRunDetail>(`/v1/imece/runs/${runId}`).then(setDetail);
        qc.invalidateQueries({ queryKey: ["imece-runs"] });
      }
    };
    es.addEventListener("imece.started", (e) => pushEv(e as MessageEvent));
    es.addEventListener("imece.phase", (e) => pushEv(e as MessageEvent));
    es.addEventListener("imece.completed", (e) => pushEv(e as MessageEvent));
    es.addEventListener("imece.stopped", (e) => pushEv(e as MessageEvent));
    es.addEventListener("imece.error", (e) => pushEv(e as MessageEvent));
  }

  async function launchCollective() {
    if (!task.trim()) return;
    setWarError("");
    try {
      const started = await api<{ id: string }>("/v1/imece/runs", {
        method: "POST",
        body: JSON.stringify({ task: task.trim(), agents, dry_run: dryRun }),
      });
      attachRunStream(started.id);
      qc.invalidateQueries({ queryKey: ["imece-runs"] });
    } catch (err) {
      setWarError(String(err));
    }
  }

  async function emergencyStop() {
    if (!activeRunId) return;
    await api(`/v1/imece/runs/${activeRunId}/stop`, { method: "POST" });
  }

  async function downloadProof(runId: string) {
    const proof = await api<Record<string, unknown>>(`/v1/imece/runs/${runId}/proof`);
    const blob = new Blob([JSON.stringify(proof, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${runId}.milyonus-proof.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function runArenaMatch() {
    if (!arenaTask.trim()) return;
    setArenaBusy(true);
    try {
      const res = await api<ArenaMatchResp>("/v1/arena/match", {
        method: "POST",
        body: JSON.stringify({
          task: arenaTask.trim(),
          contender_a: contenderA.trim() || "direct",
          contender_b: contenderB.trim() || "structured",
          dry_run: true,
        }),
      });
      setArenaResult(res);
      qc.invalidateQueries({ queryKey: ["arena-leaderboard"] });
    } finally {
      setArenaBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-label="İmece War Room & Strategy Arena"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4"
      onClick={() => setWarRoomOpen(false)}
    >
      <div
        className="glass rounded-card border border-white/15 w-full max-w-3xl max-h-[88vh] overflow-y-auto p-6 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <h2 className="font-serif italic text-2xl text-white">⚡ Milyonus-Imece</h2>
            <div className="flex rounded-full bg-black/40 p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setTab("warroom")}
                className={`rounded-full px-3 py-1 ${
                  tab === "warroom" ? "bg-brand text-white" : "text-white/60"
                }`}
              >
                War Room
              </button>
              <button
                type="button"
                onClick={() => setTab("arena")}
                className={`rounded-full px-3 py-1 ${
                  tab === "arena" ? "bg-brand text-white" : "text-white/60"
                }`}
              >
                ⚔️ Strategy Arena
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setWarRoomOpen(false)}
            className="text-white/60 hover:text-white"
          >
            ✕
          </button>
        </div>

        {tab === "warroom" ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <textarea
                rows={2}
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Describe a hard engineering task for Kapı 1 → İmece → IRADE → Kapı 2 → Kapı 3…"
                className="w-full rounded-xl bg-black/45 border border-white/15 p-3 text-sm outline-none focus:border-brand"
              />
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-white/50">Scale:</span>
                  {AGENT_SCALES.map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setAgents(n)}
                      className={`rounded-full px-2.5 py-0.5 border ${
                        agents === n
                          ? "border-accent text-accent bg-accent/15"
                          : "border-white/15 text-white/60"
                      }`}
                    >
                      {n.toLocaleString()}
                    </button>
                  ))}
                  <label className="ml-2 inline-flex items-center gap-1.5 text-white/75">
                    <input
                      type="checkbox"
                      checked={dryRun}
                      onChange={(e) => setDryRun(e.target.checked)}
                    />
                    Zero-spend dry run
                  </label>
                </div>
                <div className="flex gap-2">
                  {activeRunId && !detail && (
                    <button
                      type="button"
                      onClick={() => void emergencyStop()}
                      className="rounded-full bg-red-600 hover:bg-red-500 px-4 py-1.5 text-xs font-medium"
                    >
                      🛑 Emergency Stop
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void launchCollective()}
                    className="rounded-full bg-brand hover:bg-brand/90 px-4 py-1.5 text-xs font-medium"
                  >
                    Launch Collective
                  </button>
                </div>
              </div>
              {warError && <p className="text-xs text-red-300">{warError}</p>}
            </div>

            {events.length > 0 && (
              <div className="rounded-xl bg-black/45 border border-white/10 p-3 space-y-1.5">
                <p className="text-[11px] uppercase tracking-wide text-white/45">
                  Live Collective Telemetry ({activeRunId})
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {events
                    .filter((e) => e.phase)
                    .map((e) => (
                      <span
                        key={e.seq}
                        className="rounded-full bg-accent/15 border border-accent/30 px-2.5 py-0.5 text-[11px] text-accent"
                      >
                        {e.phase} · {e.elapsed_s}s
                      </span>
                    ))}
                </div>
              </div>
            )}

            {detail && (
              <div className="rounded-xl bg-black/50 border border-emerald-400/30 p-3 space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-emerald-300">
                    Run {detail.id} — {detail.state} ({detail.report?.status ?? "done"})
                  </span>
                  {detail.report?.proof && (
                    <button
                      type="button"
                      onClick={() => void downloadProof(detail.id)}
                      className="rounded-full bg-white/10 hover:bg-white/20 px-3 py-1 text-[11px] text-accent"
                    >
                      ↓ .milyonus-proof.json ({detail.report.proof.merkle_root.slice(0, 10)}…)
                    </button>
                  )}
                </div>
                {detail.report?.deliverable && (
                  <pre className="whitespace-pre-wrap max-h-48 overflow-y-auto rounded bg-black/50 p-2.5 text-white/80">
                    {detail.report.deliverable}
                  </pre>
                )}
              </div>
            )}

            {(runs.data?.length ?? 0) > 0 && (
              <div className="space-y-1.5 border-t border-white/10 pt-3">
                <p className="text-[11px] uppercase tracking-wide text-white/45">Recent Runs</p>
                {(runs.data ?? []).slice(0, 6).map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    onClick={() =>
                      void api<ImeceRunDetail>(`/v1/imece/runs/${r.id}`).then((d) => {
                        setActiveRunId(r.id);
                        setDetail(d);
                      })
                    }
                    className="w-full flex items-center justify-between rounded-lg bg-black/30 hover:bg-white/10 px-3 py-2 text-xs text-left"
                  >
                    <span className="truncate max-w-md">{r.task}</span>
                    <span className="text-white/50">
                      {r.agents} agents · {r.state}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              <input
                value={contenderA}
                onChange={(e) => setContenderA(e.target.value)}
                placeholder="Contender A (e.g. direct)"
                className="rounded-xl bg-black/40 border border-white/15 px-3 py-2 outline-none focus:border-brand"
              />
              <input
                value={contenderB}
                onChange={(e) => setContenderB(e.target.value)}
                placeholder="Contender B (e.g. structured)"
                className="rounded-xl bg-black/40 border border-white/15 px-3 py-2 outline-none focus:border-brand"
              />
            </div>
            <div className="flex gap-2">
              <input
                value={arenaTask}
                onChange={(e) => setArenaTask(e.target.value)}
                placeholder="Task to pit head-to-head…"
                className="flex-1 rounded-xl bg-black/40 border border-white/15 px-3 py-2 text-xs outline-none focus:border-brand"
              />
              <button
                type="button"
                disabled={arenaBusy}
                onClick={() => void runArenaMatch()}
                className="rounded-full bg-brand px-4 py-2 text-xs font-medium disabled:opacity-50"
              >
                {arenaBusy ? "Running…" : "Run Match"}
              </button>
            </div>
            {arenaResult && (
              <div className="rounded-xl bg-emerald-500/10 border border-emerald-400/30 p-3 text-xs space-y-1">
                <p className="font-medium text-emerald-300">
                  Winner: {arenaResult.winner} — {arenaResult.reason}
                </p>
                {Object.entries(arenaResult.rating_changes).map(([cid, d]) => (
                  <p key={cid} className="text-white/75">
                    {cid}: {d.before.toFixed(1)} → {d.after.toFixed(1)} (
                    {d.delta >= 0 ? "+" : ""}
                    {d.delta.toFixed(1)})
                  </p>
                ))}
              </div>
            )}
            <div className="space-y-1.5 border-t border-white/10 pt-3">
              <p className="text-[11px] uppercase tracking-wide text-white/45">
                Elo Leaderboard
              </p>
              {(arena.data?.leaderboard ?? []).length === 0 ? (
                <p className="text-xs text-white/45">No matches yet — run your first match above.</p>
              ) : (
                (arena.data?.leaderboard ?? []).map((row, i) => (
                  <div
                    key={row.contender_id}
                    className="flex items-center justify-between rounded-lg bg-black/35 px-3 py-2 text-xs"
                  >
                    <span>
                      #{i + 1} <strong className="text-accent">{row.label}</strong>
                    </span>
                    <span className="text-white/75">
                      Elo {row.rating.toFixed(1)} · {row.wins}W-{row.losses}L-{row.draws}D
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
