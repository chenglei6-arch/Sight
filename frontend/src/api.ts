type Params = Record<string, string | number | boolean | null | undefined>;
interface RequestOptions {
  params?: Params;
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(
  path: string,
  { params = {}, method = "GET", body, signal }: RequestOptions = {},
): Promise<T> {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "")
      query.set(key, String(value));
  });
  const res = await fetch(`/api${path}${query.size ? `?${query}` : ""}`, {
    method,
    signal,
    headers:
      body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let payload: { code: number; data: T; message?: string };
  try {
    payload = await res.json();
  } catch {
    throw new Error(`服务响应异常 (${res.status})`);
  }
  if (!res.ok || payload.code !== 200)
    throw new Error(payload.message || `请求失败 (${res.status})`);
  return payload.data;
}
export const api = {
  get: <T>(path: string, params?: Params, signal?: AbortSignal) =>
    request<T>(path, { params, signal }),
  post: <T>(
    path: string,
    body: unknown = {},
    params?: Params,
    signal?: AbortSignal,
  ) => request<T>(path, { params, method: "POST", body, signal }),
  put: <T>(path: string, body: unknown = {}, signal?: AbortSignal) =>
    request<T>(path, { method: "PUT", body, signal }),
  del: <T>(path: string, signal?: AbortSignal) =>
    request<T>(path, { method: "DELETE", signal }),
};
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
