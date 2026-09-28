"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type AudioClock = {
  ready: boolean;
  playing: boolean;
  duration: number;
  /** Coarse time for display (updated ~8x/s); use getTime() for animation. */
  time: number;
  error: string | null;
  getTime: () => number;
  play: () => Promise<void>;
  pause: () => void;
  toggle: () => void;
  seek: (seconds: number) => void;
  setRate: (rate: number) => void;
  rate: number;
};

/**
 * Wraps one HTMLAudioElement for the rendered piano audio. The element is the
 * single clock for the piano roll and score cursor, so they never drift apart.
 */
export function useAudioClock(src: string | null): AudioClock {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [rate, setRateState] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [loadedSrc, setLoadedSrc] = useState(src);
  if (loadedSrc !== src) {
    // New source: reset derived state during render (no effect round-trip).
    setLoadedSrc(src);
    setReady(false);
    setPlaying(false);
    setTime(0);
    setDuration(0);
    setError(null);
  }

  useEffect(() => {
    if (!src) return;
    const audio = new Audio();
    audio.preload = "auto";
    audio.src = src;
    audioRef.current = audio;
    let reloads = 0;
    const onReady = () => {
      setReady(true);
      setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onTime = () => setTime(audio.currentTime);
    const onError = () => {
      // `src` is a same-origin API path that redirects to a presigned URL valid
      // for 5 minutes; later range requests can fail. Reload for a fresh URL.
      if (reloads < 2) {
        reloads += 1;
        const at = audio.currentTime;
        const wasPlaying = !audio.paused;
        audio.src = `${src}${src.includes("?") ? "&" : "?"}r=${Date.now()}`;
        audio.addEventListener(
          "loadedmetadata",
          () => {
            audio.currentTime = at;
            if (wasPlaying) void audio.play().catch(() => undefined);
          },
          { once: true },
        );
        return;
      }
      setError("오디오를 불러오지 못했습니다.");
    };
    audio.addEventListener("loadedmetadata", onReady);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onPause);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("error", onError);
    return () => {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      audio.removeEventListener("loadedmetadata", onReady);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onPause);
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("error", onError);
      if (audioRef.current === audio) audioRef.current = null;
    };
  }, [src]);

  const getTime = useCallback(() => audioRef.current?.currentTime ?? 0, []);
  const play = useCallback(async () => {
    try {
      await audioRef.current?.play();
    } catch {
      setError("브라우저가 재생을 막았습니다. 재생 버튼을 다시 눌러 주세요.");
    }
  }, []);
  const pause = useCallback(() => audioRef.current?.pause(), []);
  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) void a.play().catch(() => setError("재생할 수 없습니다."));
    else a.pause();
  }, []);
  const seek = useCallback((seconds: number) => {
    const a = audioRef.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(seconds, Number.isFinite(a.duration) ? a.duration : seconds));
    setTime(a.currentTime);
  }, []);
  const setRate = useCallback((r: number) => {
    if (audioRef.current) {
      audioRef.current.playbackRate = r;
      audioRef.current.preservesPitch = true;
    }
    setRateState(r);
  }, []);

  return { ready, playing, duration, time, error, getTime, play, pause, toggle, seek, setRate, rate };
}
