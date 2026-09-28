import { describe, expect, it } from "vitest";

import type { JobEvent } from "@/lib/api/schemas";
import { FULL_STAGES } from "@/lib/music";
import { stageStates } from "./JobProgress";

const ev = (id: number, stage: string, message: string): JobEvent => ({
  id, stage, progress: 0, level: "info", message, created_at: "t",
});

describe("stageStates", () => {
  it("marks stages done by their completion event, parallel stages included", () => {
    const events = [
      ev(1, "ingest", "정규화 완료 (gain +3.1 dB)"),
      ev(2, "separate", "분리 완료: 보컬 (hpss@1)"),
      ev(3, "rhythm", "템포 100 BPM"),
      ev(4, "transcribe", "음표 추출: melody 57"),
    ];
    const s = stageStates(FULL_STAGES, "tonal", "running", events);
    expect(s.ingest).toBe("done");
    expect(s.transcribe).toBe("done");
    expect(s.tonal).toBe("current");
    expect(s.merge).toBe("pending");
  });

  it("marks everything done on success, including skipped (cached) stages", () => {
    const s = stageStates(FULL_STAGES, "done", "succeeded", []);
    expect(Object.values(s).every((v) => v === "done")).toBe(true);
  });

  it("does not show a failed stage as running", () => {
    const s = stageStates(FULL_STAGES, "ingest", "failed", []);
    expect(s.ingest).toBe("pending");
  });
});
