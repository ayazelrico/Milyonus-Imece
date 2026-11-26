import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, Session, SessionDetail, SkillSummary } from "./api";
import { ChatThread } from "./components/ChatThread";
import { Composer } from "./components/Composer";
import { SettingsModal } from "./components/SettingsModal";
import { Sidebar } from "./components/Sidebar";
import { TrustRail } from "./components/TrustRail";
import { WarRoomModal } from "./components/WarRoomModal";
import { Locale, t } from "./i18n";
import { useUi } from "./store";

const HypernovaModal = lazy(() => import("./components/HypernovaModal"));
const SingularityModal = lazy(() => import("./components/SingularityModal"));

const ease = [0.22, 1, 0.36, 1] as const;

export default function App() {
  const { locale, setLocale } = useUi();
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
    api<{ settings?: { locale?: string } }>("/v1/export")
      .then((exp) => {
        const saved = exp.settings?.locale;
        if (saved === "tr" || saved === "en" || saved === "de" || saved === "es") {
          setLocale(saved);
        }
        setAuthed(true);
      })
      .catch(() => setAuthed(false));
  }, [setLocale]);

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
                setBootError(t(locale, "magicSent"));
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
          <div className="flex items-center justify-between">
            <p className="font-serif italic text-3xl text-white">✦ Milyonus</p>
            <select
              aria-label="Language"
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
              className="rounded-full bg-black/40 border border-white/15 px-2.5 py-1 text-xs"
            >
              <option value="en">EN</option>
              <option value="tr">TR</option>
              <option value="de">DE</option>
              <option value="es">ES</option>
            </select>
          </div>
          <p className="mt-2 text-sm text-white/60">{t(locale, "tagline")}</p>
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
            {t(locale, "continue")}
          </button>
        </motion.form>
      </div>
    );
  }

  return <Shell onSignedOut={() => setAuthed(false)} />;
}

