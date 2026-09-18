export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(readableError(text, res.statusText));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** FastAPI 错误体为 {"detail": "..."} — 提取可读信息而不是把 JSON 甩给用户。 */
function readableError(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg?: string }) => d?.msg ?? JSON.stringify(d)).join("；");
    }
    return text;
  } catch {
    return text;
  }
}
