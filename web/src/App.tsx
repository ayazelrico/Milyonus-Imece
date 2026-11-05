import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { FormEvent, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api, MemoryItem, Session } from "./api";
import { useUi } from "./store";

const ease = [0.22, 1, 0.36, 1] as const;

export default function App() {
  const [email, setEmail] = useState("");
  const [authed, setAuthed] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("login_token");
    if (token) {
      window.history.replaceState({}, "", window.location.pathname);
      api("/v1/auth/verify", { method: "POST", body: JSON.stringify({ token }) })
        .then(() => setAuthed(true))
        .catch((err) => setBootError(String(err)));
      return;
    }
    api<{ sessions: Session[] }>("/v1/export")
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false));
  }, []);

  if (!authed) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6">
        <motion.form
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="glass rounded-card w-full max-w-md p-8 border border-white/10"
          onSubmit={async (e) => {
            e.preventDefault();
            setBootError(null);
            try {
              const link = await api<{ token: string | null }>("/v1/auth/magic-link", {
                method: "POST",
                body: JSON.stringify({ email }),
              });
              if (!link.token) {
                setBootError("Giriş bağlantısı e-posta adresinize gönderildi.");
                return;
              }
              await api("/v1/auth/verify", {
                method: "POST",
                body: JSON.stringify({ token: link.token }),
              });
              setAuthed(true);
            } catch (err) {
              setBootError(err instanceof Error ? err.message : "auth failed");
            }
          }}
        >
          <p className="font-serif italic text-3xl text-white">Milyonus</p>
          <p className="mt-2 text-sm text-white/60">
            Remembers. Verifies. Evolves. — sign in with a magic link.
          </p>
          <input
            className="mt-6 w-full rounded-full bg-black/40 border border-white/15 px-4 py-3 outline-none focus:border-brand"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            required
          />
          {bootError && <p className="mt-3 text-sm text-red-400">{bootError}</p>}
          <button
            type="submit"
            className="mt-4 w-full rounded-full bg-brand hover:bg-brand/90 py-3 font-medium transition-colors duration-300 ease-soft"
          >
            Continue
          </button>
        </motion.form>
      </div>
    );
  }

  return <Shell />;
}

