"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { FileAudioIcon } from "lucide-react";
import { toast } from "sonner";

import { AnalysisSummary } from "@/components/analysis/AnalysisSummary";
import { ArrangementPicker } from "@/components/arrange/ArrangementPicker";
import { ParameterPanel } from "@/components/arrange/ParameterPanel";
import { DownloadMenu } from "@/components/export/DownloadMenu";
import { JobProgress } from "@/components/job/JobProgress";
import { PianoRoll } from "@/components/pianoroll/PianoRoll";
import { TransportBar } from "@/components/player/TransportBar";
import { useAudioClock } from "@/components/player/useAudioClock";
import { ScoreViewer } from "@/components/score/ScoreViewer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api/client";
import {
  exportHref,
  isTerminal,
  useArrangement,
  useArrangements,
  useJob,
  useProject,
  useRequestArrangement,
} from "@/lib/api/queries";
import { ArrangementParams, type Arrangement } from "@/lib/api/schemas";
import { timeMap } from "@/lib/timing";
import { DIFFICULTY_LABEL, GRID_LABEL, PATTERN_LABEL, localizeWarning } from "@/lib/music";
import { cn, formatBytes, formatDuration } from "@/lib/utils";

function HandToggle({ hand, on, onChange }: { hand: "rh" | "lh"; on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      className={cn(
        "flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
        on ? "bg-card" : "bg-muted text-muted-foreground line-through",
      )}
    >
      <span className="size-2.5 rounded-sm" style={{ background: hand === "rh" ? "var(--roll-rh)" : "var(--roll-lh)" }} />
      {hand === "rh" ? "오른손" : "왼손"}
    </button>
  );
}

function StatsLine({ a }: { a: Arrangement }) {
  const s = a.stats;
  const parts = [
    s.measures !== undefined && `${s.measures}마디`,
    s.key,
    s.pattern && `왼손 ${PATTERN_LABEL[s.pattern as keyof typeof PATTERN_LABEL] ?? s.pattern}`,
    s.grid && GRID_LABEL[s.grid as keyof typeof GRID_LABEL],
    s.rh_notes !== undefined && `오른손 ${s.rh_notes}음 · 왼손 ${s.lh_notes}음`,
    s.difficulty_score !== undefined && `난이도 지수 ${s.difficulty_score.toFixed(1)}/10`,
  ].filter(Boolean);
  return <p className="font-mono text-xs text-muted-foreground">{parts.join(" · ")}</p>;
}

