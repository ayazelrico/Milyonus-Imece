import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, Session } from "../api";
import { t } from "../i18n";
import { useUi } from "../store";

type Props = {
  sessions: Session[];
  loading?: boolean;
  onCreate: () => void;
};

type GroupKey = "pinned" | "today" | "yesterday" | "prev7Days" | "older";

function bucketSessions(sessions: Session[]): { key: GroupKey; items: Session[] }[] {
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const startYesterday = startToday - 86400;
  const start7Days = startToday - 7 * 86400;

  const buckets: Record<GroupKey, Session[]> = {
    pinned: [],
    today: [],
    yesterday: [],
    prev7Days: [],
    older: [],
  };

  for (const s of sessions) {
    if (s.pinned) {
      buckets.pinned.push(s);
    } else if (s.updated_at >= startToday) {
      buckets.today.push(s);
    } else if (s.updated_at >= startYesterday) {
      buckets.yesterday.push(s);
    } else if (s.updated_at >= start7Days) {
      buckets.prev7Days.push(s);
    } else {
      buckets.older.push(s);
    }
  }

  return (["pinned", "today", "yesterday", "prev7Days", "older"] as GroupKey[])
    .filter((k) => buckets[k].length > 0)
    .map((key) => ({ key, items: buckets[key] }));
}

