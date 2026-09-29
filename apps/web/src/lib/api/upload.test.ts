import { describe, expect, it } from "vitest";

import { MAX_UPLOAD_BYTES, resolveMime, validateFile } from "./upload";

const file = (name: string, type: string, size = 1000) => {
  const f = new File(["x"], name, { type });
  Object.defineProperty(f, "size", { value: size });
  return f;
};

describe("upload validation", () => {
  it("accepts audio by MIME or by extension", () => {
    expect(resolveMime(file("a.mp3", "audio/mpeg"))).toBe("audio/mpeg");
    expect(resolveMime(file("a.m4a", ""))).toBe("audio/mp4");
    expect(resolveMime(file("a.WAV", "application/octet-stream"))).toBe("audio/wav");
  });

  it("rejects wrong types, empty and oversized files", () => {
    expect(validateFile(file("a.exe", "application/x-msdownload"))).toMatch(/MP3/);
    expect(validateFile(file("a.mp3", "audio/mpeg", 0))).toMatch(/빈 파일/);
    expect(validateFile(file("a.mp3", "audio/mpeg", MAX_UPLOAD_BYTES + 1))).toMatch(/100MB/);
    expect(validateFile(file("a.mp3", "audio/mpeg"))).toBeNull();
  });
});
