import { InfoIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { AnalysisSummary as Summary } from "@/lib/api/schemas";
import { formatDuration } from "@/lib/utils";

const ENGINE_LABEL: Record<string, string> = {
  separator: "음원 분리",
  beat_tracker: "비트",
  key_detector: "조성",
  chord_recognizer: "코드",
  "transcriber.melody": "멜로디",
  "transcriber.bass": "베이스",
  "transcriber.harmony": "화성",
};
// Engines that indicate a DSP fallback rather than the ML model.
const FALLBACK = /^(hpss|passthrough|pyin|fixed|chords|template)/;

export function AnalysisSummary({ analysis }: { analysis: Summary }) {
  const s = analysis.summary;
  const degraded = Object.entries(s.engines).filter(([, v]) => FALLBACK.test(v));
  const facts = [
    { k: "조성", v: s.key, hint: `신뢰도 ${Math.round(analysis.key_confidence * 100)}%` },
    { k: "템포", v: `${Math.round(s.tempo_bpm)} BPM` },
    { k: "박자", v: s.time_signature },
    { k: "길이", v: `${formatDuration(s.duration)} · ${s.bars}마디` },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>분석 결과</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {facts.map((f) => (
            <div key={f.k} className="rounded-lg bg-muted/60 px-3 py-2">
              <dt className="text-xs text-muted-foreground">{f.k}</dt>
              <dd className="font-mono text-base font-semibold tabular-nums">{f.v}</dd>
              {f.hint && <dd className="text-[11px] text-muted-foreground">{f.hint}</dd>}
            </div>
          ))}
        </dl>

        {s.top_chords.length > 0 && (
          <div className="grid gap-1.5">
            <p className="text-xs text-muted-foreground">주요 코드 (등장 시간 순위)</p>
            <div className="flex flex-wrap gap-1.5">
              {s.top_chords.map((c) => (
                <Badge key={c.label} variant="outline" className="font-mono">
                  {c.label}
                  <span className="text-muted-foreground">{Math.round(c.seconds)}s</span>
                </Badge>
              ))}
            </div>
          </div>
        )}

        {s.sections.length > 1 && (
          <div className="grid gap-1.5">
            <p className="text-xs text-muted-foreground">구조</p>
            <p className="font-mono text-sm tracking-wider">{s.sections.join(" · ")}</p>
          </div>
        )}

        {degraded.length > 0 && (
          <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
            <InfoIcon className="mt-0.5 size-4 shrink-0 text-warning" />
            <div className="grid gap-1">
              <p>
                일부 단계에 대체 엔진을 사용했습니다. 결과 품질이 낮을 수 있습니다:{" "}
                {degraded.map(([k]) => ENGINE_LABEL[k] ?? k).join(", ")}
              </p>
              <p className="font-mono text-xs text-muted-foreground">
                {degraded.map(([k, v]) => `${ENGINE_LABEL[k] ?? k}=${v}`).join(" · ")}
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