export function Sidebar({ sessions, loading = false, onCreate }: Props) {
  const qc = useQueryClient();
  const { sessionId, setSession, sidebarOpen, setSidebarOpen, setSettingsOpen, locale } = useUi();
  const [search, setSearch] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Global keyboard shortcuts (PLAN-WEB §2.2 / §10): Cmd/Ctrl+K search, Cmd/Ctrl+Shift+N new chat, Esc close.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSidebarOpen(true);
        searchRef.current?.focus();
      } else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "n") {
        e.preventDefault();
        onCreate();
      } else if (e.key === "Escape") {
        setSearch("");
        setEditingId(null);
        setSidebarOpen(false);
        setSettingsOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCreate, setSettingsOpen, setSidebarOpen]);

  const groups = useMemo(() => bucketSessions(sessions), [sessions]);

  const results = useQuery({
    queryKey: ["search", search],
    queryFn: () =>
      api<{ session_id: string; message_id: string; snippet: string }[]>(
        "/v1/search?q=" + encodeURIComponent(search),
      ),
    enabled: search.trim().length > 1,
  });

  async function saveTitle(id: string) {
    const trimmed = editTitle.trim();
    setEditingId(null);
    if (!trimmed) return;
    await api(`/v1/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title: trimmed }),
    });
    qc.invalidateQueries({ queryKey: ["sessions"] });
  }

  async function togglePin(s: Session) {
    await api(`/v1/sessions/${s.id}`, {
      method: "PATCH",
      body: JSON.stringify({ pinned: !s.pinned }),
    });
    qc.invalidateQueries({ queryKey: ["sessions"] });
  }

  async function archiveSession(id: string) {
    await api(`/v1/sessions/${id}`, { method: "DELETE" });
    if (sessionId === id) setSession(null);
    qc.invalidateQueries({ queryKey: ["sessions"] });
  }

  return (
    <>
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/70 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`${
          sidebarOpen ? "fixed inset-y-0 left-0 z-40 flex w-72" : "hidden"
        } md:static md:flex flex-col border-r border-white/10 glass p-4 gap-3`}
      >
        <div className="flex items-center justify-between">
          <div className="font-serif italic text-2xl text-white">✦ Milyonus</div>
          <button
            type="button"
            className="md:hidden text-xs text-white/60"
            onClick={() => setSidebarOpen(false)}
          >
            ✕
          </button>
        </div>
        <button
          type="button"
          title="Ctrl/Cmd+Shift+N"
          className="rounded-full bg-brand/90 hover:bg-brand py-2 text-sm font-medium transition-colors duration-300 ease-soft"
          onClick={() => {
            onCreate();
            setSidebarOpen(false);
          }}
        >
          {t(locale, "newChat")}
        </button>
        <input
          ref={searchRef}
          aria-label={t(locale, "searchPlaceholder")}
          placeholder={`${t(locale, "searchPlaceholder")} (⌘K)`}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-xl bg-black/40 border border-white/10 px-3 py-2 text-sm outline-none focus:border-brand"
        />
        {search.trim().length > 1 && (
          <div aria-label="Search results" className="text-xs space-y-2 max-h-40 overflow-y-auto">
            {(results.data ?? []).map((hit) => (
              <button
                type="button"
                key={hit.message_id}
                onClick={() => {
                  setSession(hit.session_id);
                  setSearch("");
                  setSidebarOpen(false);
                }}
                className="block w-full text-left rounded-xl p-2 bg-black/30 hover:bg-white/10"
              >
                {hit.snippet}
              </button>
            ))}
            {results.isError && <p role="alert">{t(locale, "searchFailed")}</p>}
            {results.data?.length === 0 && <p className="text-white/50">{t(locale, "noMatches")}</p>}
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-3 mt-1">
          {loading && sessions.length === 0 && (
            <div className="space-y-2 animate-pulse" aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="h-8 rounded-xl bg-white/10" />
              ))}
            </div>
          )}

          {groups.map((group) => (
            <div key={group.key} className="space-y-1">
              <p className="px-2 text-[10px] uppercase tracking-wider text-white/40">
                {t(locale, group.key)}
              </p>
              {group.items.map((s) => (
                <div
                  key={s.id}
                  className={`group flex items-center gap-1 rounded-xl px-2 py-1.5 text-sm transition-colors ${
                    sessionId === s.id ? "bg-white/15" : "hover:bg-white/10"
                  }`}
                >
                  {editingId === s.id ? (
                    <input
                      autoFocus
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onBlur={() => void saveTitle(s.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void saveTitle(s.id);
                        if (e.key === "Escape") setEditingId(null);
                      }}
                      className="flex-1 bg-black/50 rounded px-2 py-0.5 text-xs outline-none"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setSession(s.id);
                        setSidebarOpen(false);
                      }}
                      className="flex-1 text-left truncate py-0.5"
                    >
                      {s.pinned ? "📌 " : ""}
                      {s.parent_id ? "↳ " : ""}
                      {s.title || t(locale, "untitled")}
                    </button>
                  )}
                  <button
                    type="button"
                    title="Pin"
                    aria-label="Pin session"
                    onClick={() => void togglePin(s)}
                    className="opacity-60 hover:opacity-100 text-xs px-1"
                  >
                    {s.pinned ? "★" : "☆"}
                  </button>
                  <button
                    type="button"
                    title="Rename"
                    aria-label="Rename session"
                    onClick={() => {
                      setEditingId(s.id);
                      setEditTitle(s.title ?? "");
                    }}
                    className="opacity-60 hover:opacity-100 text-xs px-1"
                  >
                    ✎
                  </button>
                  <button
                    type="button"
                    title="Archive"
                    aria-label="Archive session"
                    onClick={() => void archiveSession(s.id)}
                    className="opacity-60 hover:opacity-100 hover:text-red-400 text-xs px-1"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          ))}
        </div>

        <div className="mt-auto space-y-2">
          <button
            type="button"
            onClick={() => {
              useUi.getState().setSingularityOpen(true);
              setSidebarOpen(false);
            }}
            className="w-full rounded-full border border-emerald-400/40 bg-emerald-500/15 hover:bg-emerald-500/25 py-2 text-xs text-emerald-200 font-medium"
          >
            ❖ Singularity Studio
          </button>
          <button
            type="button"
            onClick={() => {
              useUi.getState().setHypernovaOpen(true);
              setSidebarOpen(false);
            }}
            className="w-full rounded-full border border-brand/60 bg-brand/20 hover:bg-brand/35 py-2 text-xs text-white font-medium"
          >
            ✦ Hypernova Lab (10X)
          </button>
          <button
            type="button"
            onClick={() => {
              useUi.getState().setWarRoomOpen(true);
              setSidebarOpen(false);
            }}
            className="w-full rounded-full border border-accent/40 bg-accent/10 hover:bg-accent/20 py-2 text-xs text-accent font-medium"
          >
            ⚡ War Room & Arena
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="w-full rounded-full border border-white/15 bg-black/30 hover:bg-white/10 py-2 text-xs text-white/80"
          >
            ⚙ {t(locale, "settings")}
          </button>
        </div>
      </aside>
    </>
  );
}
