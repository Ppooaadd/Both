import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="grid gap-4" aria-busy="true">
      <Skeleton className="h-9 w-72" />
      <Skeleton className="h-[480px] w-full" />
    </div>
  );
}
