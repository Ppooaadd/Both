/**
 * Runtime-validated API contract (mirrors docs/api.md and backend/api/schemas.py).
 * Every response is parsed, so a backend change fails loudly instead of rendering garbage.
 */
import { z } from "zod";

export const difficulties = ["beginner", "intermediate", "advanced"] as const;
export const Difficulty = z.enum(difficulties);
export type Difficulty = z.infer<typeof Difficulty>;

export const JobStatus = z.enum(["queued", "running", "succeeded", "failed", "canceled"]);
export type JobStatus = z.infer<typeof JobStatus>;

export const ExportFormat = z.enum(["midi", "musicxml", "pdf", "wav", "mp3"]);
export type ExportFormat = z.infer<typeof ExportFormat>;

export const ArrangementParams = z.object({
  difficulty: Difficulty.default("intermediate"),
  transpose: z.number().int().min(-6).max(6).default(0),
  simplify_key: z.boolean().default(false),
  tempo_scale: z.number().min(0.5).max(1.5).default(1),
  melody_source: z.enum(["auto", "vocals", "other"]).default("auto"),
  left_hand_pattern: z.enum(["auto", "root", "block", "alberti", "arpeggio", "stride"]).default("auto"),
  quantize_grid: z.enum(["auto", "1/4", "1/8", "1/16", "1/8t"]).default("auto"),
  density: z.number().min(0).max(1).default(0.5),
  range_low: z.number().int().min(21).max(108).default(36),
  range_high: z.number().int().min(21).max(108).default(96),
  include_intro_outro: z.boolean().default(true),
});
export type ArrangementParams = z.infer<typeof ArrangementParams>;
export const defaultParams = (difficulty: Difficulty = "intermediate"): ArrangementParams =>
  ArrangementParams.parse({ difficulty });

export const User = z.object({
  id: z.string(),
  email: z.string(),
  display_name: z.string(),
  plan: z.enum(["free", "pro"]),
  email_verified: z.boolean(),
  created_at: z.string(),
});
export type User = z.infer<typeof User>;

export const Session = z.object({
  user: User,
  csrf_token: z.string(),
  access_expires_in: z.number(),
});

export const UploadCreated = z.object({
  upload_id: z.string(),
  url: z.string(),
  fields: z.record(z.string(), z.string()),
  expires_in: z.number(),
  max_bytes: z.number(),
});
export type UploadCreated = z.infer<typeof UploadCreated>;

export const Job = z.object({
  id: z.string(),
  project_id: z.string(),
  kind: z.enum(["full", "rearrange", "export"]),
  status: JobStatus,
  stage: z.string(),
  progress: z.number(),
  params: z.record(z.string(), z.unknown()),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});
export type Job = z.infer<typeof Job>;

export const JobEvent = z.object({
  id: z.number(),
  stage: z.string(),
  progress: z.number(),
  level: z.enum(["info", "warn", "error"]),
  message: z.string(),
  created_at: z.string(),
});
export type JobEvent = z.infer<typeof JobEvent>;

export const Asset = z.object({
  id: z.string(),
  original_filename: z.string(),
  mime_type: z.string(),
  size_bytes: z.number(),
  duration_sec: z.number().nullable(),
  sample_rate: z.number().nullable(),
  channels: z.number().nullable(),
  status: z.string(),
  purge_after: z.string().nullable(),
});

export const AnalysisSummary = z.object({
  id: z.string(),
  tempo_bpm: z.number(),
  time_signature: z.string(),
  key_tonic: z.number(),
  key_mode: z.string(),
  key_confidence: z.number(),
  engine_versions: z.record(z.string(), z.unknown()),
  summary: z.object({
    key: z.string(),
    tempo_bpm: z.number(),
    time_signature: z.string(),
    duration: z.number(),
    bars: z.number(),
    top_chords: z.array(z.object({ label: z.string(), seconds: z.number() })),
    sections: z.array(z.string()),
    note_counts: z.record(z.string(), z.number()),
    engines: z.record(z.string(), z.string()),
    warnings: z.array(z.string()),
  }),
  created_at: z.string(),
});
export type AnalysisSummary = z.infer<typeof AnalysisSummary>;

export const ExportInfo = z.object({
  format: ExportFormat,
  size_bytes: z.number(),
  engine: z.string(),
  created_at: z.string(),
});

