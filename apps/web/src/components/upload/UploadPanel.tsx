"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileAudioIcon, Loader2Icon, UploadIcon, XIcon } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { errorMessage } from "@/lib/api/client";
import { qk } from "@/lib/api/queries";
import { defaultParams, difficulties, type Difficulty } from "@/lib/api/schemas";
import { ACCEPT_ATTR, uploadAndCreateProject, validateFile, type UploadPhase } from "@/lib/api/upload";
import { DIFFICULTY_HINT, DIFFICULTY_LABEL } from "@/lib/music";
import { cn, formatBytes } from "@/lib/utils";

const PHASE_LABEL: Record<UploadPhase, string> = {
  signing: "업로드 준비 중",
  uploading: "업로드 중",
  starting: "분석 시작 중",
};

export function UploadPanel() {
  const router = useRouter();
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [difficulty, setDifficulty] = useState<Difficulty>("intermediate");
  const [progress, setProgress] = useState<{ phase: UploadPhase; fraction: number } | null>(null);

  const mutation = useMutation({
    mutationFn: (f: File) => {
      abortRef.current = new AbortController();
      return uploadAndCreateProject(
        f,
        { ...defaultParams(difficulty), simplify_key: difficulty === "beginner" },
        (phase, fraction) => setProgress({ phase, fraction }),
        abortRef.current.signal,
      );
    },
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: qk.projects });
      router.push(`/projects/${created.project.id}`);
    },
    onError: () => setProgress(null),
  });

  const pick = (f: File | undefined) => {
    if (!f) return;
    const err = validateFile(f);
    setProblem(err);
    setFile(err ? null : f);
    mutation.reset();
  };

  const busy = mutation.isPending;
  const overall = progress ? (progress.phase === "signing" ? 2 : progress.phase === "uploading" ? 2 + progress.fraction * 93 : 97) : 0;

  return (
    <div className="flex flex-col gap-5">
      <div
        role="button"
        tabIndex={0}
        aria-label="오디오 파일 선택 또는 끌어다 놓기"
        aria-disabled={busy}
        onClick={() => !busy && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!busy && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!busy) pick(e.dataTransfer.files[0]);
        }}
        className={cn(
          "group flex min-h-44 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed bg-card px-6 py-8 text-center transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
          dragging ? "border-primary bg-accent" : "border-input hover:border-primary/60",
          busy && "cursor-default opacity-80",
        )}
      >
        {file ? (
          <>
            <FileAudioIcon className="size-8 text-primary" />
            <div>
              <p className="font-medium break-all">{file.name}</p>
              <p className="text-sm text-muted-foreground">{formatBytes(file.size)}</p>
            </div>
            {!busy && <p className="text-xs text-muted-foreground">다른 파일을 고르려면 클릭하세요</p>}
          </>
        ) : (
          <>
            <UploadIcon className="size-8 text-muted-foreground transition-colors group-hover:text-primary" />
            <div>
              <p className="font-medium">MP3 · WAV · M4A 파일을 끌어다 놓거나 클릭해서 고르세요</p>
              <p className="text-sm text-muted-foreground">최대 50MB · 무료 플랜 곡당 10분</p>
            </div>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTR}
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>

      <fieldset className="grid gap-2" disabled={busy}>
        <legend className="mb-2 text-sm font-medium">처음 만들 난이도</legend>
        <div className="grid gap-2 sm:grid-cols-3">
          {difficulties.map((d) => (
            <label
              key={d}
              className={cn(
                "flex cursor-pointer flex-col gap-1 rounded-lg border bg-card px-4 py-3 transition-colors has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/50",
                difficulty === d ? "border-primary bg-accent" : "hover:border-primary/40",
              )}
            >
              <input
                type="radio"
                name="difficulty"
                value={d}
                checked={difficulty === d}
                onChange={() => setDifficulty(d)}
                className="sr-only"
              />
              <span className="font-medium">{DIFFICULTY_LABEL[d]}</span>
              <span className="text-xs text-muted-foreground">{DIFFICULTY_HINT[d]}</span>
            </label>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">분석이 끝나면 다른 난이도와 세부 설정으로 몇 초 만에 다시 편곡할 수 있습니다.</p>
      </fieldset>

      {problem && (
        <Alert variant="destructive">
          <AlertDescription className="text-destructive">{problem}</AlertDescription>
        </Alert>
      )}
      {mutation.isError && (
        <Alert variant="destructive">
          <AlertDescription className="text-destructive">{errorMessage(mutation.error)}</AlertDescription>
        </Alert>
      )}

      {busy && progress && (
        <div className="grid gap-2" aria-live="polite">
          <div className="flex justify-between text-sm">
            <span>{PHASE_LABEL[progress.phase]}</span>
            <span className="font-mono tabular-nums text-muted-foreground">{Math.round(overall)}%</span>
          </div>
          <Progress value={overall} aria-label="업로드 진행률" />
        </div>
      )}

      <div className="flex gap-2">
        <Button size="lg" className="flex-1 sm:flex-none" disabled={!file || busy} onClick={() => file && mutation.mutate(file)}>
          {busy ? <Loader2Icon className="animate-spin" /> : <UploadIcon />}
          편곡 시작
        </Button>
        {busy && (
          <Button size="lg" variant="outline" onClick={() => abortRef.current?.abort()}>
            <XIcon />
            취소
          </Button>
        )}
      </div>
    </div>
  );
}
