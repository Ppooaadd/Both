import { describe, expect, it, vi } from "vitest";

import type { JobEvent } from "@/lib/api/schemas";
import { JobSocket, type ConnectionState } from "./jobSocket";

class FakeSocket {
  static instances: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  open() {
    this.onopen?.();
  }
  send(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) } as MessageEvent);
  }
  close() {
    this.onclose?.();
  }
}

const job = (status: string, progress = 10) => ({
  id: "j1", project_id: "p1", kind: "full", status, stage: "separate", progress, params: {},
  error_code: null, error_message: null, created_at: "t", started_at: null, finished_at: null,
});
const event = (id: number) => ({
  type: "event", job_id: "j1", id, stage: "separate", progress: 20, level: "info", message: `e${id}`, created_at: "t",
});
const flush = () => new Promise((r) => setTimeout(r, 0));

function setup(maxAttempts = 3) {
  FakeSocket.instances = [];
  const states: ConnectionState[] = [];
  const events: JobEvent[] = [];
  const statuses: string[] = [];
  const scheduled: (() => void)[] = [];
  const getTicket = vi.fn().mockResolvedValue("tkt");
  const sock = new JobSocket(
    "j1",
    {
      onConnection: (s) => states.push(s),
      onEvent: (e) => events.push(e),
      onSnapshot: (_j, evs) => events.push(...evs),
      onStatus: (m) => statuses.push(m.status),
    },
    {
      getTicket,
      origin: "ws://api",
      WebSocketImpl: FakeSocket as unknown as typeof WebSocket,
      maxAttempts,
      schedule: (fn) => scheduled.push(fn),
    },
  );
  return { sock, states, events, statuses, scheduled, getTicket };
}

describe("JobSocket", () => {
  it("connects with a ticket and dedupes events across reconnects", async () => {
    const t = setup();
    t.sock.start();
    await flush();
    const ws = FakeSocket.instances[0];
    expect(ws.url).toBe("ws://api/ws/jobs/j1?ticket=tkt&last_event_id=0");
    ws.open();
    const stored = (id: number) => ({ id, stage: "separate", progress: 20, level: "info", message: `e${id}`, created_at: "t" });
    ws.send({ type: "snapshot", job: job("running"), events: [stored(1), stored(2)] });
    ws.send(event(3));
    ws.close(); // network drop
    expect(t.states.at(-1)).toBe("reconnecting");
    t.scheduled.shift()!();
    await flush();
    const ws2 = FakeSocket.instances[1];
    expect(ws2.url).toContain("last_event_id=3");
    ws2.open();
    ws2.send(event(3)); // duplicate replay
    ws2.send(event(4));
    expect(t.events.map((e) => e.id)).toEqual([1, 2, 3, 4]);
    expect(t.states).toContain("live");
  });

  it("stops reconnecting after a terminal status", async () => {
    const t = setup();
    t.sock.start();
    await flush();
    const ws = FakeSocket.instances[0];
    ws.open();
    ws.send({ type: "status", job_id: "j1", status: "succeeded", stage: "done", progress: 100 });
    ws.close();
    expect(t.statuses).toEqual(["succeeded"]);
    expect(t.states.at(-1)).toBe("closed");
    expect(t.scheduled).toHaveLength(0);
  });

  it("falls back to polling after repeated failures", async () => {
    const t = setup(2);
    t.getTicket.mockRejectedValue(new Error("offline"));
    t.sock.start();
    await flush();
    t.scheduled.shift()!();
    await flush();
    t.scheduled.shift()!();
    await flush();
    expect(t.states.at(-1)).toBe("polling");
    expect(t.scheduled).toHaveLength(0);
  });

  it("ignores malformed frames", async () => {
    const t = setup();
    t.sock.start();
    await flush();
    const ws = FakeSocket.instances[0];
    ws.onmessage?.({ data: "not json" } as MessageEvent);
    ws.send({ type: "event", id: "x" });
    expect(t.events).toHaveLength(0);
  });
});
