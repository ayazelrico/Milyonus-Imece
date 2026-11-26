import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import { t } from "../i18n";
import { ToolEvent, useUi } from "../store";

const ease = [0.22, 1, 0.36, 1] as const;
const WINDOW_SIZE = 60;

type Props = {
  activeTurn: string | null;
  loading?: boolean;
  turnError: string;
  contextNotice: string;
  compacted: boolean;
  offline: boolean;
  onRegenerate: () => void;
  onEditResend: (messageId: string, nextText: string) => void;
  onStartLinkedSession: () => void;
  onFeedback: (messageId: string, rating: "up" | "down") => void;
};

function ToolCard({ tool }: { tool: ToolEvent }) {
  const [open, setOpen] = useState(false);
  const [fullText, setFullText] = useState<string | null>(null);

  async function loadFull() {
    if (!tool.full_ref) return;
    const res = await api<{ content: string }>(tool.full_ref);
    setFullText(res.content);
  }

  const badge =
    tool.ok === undefined
      ? "running…"
      : tool.ok
        ? `ok · ${tool.duration_ms ?? 0}ms`
        : `error · ${tool.duration_ms ?? 0}ms`;

  return (
    <div className="max-w-3xl rounded-xl border border-white/10 bg-black/40 px-3 py-2 text-xs text-white/75">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between text-left gap-2"
      >
        <span>
          {open ? "▾" : "▸"} tool: <span className="text-accent font-medium">{tool.name}</span>{" "}
          <span className="text-white/40">{tool.risk}</span>
        </span>
        <span
          className={
            tool.ok === false
              ? "text-red-300"
              : tool.ok === true
                ? "text-emerald-300"
                : "text-white/50"
          }
        >
          {badge}
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {tool.args_preview && (
            <pre className="overflow-x-auto rounded bg-black/50 p-2 text-white/60">
              {tool.args_preview}
            </pre>
          )}
          {(fullText ?? tool.preview) && (
            <pre className="overflow-x-auto max-h-60 rounded bg-black/60 p-2 text-white/80 whitespace-pre-wrap">
              {fullText ?? tool.preview}
            </pre>
          )}
          {tool.truncated && !fullText && tool.full_ref && (
            <button
              type="button"
              onClick={() => void loadFull()}
              className="text-accent underline text-xs"
            >
              Load full output
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function ChatThread({
  activeTurn,
  loading = false,
  turnError,
  contextNotice,
  compacted,
  offline,
  onRegenerate,
  onEditResend,
  onStartLinkedSession,
  onFeedback,
}: Props) {
  const { messages, streaming, tools, approval, setApproval, feedback, locale } = useUi();
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [editingMsgId, setEditingMsgId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState("");
  const [showAll, setShowAll] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming, tools, approval]);

  async function copyText(id: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500);
    } catch {
      // Clipboard unavailable in insecure context.
    }
  }

  const hiddenCount = !showAll && messages.length > WINDOW_SIZE ? messages.length - WINDOW_SIZE : 0;
  const visibleMessages = hiddenCount > 0 ? messages.slice(-WINDOW_SIZE) : messages;

  return (
    <>
      {offline && (
        <div
          role="status"
          className="bg-amber-500/20 border-b border-amber-400/30 px-4 py-2 text-xs text-amber-200"
        >
          {t(locale, "offlineBanner")}
        </div>
      )}
      {turnError && (
        <p
          role="alert"
          className="px-4 py-2 text-sm text-red-300 bg-red-500/10 border-b border-red-500/20"
        >
          {turnError}
        </p>
      )}
      {contextNotice && (
        <div
          role="status"
          className="px-4 py-1.5 text-xs text-white/65 border-b border-white/5 flex flex-wrap items-center justify-between gap-2"
        >
          <span>{contextNotice}</span>
          {compacted && (
            <button
              type="button"
              onClick={onStartLinkedSession}
              className="rounded-full bg-brand/30 hover:bg-brand/50 border border-brand/50 px-2.5 py-0.5 text-[11px] text-white"
            >
              ↳ {t(locale, "startLinked")}
            </button>
          )}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 space-y-4">
        {loading && messages.length === 0 && (
          <div className="max-w-3xl space-y-3 animate-pulse" aria-busy="true">
            <div className="h-14 rounded-card bg-white/10 w-2/3 ml-auto" />
            <div className="h-24 rounded-card bg-white/10 w-5/6" />
          </div>
        )}

        {!loading && messages.length === 0 && !streaming && (
          <div className="max-w-2xl mx-auto mt-16 text-center space-y-2">
            <p className="font-serif italic text-4xl text-white">✦ Milyonus</p>
            <p className="text-sm text-white/55">{t(locale, "tagline")}</p>
          </div>
        )}

        {hiddenCount > 0 && (
          <div className="text-center">
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="rounded-full bg-white/10 hover:bg-white/20 px-4 py-1.5 text-xs text-white/75"
            >
              {t(locale, "loadEarlier")} ({hiddenCount})
            </button>
          </div>
        )}

        <AnimatePresence initial={false}>
          {visibleMessages.map((m, idx) => {
            const isLastAssistant =
              m.role === "assistant" && idx === visibleMessages.length - 1 && !activeTurn;
            const currentRating = feedback[m.id];
            const isEditing = editingMsgId === m.id;
            return (
              <motion.div
                key={m.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease }}
                className={`max-w-3xl ${m.role === "user" ? "ml-auto" : ""}`}
              >
                <div
                  className={`rounded-card px-4 py-3 border border-white/10 ${
                    m.role === "user" ? "bg-brand/20" : "glass"
                  }`}
                >
                  {m.role === "assistant" ? (
                    <ReactMarkdown
                      className="prose prose-invert prose-sm max-w-none"
                      components={{
                        a({ href, children }) {
                          return (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-accent underline decoration-accent/50 hover:decoration-accent"
                            >
                              {children}
                            </a>
                          );
                        },
                        pre({ children }) {
                          const raw =
                            typeof children === "object" &&
                            children !== null &&
                            "props" in (children as { props?: { children?: unknown } })
                              ? String(
                                  (children as { props?: { children?: unknown } }).props
                                    ?.children ?? "",
                                )
                              : "";
                          return (
                            <div className="relative group my-2">
                              <button
                                type="button"
                                onClick={() => void copyText(m.id + raw.slice(0, 12), raw)}
                                className="absolute right-2 top-2 rounded-full bg-white/10 hover:bg-white/20 px-2 py-0.5 text-[10px] text-white/80"
                              >
                                {copiedId === m.id + raw.slice(0, 12)
                                  ? t(locale, "copied")
                                  : t(locale, "copy")}
                              </button>
                              <pre className="rounded-xl bg-black/70 border border-white/10 p-3 overflow-x-auto">
                                {children}
                              </pre>
                            </div>
                          );
                        },
                      }}
                    >
                      {m.content}
                    </ReactMarkdown>
                  ) : isEditing ? (
                    <div className="space-y-2">
                      <textarea
                        value={editingText}
                        onChange={(e) => setEditingText(e.target.value)}
                        rows={3}
                        className="w-full rounded-xl bg-black/50 border border-white/20 p-2 text-sm outline-none focus:border-brand"
                      />
                      <div className="flex gap-2 justify-end text-xs">
                        <button
                          type="button"
                          onClick={() => setEditingMsgId(null)}
                          className="rounded-full bg-white/10 px-3 py-1"
                        >
                          {t(locale, "cancel")}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const next = editingText.trim();
                            setEditingMsgId(null);
                            if (next) onEditResend(m.id, next);
                          }}
                          className="rounded-full bg-brand px-3 py-1 font-medium"
                        >
                          {t(locale, "saveResend")}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="whitespace-pre-wrap text-sm">{m.content}</p>
                  )}
                </div>

                {m.role === "user" && !activeTurn && !isEditing && (
                  <div className="mt-1 flex justify-end gap-3 px-2 text-[11px] text-white/40">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingMsgId(m.id);
                        setEditingText(m.content);
                      }}
                      className="hover:text-white/80"
                    >
                      ✎ {t(locale, "edit")}
                    </button>
                  </div>
                )}

                {m.role === "assistant" && (
                  <div className="mt-1 flex items-center gap-3 px-2 text-[11px] text-white/45">
                    <button
                      type="button"
                      onClick={() => void copyText(m.id, m.content)}
                      className="hover:text-white/80"
                    >
                      {copiedId === m.id ? t(locale, "copied") : t(locale, "copy")}
                    </button>
                    {isLastAssistant && (
                      <button
                        type="button"
                        onClick={onRegenerate}
                        className="hover:text-white/80"
                      >
                        ↻ {t(locale, "regenerate")}
                      </button>
                    )}
                    {!m.id.startsWith("tmp_") && (
                      <>
                        <button
                          type="button"
                          aria-label="Helpful"
                          onClick={() => onFeedback(m.id, "up")}
                          className={
                            currentRating === "up"
                              ? "text-emerald-300"
                              : "hover:text-white/80"
                          }
                        >
                          👍
                        </button>
                        <button
                          type="button"
                          aria-label="Not helpful"
                          onClick={() => onFeedback(m.id, "down")}
                          className={
                            currentRating === "down" ? "text-red-300" : "hover:text-white/80"
                          }
                        >
                          👎
                        </button>
                      </>
                    )}
                  </div>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>

        {tools.map((tool) => (
          <ToolCard key={tool.call_id} tool={tool} />
        ))}

        {approval && (
          <div
            role="dialog"
            aria-label={t(locale, "approvalRequired")}
            className="fixed inset-x-3 bottom-3 z-50 md:static max-w-3xl rounded-card border border-amber-400/50 bg-black/95 md:bg-amber-500/10 p-4 shadow-2xl"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium text-amber-200">
                ⚠ {t(locale, "approvalRequired")} — {approval.name}
              </p>
              {approval.irreversible && (
                <span className="rounded-full bg-red-500/25 border border-red-400/40 px-2.5 py-0.5 text-[11px] text-red-200">
                  {t(locale, "irreversible")}
                </span>
              )}
            </div>
            <p className="text-sm text-white/75 mt-1">{approval.reason}</p>
            {approval.findings.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {approval.findings.map((f) => (
                  <span
                    key={f}
                    className="rounded bg-red-500/20 px-2 py-0.5 text-[11px] text-red-200"
                  >
                    {f}
                  </span>
                ))}
              </div>
            )}
            <pre className="mt-2 text-xs overflow-x-auto max-h-40 rounded bg-black/50 p-2 text-white/60">
              {JSON.stringify(approval.args, null, 2)}
            </pre>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-full bg-brand px-4 py-2 text-sm font-medium"
                onClick={async () => {
                  await api(`/v1/approvals/${approval.approval_id}`, {
                    method: "POST",
                    body: JSON.stringify({ decision: "allow" }),
                  });
                  setApproval(null);
                }}
              >
                {t(locale, "allow")}
              </button>
              {!approval.irreversible && (
                <button
                  type="button"
                  className="rounded-full bg-white/10 hover:bg-white/20 px-4 py-2 text-sm"
                  onClick={async () => {
                    await api(`/v1/approvals/${approval.approval_id}`, {
                      method: "POST",
                      body: JSON.stringify({ decision: "allow_session" }),
                    });
                    setApproval(null);
                  }}
                >
                  {t(locale, "allowSession")}
                </button>
              )}
              <button
                type="button"
                className="rounded-full bg-red-500/80 hover:bg-red-500 px-4 py-2 text-sm"
                onClick={async () => {
                  await api(`/v1/approvals/${approval.approval_id}`, {
                    method: "POST",
                    body: JSON.stringify({ decision: "deny" }),
                  });
                  setApproval(null);
                }}
              >
                {t(locale, "deny")}
              </button>
            </div>
          </div>
        )}

        {streaming && (
          <div
            aria-live="polite"
            className="max-w-3xl glass rounded-card px-4 py-3 border border-white/10"
          >
            <ReactMarkdown className="prose prose-invert prose-sm max-w-none">
              {streaming}
            </ReactMarkdown>
          </div>
        )}
        <div ref={bottom} />
      </div>
    </>
  );
}