function Shell() {
  const [attachments, setAttachments] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const qc = useQueryClient();
  const {
    sessionId,
    setSession,
    messages,
    setMessages,
    pushMessage,
    streaming,
    appendStream,
    clearStream,
    tools,
    addTool,
    approval,
    setApproval,
    railOpen,
    setRailOpen,
  } = useUi();
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [activeTurn, setActiveTurn] = useState<string | null>(null);
  const [contextNotice, setContextNotice] = useState("");
  const [turnError, setTurnError] = useState("");
  const [revokeUri, setRevokeUri] = useState("");
  const [revokePreview, setRevokePreview] = useState<string[] | null>(null);
  const [why, setWhy] = useState<Record<string, unknown> | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api<Session[]>("/v1/sessions"),
  });
  const results = useQuery({
    queryKey: ["search", search],
    queryFn: () => api<{ session_id: string; message_id: string; snippet: string }[]>(
      "/v1/search?q=" + encodeURIComponent(search),
    ),
    enabled: search.trim().length > 1,
  });
  const memory = useQuery({
    queryKey: ["memory"],
    queryFn: () => api<{ items: MemoryItem[] }>("/v1/memory"),
  });
  const usage = useQuery({
    queryKey: ["usage"],
    queryFn: () => api<{ tokens_used: number; cost_usd: number; turns: number }>("/v1/usage"),
  });

  const createSession = useMutation({
    mutationFn: () => api<{ id: string }>("/v1/sessions", { method: "POST", body: "{}" }),
    onSuccess: (data) => {
      setSession(data.id);
      setMessages([]);
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming, tools, approval]);

  useEffect(() => {
    if (!sessionId) return;
    api<{ messages: { id: string; role: string; content: string }[] }>(
      `/v1/sessions/${sessionId}`,
    ).then((s) =>
      setMessages(
        s.messages
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            id: m.id,
            role: m.role as "user" | "assistant",
            content: m.content,
          })),
      ),
    );
  }, [sessionId, setMessages]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!draft.trim() || activeTurn) return;
    let sid = sessionId;
    if (!sid) {
      const created = await createSession.mutateAsync();
      sid = created.id;
    }
    const text = draft.trim();
    setDraft("");
    pushMessage({ id: crypto.randomUUID(), role: "user", content: text });
    clearStream();
    setContextNotice("");
    setTurnError("");
    let turn_id: string;
    try {
      ({ turn_id } = await api<{ turn_id: string }>(`/v1/sessions/${sid}/messages`, {
        method: "POST",
        body: JSON.stringify({ text, attachments }),
      }));
    } catch (error) {
      setTurnError(String(error));
      setDraft(text);
      return;
    }
    setAttachments([]);
    setActiveTurn(turn_id);
    const es = new EventSource(`/v1/sessions/${sid}/stream?turn_id=${encodeURIComponent(turn_id)}`, { withCredentials: true });
    es.addEventListener("error", (ev) => {
      // Transport errors have no data and reconnect automatically.
      if (ev instanceof MessageEvent && ev.data) {
        const data = JSON.parse(ev.data);
        setTurnError(data.message ?? data.code ?? "The turn failed.");
      }
    });
    es.addEventListener("context.sources", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as {
        sources: { source: string; included: boolean; reason: string }[];
      };
      setContextNotice(data.sources.map((s) =>
        `${s.source}: ${s.included ? "scanned reference" : `skipped (${s.reason})`}`,
      ).join(" · "));
    });
    es.addEventListener("context.compacted", () => {
      setContextNotice((previous) => [previous, "Older conversation shortened; full history saved."].filter(Boolean).join(" · "));
    });
    es.addEventListener("text.delta", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      appendStream(data.text ?? "");
    });
    es.addEventListener("tool.call", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      addTool({
        call_id: data.call_id,
        name: data.name,
        args_preview: data.args_preview,
        risk: data.risk,
      });
    });
    es.addEventListener("approval.required", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data);
      setApproval({
        approval_id: data.approval_id,
        name: data.name,
        args: data.args,
        risk: data.risk,
        reason: data.reason,
        irreversible: data.irreversible,
        findings: data.findings ?? [],
      });
    });
    es.addEventListener("turn.completed", () => {
      es.close();
      setActiveTurn(null);
      setApproval(null);
      const finalText = useUi.getState().streaming;
      if (finalText) {
        pushMessage({ id: crypto.randomUUID(), role: "assistant", content: finalText });
        clearStream();
      }
      qc.invalidateQueries({ queryKey: ["usage"] });
      qc.invalidateQueries({ queryKey: ["memory"] });
    });
    // EventSource reconnects automatically and sends Last-Event-ID for replay.
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setApproval(null);
      }
    };
  }

  return (
    <div className="h-screen grid grid-cols-1 md:grid-cols-[240px_1fr_280px]">
      <aside className="hidden md:flex flex-col border-r border-white/10 glass p-4 gap-3">
        <div className="font-serif italic text-2xl text-white">Milyonus</div>
        <button
          className="rounded-full bg-brand/90 hover:bg-brand py-2 text-sm transition-colors duration-300 ease-soft"
          onClick={() => createSession.mutate()}
        >
          New chat
        </button>
        <input aria-label="Search conversations" placeholder="Search conversations…"
          value={search} onChange={(e) => setSearch(e.target.value)}
          className="rounded-xl bg-black/40 px-3 py-2 text-sm" />
        {search.trim().length > 1 && (
          <div aria-label="Search results" className="text-xs space-y-2">
            {(results.data ?? []).map((hit) => (
              <button key={hit.message_id} onClick={() => setSession(hit.session_id)}
                className="block text-left rounded-xl p-2 hover:bg-white/10">
                {hit.snippet}
              </button>
            ))}
            {results.isError && <p role="alert">Search failed.</p>}
            {results.data?.length === 0 && <p>No matching conversations.</p>}
          </div>
        )}
        <div className="flex-1 overflow-y-auto space-y-1 mt-2">
          {(sessions.data ?? []).map((s) => (
            <button
              key={s.id}
              onClick={() => setSession(s.id)}
              className={`w-full text-left rounded-xl px-3 py-2 text-sm transition-colors ${
                sessionId === s.id ? "bg-white/15" : "hover:bg-white/10"
              }`}
            >
              {s.title || "Untitled"}
            </button>
          ))}
        </div>
      </aside>

      <main className="flex flex-col min-h-0">
        {turnError && <p role="alert" className="px-4 py-2 text-sm text-red-300">{turnError}</p>}
        {contextNotice && <p role="status" className="px-4 py-2 text-xs text-white/60">{contextNotice}</p>}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-4">
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <motion.div
                key={m.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease }}
                className={`max-w-3xl ${m.role === "user" ? "ml-auto" : ""}`}
              >
                <div
                  className={`rounded-card px-4 py-3 border border-white/10 ${
                    m.role === "user" ? "bg-brand/20" : "glass"
                  }`}
                >
                  {m.role === "assistant" ? (
                    <ReactMarkdown className="prose prose-invert prose-sm max-w-none">
                      {m.content}
                    </ReactMarkdown>
                  ) : (
                    <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {tools.map((t) => (
            <div
              key={t.call_id}
              className="max-w-3xl rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-xs text-white/70"
            >
              ▸ tool: <span className="text-accent">{t.name}</span>{" "}
              <span className="text-white/40">{t.risk}</span>
              {t.args_preview && (
                <pre className="mt-1 overflow-x-auto text-white/50">{t.args_preview}</pre>
              )}
            </div>
          ))}
          {approval && (
            <div className="max-w-3xl rounded-card border border-amber-400/40 bg-amber-500/10 p-4">
              <p className="font-medium text-amber-200">Approval required — {approval.name}</p>
              <p className="text-sm text-white/70 mt-1">{approval.reason}</p>
              <pre className="mt-2 text-xs overflow-x-auto text-white/50">
                {JSON.stringify(approval.args, null, 2)}
              </pre>
              <div className="mt-3 flex gap-2">
                <button
                  className="rounded-full bg-brand px-4 py-2 text-sm"
                  onClick={async () => {
                    await api(`/v1/approvals/${approval.approval_id}`, {
                      method: "POST",
                      body: JSON.stringify({ decision: "allow" }),
                    });
                    setApproval(null);
                  }}
                >
                  Allow
                </button>
                {!approval.irreversible && (
                  <button
                    className="rounded-full bg-white/10 px-4 py-2 text-sm"
                    onClick={async () => {
                      await api(`/v1/approvals/${approval.approval_id}`, {
                        method: "POST",
                        body: JSON.stringify({ decision: "allow_session" }),
                      });
                      setApproval(null);
                    }}
                  >
                    Allow for session
                  </button>
                )}
                <button
                  className="rounded-full bg-red-500/80 px-4 py-2 text-sm"
                  onClick={async () => {
                    await api(`/v1/approvals/${approval.approval_id}`, {
                      method: "POST",
                      body: JSON.stringify({ decision: "deny" }),
                    });
                    setApproval(null);
                  }}
                >
                  Deny
                </button>
              </div>
            </div>
          )}
          {streaming && (
            <div className="max-w-3xl glass rounded-card px-4 py-3 border border-white/10">
              <ReactMarkdown className="prose prose-invert prose-sm max-w-none">
                {streaming}
              </ReactMarkdown>
            </div>
          )}
          <div ref={bottom} />
        </div>
        <form
          onSubmit={send}
          className="border-t border-white/10 p-4 md:px-8 glass"
        >
          <label className="text-xs text-white/70">
            Metin dosyası ekle ({attachments.length}/4)
            <input type="file" accept="text/*,.json,.csv,.md" disabled={attachments.length >= 4 || !!activeTurn}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                setUploadError(null);
                try {
                  const result = await api<{id: string}>("/v1/attachments", {
                    method: "POST", headers: {"Content-Type": "text/plain"}, body: file,
                  });
                  setAttachments((ids) => [...ids, result.id]);
                } catch (error) { setUploadError(String(error)); }
                e.target.value = "";
              }} />
          </label>
          {uploadError && <p role="alert">{uploadError}</p>}
          <div className="flex gap-2 max-w-3xl">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={2}
              placeholder="Message Milyonus…"
              className="flex-1 resize-none rounded-card bg-black/40 border border-white/15 px-4 py-3 outline-none focus:border-brand text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(e);
                }
              }}
            />
            <button
              type="submit"
              className="self-end rounded-full bg-brand px-5 py-3 text-sm font-medium"
            >
              {activeTurn ? "Responding…" : "Send"}
            </button>
            {activeTurn && sessionId && (
              <button type="button" className="self-end rounded-full bg-red-500/80 px-4 py-3 text-sm"
                onClick={() => api(`/v1/sessions/${sessionId}/cancel`, {
                  method: "POST", body: JSON.stringify({ turn_id: activeTurn }),
                })}>Stop</button>
            )}
          </div>
        </form>
      </main>

      <aside
        className={`${
          railOpen ? "flex" : "hidden"
        } md:flex flex-col border-l border-white/10 glass p-4 gap-4 overflow-y-auto`}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-white/80">Trust rail</h2>
          <button className="md:hidden text-xs" onClick={() => setRailOpen(false)}>
            Close
          </button>
        </div>
        <section>
          <h3 className="text-xs uppercase tracking-wide text-white/40">Usage</h3>
          <p className="text-sm mt-1">
            {usage.data?.turns ?? 0} turns · {usage.data?.tokens_used ?? 0} tokens
          </p>
        </section>
        <section>
          <h3 className="text-xs uppercase tracking-wide text-white/40">Memories</h3>
          <ul className="mt-2 space-y-2">
            {(memory.data?.items ?? []).slice(0, 12).map((m) => (
              <li key={m.id} className="rounded-xl bg-black/30 border border-white/10 p-2 text-xs">
                <div className="flex justify-between text-white/50">
                  <span>{m.trust_tier}</span>
                  <span>{m.state}</span>
                </div>
                <p className="mt-1 text-white/80 line-clamp-3">{m.content}</p>
                <button
                  className="mt-1 text-accent underline"
                  onClick={async () => {
                    const why = await api<Record<string, unknown>>(`/v1/memory/${m.id}/why`);
                    setWhy(why);
                  }}
                >
                  why
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3 className="text-xs uppercase tracking-wide text-white/40">Revoke by source</h3>
          <form
            className="mt-2 flex gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
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
              className="flex-1 rounded-full bg-black/40 border border-white/15 px-3 py-1.5 text-xs"
              placeholder="https://…"
              value={revokeUri}
              onChange={(e) => { setRevokeUri(e.target.value); setRevokePreview(null); }}
            />
            <button className="rounded-full bg-white/10 px-3 text-xs">{revokePreview === null ? "Preview" : "Revoke"}</button>
          </form>
        </section>
        {revokePreview !== null && (
          <p role="status" className="text-xs text-amber-200">
            {revokePreview.length} memories will be revoked, including derived records.
          </p>
        )}
        {why && (
          <section aria-label="Memory provenance" className="text-xs">
            <button onClick={() => setWhy(null)}>Close provenance</button>
            <pre className="whitespace-pre-wrap break-all mt-2">{JSON.stringify(why, null, 2)}</pre>
          </section>
        )}
        <button
          className="mt-auto text-xs text-white/50 underline"
          onClick={async () => {
            const v = await api<{ intact: boolean }>("/v1/audit/verify");
            alert(v.intact ? "Ledger intact" : "Ledger broken");
          }}
        >
          Verify audit ledger
        </button>
      </aside>
    </div>
  );
}
