"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { z } from "zod";

import { API_BASE, ApiError, api, apiVoid } from "./client";
import {
  ArrangementDetail,
  ArrangementRequest,
  Arrangement,
  Download,
  Job,
  JobEvent,
  ProjectDetail,
  ProjectPage,
  Project,
  Session,
  User,
  type ArrangementParams,
  type ExportFormat,
} from "./schemas";

export const qk = {
  me: ["me"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  job: (id: string) => ["job", id] as const,
  jobEvents: (id: string) => ["job", id, "events"] as const,
  arrangements: (projectId: string) => ["project", projectId, "arrangements"] as const,
  arrangement: (id: string) => ["arrangement", id] as const,
};

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);
export const isTerminal = (status: string | undefined) => status !== undefined && TERMINAL.has(status);

// ------------------------------------------------------------------------ auth
export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: async () => {
      try {
        return await api("/auth/me", User);
      } catch (e) {
        if (e instanceof ApiError && e.isAuth) return null;
        throw e;
      }
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
}

type Credentials = { email: string; password: string };

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Credentials) =>
      api("/auth/login", Session, { method: "POST", body, retryOnAuth: false }),
    onSuccess: (s) => qc.setQueryData(qk.me, s.user),
  });
}

export function useSignup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Credentials & { display_name: string }) =>
      api("/auth/signup", Session, { method: "POST", body, retryOnAuth: false }),
    onSuccess: (s) => qc.setQueryData(qk.me, s.user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiVoid("/auth/logout", { method: "POST", retryOnAuth: false }),
    onSettled: () => {
      qc.clear();
      qc.setQueryData(qk.me, null);
    },
  });
}

// -------------------------------------------------------------------- projects
export function useProjects() {
  return useInfiniteQuery({
    queryKey: qk.projects,
    queryFn: ({ pageParam, signal }) =>
      api(`/projects?limit=20${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`, ProjectPage, {
        signal,
      }),
    initialPageParam: "" as string,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: qk.project(id),
    queryFn: ({ signal }) => api(`/projects/${id}`, ProjectDetail, { signal }),
  });
}

export function useRenameProject(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => api(`/projects/${id}`, Project, { method: "PATCH", body: { title } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.project(id) });
      void qc.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiVoid(`/projects/${id}`, { method: "DELETE" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.projects }),
  });
}

// ------------------------------------------------------------------------ jobs
export function useJob(id: string | null | undefined, opts: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: qk.job(id ?? "none"),
    queryFn: ({ signal }) => api(`/jobs/${id}`, Job, { signal }),
    enabled: Boolean(id),
    refetchInterval: (q) => (opts.poll && !isTerminal(q.state.data?.status) ? 2000 : false),
  });
}

export function fetchJobEvents(id: string, afterId: number, signal?: AbortSignal) {
  return api(`/jobs/${id}/events?after_id=${afterId}`, z.array(JobEvent), { signal });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/jobs/${id}/cancel`, Job, { method: "POST" }),
    onSuccess: (job) => {
      qc.setQueryData(qk.job(job.id), job);
      void qc.invalidateQueries({ queryKey: qk.project(job.project_id) });
    },
  });
}

// ---------------------------------------------------------------- arrangements
export function useArrangements(projectId: string, enabled = true) {
  return useQuery({
    queryKey: qk.arrangements(projectId),
    queryFn: ({ signal }) => api(`/projects/${projectId}/arrangements`, z.array(Arrangement), { signal }),
    enabled,
  });
}

export function useArrangement(id: string | null | undefined) {
  return useQuery({
    queryKey: qk.arrangement(id ?? "none"),
    queryFn: ({ signal }) => api(`/arrangements/${id}?include_score=true`, ArrangementDetail, { signal }),
    enabled: Boolean(id),
    staleTime: Infinity, // an arrangement never changes once ready
  });
}

export function useRequestArrangement(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: ArrangementParams) =>
      api(`/projects/${projectId}/arrangements`, ArrangementRequest, { method: "POST", body: { params } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.arrangements(projectId) }),
  });
}

/** Same-origin URL; the API answers 302 to a short-lived presigned download. */
export function exportHref(arrangementId: string, format: ExportFormat): string {
  return `${API_BASE}/arrangements/${arrangementId}/exports/${format}`;
}

export function fetchExportUrl(arrangementId: string, format: ExportFormat, signal?: AbortSignal) {
  return api(`/arrangements/${arrangementId}/exports/${format}?redirect=false`, Download, { signal });
}

/** Refresh everything a finished job may have changed. */
export function invalidateAfterJob(qc: QueryClient, projectId: string): void {
  void qc.invalidateQueries({ queryKey: qk.project(projectId) });
  void qc.invalidateQueries({ queryKey: qk.arrangements(projectId) });
  void qc.invalidateQueries({ queryKey: qk.projects });
}
