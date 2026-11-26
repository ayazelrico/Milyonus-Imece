import { create } from "zustand";
import type { Locale } from "./i18n";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
};

export type ToolEvent = {
  call_id: string;
  name: string;
  args_preview?: string;
  risk?: string;
  ok?: boolean;
  duration_ms?: number;
  preview?: string;
  truncated?: boolean;
  full_ref?: string;
};

export type ApprovalEvent = {
  approval_id: string;
  name: string;
  args: Record<string, unknown>;
  risk: string;
  reason: string;
  irreversible: boolean;
  findings: string[];
};

type UiState = {
  sessionId: string | null;
  messages: ChatMessage[];
  streaming: string;
  tools: ToolEvent[];
  approval: ApprovalEvent | null;
  railOpen: boolean;
  sidebarOpen: boolean;
  settingsOpen: boolean;
  warRoomOpen: boolean;
  hypernovaOpen: boolean;
  singularityOpen: boolean;
  locale: Locale;
  quietMemory: boolean;
  toolsEnabled: boolean;
  feedback: Record<string, "up" | "down">;
  budgetPressure: number;
  prefixCacheHit: boolean | null;
  setSession: (id: string | null) => void;
  pushMessage: (m: ChatMessage) => void;
  setMessages: (m: ChatMessage[]) => void;
  appendStream: (t: string) => void;
  clearStream: () => void;
  addTool: (t: ToolEvent) => void;
  updateToolResult: (call_id: string, patch: Partial<ToolEvent>) => void;
  clearTools: () => void;
  setApproval: (a: ApprovalEvent | null) => void;
  setRailOpen: (v: boolean) => void;
  setSidebarOpen: (v: boolean) => void;
  setSettingsOpen: (v: boolean) => void;
  setWarRoomOpen: (v: boolean) => void;
  setHypernovaOpen: (v: boolean) => void;
  setSingularityOpen: (v: boolean) => void;
  setLocale: (l: Locale) => void;
  setQuietMemory: (v: boolean) => void;
  setToolsEnabled: (v: boolean) => void;
  setFeedback: (id: string, rating: "up" | "down") => void;
  setFeedbackMap: (map: Record<string, "up" | "down">) => void;
  setBudgetPressure: (p: number) => void;
  setPrefixCacheHit: (v: boolean | null) => void;
};

export const useUi = create<UiState>((set) => ({
  sessionId: null,
  messages: [],
  streaming: "",
  tools: [],
  approval: null,
  railOpen: true,
  sidebarOpen: false,
  settingsOpen: false,
  warRoomOpen: false,
  hypernovaOpen: false,
  singularityOpen: false,
  locale: "en",
  quietMemory: false,
  toolsEnabled: true,
  feedback: {},
  budgetPressure: 0,
  prefixCacheHit: null,
  setSession: (id) =>
    set({
      sessionId: id,
      tools: [],
      streaming: "",
      approval: null,
      feedback: {},
      budgetPressure: 0,
      prefixCacheHit: null,
    }),
  pushMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (m) => set({ messages: m }),
  appendStream: (t) => set((s) => ({ streaming: s.streaming + t })),
  clearStream: () => set({ streaming: "" }),
  addTool: (t) =>
    set((s) => ({
      tools: s.tools.some((x) => x.call_id === t.call_id) ? s.tools : [...s.tools, t],
    })),
  updateToolResult: (call_id, patch) =>
    set((s) => ({
      tools: s.tools.map((x) => (x.call_id === call_id ? { ...x, ...patch } : x)),
    })),
  clearTools: () => set({ tools: [] }),
  setApproval: (a) => set({ approval: a }),
  setRailOpen: (v) => set({ railOpen: v }),
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  setSettingsOpen: (v) => set({ settingsOpen: v }),
  setWarRoomOpen: (v) => set({ warRoomOpen: v }),
  setHypernovaOpen: (v) => set({ hypernovaOpen: v }),
  setSingularityOpen: (v) => set({ singularityOpen: v }),
  setLocale: (l) => set({ locale: l }),
  setQuietMemory: (v) => set({ quietMemory: v }),
  setToolsEnabled: (v) => set({ toolsEnabled: v }),
  setFeedback: (id, rating) =>
    set((s) => ({ feedback: { ...s.feedback, [id]: rating } })),
  setFeedbackMap: (map) => set({ feedback: map }),
  setBudgetPressure: (p) => set({ budgetPressure: p }),
  setPrefixCacheHit: (v) => set({ prefixCacheHit: v }),
}));
