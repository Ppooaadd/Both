import { Badge } from "@/components/ui/badge";
import type { Job } from "@/lib/api/schemas";
import { STAGE_LABEL } from "@/lib/music";

export function JobStatusBadge({ job }: { job: Job | null }) {
  if (!job) return <Badge variant="secondary">대기</Badge>;
  switch (job.status) {
    case "succeeded":
      return <Badge variant="success">완료</Badge>;
    case "failed":
      return <Badge variant="destructive">실패</Badge>;
    case "canceled":
      return <Badge variant="secondary">취소됨</Badge>;
    default:
      return (
        <Badge variant="warning">
          {STAGE_LABEL[job.stage] ?? job.stage} {job.progress}%
        </Badge>
      );
  }
}
