"use client";

import { SSE_EVENT_TYPES } from "@/types/sse";
import type { SseEvent } from "@/types/sse";

type EventHandler = (event: SseEvent) => void;
type StatusHandler = (status: "connecting" | "connected" | "disconnected") => void;

export class UsamiSSE {
  private es: EventSource | null = null;
  private baseUrl: string;
  private handlers = new Set<EventHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shouldReconnect = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastEventId: string | null = null;

  constructor(url: string) {
    this.baseUrl = url;
  }

  connect(): void {
    this.shouldReconnect = true;
    this.notifyStatus("connecting");

    // Build URL with last_event_id for replay on reconnect
    let url = this.baseUrl;
    if (this.lastEventId) {
      const sep = url.includes("?") ? "&" : "?";
      url = `${url}${sep}last_event_id=${encodeURIComponent(this.lastEventId)}`;
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
          const data = JSON.parse(e.data);
          // Store last event ID for replay
          if (e.lastEventId) {
            this.lastEventId = e.lastEventId;
          }
          const event: SseEvent = { type: eventType, ...data };
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