export const ArrangementStats = z
  .object({
    measures: z.number(),
    key: z.string(),
    tempo_bpm: z.number(),
    pattern: z.string(),
    grid: z.string(),
    rh_notes: z.number(),
    lh_notes: z.number(),
    rh_max_poly: z.number(),
    lh_max_poly: z.number(),
    difficulty_score: z.number(),
    onsets_per_second: z.number(),
    warnings: z.array(z.string()),
  })
  .partial();

export const Arrangement = z.object({
  id: z.string(),
  project_id: z.string(),
  analysis_id: z.string(),
  difficulty: Difficulty,
  params: z.record(z.string(), z.unknown()),
  revision: z.number(),
  status: z.enum(["pending", "ready", "failed"]),
  stats: ArrangementStats,
  created_at: z.string(),
  exports: z.array(ExportInfo),
});
export type Arrangement = z.infer<typeof Arrangement>;

export const ScoreNote = z.object({
  hand: z.enum(["rh", "lh"]),
  pitch: z.number(),
  start: z.number(),
  dur: z.number(),
  velocity: z.number(),
  role: z.enum(["melody", "harmony", "bass", "accomp"]),
  finger: z.number().nullable(),
});
export type ScoreNote = z.infer<typeof ScoreNote>;

export const Score = z.object({
  title: z.string(),
  difficulty: Difficulty,
  tpq: z.number(),
  tempo_bpm: z.number(),
  time_signature: z.tuple([z.number(), z.number()]),
  key: z.object({ tonic: z.number(), mode: z.enum(["major", "minor"]), fifths: z.number() }),
  transpose: z.number(),
  grid: z.number(),
  measures: z.number(),
  notes: z.array(ScoreNote),
  chords: z.array(
    z.object({ start: z.number(), root: z.number(), quality: z.string(), bass: z.number().nullable() }),
  ),
  sections: z.array(z.object({ start: z.number(), label: z.string() })),
  pedal: z.array(z.object({ start: z.number(), end: z.number() })),
  beat_times: z.array(z.number()),
  show_fingering: z.boolean(),
  stats: z.record(z.string(), z.unknown()),
  warnings: z.array(z.string()),
});
export type Score = z.infer<typeof Score>;

export const ArrangementDetail = Arrangement.extend({ score: Score.nullable().optional() });
export type ArrangementDetail = z.infer<typeof ArrangementDetail>;

export const Project = z.object({
  id: z.string(),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  latest_job: Job.nullable(),
});
export type Project = z.infer<typeof Project>;

export const ProjectDetail = Project.extend({
  asset: Asset,
  analysis: AnalysisSummary.nullable(),
  latest_arrangement: Arrangement.nullable(),
});
export type ProjectDetail = z.infer<typeof ProjectDetail>;

export const ProjectCreated = z.object({ project: Project, job: Job });
export const ProjectPage = z.object({ items: z.array(Project), next_cursor: z.string().nullable() });
export type ProjectPage = z.infer<typeof ProjectPage>;

export const ArrangementRequest = z.object({
  arrangement: Arrangement.nullable(),
  job: Job.nullable(),
});
export type ArrangementRequest = z.infer<typeof ArrangementRequest>;

export const Download = z.object({ url: z.string(), expires_in: z.number(), filename: z.string() });
export const WsTicket = z.object({ ticket: z.string(), expires_in: z.number(), url: z.string() });

// ------------------------------------------------------------- WebSocket frames
export const WsMessage = z.discriminatedUnion("type", [
  z.object({ type: z.literal("snapshot"), job: Job, events: z.array(JobEvent) }),
  z.object({
    type: z.literal("progress"),
    job_id: z.string(),
    stage: z.string(),
    progress: z.number(),
    status: z.literal("running"),
  }),
  z.object({
    type: z.literal("event"),
    job_id: z.string(),
    id: z.number(),
    stage: z.string(),
    progress: z.number(),
    level: z.enum(["info", "warn", "error"]),
    message: z.string(),
    created_at: z.string(),
  }),
  z.object({
    type: z.literal("status"),
    job_id: z.string(),
    status: JobStatus,
    stage: z.string(),
    progress: z.number(),
    error_code: z.string().nullish(),
    error_message: z.string().nullish(),
    analysis_id: z.string().nullish(),
    arrangement_id: z.string().nullish(),
  }),
  z.object({ type: z.literal("ping") }),
]);
export type WsMessage = z.infer<typeof WsMessage>;

export const ApiErrorBody = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    request_id: z.string().nullish(),
    details: z.array(z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() })).optional(),
  }),
});
