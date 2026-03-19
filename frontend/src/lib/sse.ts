"use client";

import { SSE_EVENT_TYPES } from "@/types/sse";
import type { SseEvent } from "@/types/sse";

type EventHandler = (event: SseEvent) => void;
type StatusHandler = (status: "connecting" | "connected" | "disconnected") => void;

/**
 * UsamiSSE — v2 SSE Client
 *
 * v2 Changes:
 * - Uses last_seq query param instead of last_event_id (更精确)
 * - Supports new event types: phase.change, llm.token, interrupt
 * - Last-Event-ID header still works (browser auto-sends on reconnect)
 */
export class UsamiSSE {
  private es: EventSource | null = null;
  private baseUrl: string;
  private handlers = new Set<EventHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shouldReconnect = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastSeq = 0;

  constructor(url: string) {
    this.baseUrl = url;
  }

  connect(): void {
    this.shouldReconnect = true;
    this.notifyStatus("connecting");

    // Build URL with last_seq for replay on reconnect (v2)
    let url = this.baseUrl;
    if (this.lastSeq > 0) {
      const sep = url.includes("?") ? "&" : "?";
      url = `${url}${sep}last_seq=${this.lastSeq}`;
    }

    const es = new EventSource(url, { withCredentials: true });

    es.onopen = () => {
      this.reconnectDelay = 1000;
      this.notifyStatus("connected");
    };

    es.onerror = () => {
      // EventSource fires error on both connection failure and stream end.
      // Close and reconnect manually for better control over backoff.
      es.close();
      this.es = null;
      this.notifyStatus("disconnected");
      if (this.shouldReconnect) {
        this.scheduleReconnect();
      }
    };

    // Listen to all known named SSE event types
    for (const eventType of SSE_EVENT_TYPES) {
      es.addEventListener(eventType, (e: MessageEvent) => {
        try {
          const rawData = JSON.parse(e.data);

          // Store last event ID/seq for replay (v2: use numeric seq)
          if (e.lastEventId) {
            const seq = parseInt(e.lastEventId, 10);
            if (!isNaN(seq) && seq > this.lastSeq) {
              this.lastSeq = seq;
            }
          }

          // v2: Backend sends { type, data: {...} } — extract from nested data
          const payload = rawData.data || rawData;
          const threadId = payload.thread_id || rawData.thread_id || "";

          const event: SseEvent = {
            type: eventType,
            thread_id: threadId,
            seq: e.lastEventId ? parseInt(e.lastEventId, 10) : undefined,
            ...payload,
          } as SseEvent;

          this.handlers.forEach((h) => h(event));
        } catch {
          // Ignore malformed messages
        }
      });
    }

    this.es = es;
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.es?.close();
    this.es = null;
    this.notifyStatus("disconnected");
  }

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /** Reset last_seq to 0 (for fresh connection without replay) */
  resetSeq(): void {
    this.lastSeq = 0;
  }

  /** Get current last received seq */
  getLastSeq(): number {
    return this.lastSeq;
  }

  private notifyStatus(status: "connecting" | "connected" | "disconnected"): void {
    this.statusHandlers.forEach((h) => h(status));
  }

  private scheduleReconnect(): void {
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }
}
