import { describe, expect, it } from "vitest";

import { passwordProblem, safeNext } from "./AuthForm";

describe("auth helpers", () => {
  it("only allows in-app redirects", () => {
    expect(safeNext("/projects/1")).toBe("/projects/1");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });

  it("mirrors the backend password policy", () => {
    expect(passwordProblem("short1A")).toMatch(/10자/);
    expect(passwordProblem("alllowercase")).toMatch(/2종류/);
    expect(passwordProblem("Correct-Horse-9")).toBeNull();
  });
});
