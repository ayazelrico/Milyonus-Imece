import { create } from "zustand";

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
  setSession: (id: string | null) => void;
  pushMessage: (m: ChatMessage) => void;
  setMessages: (m: ChatMessage[]) => void;
  appendStream: (t: string) => void;
  clearStream: () => void;
  addTool: (t: ToolEvent) => void;
  setApproval: (a: ApprovalEvent | null) => void;
  setRailOpen: (v: boolean) => void;
};

export const useUi = create<UiState>((set) => ({
  sessionId: null,
  messages: [],
  streaming: "",
  tools: [],
  approval: null,
  railOpen: true,
  setSession: (id) => set({ sessionId: id }),
  pushMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (m) => set({ messages: m }),
  appendStream: (t) => set((s) => ({ streaming: s.streaming + t })),
  clearStream: () => set({ streaming: "" }),
  addTool: (t) => set((s) => ({ tools: [...s.tools, t] })),
  setApproval: (a) => set({ approval: a }),
  setRailOpen: (v) => set({ railOpen: v }),
}));
