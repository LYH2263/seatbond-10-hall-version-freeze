export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    // FastAPI 错误体为 {detail: "..."}，取出可读提示
    let msg = res.statusText;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") msg = data.detail;
      else if (Array.isArray(data?.detail)) msg = data.detail.map((d: { msg?: string }) => d.msg).join("；");
    } catch {
      /* 保留 statusText */
    }
    throw new Error(msg || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
