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
  if (!headers.has("Content-Type") && init.body) {
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
};

export type MemoryItem = {
  id: string;
  content: string;
  state: string;
  trust_tier: string;
  source_uri: string | null;
};
