import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, MemoryItem, SkillSummary, UsageData } from "../api";
import { t } from "../i18n";
import { useUi } from "../store";

type Tab = "memory" | "skills" | "rules";

function formatDecay(reviewAt: number | null | undefined, dueLabel: string): string | null {
  if (!reviewAt) return null;
  const delta = reviewAt - Date.now() / 1000;
  if (delta <= 0) return dueLabel;
  const days = Math.ceil(delta / 86400);
  if (days >= 2) return `${days}d`;
  const hours = Math.max(1, Math.ceil(delta / 3600));
  return `${hours}h`;
}

export function TrustRail() {
  const qc = useQueryClient();
  const { railOpen, setRailOpen, locale, budgetPressure, prefixCacheHit } = useUi();
  const [tab, setTab] = useState<Tab>("memory");
  const [memState, setMemState] = useState<string>("active");
  const [revokeUri, setRevokeUri] = useState("");
  const [revokePreview, setRevokePreview] = useState<string[] | null>(null);
  const [why, setWhy] = useState<Record<string, unknown> | null>(null);
  const [reaffirmMsg, setReaffirmMsg] = useState<string>("");
  const [ledgerStatus, setLedgerStatus] = useState<{ intact: boolean; head: string } | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<{ name: string; body: string } | null>(null);
  const [rulesDraft, setRulesDraft] = useState("");
  const [rulesStatus, setRulesStatus] = useState("");

  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: () => api<UsageData>("/v1/usage"),
  });

  const memory = useQuery({
    queryKey: ["memory", memState],
    queryFn: () => api<{ items: MemoryItem[] }>(`/v1/memory?state=${encodeURIComponent(memState)}`),
  });

  const t0Staged = useQuery({
    queryKey: ["memory", "t0_staged"],
    queryFn: () => api<{ items: MemoryItem[] }>("/v1/memory?state=t0_staged"),
  });

  const skills = useQuery({
    queryKey: ["skills"],
    queryFn: () => api<SkillSummary[]>("/v1/skills"),
  });

  const projectRules = useQuery({
    queryKey: ["project-instructions"],
    queryFn: () => api<{ filename: string; content: string }>("/v1/project-instructions"),
    enabled: tab === "rules",
  });

  useEffect(() => {
    if (projectRules.data) {
      setRulesDraft(projectRules.data.content);
    }
  }, [projectRules.data]);

  async function handleReaffirm(id: string) {
    setReaffirmMsg("");
    try {
      const res = await api<{ trust_ceiling: number }>(`/v1/memory/${id}/reaffirm`, {
        method: "POST",
      });
      setReaffirmMsg(`Reaffirmed (ceiling ${(res.trust_ceiling * 100).toFixed(0)}%)`);
      qc.invalidateQueries({ queryKey: ["memory"] });
    } catch (err) {
      setReaffirmMsg(String(err));
    }
  }

  async function saveRules() {
    setRulesStatus("");
    try {
      const res = await api<{ findings: string[] }>("/v1/project-instructions", {
        method: "PUT",
        body: JSON.stringify({ content: rulesDraft }),
      });
      setRulesStatus(
        res.findings.length
          ? `Saved (notes: ${res.findings.join(", ")})`
          : "Saved .milyonusrules ✓",
      );
    } catch (err) {
      setRulesStatus(String(err));
    }
  }

  const stagedCount = t0Staged.data?.items.length ?? 0;
  const pressurePct = Math.max(0, Math.min(100, Math.round(budgetPressure * 100)));

  return (
    <aside
      className={`${
        railOpen
          ? "fixed inset-x-0 bottom-0 z-40 h-[75vh] md:static md:h-auto flex"
          : "hidden"
      } md:flex flex-col border-t md:border-t-0 md:border-l border-white/10 glass p-4 gap-3 overflow-y-auto`}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-white/85">{t(locale, "trustRail")}</h2>
        <button
          type="button"
          className="md:hidden text-xs text-white/60"
          onClick={() => setRailOpen(false)}
        >
          ✕
        </button>
      </div>

      <section className="rounded-xl bg-black/30 border border-white/10 p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <h3 className="text-[11px] uppercase tracking-wide text-white/40">{t(locale, "usage")}</h3>
          {prefixCacheHit !== null && (
            <span
              className={`text-[10px] rounded-full px-2 py-0.5 ${
                prefixCacheHit
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-white/10 text-white/50"
              }`}
            >
              {prefixCacheHit ? "cache hit" : "cache warm"}
            </span>
          )}
        </div>
        <p className="text-xs text-white/85">
          {usage.data?.turns ?? 0} turns · {(usage.data?.tokens_used ?? 0).toLocaleString()} tok
          {usage.data?.cost_usd ? ` · $${usage.data.cost_usd.toFixed(4)}` : ""}
        </p>
        <div className="space-y-0.5">
          <div className="flex justify-between text-[10px] text-white/40">
            <span>context budget</span>
            <span>{pressurePct}%</span>
          </div>
          <div className="h-1 rounded-full bg-white/10 overflow-hidden">
            <div
              className={`h-full transition-all ${
                pressurePct >= 75
                  ? "bg-red-400"
                  : pressurePct >= 55
                    ? "bg-amber-400"
                    : "bg-accent"
              }`}
              style={{ width: `${Math.max(2, pressurePct)}%` }}
            />
          </div>
        </div>
      </section>

      <div className="grid grid-cols-3 gap-1 rounded-full bg-black/40 p-1 text-xs">
        {(["memory", "skills", "rules"] as Tab[]).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setTab(k)}
            className={`rounded-full py-1 transition-colors ${
              tab === k ? "bg-brand text-white" : "text-white/60 hover:text-white"
            }`}
          >
            {k === "memory"
              ? t(locale, "memories")
              : k === "skills"
                ? t(locale, "skills")
                : t(locale, "rules")}
          </button>
        ))}
      </div>

      {tab === "memory" && (
        <div className="space-y-3 flex-1 overflow-y-auto">
          <div className="flex flex-wrap gap-1 text-[11px]">
            {["active", "pending", "rejected", "revoked", "t0_staged"].map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => setMemState(st)}
                className={`rounded-full px-2 py-0.5 border ${
                  memState === st
                    ? "border-accent text-accent bg-accent/10"
                    : "border-white/10 text-white/50 hover:text-white"
                }`}
              >
                {st}
                {st === "t0_staged" && stagedCount > 0 ? ` (${stagedCount})` : ""}
              </button>
            ))}
          </div>

          {reaffirmMsg && (
            <p role="status" className="text-xs text-accent">
              {reaffirmMsg}
            </p>
          )}

          <ul className="space-y-2">
            {(memory.data?.items ?? []).slice(0, 20).map((m) => {
              const score = m.trust_score ?? 1;
              const decay = formatDecay(m.review_at, t(locale, "reviewDue"));
              return (
                <li
                  key={m.id}
                  className="rounded-xl bg-black/35 border border-white/10 p-2.5 text-xs space-y-1.5"
                >
                  <div className="flex justify-between text-white/55">
                    <span className="font-medium text-accent">{m.trust_tier}</span>
                    <span>
                      {m.state} · {(score * 100).toFixed(0)}%
                      {decay ? ` · ⏱ ${decay}` : ""}
                    </span>
                  </div>
                  <div className="h-1 rounded-full bg-white/10 overflow-hidden">
                    <div
                      className="h-full bg-brand"
                      style={{ width: `${Math.max(4, Math.min(100, score * 100))}%` }}
                    />
                  </div>
                  <p className="text-white/85 line-clamp-3">{m.content}</p>
                  <div className="flex gap-3">
                    <button
                      type="button"
                      className="text-accent underline"
                      onClick={async () => {
                        const detail = await api<Record<string, unknown>>(`/v1/memory/${m.id}/why`);
                        setWhy(detail);
                      }}
                    >
                      {t(locale, "why")}
                    </button>
                    {m.state === "active" && (
                      <button
                        type="button"
                        className="text-white/70 hover:text-white underline"
                        onClick={() => void handleReaffirm(m.id)}
                      >
                        {t(locale, "reaffirm")}
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <section className="pt-2 border-t border-white/10">
            <h3 className="text-[11px] uppercase tracking-wide text-white/45">
              {t(locale, "revokeBySource")}
            </h3>
            <form
              className="mt-2 flex gap-1.5"
              onSubmit={async (e) => {
                e.preventDefault();
                if (!revokeUri.trim()) return;
                if (revokePreview === null) {
                  const preview = await api<{ affected: string[] }>("/v1/memory/revoke-preview", {
                    method: "POST",
                    body: JSON.stringify({ source_uri: revokeUri }),
                  });
                  setRevokePreview(preview.affected);
                  return;
                }
                await api("/v1/memory/revoke", {
                  method: "POST",
                  body: JSON.stringify({ source_uri: revokeUri }),
                });
                setRevokeUri("");
                setRevokePreview(null);
                qc.invalidateQueries({ queryKey: ["memory"] });
              }}
            >
              <input
                className="flex-1 rounded-full bg-black/40 border border-white/15 px-3 py-1.5 text-xs outline-none focus:border-brand"
                placeholder="https://…"
                value={revokeUri}
                onChange={(e) => {
                  setRevokeUri(e.target.value);
                  setRevokePreview(null);
                }}
              />
              <button
                type="submit"
                className="rounded-full bg-white/10 hover:bg-white/20 px-3 text-xs"
              >
                {revokePreview === null ? t(locale, "preview") : t(locale, "revoke")}
              </button>
            </form>
            {revokePreview !== null && (
              <p role="status" className="mt-1.5 text-xs text-amber-200">
                {revokePreview.length} memories will be revoked (including derived records).
              </p>
            )}
            {revokeUri.trim() && (
              <CounterfactualButton sourceUri={revokeUri.trim()} />
            )}
          </section>

          {why && (
            <section
              aria-label="Memory provenance"
              className="rounded-xl bg-black/60 border border-white/15 p-2.5 text-xs"
            >
              <div className="flex justify-between items-center mb-1">
                <span className="font-medium text-white/80">Provenance</span>
                <button type="button" onClick={() => setWhy(null)} className="text-white/50">
                  ✕
                </button>
              </div>
              <pre className="whitespace-pre-wrap break-all text-[11px] text-white/70">
                {JSON.stringify(why, null, 2)}
              </pre>
            </section>
          )}
        </div>
      )}

      {tab === "skills" && (
        <div className="space-y-2 flex-1 overflow-y-auto text-xs">
          {selectedSkill ? (
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setSelectedSkill(null)}
                className="text-accent underline"
              >
                ← All skills
              </button>
              <pre className="whitespace-pre-wrap rounded-xl bg-black/50 p-2.5 text-[11px] text-white/80">
                {selectedSkill.body}
              </pre>
            </div>
          ) : (
            (skills.data ?? []).map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={async () => {
                  const full = await api<{ name: string; body: string }>(`/v1/skills/${s.name}`);
                  setSelectedSkill(full);
                }}
                className="w-full text-left rounded-xl bg-black/35 border border-white/10 hover:border-brand/50 p-2.5"
              >
                <div className="font-medium text-accent">{s.name}</div>
                <div className="text-white/55 line-clamp-2 mt-0.5">{s.description}</div>
              </button>
            ))
          )}
        </div>
      )}

      {tab === "rules" && (
        <div className="space-y-2 flex-1 flex flex-col text-xs">
          <p className="text-white/55">
            Workspace instructions (`.milyonusrules`). Scanned for prompt injection on save.
          </p>
          <textarea
            value={rulesDraft}
            onChange={(e) => setRulesDraft(e.target.value)}
            rows={10}
            className="flex-1 rounded-xl bg-black/40 border border-white/15 p-2.5 text-xs outline-none focus:border-brand"
            placeholder="Project coding conventions, architecture notes…"
          />
          {rulesStatus && (
            <p role="status" className="text-accent">
              {rulesStatus}
            </p>
          )}
          <button
            type="button"
            onClick={() => void saveRules()}
            className="rounded-full bg-brand py-2 text-xs font-medium"
          >
            {t(locale, "saveRules")}
          </button>
        </div>
      )}

      <div className="mt-auto pt-2 border-t border-white/10 space-y-2">
        <MoonshotRailTools />
        <div className="space-y-1">
          <button
            type="button"
            className="text-xs text-white/60 hover:text-white underline"
            onClick={async () => {
              const v = await api<{ intact: boolean; head: string }>("/v1/audit/verify");
              setLedgerStatus(v);
            }}
          >
            {t(locale, "verifyLedger")}
          </button>
          {ledgerStatus && (
            <p
              role="status"
              className={`text-[11px] ${ledgerStatus.intact ? "text-emerald-300" : "text-red-300"}`}
            >
              {ledgerStatus.intact
                ? `✓ ${t(locale, "ledgerIntact")}`
                : `✗ ${t(locale, "ledgerBroken")}`}{" "}
              {ledgerStatus.head ? `(${ledgerStatus.head.slice(0, 12)}…)` : ""}
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}

type TimelineCheckpoint = {
  seq: number;
  action: string;
  item_id: string | null;
  preview: string;
  valid_link: boolean;
};

type SnapshotAt = {
  seq: number;
  chain_intact: boolean;
  active_count: number;
  pending_count: number;
  revoked_count: number;
  rendered_snapshot: string;
};

function MoonshotRailTools() {
  const { sessionId } = useUi();
  const [ttOpen, setTtOpen] = useState(false);
  const [checkpoints, setCheckpoints] = useState<TimelineCheckpoint[]>([]);
  const [selectedSeq, setSelectedSeq] = useState<number>(0);
  const [snap, setSnap] = useState<SnapshotAt | null>(null);
  const [statusMsg, setStatusMsg] = useState("");

  async function openTimeTravel() {
    if (ttOpen) {
      setTtOpen(false);
      return;
    }
    const res = await api<{ checkpoints: TimelineCheckpoint[] }>("/v1/memory/timeline");
    setCheckpoints(res.checkpoints);
    const maxSeq = res.checkpoints.length ? res.checkpoints[res.checkpoints.length - 1].seq : 0;
    setSelectedSeq(maxSeq);
    if (maxSeq > 0) {
      const s = await api<SnapshotAt>(`/v1/memory/snapshot?seq=${maxSeq}`);
      setSnap(s);
    }
    setTtOpen(true);
  }

  async function scrubTo(seq: number) {
    setSelectedSeq(seq);
    const s = await api<SnapshotAt>(`/v1/memory/snapshot?seq=${seq}`);
    setSnap(s);
  }

  async function exportSessionProof() {
    if (!sessionId) return;
    setStatusMsg("");
    try {
      const bundle = await api<Record<string, unknown>>(`/v1/sessions/${sessionId}/proof`);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${sessionId}.milyonus-proof.json`;
      a.click();
      URL.revokeObjectURL(url);
      const root = String(bundle.merkle_root ?? "").slice(0, 12);
      setStatusMsg(`Proof exported ✓ (merkle ${root}…)`);
    } catch (e) {
      setStatusMsg(String(e));
    }
  }

  async function forgeSkillFromChat() {
    if (!sessionId) return;
    setStatusMsg("");
    try {
      const res = await api<{ name: string; sha256?: string }>(
        `/v1/sessions/${sessionId}/forge-skill`,
        {
          method: "POST",
          body: JSON.stringify({ name: `session-${sessionId.slice(2, 8)}`, publish: true }),
        },
      );
      setStatusMsg(`Forged skill '${res.name}' ✓`);
    } catch (e) {
      setStatusMsg(String(e));
    }
  }

  return (
    <div className="space-y-1.5 text-xs">
      <div className="flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => void openTimeTravel()}
          className="rounded-full bg-white/10 hover:bg-white/20 px-2.5 py-1 text-[11px]"
        >
          ⏳ Time-Travel
        </button>
        {sessionId && (
          <>
            <button
              type="button"
              onClick={() => void exportSessionProof()}
              className="rounded-full bg-white/10 hover:bg-white/20 px-2.5 py-1 text-[11px]"
            >
              🔐 Proof
            </button>
            <button
              type="button"
              onClick={() => void forgeSkillFromChat()}
              className="rounded-full bg-white/10 hover:bg-white/20 px-2.5 py-1 text-[11px]"
            >
              ⚒ Forge Skill
            </button>
          </>
        )}
      </div>

      {statusMsg && (
        <p role="status" className="text-[11px] text-accent">
          {statusMsg}
        </p>
      )}

      {ttOpen && (
        <div className="rounded-xl bg-black/50 border border-white/15 p-2.5 space-y-1.5">
          {checkpoints.length === 0 ? (
            <p className="text-[11px] text-white/50">No ledger checkpoints yet.</p>
          ) : (
            <>
              <div className="flex justify-between text-[11px] text-white/70">
                <span>Seq #{selectedSeq}</span>
                <span>
                  {snap
                    ? `${snap.active_count} active · ${snap.chain_intact ? "chain ✓" : "BROKEN"}`
                    : ""}
                </span>
              </div>
              <input
                type="range"
                aria-label="Memory ledger sequence"
                min={checkpoints[0].seq}
                max={checkpoints[checkpoints.length - 1].seq}
                value={selectedSeq}
                onChange={(e) => void scrubTo(Number(e.target.value))}
                className="w-full accent-brand"
              />
              {snap?.rendered_snapshot && (
                <pre className="whitespace-pre-wrap max-h-28 overflow-y-auto rounded bg-black/60 p-1.5 text-[10px] text-white/75">
                  {snap.rendered_snapshot}
                </pre>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

type CounterfactualResp = {
  direct_count: number;
  derived_count: number;
  before_active_count: number;
  after_active_count: number;
  tokens_freed_estimate: number;
};

function CounterfactualButton({ sourceUri }: { sourceUri: string }) {
  const [sim, setSim] = useState<CounterfactualResp | null>(null);

  return (
    <div className="mt-1.5 space-y-1">
      <button
        type="button"
        onClick={async () => {
          const res = await api<CounterfactualResp>("/v1/memory/counterfactual", {
            method: "POST",
            body: JSON.stringify({ source_uri: sourceUri }),
          });
          setSim(res);
        }}
        className="text-[11px] text-accent underline"
      >
        Simulate counterfactual (no mutation)
      </button>
      {sim && (
        <p className="text-[11px] text-white/70">
          Direct {sim.direct_count} + derived {sim.derived_count} · active {sim.before_active_count}{" "}
          → {sim.after_active_count} (~{sim.tokens_freed_estimate} tok freed)
        </p>
      )}
    </div>
  );
}
