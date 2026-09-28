"use client";

import { Loader2Icon, TriangleAlertIcon } from "lucide-react";

import type { Arrangement } from "@/lib/api/schemas";
import { DIFFICULTY_LABEL } from "@/lib/music";
import { cn } from "@/lib/utils";

export function ArrangementPicker({
  items,
  selectedId,
  onSelect,
}: {
  items: Arrangement[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div role="radiogroup" aria-label="편곡 버전" className="flex flex-wrap gap-2">
      {items.map((a) => {
        const selected = a.id === selectedId;
        const disabled = a.status !== "ready";
        return (
          <button
            key={a.id}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onSelect(a.id)}
            className={cn(
              "flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60",
              selected ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:border-primary/50",
            )}
          >
            <span className="font-medium">{DIFFICULTY_LABEL[a.difficulty]}</span>
            <span className={cn("font-mono text-xs", selected ? "text-primary-foreground/80" : "text-muted-foreground")}>
              v{a.revision}
              {a.stats.difficulty_score !== undefined && ` · ${a.stats.difficulty_score.toFixed(1)}`}
            </span>
            {a.status === "pending" && <Loader2Icon className="size-3.5 animate-spin" aria-label="생성 중" />}
            {a.status === "failed" && <TriangleAlertIcon className="size-3.5 text-destructive" aria-label="실패" />}
          </button>
        );
      })}
    </div>
  );
}
