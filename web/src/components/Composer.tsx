import { useQuery } from "@tanstack/react-query";
import { ClipboardEvent, DragEvent, FormEvent, useState } from "react";
import { api, SkillSummary } from "../api";
import { t } from "../i18n";
import { useUi } from "../store";

type UploadedChip = { id: string; name: string };

type Props = {
  activeTurn: string | null;
  skills: SkillSummary[];
  onSend: (text: string, attachmentIds: string[], toolsEnabled: boolean) => Promise<boolean>;
  onCancel: () => void;
  onSlashCommand: (cmd: string) => Promise<void>;
};

const MODEL_PRESETS = [
  { label: "Default", value: "" },
  { label: "claude-opus-4-8", value: "claude-opus-4-8" },
  { label: "claude-sonnet-5", value: "claude-sonnet-5" },
  { label: "gpt-4o", value: "gpt-4o" },
];

export function Composer({ activeTurn, skills, onSend, onCancel, onSlashCommand }: Props) {
  const { locale, toolsEnabled, setToolsEnabled } = useUi();
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<UploadedChip[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<Record<string, unknown>>("/v1/settings"),
  });
  const activeModel = String(settings.data?.["provider.model"] ?? "");

  const estTokens = Math.ceil(draft.length / 4);
  const skillQuery = draft.match(/@([a-z0-9_-]*)$/i)?.[1] ?? null;
  const matchingSkills =
    skillQuery !== null
      ? skills.filter((s) => s.name.toLowerCase().includes(skillQuery.toLowerCase())).slice(0, 6)
      : [];

  async function selectModel(model: string) {
    await api("/v1/settings", {
      method: "PUT",
      body: JSON.stringify({ values: { "provider.model": model } }),
    });
    void settings.refetch();
  }

  async function uploadFile(file: File) {
    if (attachments.length >= 4) return;
    setUploadError(null);
    try {
      const contentType = file.type || "text/plain";
      const result = await api<{ id: string }>("/v1/attachments", {
        method: "POST",
        headers: {
          "Content-Type": contentType,
          "X-Filename": file.name || "pasted",
        },
        body: file,
      });
      setAttachments((prev) => [...prev, { id: result.id, name: file.name || "attachment" }]);
    } catch (error) {
      setUploadError(String(error));
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed || activeTurn) return;
    if (trimmed.startsWith("/")) {
      setDraft("");
      await onSlashCommand(trimmed);
      return;
    }
    const ids = attachments.map((a) => a.id);
    setDraft("");
    const ok = await onSend(trimmed, ids, toolsEnabled);
    if (ok) {
      setAttachments([]);
    } else {
      setDraft(trimmed);
    }
  }

  function handleDrop(e: DragEvent<HTMLFormElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void uploadFile(file);
  }

  function handlePaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const item = Array.from(e.clipboardData.items).find((i) => i.kind === "file");
    const file = item?.getAsFile();
    if (file) {
      e.preventDefault();
      void uploadFile(file);
    }
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`relative border-t p-4 md:px-8 glass transition-colors ${
        dragging ? "border-brand bg-brand/10" : "border-white/10"
      }`}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-card border-2 border-dashed border-brand bg-black/80 text-sm text-accent">
          📎 {t(locale, "dropHere")}
        </div>
      )}

      <div className="max-w-3xl space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-white/65">
          <div className="flex flex-wrap items-center gap-3">
            <label className="cursor-pointer hover:text-white inline-flex items-center gap-1.5">
              <span>
                📎 {t(locale, "attachFile")} ({attachments.length}/4)
              </span>
              <input
                type="file"
                className="sr-only"
                accept="text/*,.json,.csv,.md,.pdf,image/png,image/jpeg,image/webp"
                disabled={attachments.length >= 4 || !!activeTurn}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void uploadFile(file);
                  e.target.value = "";
                }}
              />
            </label>
            <button
              type="button"
              onClick={() => setToolsEnabled(!toolsEnabled)}
              className={`rounded-full px-2.5 py-0.5 border text-[11px] transition-colors ${
                toolsEnabled
                  ? "border-accent/50 bg-accent/10 text-accent"
                  : "border-white/15 bg-black/30 text-white/45"
              }`}
            >
              {toolsEnabled ? `⚡ ${t(locale, "toolsOn")}` : `○ ${t(locale, "toolsOff")}`}
            </button>
            <select
              aria-label="Model picker"
              value={MODEL_PRESETS.some((p) => p.value === activeModel) ? activeModel : ""}
              onChange={(e) => void selectModel(e.target.value)}
              className="rounded-full bg-black/40 border border-white/15 px-2.5 py-0.5 text-[11px] text-white/75 outline-none focus:border-brand"
            >
              {MODEL_PRESETS.map((m) => (
                <option key={m.value || "default"} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <span className="text-white/40">~{estTokens} tok</span>
        </div>

        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {attachments.map((a) => (
              <span
                key={a.id}
                className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-0.5 text-xs"
              >
                {a.name}
                <button
                  type="button"
                  onClick={() => setAttachments((prev) => prev.filter((x) => x.id !== a.id))}
                  className="text-white/50 hover:text-red-300"
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}

        {uploadError && (
          <p role="alert" className="text-xs text-red-300">
            {uploadError}
          </p>
        )}

        {matchingSkills.length > 0 && (
          <div className="rounded-xl bg-black/80 border border-white/15 p-2 flex flex-wrap gap-1.5 text-xs">
            {matchingSkills.map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={() =>
                  setDraft((cur) => cur.replace(/@[a-z0-9_-]*$/i, `@${s.name} `))
                }
                className="rounded-full bg-white/10 hover:bg-brand/40 px-2.5 py-1 text-left"
              >
                @{s.name}
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPaste={handlePaste}
            rows={2}
            placeholder={t(locale, "messagePlaceholder")}
            className="flex-1 resize-none rounded-card bg-black/40 border border-white/15 px-4 py-3 outline-none focus:border-brand text-sm"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void submit(e);
              }
            }}
          />
          <button
            type="submit"
            disabled={!!activeTurn}
            className="self-end rounded-full bg-brand hover:bg-brand/90 disabled:opacity-50 px-5 py-3 text-sm font-medium"
          >
            {activeTurn ? t(locale, "responding") : t(locale, "send")}
          </button>
          {activeTurn && (
            <button
              type="button"
              className="self-end rounded-full bg-red-500/80 hover:bg-red-500 px-4 py-3 text-sm"
              onClick={onCancel}
            >
              {t(locale, "stop")}
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
