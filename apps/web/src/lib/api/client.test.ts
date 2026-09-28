import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { AUTH_EXPIRED_EVENT, ApiError, api, errorMessage } from "./client";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("api client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "pf_csrf=tok123; path=/";
  });
  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("sends the CSRF header on unsafe methods only", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json(200, { ok: true })));
    await api("/x", z.object({ ok: z.boolean() }), { method: "POST", body: { a: 1 } });
    await api("/x", z.object({ ok: z.boolean() }));
    const [postInit, getInit] = fetchMock.mock.calls.map((c) => c[1] as RequestInit);
    expect((postInit.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
    expect((getInit.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/x");
  });

  it("refreshes once on 401 and retries the request", async () => {
    fetchMock
      .mockResolvedValueOnce(json(401, { error: { code: "token_expired", message: "expired" } }))
      .mockResolvedValueOnce(json(200, {})) // /auth/refresh
      .mockResolvedValueOnce(json(200, { ok: true }));
    const out = await api("/projects", z.object({ ok: z.boolean() }));
    expect(out.ok).toBe(true);
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/api/v1/projects", "/api/v1/auth/refresh", "/api/v1/projects"]);
  });

  it("emits auth-expired when refresh fails and throws the parsed error", async () => {
    const onExpired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    fetchMock
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "로그인이 필요합니다." } }))
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "x" } }));
    await expect(api("/projects", z.object({}))).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    expect(onExpired).toHaveBeenCalledOnce();
    window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  });

  it("does not refresh for auth endpoints", async () => {
    fetchMock.mockResolvedValueOnce(json(401, { error: { code: "invalid_credentials", message: "틀림" } }));
    await expect(api("/auth/login", z.object({}), { method: "POST", body: {} })).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("formats validation errors and non-JSON failures", async () => {
    const v = new ApiError(422, "validation_error", "bad", null, [{ loc: ["body", "x"], msg: "Value error, 음역은 두 옥타브 이상" }]);
    expect(errorMessage(v)).toBe("음역은 두 옥타브 이상");
    fetchMock.mockResolvedValueOnce(new Response("<html>bad gateway</html>", { status: 502 }));
    const err = await api("/x", z.object({})).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toContain("잠시 후");
  });
});
