import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiKeyRow } from "../api";
import { Locale, t } from "../i18n";
import { useUi } from "../store";

type Props = {
  onSignedOut: () => void;
};

export function SettingsModal({ onSignedOut }: Props) {
  const qc = useQueryClient();
  const { settingsOpen, setSettingsOpen, locale, setLocale, quietMemory, setQuietMemory, setRailOpen } =
    useUi();
  const [model, setModel] = useState("");
  const [keyName, setKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [confirmErase, setConfirmErase] = useState(false);
  const [status, setStatus] = useState("");

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<Record<string, unknown>>("/v1/settings"),
    enabled: settingsOpen,
  });

  const apiKeys = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api<ApiKeyRow[]>("/v1/api-keys"),
    enabled: settingsOpen,
  });

  useEffect(() => {
    if (settings.data) {
      if (typeof settings.data["provider.model"] === "string") {
        setModel(settings.data["provider.model"]);
      }
      if (typeof settings.data["ui.quiet_memory"] === "boolean") {
        setQuietMemory(settings.data["ui.quiet_memory"]);
      }
    }
  }, [settings.data, setQuietMemory]);

  if (!settingsOpen) return null;

  async function savePrefs(nextLocale: Locale, nextModel: string, nextQuiet: boolean) {
    setLocale(nextLocale);
    setQuietMemory(nextQuiet);
    if (nextQuiet) setRailOpen(false);
    await api("/v1/settings", {
      method: "PUT",
      body: JSON.stringify({
        values: {
          locale: nextLocale,
          "ui.language": nextLocale,
          "provider.model": nextModel.trim(),
          "ui.quiet_memory": nextQuiet,
        },
      }),
    });
    setStatus("Saved ✓");
    qc.invalidateQueries({ queryKey: ["settings"] });
  }

  async function exportJson() {
    const data = await api<Record<string, unknown>>("/v1/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "milyonus-export.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4">
      <div
        role="dialog"
        aria-label={t(locale, "settings")}
        className="glass rounded-card border border-white/15 w-full max-w-lg max-h-[85vh] overflow-y-auto p-6 space-y-5 text-sm"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium text-white">{t(locale, "settings")}</h2>
          <button type="button" onClick={() => setSettingsOpen(false)} className="text-white/60">
            ✕
          </button>
        </div>

        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <label htmlFor="mil-locale" className="text-white/75">
              Language
            </label>
            <select
              id="mil-locale"
              value={locale}
              onChange={(e) => void savePrefs(e.target.value as Locale, model, quietMemory)}
              className="rounded-xl bg-black/50 border border-white/15 px-3 py-1.5 text-xs"
            >
              <option value="en">English</option>
              <option value="tr">Türkçe</option>
              <option value="de">Deutsch</option>
              <option value="es">Español</option>
            </select>
          </div>

          <div className="space-y-1">
            <label htmlFor="mil-model" className="text-white/75 text-xs">
              Model override (allowlisted)
            </label>
            <div className="flex gap-2">
              <input
                id="mil-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="default from server config"
                className="flex-1 rounded-xl bg-black/40 border border-white/15 px-3 py-1.5 text-xs"
              />
              <button
                type="button"
                onClick={() => void savePrefs(locale, model, quietMemory)}
                className="rounded-full bg-brand px-4 py-1.5 text-xs"
              >
                Save
              </button>
            </div>
          </div>

          <label className="flex items-center gap-2 text-xs text-white/75">
            <input
              type="checkbox"
              checked={quietMemory}
              onChange={(e) => void savePrefs(locale, model, e.target.checked)}
            />
            {t(locale, "quietMemory")}
          </label>
          {status && <p className="text-xs text-accent">{status}</p>}
        </section>

        <section className="space-y-2 border-t border-white/10 pt-4">
          <h3 className="text-xs uppercase tracking-wide text-white/50">{t(locale, "apiKeys")}</h3>
          <div className="flex gap-2">
            <input
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="CLI / automation key name"
              className="flex-1 rounded-xl bg-black/40 border border-white/15 px-3 py-1.5 text-xs"
            />
            <button
              type="button"
              onClick={async () => {
                if (!keyName.trim()) return;
                const created = await api<{ key: string }>("/v1/api-keys", {
                  method: "POST",
                  body: JSON.stringify({ name: keyName.trim() }),
                });
                setCreatedKey(created.key);
                setKeyName("");
                qc.invalidateQueries({ queryKey: ["api-keys"] });
              }}
              className="rounded-full bg-white/15 hover:bg-white/25 px-3 py-1.5 text-xs"
            >
              {t(locale, "createKey")}
            </button>
          </div>
          {createdKey && (
            <div className="rounded-xl bg-emerald-500/15 border border-emerald-400/30 p-2 text-xs break-all">
              Copy once: <code>{createdKey}</code>
            </div>
          )}
          <ul className="space-y-1 text-xs">
            {(apiKeys.data ?? []).map((k) => (
              <li
                key={k.id}
                className="flex items-center justify-between rounded-lg bg-black/35 px-2.5 py-1.5"
              >
                <span>
                  {k.name} <code className="text-white/45">{k.prefix}…</code>
                </span>
                {k.revoked_at ? (
                  <span className="text-white/40">revoked</span>
                ) : (
                  <button
                    type="button"
                    onClick={async () => {
                      await api(`/v1/api-keys/${k.id}`, { method: "DELETE" });
                      qc.invalidateQueries({ queryKey: ["api-keys"] });
                    }}
                    className="text-red-300 hover:underline"
                  >
                    {t(locale, "revoke")}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section className="space-y-2 border-t border-white/10 pt-4">
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void exportJson()}
              className="rounded-full bg-white/10 hover:bg-white/20 px-4 py-2 text-xs"
            >
              ↓ {t(locale, "exportData")}
            </button>
            <button
              type="button"
              onClick={async () => {
                await api("/v1/auth/logout", { method: "POST" });
                setSettingsOpen(false);
                onSignedOut();
              }}
              className="rounded-full bg-white/10 hover:bg-white/20 px-4 py-2 text-xs"
            >
              {t(locale, "logout")}
            </button>
          </div>

          {!confirmErase ? (
            <button
              type="button"
              onClick={() => setConfirmErase(true)}
              className="text-xs text-red-400 hover:underline block pt-2"
            >
              {t(locale, "deleteAccount")}
            </button>
          ) : (
            <div className="rounded-xl bg-red-500/15 border border-red-400/40 p-3 space-y-2 text-xs">
              <p className="text-red-200">{t(locale, "deleteConfirm")}</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    await api("/v1/account", { method: "DELETE" });
                    setSettingsOpen(false);
                    onSignedOut();
                  }}
                  className="rounded-full bg-red-600 px-3 py-1.5 text-white"
                >
                  Confirm erasure
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmErase(false)}
                  className="rounded-full bg-white/10 px-3 py-1.5"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
