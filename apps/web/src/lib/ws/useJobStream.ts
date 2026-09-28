"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { invalidateAfterJob, isTerminal, qk, useJob } from "@/lib/api/queries";
import { WsTicket, type Job, type JobEvent } from "@/lib/api/schemas";
import { JobSocket, defaultWsOrigin, type ConnectionState } from "./jobSocket";

export type JobStream = {
  job: Job | undefined;
  events: JobEvent[];
  connection: ConnectionState;
};

async function getTicket(jobId: string): Promise<string> {
  const t = await api("/ws-ticket", WsTicket, { method: "POST", body: { job_id: jobId } });
  return t.ticket;
}

/**
 * Live job state. WebSocket first; polling (`GET /jobs/{id}`) when the socket
 * cannot be established. Invalidates project/arrangement queries on completion.
 */
export function useJobStream(
  jobId: string | null | undefined,
  projectId: string,
  onFinished?: (status: Job["status"]) => void,
): JobStream {
  const qc = useQueryClient();
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [streamFor, setStreamFor] = useState(jobId);
  if (streamFor !== jobId) {
    setStreamFor(jobId);
    setEvents([]);
    setConnection("connecting");
  }
  const polled = useJob(jobId, { poll: connection === "polling" });
  const finishedRef = useRef(false);
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    onFinishedRef.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    if (!jobId) return;
    finishedRef.current = false;
    const merge = (incoming: JobEvent[]) =>
      setEvents((prev) => {
        const seen = new Set(prev.map((e) => e.id));
        return [...prev, ...incoming.filter((e) => !seen.has(e.id))].sort((a, b) => a.id - b.id);
      });
    const patchJob = (patch: Partial<Job>) =>
      qc.setQueryData<Job>(qk.job(jobId), (old) => (old ? { ...old, ...patch } : old));
    const finish = (status: Job["status"]) => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      invalidateAfterJob(qc, projectId);
      void qc.invalidateQueries({ queryKey: qk.job(jobId) });
      onFinishedRef.current?.(status);
    };

    const socket = new JobSocket(
      jobId,
      {
        onConnection: setConnection,
        onSnapshot: (job, evs) => {
          qc.setQueryData(qk.job(jobId), job);
          merge(evs);
          if (isTerminal(job.status)) finish(job.status);
        },
        onEvent: (e) => merge([e]),
        onProgress: (m) =>
          patchJob({ stage: m.stage, progress: Math.max(m.progress, qc.getQueryData<Job>(qk.job(jobId))?.progress ?? 0), status: "running" }),
        onStatus: (m) => {
          patchJob({
            status: m.status,
            stage: m.stage,
            progress: m.progress,
            error_code: m.error_code ?? null,
            error_message: m.error_message ?? null,
          });
          if (isTerminal(m.status)) finish(m.status);
        },
      },
      { getTicket, origin: defaultWsOrigin() },
    );
    socket.start();
    return () => socket.stop();
  }, [jobId, projectId, qc]);

  // Polling fallback also needs completion handling.
  useEffect(() => {
    const status = polled.data?.status;
    if (connection === "polling" && status && isTerminal(status) && !finishedRef.current) {
      finishedRef.current = true;
      invalidateAfterJob(qc, projectId);
      onFinishedRef.current?.(status);
    }
  }, [connection, polled.data?.status, projectId, qc]);

  return { job: polled.data, events, connection };
}