export function ProjectWorkspace({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const analysisReady = Boolean(project.data?.analysis);
  const arrangements = useArrangements(projectId, analysisReady);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [rearrangeJobId, setRearrangeJobId] = useState<string | null>(null);
  const [hands, setHands] = useState({ rh: true, lh: true });
  const request = useRequestArrangement(projectId);
  const rearrangeJob = useJob(rearrangeJobId);

  const ready = useMemo(() => (arrangements.data ?? []).filter((a) => a.status === "ready"), [arrangements.data]);
  // Explicit pick wins; otherwise the newest ready arrangement.
  const selectedId = pickedId ?? ready[0]?.id ?? null;
  const setSelectedId = setPickedId;

  const onRearranged = (status: string) => {
    if (status !== "succeeded") {
      if (status === "failed") toast.error("다시 편곡하지 못했습니다. 처리 기록을 확인해 주세요.");
      return;
    }
    void arrangements.refetch().then((r) => {
      const newest = r.data?.find((a) => a.status === "ready");
      if (newest) setPickedId(newest.id);
      setRearrangeJobId(null);
      toast.success("새 편곡이 준비되었습니다.");
    });
  };

  const selected = (arrangements.data ?? []).find((a) => a.id === selectedId) ?? null;
  const detail = useArrangement(selected?.status === "ready" ? selected.id : null);
  const score = detail.data?.score ?? null;
  const fallbackBpm = project.data?.analysis?.tempo_bpm ?? 120;
  const toQuarters = useMemo(() => {
    if (!score) return (s: number) => (s * fallbackBpm) / 60;
    const map = timeMap(score);
    return (s: number) => map.secToTick(s) / score.tpq;
  }, [score, fallbackBpm]);
  const hasAudio = Boolean(selected?.exports.some((e) => e.format === "mp3"));
  const clock = useAudioClock(selected && hasAudio ? exportHref(selected.id, "mp3") : null);

  const initialParams = useMemo(
    () => ArrangementParams.parse(selected?.params ?? project.data?.latest_arrangement?.params ?? {}),
    [selected?.params, project.data?.latest_arrangement?.params],
  );

  if (project.isPending) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (project.isError) {
    return <p className="text-sm text-destructive">{errorMessage(project.error)}</p>;
  }

  const p = project.data;
  const fullJob = p.latest_job && p.latest_job.kind === "full" ? p.latest_job : null;
  const analysisRunning = !p.analysis && fullJob && !isTerminal(fullJob.status);
  const analysisFailed = !p.analysis && fullJob && isTerminal(fullJob.status) && fullJob.status !== "succeeded";
  const rearranging = rearrangeJobId && !isTerminal(rearrangeJob.data?.status);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{p.title}</h1>
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <FileAudioIcon className="size-4" />
            {p.asset.original_filename} · {formatBytes(p.asset.size_bytes)}
            {p.asset.duration_sec ? ` · ${formatDuration(p.asset.duration_sec)}` : ""}
          </p>
        </div>
        {selected && selected.status === "ready" && <DownloadMenu arrangement={selected} />}
      </div>

      {(analysisRunning || analysisFailed) && fullJob && (
        <div className="grid gap-3">
          <JobProgress jobId={fullJob.id} projectId={projectId} title="분석과 편곡 진행 중" />
          {analysisFailed && (
            <Button asChild variant="outline" className="w-fit">
              <Link href="/">다른 파일 올리기</Link>
            </Button>
          )}
        </div>
      )}

      {p.analysis && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-w-0 flex-col gap-6">
            <Card className="gap-3">
              <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
                <CardTitle>편곡</CardTitle>
                {arrangements.data && (
                  <ArrangementPicker items={arrangements.data} selectedId={selectedId} onSelect={setSelectedId} />
                )}
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {!selected && (
                  <div className="grid gap-3">
                    {fullJob && !isTerminal(fullJob.status) ? (
                      <JobProgress jobId={fullJob.id} projectId={projectId} title="편곡 만드는 중" />
                    ) : (
                      <p className="text-sm text-muted-foreground">오른쪽 패널에서 설정을 고르고 편곡을 만들어 보세요.</p>
                    )}
                  </div>
                )}
                {selected && (
                  <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <StatsLine a={selected} />
                      <div className="flex gap-1.5">
                        <HandToggle hand="rh" on={hands.rh} onChange={(v) => setHands((h) => ({ ...h, rh: v }))} />
                        <HandToggle hand="lh" on={hands.lh} onChange={(v) => setHands((h) => ({ ...h, lh: v }))} />
                      </div>
                    </div>
                    <TransportBar clock={clock} bpm={score?.tempo_bpm ?? p.analysis.tempo_bpm} />
                    <Tabs defaultValue="roll">
                      <TabsList>
                        <TabsTrigger value="roll">피아노 롤</TabsTrigger>
                        <TabsTrigger value="score">악보</TabsTrigger>
                      </TabsList>
                      <TabsContent value="roll">
                        {score ? (
                          <PianoRoll
                            key={selected.id}
                            score={score}
                            getTime={clock.getTime}
                            playing={clock.playing}
                            onSeek={(t) => {
                              clock.seek(t);
                              if (!clock.playing) void clock.play();
                            }}
                            hands={hands}
                            className="h-[420px]"
                          />
                        ) : (
                          <Skeleton className="h-[420px] w-full" />
                        )}
                      </TabsContent>
                      <TabsContent value="score">
                        <ScoreViewer
                          key={selected.id}
                          arrangementId={selected.id}
                          toQuarters={toQuarters}
                          getTime={clock.getTime}
                          playing={clock.playing}
                        />
                      </TabsContent>
                    </Tabs>
                    {score && score.warnings.length > 0 && (
                      <ul className="grid gap-0.5 text-xs text-muted-foreground">
                        {score.warnings.map((w) => (
                          <li key={w}>· {localizeWarning(w)}</li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </CardContent>
            </Card>
            <AnalysisSummary analysis={p.analysis} />
          </div>

          <aside className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle>설정 바꿔 다시 편곡</CardTitle>
              </CardHeader>
              <CardContent>
                <ParameterPanel
                  key={selectedId ?? "none"}
                  initial={initialParams}
                  keyTonic={p.analysis.key_tonic}
                  pending={request.isPending || Boolean(rearranging)}
                  onSubmit={(params) =>
                    request.mutate(params, {
                      onSuccess: (r) => {
                        if (r.arrangement) {
                          setSelectedId(r.arrangement.id);
                          toast.info(`같은 설정의 ${DIFFICULTY_LABEL[r.arrangement.difficulty]} 편곡이 있어 바로 불러왔습니다.`);
                        } else if (r.job) {
                          setRearrangeJobId(r.job.id);
                        }
                      },
                      onError: (e) => toast.error(errorMessage(e)),
                    })
                  }
                />
              </CardContent>
            </Card>
            {rearrangeJobId && (
              <JobProgress jobId={rearrangeJobId} projectId={projectId} title="다시 편곡하는 중" onFinished={onRearranged} />
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
