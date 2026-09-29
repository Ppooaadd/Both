/** Music helpers and user-facing labels shared by the UI. */
import type { ArrangementParams, Difficulty } from "@/lib/api/schemas";

export const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"] as const;
const BLACK = new Set([1, 3, 6, 8, 10]);

export const noteName = (pitch: number): string => `${NOTE_NAMES[((pitch % 12) + 12) % 12]}${Math.floor(pitch / 12) - 1}`;
export const isBlackKey = (pitch: number): boolean => BLACK.has(((pitch % 12) + 12) % 12);

const QUALITY_SUFFIX: Record<string, string> = {
  maj: "", min: "m", dim: "dim", aug: "aug", sus4: "sus4", "7": "7", maj7: "maj7", min7: "m7", N: "",
};

export function chordLabel(root: number, quality: string, bass: number | null): string {
  let label = NOTE_NAMES[root] + (QUALITY_SUFFIX[quality] ?? "");
  if (bass !== null && bass !== root) label += `/${NOTE_NAMES[bass]}`;
  return label;
}

export const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  beginner: "초급",
  intermediate: "중급",
  advanced: "고급",
};

export const DIFFICULTY_HINT: Record<Difficulty, string> = {
  beginner: "멜로디 단선율 · 4분음표 · 왼손 두 음",
  intermediate: "강박 화음 보강 · 8분음표 · 알베르티/아르페지오",
  advanced: "화음 보강 · 16분음표 · 넓은 아르페지오/스트라이드",
};

export const PATTERN_LABEL: Record<ArrangementParams["left_hand_pattern"], string> = {
  auto: "자동",
  root: "근음",
  block: "블록 코드",
  alberti: "알베르티",
  arpeggio: "아르페지오",
  stride: "스트라이드",
};

export const TIMING_LABEL: Record<ArrangementParams["timing"], string> = {
  original: "원곡 박자",
  steady: "일정한 템포",
};

export const GRID_LABEL: Record<ArrangementParams["quantize_grid"], string> = {
  auto: "난이도 기본",
  "1/4": "4분음표",
  "1/8": "8분음표",
  "1/16": "16분음표",
  "1/8t": "8분 셋잇단",
};

export const MELODY_SOURCE_LABEL: Record<ArrangementParams["melody_source"], string> = {
  auto: "자동",
  vocals: "보컬",
  other: "반주 최상성부",
};

export const STAGE_LABEL: Record<string, string> = {
  queued: "대기 중",
  ingest: "파일 검증",
  separate: "음원 분리",
  rhythm: "템포·박자",
  tonal: "조성·코드",
  transcribe: "음표 추출",
  merge: "분석 정리",
  arrange: "편곡",
  export: "파일 생성",
  done: "완료",
};

export const FULL_STAGES = ["ingest", "separate", "rhythm", "tonal", "transcribe", "merge", "arrange", "export"] as const;
export const REARRANGE_STAGES = ["arrange", "export"] as const;

export const EXPORT_LABEL: Record<string, { name: string; hint: string }> = {
  pdf: { name: "PDF 악보", hint: "인쇄용" },
  musicxml: { name: "MusicXML", hint: "MuseScore·Finale·Sibelius에서 편집" },
  midi: { name: "MIDI", hint: "DAW·전자 피아노" },
  mp3: { name: "MP3", hint: "피아노 렌더링 오디오" },
  wav: { name: "WAV", hint: "무손실 오디오" },
};

/** Backend warnings are technical English; show known ones in Korean, pass others through. */
const WARNING_RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^playability: (\d+) note\(s\) removed/, (m) => `손 크기·음역 제한에 맞추기 위해 ${m[1]}개 음을 뺐습니다.`],
  [/^playability: (\d+) left-hand note\(s\) moved down/, (m) => `오른손과 겹치지 않도록 왼손 ${m[1]}개 음을 한 옥타브 내렸습니다.`],
  [/^transposed by ([+-]\d+) semitones to (.+)$/, (m) => `${m[2]}(으)로 ${m[1]}반음 이조했습니다.`],
  [/^melody: none detected/, () => "멜로디를 찾지 못해 반주만 편곡했습니다."],
  [/^melody: no melodic line detected/, () => "멜로디 선율이 뚜렷하지 않아 화음의 최상성부를 멜로디로 썼습니다."],
  [/^melody: vocals near-silent/, () => "보컬이 거의 없어 반주에서 멜로디를 추출했습니다."],
  [/^harmony: derived from recognised chords/, () => "화성은 인식한 코드로부터 만들었습니다."],
  [/^bass: derived from chord roots/, () => "베이스는 코드 근음으로 만들었습니다."],
  [/^rhythm: low beat confidence/, () => "박자 인식 신뢰도가 낮아 리듬이 부정확할 수 있습니다."],
  [/^key: ambiguous tonality/, () => "조성이 모호합니다."],
  [/^pdf: unavailable/, () => "PDF를 만들지 못했습니다. MusicXML을 받아 악보 프로그램에서 인쇄해 주세요."],
];

export function localizeWarning(text: string): string {
  for (const [re, fmt] of WARNING_RULES) {
    const m = text.match(re);
    if (m) return fmt(m);
  }
  return text;
}
