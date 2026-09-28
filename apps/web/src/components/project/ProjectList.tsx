"use client";

import Link from "next/link";
import { useState } from "react";
import { FileMusicIcon, Loader2Icon, PlusIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/client";
import { isTerminal, useDeleteProject, useProjects } from "@/lib/api/queries";
import { formatDate } from "@/lib/utils";
import { JobStatusBadge } from "./status";

export function ProjectList() {
  const projects = useProjects();
  const del = useDeleteProject();
  const [confirming, setConfirming] = useState<string | null>(null);
  const items = projects.data?.pages.flatMap((p) => p.items) ?? [];

  if (projects.isPending) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
    );
  }
  if (projects.isError) return <p className="text-sm text-destructive">{errorMessage(projects.error)}</p>;
  if (items.length === 0) {
    return (
      <Card className="items-center py-12 text-center">
        <FileMusicIcon className="size-10 text-muted-foreground" />
        <CardHeader className="items-center">
          <CardTitle>아직 프로젝트가 없습니다</CardTitle>
          <CardDescription>음원을 올리면 분석과 편곡이 시작되고, 결과가 여기에 쌓입니다.</CardDescription>
        </CardHeader>
        <Button asChild>
          <Link href="/">
            <PlusIcon />첫 곡 올리기
          </Link>
        </Button>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((p) => {
          const job = p.latest_job;
          const running = job && !isTerminal(job.status);
          return (
            <li key={p.id}>
              <Card className="h-full gap-3 py-4 transition-colors hover:border-primary/40">
                <CardHeader className="flex-row items-start justify-between gap-2 px-4">
                  <div className="min-w-0">
                    <CardTitle className="truncate">
                      <Link href={`/projects/${p.id}`} className="outline-none after:absolute after:inset-0 focus-visible:underline">
                        {p.title}
                      </Link>
                    </CardTitle>
                    <CardDescription className="text-xs">{formatDate(p.created_at)}</CardDescription>
                  </div>
                  <JobStatusBadge job={job} />
                </CardHeader>
                <CardContent className="relative z-10 mt-auto flex items-center gap-2 px-4">
                  {running ? (
                    <Progress value={job.progress} className="flex-1" aria-label={`${p.title} 진행률`} />
                  ) : (
                    <span className="flex-1 text-xs text-muted-foreground">
                      {job?.kind === "rearrange" ? "최근 작업: 다시 편곡" : "최근 작업: 분석 및 편곡"}
                    </span>
                  )}
                  {confirming === p.id ? (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={del.isPending}
                        onClick={() =>
                          del.mutate(p.id, {
                            onSuccess: () => toast.success(`'${p.title}'을(를) 삭제했습니다.`),
                            onError: (e) => toast.error(errorMessage(e)),
                            onSettled: () => setConfirming(null),
                          })
                        }
                      >
                        {del.isPending ? <Loader2Icon className="animate-spin" /> : "삭제"}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                        취소
                      </Button>
                    </div>
                  ) : (
                    <Button size="icon" variant="ghost" aria-label={`${p.title} 삭제`} onClick={() => setConfirming(p.id)}>
                      <Trash2Icon />
                    </Button>
                  )}
                </CardContent>
              </Card>
            </li>
          );
        })}
      </ul>
      {projects.hasNextPage && (
        <Button variant="outline" className="self-center" disabled={projects.isFetchingNextPage} onClick={() => void projects.fetchNextPage()}>
          {projects.isFetchingNextPage && <Loader2Icon className="animate-spin" />}더 보기
        </Button>
      )}
    </div>
  );
}
