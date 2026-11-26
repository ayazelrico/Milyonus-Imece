function csrf(): string {
  return (
    document.cookie
      .split("; ")
      .find((c) => c.startsWith("milyonus_csrf="))
      ?.split("=")[1] ?? ""
  );
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && typeof init.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  const token = csrf();
  if (token) headers.set("x-csrf-token", token);
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type Session = {
  id: string;
  title: string | null;
  updated_at: number;
  pinned: boolean;
  parent_id?: string | null;
};

export type PendingApproval = {
  approval_id: string;
  call_id: string;
  name: string;
  args: Record<string, unknown>;
  risk: string;
  reason: string;
  irreversible: boolean;
  expires_at: number;
};

export type SessionDetail = Session & {
  messages: { id: number | string; role: string; content: string; created_at: number }[];
  active_turn_id: string | null;
  pending_approvals: PendingApproval[];
  feedback?: Record<string, "up" | "down">;
};

export type MemoryItem = {
  id: string;
  content: string;
  state: string;
  trust_tier: string;
  trust_score?: number;
  trust_ceiling?: number;
  review_at?: number | null;
  reaffirm_count?: number;
  sensitivity?: string;
  source_uri: string | null;
};

export type SkillSummary = {
  name: string;
  description: string;
  category: string;
};

export type ApiKeyRow = {
  id: string;
  name: string;
  prefix: string;
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
};

export type UsageData = {
  tokens_used: number;
  cost_usd: number;
  turns: number;
  period?: string;
};
