import { describe, expect, it } from "vitest";

import { chordLabel, localizeWarning, noteName } from "./music";

describe("music helpers", () => {
  it("names notes and chords", () => {
    expect(noteName(60)).toBe("C4");
    expect(noteName(70)).toBe("Bb4");
    expect(chordLabel(9, "min7", null)).toBe("Am7");
    expect(chordLabel(0, "maj", 4)).toBe("C/E");
  });

  it("localizes known backend warnings and passes unknown ones through", () => {
    expect(localizeWarning("playability: 10 left-hand note(s) moved down to avoid the right hand")).toBe(
      "오른손과 겹치지 않도록 왼손 10개 음을 한 옥타브 내렸습니다.",
    );
    expect(localizeWarning("transposed by +2 semitones to F major")).toBe("F major(으)로 +2반음 이조했습니다.");
    expect(localizeWarning("something new")).toBe("something new");
  });
});
