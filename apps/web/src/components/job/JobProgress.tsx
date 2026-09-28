"use client";

import { useMemo, useState } from "react";
import { AlertTriangleIcon, CheckIcon, ChevronDownIcon, CircleIcon, Loader2Icon, XIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api/client";
import { useCancelJob } from "@/lib/api/queries";
import type { Job, JobEvent } from "@/lib/api/schemas";
import { FULL_STAGES, REARRANGE_STAGES, STAGE_LABEL } from "@/lib/music";
import { cn } from "@/lib/utils";
import { useJobStream } from "@/lib/ws/useJobStream";
import type { ConnectionState } from "@/lib/ws/jobSocket";

const CONNECTION: Record<ConnectionState, { label: string; variant: "success" | "warning" | "secondary" }> = {
  connecting: { label: "연결 중", variant: "secondary" },
  live: { label: "실시간", variant: "success" },
  reconnecting: { label: "재연결 중", variant: "warning" },
  polling: { label: "2초마다 확인", variant: "warning" },
  closed: { label: "종료", variant: "secondary" },
};

type StageState = "done" | "current" | "pending";

/** Final event each worker stage emits (backend/worker/tasks/*). */
const STAGE_DONE: Record<string, RegExp> = {
  ingest: /정규화 완료|재사용/,
  separate: /분리 완료|재사용/,
  rhythm: /템포/,
  tonal: /조성/,
  transcribe: /음표 추출/,
  merge: /분석 완료/,
  arrange: /편곡:|재사용/,
  export: /내보내기 완료/,
};

export function stageStates(
  stages: readonly string[],
  currentStage: string,
  status: string,
  events: JobEvent[],
): Record<string, StageState> {
  const out: Record<string, StageState> = {};
  for (const s of stages) {
    const finished = events.some((e) => e.stage === s && STAGE_DONE[s]?.test(e.message));
    if (status === "succeeded" || finished) out[s] = "done";
    else if (s === currentStage && (status === "running" || status === "queued")) out[s] = "current";
    else out[s] = "pending";
  }
  return out;
}

export function JobProgress({
  jobId,
  projectId,
  title = "처리 상황",
  onFinished,
}: {
  jobId: string;
  projectId: string;
  title?: string;
  onFinished?: (status: Job["status"]) => void;
}) {
  const { job, events, connection } = useJobStream(jobId, projectId, onFinished);
  const cancel = useCancelJob();
  const [showLog, setShowLog] = useState(false);

  const stages = job?.kind === "rearrange" ? REARRANGE_STAGES : FULL_STAGES;
  const states = useMemo(
    () => stageStates(stages, job?.stage ?? "queued", job?.status ?? "queued", events),
    [stages, job?.stage, job?.status, events],
  );
  const conn = CONNECTION[connection];
  const running = job?.status === "queued" || job?.status === "running";
  const warnings = events.filter((e) => e.level !== "info");

  return (
    <Card aria-live="polite">
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle>{title}</CardTitle>
        <div className="flex items-center gap-2">
          {running && <Badge variant={conn.variant}>{conn.label}</Badge>}
          {running && (
            <Button size="sm" variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate(jobId)}>
              <XIcon />
              취소
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid gap-2">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium">
              {job?.status === "succeeded"
                ? "완료"
                : job?.status === "failed"
                  ? "실패"
                  : job?.status === "canceled"
                    ? "취소됨"
                    : STAGE_LABEL[job?.stage ?? "queued"] ?? job?.stage}
            </span>
            <span className="font-mono tabular-nums text-muted-foreground">{job?.progress ?? 0}%</span>
          </div>
          <Progress value={job?.progress ?? 0} aria-label="전체 진행률" />
        </div>

        <ol className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          {stages.map((s) => (
            <li key={s} className="flex items-center gap-2">
              {states[s] === "done" ? (
                <CheckIcon className="size-4 text-success" aria-label="완료" />
              ) : states[s] === "current" ? (
                <Loader2Icon className="size-4 animate-spin text-primary" aria-label="진행 중" />
              ) : (
                <CircleIcon className="size-3 text-muted-foreground/60" aria-label="대기" />
              )}
              <span className={cn(states[s] === "pending" && "text-muted-foreground")}>{STAGE_LABEL[s]}</span>
            </li>
          ))}
        </ol>

        {job?.status === "failed" && (
          <Alert variant="destructive">
            <AlertTriangleIcon />
            <AlertTitle>처리하지 못했습니다</AlertTitle>
            <AlertDescription className="text-destructive">{job.error_message}</AlertDescription>
          </Alert>
        )}
        {cancel.isError && <p className="text-sm text-destructive">{errorMessage(cancel.error)}</p>}

        {events.length > 0 && (
          <div className="grid gap-2">
            <button
              type="button"
              className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
              onClick={() => setShowLog((v) => !v)}
              aria-expanded={showLog}
            >
              <ChevronDownIcon className={cn("size-4 transition-transform", showLog && "rotate-180")} />
              처리 기록 {events.length}건{warnings.length ? ` · 참고 ${warnings.length}건` : ""}
            </button>
            {showLog && (
              <ul className="max-h-56 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                {events.map((e) => (
                  <li key={e.id} className={cn(e.level === "warn" && "text-warning", e.level === "error" && "text-destructive")}>
                    <span className="text-muted-foreground">[{STAGE_LABEL[e.stage] ?? e.stage}]</span> {e.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