function Shell({ onSignedOut }: { onSignedOut: () => void }) {
  const qc = useQueryClient();
  const {
    sessionId,
    setSession,
    setMessages,
    pushMessage,
    appendStream,
    clearStream,
    addTool,
    updateToolResult,
    clearTools,
    setApproval,
    railOpen,
    setRailOpen,
    setSidebarOpen,
    setFeedback,
    setFeedbackMap,
    setBudgetPressure,
    setPrefixCacheHit,
    toolsEnabled,
    locale,
  } = useUi();

  const [activeTurn, setActiveTurn] = useState<string | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [contextNotice, setContextNotice] = useState("");
  const [compacted, setCompacted] = useState(false);
  const [turnError, setTurnError] = useState("");
  const [offline, setOffline] = useState(!navigator.onLine);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const onOff = () => setOffline(true);
    const onOn = () => setOffline(false);
    window.addEventListener("offline", onOff);
    window.addEventListener("online", onOn);
    return () => {
      window.removeEventListener("offline", onOff);
      window.removeEventListener("online", onOn);
      esRef.current?.close();
    };
  }, []);

  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: () => api<Session[]>("/v1/sessions"),
  });

  const skills = useQuery({
    queryKey: ["skills"],
    queryFn: () => api<SkillSummary[]>("/v1/skills"),
  });

  const createSession = useMutation({
    mutationFn: (payload?: {
      title?: string;
      parent_id?: string;
      fork_before_message_id?: string;
    }) =>
      api<{ id: string }>("/v1/sessions", {
        method: "POST",
        body: JSON.stringify(payload ?? {}),
      }),
    onSuccess: (data) => {
      setSession(data.id);
      setMessages([]);
      setCompacted(false);
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const attachStream = useCallback(
    (sid: string, turnId: string) => {
      esRef.current?.close();
      setActiveTurn(turnId);
      const es = new EventSource(
        `/v1/sessions/${sid}/stream?turn_id=${encodeURIComponent(turnId)}`,
        { withCredentials: true },
      );
      esRef.current = es;

      es.addEventListener("error", (ev) => {
        if (ev instanceof MessageEvent && ev.data) {
          const data = JSON.parse(ev.data);
          setTurnError(data.message ?? data.code ?? "The turn failed.");
        }
      });
      es.addEventListener("context.sources", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data) as {
          sources: { source: string; included: boolean; reason: string }[];
        };
        setContextNotice(
          data.sources
            .map(
              (s) => `${s.source}: ${s.included ? "scanned reference" : `skipped (${s.reason})`}`,
            )
            .join(" · "),
        );
      });
      es.addEventListener("context.compacted", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data) as { message?: string };
        setCompacted(true);
        setContextNotice((prev) =>
          [prev, data.message ?? "Older conversation shortened; full history saved."]
            .filter(Boolean)
            .join(" · "),
        );
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
      es.addEventListener("tool.result", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        updateToolResult(data.call_id, {
          ok: Boolean(data.ok),
          duration_ms: Number(data.duration_ms ?? 0),
          preview: String(data.preview ?? ""),
          truncated: Boolean(data.truncated),
          full_ref: data.full_ref,
        });
      });
      es.addEventListener("usage", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        if (typeof data.pressure === "number") {
          setBudgetPressure(data.pressure);
        }
        if (typeof data.prefix_cache_hit === "boolean") {
          setPrefixCacheHit(data.prefix_cache_hit);
        }
      });
      es.addEventListener("memory.proposed", () => {
        qc.invalidateQueries({ queryKey: ["memory"] });
      });
      es.addEventListener("approval.required", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        setApproval({
          approval_id: data.approval_id,
          name: data.name,
          args: data.args,
          risk: data.risk,
          reason: data.reason,
          irreversible: Boolean(data.irreversible),
          findings: data.findings ?? [],
        });
      });
      es.addEventListener("approval.resolved", () => {
        setApproval(null);
      });
      es.addEventListener("turn.completed", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data) as { message_id?: string | null };
        es.close();
        esRef.current = null;
        setActiveTurn(null);
        setApproval(null);
        const finalText = useUi.getState().streaming;
        if (finalText) {
          pushMessage({
            id: data.message_id ? String(data.message_id) : "tmp_" + crypto.randomUUID(),
            role: "assistant",
            content: finalText,
          });
          clearStream();
        }
        qc.invalidateQueries({ queryKey: ["usage"] });
        qc.invalidateQueries({ queryKey: ["memory"] });
      });
      es.onerror = () => {
        if (es.readyState === EventSource.CLOSED) {
          setApproval(null);
        }
      };
    },
    [
      addTool,
      appendStream,
      clearStream,
      pushMessage,
      qc,
      setApproval,
      setBudgetPressure,
      setPrefixCacheHit,
      updateToolResult,
    ],
  );

  // Load session history + seamlessly reattach to any in-flight turn or pending approval on reload.
  useEffect(() => {
    if (!sessionId) return;
    esRef.current?.close();
    setActiveTurn(null);
    setCompacted(false);
    setThreadLoading(true);
    api<SessionDetail>(`/v1/sessions/${sessionId}`)
      .then((s) => {
        setMessages(
          s.messages
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({
              id: String(m.id),
              role: m.role as "user" | "assistant",
              content: m.content,
            })),
        );
        setFeedbackMap(s.feedback ?? {});
        if (s.pending_approvals?.length) {
          const first = s.pending_approvals[0];
          setApproval({
            approval_id: first.approval_id,
            name: first.name,
            args: first.args,
            risk: first.risk,
            reason: first.reason,
            irreversible: first.irreversible,
            findings: [],
          });
        }
        if (s.active_turn_id) {
          attachStream(sessionId, s.active_turn_id);
        }
      })
      .finally(() => setThreadLoading(false));
  }, [sessionId, setMessages, setApproval, setFeedbackMap, attachStream]);

  async function handleSend(
    text: string,
    attachmentIds: string[],
    useTools: boolean,
  ): Promise<boolean> {
    let sid = sessionId;
    if (!sid) {
      const created = await createSession.mutateAsync(undefined);
      sid = created.id;
    }
    pushMessage({ id: "tmp_" + crypto.randomUUID(), role: "user", content: text });
    clearStream();
    clearTools();
    setContextNotice("");
    setCompacted(false);
    setTurnError("");
    try {
      const { turn_id } = await api<{ turn_id: string }>(`/v1/sessions/${sid}/messages`, {
        method: "POST",
        body: JSON.stringify({
          text,
          attachments: attachmentIds,
          tools_enabled: useTools,
        }),
      });
      attachStream(sid, turn_id);
      return true;
    } catch (error) {
      setTurnError(String(error));
      return false;
    }
  }

  async function handleRegenerate() {
    if (!sessionId || activeTurn) return;
    clearStream();
    clearTools();
    setTurnError("");
    const currentMsgs = useUi.getState().messages;
    if (currentMsgs.length && currentMsgs[currentMsgs.length - 1].role === "assistant") {
      setMessages(currentMsgs.slice(0, -1));
    }
    try {
      const { turn_id } = await api<{ turn_id: string }>(`/v1/sessions/${sessionId}/regenerate`, {
        method: "POST",
      });
      attachStream(sessionId, turn_id);
    } catch (error) {
      setTurnError(String(error));
    }
  }

  async function handleEditResend(messageId: string, nextText: string) {
    if (!sessionId || activeTurn) return;
    const forkId = messageId.startsWith("tmp_") ? undefined : messageId;
    try {
      const forked = await createSession.mutateAsync({
        parent_id: sessionId,
        fork_before_message_id: forkId,
      });
      const detail = await api<SessionDetail>(`/v1/sessions/${forked.id}`);
      setMessages([
        ...detail.messages
          .filter((m) => m.role === "user" || m.role === "assistant")
          .map((m) => ({
            id: String(m.id),
            role: m.role as "user" | "assistant",
            content: m.content,
          })),
        { id: "tmp_" + crypto.randomUUID(), role: "user", content: nextText },
      ]);
      const { turn_id } = await api<{ turn_id: string }>(`/v1/sessions/${forked.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ text: nextText, attachments: [], tools_enabled: toolsEnabled }),
      });
      attachStream(forked.id, turn_id);
    } catch (error) {
      setTurnError(String(error));
    }
  }

  async function handleStartLinkedSession() {
    if (!sessionId) return;
    await createSession.mutateAsync({ parent_id: sessionId });
  }

  async function handleFeedback(messageId: string, rating: "up" | "down") {
    if (!sessionId || messageId.startsWith("tmp_")) return;
    setFeedback(messageId, rating);
    try {
      await api(`/v1/messages/${encodeURIComponent(messageId)}/feedback`, {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, rating }),
      });
    } catch {
      // Non-critical UI feedback failure.
    }
  }

  async function handleSlashCommand(raw: string) {
    const [cmd, ...rest] = raw.slice(1).trim().split(/\s+/);
    const arg = rest.join(" ").trim();
    if (cmd === "clear") {
      createSession.mutate(undefined);
      return;
    }
    if (cmd === "usage") {
      const u = await api<{ turns: number; tokens_used: number; cost_usd: number }>("/v1/usage");
      setContextNotice(
        `Usage: ${u.turns} turns · ${u.tokens_used} tokens · $${u.cost_usd.toFixed(4)}`,
      );
      return;
    }
    if (cmd === "model") {
      if (!arg) {
        const s = await api<Record<string, unknown>>("/v1/settings");
        setContextNotice(`Model: ${String(s["provider.model"] || "(server default)")}`);
      } else {
        await api("/v1/settings", {
          method: "PUT",
          body: JSON.stringify({ values: { "provider.model": arg } }),
        });
        qc.invalidateQueries({ queryKey: ["settings"] });
        setContextNotice(`Switched model override to ${arg}`);
      }
      return;
    }
    setContextNotice("Slash commands: /model [name] · /usage · /clear · /help");
  }

  return (
    <div className="h-screen grid grid-cols-1 md:grid-cols-[240px_1fr_300px]">
      <Sidebar
        sessions={sessions.data ?? []}
        loading={sessions.isLoading}
        onCreate={() => createSession.mutate(undefined)}
      />

      <main className="flex flex-col min-h-0">
        <header className="md:hidden flex items-center justify-between border-b border-white/10 glass px-4 py-2.5">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="text-sm text-white/80"
          >
            ☰
          </button>
          <span className="font-serif italic text-xl text-white">✦ Milyonus</span>
          <button
            type="button"
            onClick={() => setRailOpen(!railOpen)}
            className="text-xs rounded-full bg-white/10 px-3 py-1 text-white/80"
          >
            {t(locale, "trustRail")}
          </button>
        </header>

        <ChatThread
          activeTurn={activeTurn}
          loading={threadLoading}
          turnError={turnError}
          contextNotice={contextNotice}
          compacted={compacted}
          offline={offline}
          onRegenerate={() => void handleRegenerate()}
          onEditResend={(id, next) => void handleEditResend(id, next)}
          onStartLinkedSession={() => void handleStartLinkedSession()}
          onFeedback={(id, rating) => void handleFeedback(id, rating)}
        />

        <Composer
          activeTurn={activeTurn}
          skills={skills.data ?? []}
          onSend={handleSend}
          onCancel={() => {
            if (activeTurn && sessionId) {
              void api(`/v1/sessions/${sessionId}/cancel`, {
                method: "POST",
                body: JSON.stringify({ turn_id: activeTurn }),
              });
            }
          }}
          onSlashCommand={handleSlashCommand}
        />
      </main>

      <TrustRail />
      <SettingsModal onSignedOut={onSignedOut} />
      <WarRoomModal />
      <Suspense fallback={null}>
        <HypernovaModal />
        <SingularityModal />
      </Suspense>
    </div>
  );
}
