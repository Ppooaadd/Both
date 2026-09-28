"use client";

import { useEffect, useRef, useState } from "react";
import type { OpenSheetMusicDisplay } from "opensheetmusicdisplay";

import { Skeleton } from "@/components/ui/skeleton";
import { fetchExportUrl } from "@/lib/api/queries";
import { errorMessage } from "@/lib/api/client";

type Props = {
  arrangementId: string;
  bpm: number;
  getTime: () => number;
  playing: boolean;
};

/**
 * Renders the arrangement's MusicXML with OpenSheetMusicDisplay and moves the
 * OSMD cursor with playback. Rendered on white "paper" in both themes so the
 * engraving keeps full contrast.
 */
export function ScoreViewer({ arrangementId, bpm, getTime, playing }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ac = new AbortController();
    let disposed = false;
    // Parent keys this component by arrangement, so state starts at "loading".
    (async () => {
      try {
        const [{ OpenSheetMusicDisplay }, link] = await Promise.all([
          import("opensheetmusicdisplay"),
          fetchExportUrl(arrangementId, "musicxml", ac.signal),
        ]);
        const res = await fetch(link.url, { signal: ac.signal });
        if (!res.ok) throw new Error(`악보 파일을 받을 수 없습니다 (${res.status}).`);
        const xml = await res.text();
        if (disposed || !hostRef.current) return;
        hostRef.current.innerHTML = "";
        const osmd = new OpenSheetMusicDisplay(hostRef.current, {
          autoResize: true,
          backend: "svg",
          drawTitle: true,
          drawComposer: false,
          drawCredits: false,
          drawPartNames: false,
          followCursor: true,
          cursorsOptions: [{ type: 0, color: "#d23b2b", alpha: 0.35, follow: true }],
        });
        await osmd.load(xml);
        if (disposed) return;
        osmd.render();
        osmd.cursor.show();
        osmdRef.current = osmd;
        setState("ready");
      } catch (e) {
        if (disposed || (e instanceof Error && e.name === "AbortError")) return;
        setError(e instanceof Error && !("status" in e) ? e.message : errorMessage(e));
        setState("error");
      }
    })();
    return () => {
      disposed = true;
      ac.abort();
      osmdRef.current = null;
    };
  }, [arrangementId]);

  // Cursor follows playback: advance while the next timestamp is not in the future.
  useEffect(() => {
    if (!playing || state !== "ready") return;
    let raf = 0;
    let last = -1;
    const step = () => {
      const osmd = osmdRef.current;
      if (osmd) {
        const quarters = (getTime() * bpm) / 60;
        if (quarters < last) osmd.cursor.reset();
        last = quarters;
        const cursor = osmd.cursor;
        const whole = () => cursor.Iterator.currentTimeStamp.RealValue * 4;
        if (whole() > quarters + 0.01) cursor.reset();
        let guard = 0;
        while (!cursor.Iterator.EndReached && guard++ < 64) {
          const clone = cursor.Iterator.clone();
          clone.moveToNext();
          if (clone.EndReached || clone.currentTimeStamp.RealValue * 4 > quarters + 0.01) break;
          cursor.next();
        }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, state, bpm, getTime]);

  return (
    <div className="relative min-h-[320px] overflow-auto rounded-lg border bg-white text-black">
      {/* The host stays in layout while loading: OSMD measures its width to lay out systems. */}
      <div ref={hostRef} aria-label="악보 미리보기" className="p-2" />
      {state === "loading" && (
        <div className="absolute inset-0 space-y-3 bg-white p-6">
          <Skeleton className="mx-auto h-6 w-48 bg-slate-200" />
          <Skeleton className="h-24 w-full bg-slate-100" />
          <Skeleton className="h-24 w-full bg-slate-100" />
        </div>
      )}
      {state === "error" && (
        <p className="absolute inset-0 bg-white p-6 text-sm text-red-700">
          {error} PDF 악보는 다운로드 메뉴에서 받을 수 있습니다.
        </p>
      )}
    </div>
  );
}
