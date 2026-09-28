"use client";

import { PauseIcon, PlayIcon, SkipBackIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { formatDuration } from "@/lib/utils";
import type { AudioClock } from "./useAudioClock";

const RATES = [0.5, 0.75, 1, 1.25];

export function TransportBar({ clock, bpm }: { clock: AudioClock; bpm: number }) {
  const disabled = !clock.ready;
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1">
        <Button size="icon" variant="ghost" aria-label="처음으로" disabled={disabled} onClick={() => clock.seek(0)}>
          <SkipBackIcon />
        </Button>
        <Button
          size="icon"
          aria-label={clock.playing ? "일시정지" : "재생"}
          disabled={disabled}
          onClick={clock.toggle}
        >
          {clock.playing ? <PauseIcon /> : <PlayIcon />}
        </Button>
      </div>
      <Slider
        aria-label="재생 위치"
        className="min-w-[140px] flex-1"
        min={0}
        max={Math.max(clock.duration, 0.1)}
        step={0.1}
        value={[Math.min(clock.time, clock.duration || clock.time)]}
        onValueChange={([v]) => clock.seek(v)}
        disabled={disabled}
      />
      <span className="w-[92px] text-right font-mono text-xs tabular-nums text-muted-foreground">
        {formatDuration(clock.time)} / {formatDuration(clock.duration)}
      </span>
      <Select value={String(clock.rate)} onValueChange={(v) => clock.setRate(Number(v))} disabled={disabled}>
        <SelectTrigger className="h-8 w-[128px] whitespace-nowrap text-xs" aria-label="재생 속도">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {RATES.map((r) => (
            <SelectItem key={r} value={String(r)}>
              {r}× · {Math.round(bpm * r)} BPM
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {clock.error && <p className="w-full text-xs text-destructive">{clock.error}</p>}
    </div>
  );
}
