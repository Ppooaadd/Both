"use client";

import { useMemo, useState } from "react";
import { Loader2Icon, RotateCcwIcon, WandSparklesIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ArrangementParams, difficulties, type Difficulty } from "@/lib/api/schemas";
import { DIFFICULTY_HINT, DIFFICULTY_LABEL, GRID_LABEL, MELODY_SOURCE_LABEL, NOTE_NAMES, PATTERN_LABEL, noteName } from "@/lib/music";

const RANGE_OPTIONS = Array.from({ length: 108 - 21 + 1 }, (_, i) => 21 + i).filter((p) => p % 12 === 0 || p === 21 || p === 108);

export function paramsEqual(a: ArrangementParams, b: ArrangementParams): boolean {
  return JSON.stringify(ArrangementParams.parse(a)) === JSON.stringify(ArrangementParams.parse(b));
}

export function describeTranspose(semitones: number, tonic: number | null): string {
  if (semitones === 0) return "원래 조";
  const sign = semitones > 0 ? "+" : "−";
  const target = tonic === null ? "" : ` → ${NOTE_NAMES[(((tonic + semitones) % 12) + 12) % 12]}`;
  return `${sign}${Math.abs(semitones)}반음${target}`;
}

type Props = {
  initial: ArrangementParams;
  keyTonic: number | null;
  pending: boolean;
  onSubmit: (params: ArrangementParams) => void;
};

export function ParameterPanel({ initial, keyTonic, pending, onSubmit }: Props) {
  // Parent remounts this form (key) when the selected arrangement changes.
  const [p, setP] = useState<ArrangementParams>(initial);
  const dirty = useMemo(() => !paramsEqual(p, initial), [p, initial]);
  const set = <K extends keyof ArrangementParams>(k: K, v: ArrangementParams[K]) => setP((old) => ({ ...old, [k]: v }));
  const rangeOk = p.range_high - p.range_low >= 24;

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (rangeOk) onSubmit(ArrangementParams.parse(p));
      }}
    >
      <div className="grid gap-2">
        <Label>난이도</Label>
        <Tabs value={p.difficulty} onValueChange={(v) => set("difficulty", v as Difficulty)}>
          <TabsList className="w-full">
            {difficulties.map((d) => (
              <TabsTrigger key={d} value={d}>
                {DIFFICULTY_LABEL[d]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <p className="text-xs text-muted-foreground">{DIFFICULTY_HINT[p.difficulty]}</p>
      </div>

      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="transpose">조 옮기기</Label>
          <span className="font-mono text-xs text-muted-foreground">{describeTranspose(p.transpose, keyTonic)}</span>
        </div>
        <Slider id="transpose" aria-label="조 옮기기" min={-6} max={6} step={1} value={[p.transpose]} onValueChange={([v]) => set("transpose", v)} />
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="simplify" className="font-normal text-muted-foreground">
            쉬운 조(C·G·F / Am·Dm·Em)로 자동 이조
          </Label>
          <Switch id="simplify" checked={p.simplify_key} onCheckedChange={(v) => set("simplify_key", v)} />
        </div>
      </div>

      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="tempo">템포</Label>
          <span className="font-mono text-xs text-muted-foreground">{Math.round(p.tempo_scale * 100)}%</span>
        </div>
        <Slider id="tempo" aria-label="템포 배율" min={0.5} max={1.5} step={0.05} value={[p.tempo_scale]} onValueChange={([v]) => set("tempo_scale", v)} />
      </div>

      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="density">음 밀도</Label>
          <span className="font-mono text-xs text-muted-foreground">{p.density < 0.34 ? "가볍게" : p.density < 0.67 ? "보통" : "풍성하게"}</span>
        </div>
        <Slider id="density" aria-label="음 밀도" min={0} max={1} step={0.05} value={[p.density]} onValueChange={([v]) => set("density", v)} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="grid gap-2">
          <Label>왼손 반주</Label>
          <Select value={p.left_hand_pattern} onValueChange={(v) => set("left_hand_pattern", v as ArrangementParams["left_hand_pattern"])}>
            <SelectTrigger aria-label="왼손 반주 패턴">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(PATTERN_LABEL).map(([k, label]) => (
                <SelectItem key={k} value={k}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label>리듬 단위</Label>
          <Select value={p.quantize_grid} onValueChange={(v) => set("quantize_grid", v as ArrangementParams["quantize_grid"])}>
            <SelectTrigger aria-label="리듬 단위">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(GRID_LABEL).map(([k, label]) => (
                <SelectItem key={k} value={k}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label>멜로디 출처</Label>
          <Select value={p.melody_source} onValueChange={(v) => set("melody_source", v as ArrangementParams["melody_source"])}>
            <SelectTrigger aria-label="멜로디 출처">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(MELODY_SOURCE_LABEL).map(([k, label]) => (
                <SelectItem key={k} value={k}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label>음역</Label>
          <div className="flex items-center gap-1">
            <Select value={String(p.range_low)} onValueChange={(v) => set("range_low", Number(v))}>
              <SelectTrigger aria-label="가장 낮은 음" className="px-2 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RANGE_OPTIONS.filter((x) => x < 96).map((x) => (
                  <SelectItem key={x} value={String(x)}>
                    {noteName(x)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-muted-foreground">–</span>
            <Select value={String(p.range_high)} onValueChange={(v) => set("range_high", Number(v))}>
              <SelectTrigger aria-label="가장 높은 음" className="px-2 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RANGE_OPTIONS.filter((x) => x > 48).map((x) => (
                  <SelectItem key={x} value={String(x)}>
                    {noteName(x)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
      {!rangeOk && <p className="text-xs text-destructive">음역은 두 옥타브 이상이어야 합니다.</p>}

      <div className="flex items-center justify-between gap-3">
        <Label htmlFor="intro" className="font-normal">
          멜로디 없는 전주·후주 포함
        </Label>
        <Switch id="intro" checked={p.include_intro_outro} onCheckedChange={(v) => set("include_intro_outro", v)} />
      </div>

      <div className="flex gap-2">
        <Button type="submit" className="flex-1" disabled={!dirty || !rangeOk || pending}>
          {pending ? <Loader2Icon className="animate-spin" /> : <WandSparklesIcon />}
          이 설정으로 다시 편곡
        </Button>
        <Button type="button" variant="outline" size="icon" aria-label="현재 편곡 설정으로 되돌리기" disabled={!dirty || pending} onClick={() => setP(initial)}>
          <RotateCcwIcon />
        </Button>
      </div>
    </form>
  );
}
