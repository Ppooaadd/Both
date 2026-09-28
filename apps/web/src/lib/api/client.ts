/**
 * Fetch wrapper for the PianoForge API.
 *
 * - Same-origin requests (Next rewrites /api/* to the backend), so the session
 *   cookies travel automatically.
 * - Unsafe methods carry the double-submit CSRF token from the pf_csrf cookie.
 * - A 401 triggers one refresh attempt (single-flight across concurrent calls),
 *   then the original request is retried once.
 * - Errors are normalised to ApiError; successful bodies are schema-validated.
 */
import type { z } from "zod";

import { ApiErrorBody } from "./schemas";

export const API_BASE = "/api/v1";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);
export const AUTH_EXPIRED_EVENT = "pianoforge:auth-expired";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string | null,
    readonly details?: { loc: (string | number)[]; msg: string }[],
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isAuth(): boolean {
    return this.status === 401;
  }
}

export function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : undefined;
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // Non-JSON error (proxy, gateway): fall through to a generic message.
  }
  const parsed = ApiErrorBody.safeParse(body);
  if (parsed.success) {
    const e = parsed.data.error;
    return new ApiError(res.status, e.code, e.message, e.request_id, e.details);
  }
  const generic =
    res.status >= 500 ? "서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요." : `요청이 실패했습니다 (${res.status}).`;
  return new ApiError(res.status, `http_${res.status}`, generic);
}

let refreshing: Promise<boolean> | null = null;

/** Exchange the refresh cookie for a new session. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** Set false for auth endpoints so a 401 is returned instead of refreshed. */
  retryOnAuth?: boolean;
};

async function send(path: string, opts: RequestOptions): Promise<Response> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const csrf = readCookie("pf_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });
}

export async function request(path: string, opts: RequestOptions = {}): Promise<Response> {
  let res = await send(path, opts);
  if (res.status === 401 && opts.retryOnAuth !== false && !path.startsWith("/auth/")) {
    if (await refreshSession()) {
      res = await send(path, opts);
    }
    if (res.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

export async function api<S extends z.ZodType>(path: string, schema: S, opts: RequestOptions = {}): Promise<z.infer<S>> {
  const res = await request(path, opts);
  return schema.parse(await res.json());
}

export async function apiVoid(path: string, opts: RequestOptions = {}): Promise<void> {
  await request(path, opts);
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "validation_error" && err.details?.length) {
      return err.details.map((d) => d.msg.replace(/^Value error, /, "")).join(" ");
    }
    return err.message;
  }
  if (err instanceof Error && err.name === "AbortError") return "요청이 취소되었습니다.";
  return "네트워크 오류가 발생했습니다. 연결을 확인해 주세요.";
}
