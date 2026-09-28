/**
 * Job progress over WebSocket with ticket auth, resumable reconnects and a
 * polling fallback. Framework-agnostic so it can be unit-tested with a fake socket.
 *
 * Lifecycle: connecting -> live -> (reconnecting -> live)* -> closed
 *            after `maxAttempts` failed connects in a row -> polling
 */
import { WsMessage, type Job, type JobEvent } from "@/lib/api/schemas";

export type ConnectionState = "connecting" | "live" | "reconnecting" | "polling" | "closed";
type StatusMsg = Extract<WsMessage, { type: "status" }>;
type ProgressMsg = Extract<WsMessage, { type: "progress" }>;

export type JobSocketHandlers = {
  onSnapshot?: (job: Job, events: JobEvent[]) => void;
  onProgress?: (msg: ProgressMsg) => void;
  onEvent?: (event: JobEvent) => void;
  onStatus?: (msg: StatusMsg) => void;
  onConnection?: (state: ConnectionState) => void;
};

export type JobSocketDeps = {
  getTicket: (jobId: string) => Promise<string>;
  origin: string; // ws(s)://host[:port]
  WebSocketImpl?: typeof WebSocket;
  maxAttempts?: number;
  baseDelayMs?: number;
  schedule?: (fn: () => void, ms: number) => unknown;
};

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);

export function defaultWsOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_WS_ORIGIN;
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

export class JobSocket {
  private ws: WebSocket | null = null;
  private lastEventId = 0;
  private attempts = 0;
  private stopped = false;
  private finished = false;
  private readonly WS: typeof WebSocket;
  private readonly maxAttempts: number;
  private readonly baseDelay: number;
  private readonly schedule: (fn: () => void, ms: number) => unknown;

  constructor(
    private readonly jobId: string,
    private readonly handlers: JobSocketHandlers,
    private readonly deps: JobSocketDeps,
  ) {
    this.WS = deps.WebSocketImpl ?? WebSocket;
    this.maxAttempts = deps.maxAttempts ?? 5;
    this.baseDelay = deps.baseDelayMs ?? 1000;
    this.schedule = deps.schedule ?? ((fn, ms) => setTimeout(fn, ms));
  }

  start(): void {
    this.handlers.onConnection?.("connecting");
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close(1000);
    this.ws = null;
  }

  private async connect(): Promise<void> {
    if (this.stopped || this.finished) return;
    let ticket: string;
    try {
      ticket = await this.deps.getTicket(this.jobId);
    } catch {
      this.retry();
      return;
    }
    if (this.stopped) return;
    const url = `${this.deps.origin}/ws/jobs/${this.jobId}?ticket=${encodeURIComponent(ticket)}&last_event_id=${this.lastEventId}`;
    const ws = new this.WS(url);
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      this.handlers.onConnection?.("live");
    };
    ws.onmessage = (ev: MessageEvent) => this.handle(ev.data);
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.stopped || this.finished) {
        this.handlers.onConnection?.("closed");
        return;
      }
      this.retry();
    };
    ws.onerror = () => {
      // onclose follows; reconnect logic lives there.
    };
  }

  private retry(): void {
    if (this.stopped || this.finished) return;
    this.attempts += 1;
    if (this.attempts > this.maxAttempts) {
      this.handlers.onConnection?.("polling");
      return;
    }
    this.handlers.onConnection?.("reconnecting");
    const delay = Math.min(this.baseDelay * 2 ** (this.attempts - 1), 15_000);
    const jitter = delay * 0.2 * Math.random();
    this.schedule(() => void this.connect(), delay + jitter);
  }

  private handle(raw: unknown): void {
    let data: unknown;
    try {
      data = JSON.parse(String(raw));
    } catch {
      return;
    }
    const parsed = WsMessage.safeParse(data);
    if (!parsed.success) return;
    const msg = parsed.data;
    switch (msg.type) {
      case "snapshot": {
        for (const e of msg.events) this.lastEventId = Math.max(this.lastEventId, e.id);
        this.handlers.onSnapshot?.(msg.job, msg.events);
        if (TERMINAL.has(msg.job.status)) this.finished = true;
        break;
      }
      case "event": {
        if (msg.id <= this.lastEventId) return; // duplicate after a reconnect
        this.lastEventId = msg.id;
        this.handlers.onEvent?.({
          id: msg.id,
          stage: msg.stage,
          progress: msg.progress,
          level: msg.level,
          message: msg.message,
          created_at: msg.created_at,
        });
        break;
      }
      case "progress":
        this.handlers.onProgress?.(msg);
        break;
      case "status":
        if (TERMINAL.has(msg.status)) this.finished = true;
        this.handlers.onStatus?.(msg);
        break;
      case "ping":
        break;
    }
  }
}
