import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { LogEntry, LogResponse } from "../types";

export class LogBuffer {
  entries: LogEntry[] = [];
  seq = 0;
  boot = "";
  ingest(list: LogEntry[]) {
    let added = 0;
    for (const entry of list) {
      if (entry.boot !== this.boot) {
        this.entries = [];
        this.seq = 0;
        this.boot = entry.boot;
      }
      if (entry.seq <= this.seq) continue;
      this.seq = entry.seq;
      this.entries.push(entry);
      added++;
    }
    this.entries = this.entries.slice(-2000);
    return added;
  }
}
export function useLogs() {
  const buffer = useRef(new LogBuffer());
  const [entries, setEntries] = useState<LogEntry[]>([]),
    [paused, setPaused] = useState(false);
  const pause = useRef(paused);
  pause.current = paused;
  const resume = useRef<() => void>(() => {});
  const previouslyPaused = useRef(false);
  useEffect(() => {
    let disposed = false,
      source: EventSource | null = null,
      timer: ReturnType<typeof setTimeout> | undefined,
      fallback: ReturnType<typeof setTimeout> | undefined;
    const controllers = new Set<AbortController>();
    const commit = (list: LogEntry[]) => {
      if (disposed || pause.current) return;
      buffer.current.ingest(list);
      setEntries([...buffer.current.entries]);
    };
    async function recent(initial = false) {
      const controller = new AbortController();
      controllers.add(controller);
      try {
        const data = await api.get<LogResponse>(
          "/logs/recent",
          initial ? { limit: 500 } : { after: buffer.current.seq, limit: 500 },
          controller.signal,
        );
        commit(data.entries || []);
      } catch {
        /* Retry on stream reconnect or polling. */
      } finally {
        controllers.delete(controller);
      }
    }
    async function poll() {
      if (disposed) return;
      if (!pause.current) await recent();
      if (!disposed) timer = setTimeout(() => void poll(), 2000);
    }
    function startPolling() {
      source?.close();
      source = null;
      clearTimeout(fallback);
      if (!disposed) void poll();
    }
    function startSse() {
      if (disposed) return;
      if (typeof EventSource === "undefined") {
        startPolling();
        return;
      }
      source = new EventSource(`/api/logs/stream?after=${buffer.current.seq}`);
      source.onopen = () => {
        clearTimeout(fallback);
        fallback = undefined;
      };
      source.onmessage = (event) => {
        try {
          commit([JSON.parse(event.data) as LogEntry]);
        } catch {
          /* Ignore malformed frames. */
        }
      };
      source.onerror = () => {
        if (!source || disposed) return;
        if (source.readyState === EventSource.CLOSED) {
          startPolling();
          return;
        }
        if (!fallback) fallback = setTimeout(startPolling, 3000);
      };
    }
    resume.current = () => void recent();
    // Defer startup to avoid an extra stream in StrictMode's effect probe.
    queueMicrotask(() => {
      if (!disposed) void recent(true).finally(startSse);
    });
    return () => {
      disposed = true;
      source?.close();
      clearTimeout(timer);
      clearTimeout(fallback);
      controllers.forEach((c) => c.abort());
      resume.current = () => {};
    };
  }, []);
  useEffect(() => {
    if (previouslyPaused.current && !paused) resume.current();
    previouslyPaused.current = paused;
  }, [paused]);
  return {
    entries,
    paused,
    setPaused,
    clearLogs: () => {
      buffer.current.entries = [];
      setEntries([]);
    },
  };
}
