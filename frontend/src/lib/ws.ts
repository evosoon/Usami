"use client";

import type { WsServerEvent, WsClientEvent } from "@/types/ws";

type EventHandler = (event: WsServerEvent) => void;
type StatusHandler = (status: "connecting" | "connected" | "disconnected") => void;

/** Auth failure close code sent by backend */
const WS_AUTH_FAILED = 4001;

export class UsamiWebSocket {
  private ws: WebSocket | null = null;
  private clientId: string;
  private baseUrl: string;
  private handlers = new Set<EventHandler>();
  private statusHandlers = new Set<StatusHandler>();
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shouldReconnect = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private getToken: (() => string | null) | null = null;
  private authFailedHandlers = new Set<() => void>();

  constructor(url: string, getToken?: () => string | null) {
    let id = sessionStorage.getItem("usami_client_id");
    if (!id) {
      id = `client_${crypto.randomUUID().slice(0, 12)}`;
      sessionStorage.setItem("usami_client_id", id);
    }
    this.clientId = id;
    this.baseUrl = `${url}/${this.clientId}`;
    this.getToken = getToken ?? null;
  }

  /** Build WS URL with fresh token on every call */
  private buildUrl(): string {
    const token = this.getToken?.();
    if (token) {
      return `${this.baseUrl}?token=${encodeURIComponent(token)}`;
    }
    return this.baseUrl;
  }

  connect(): void {
    this.shouldReconnect = true;
    this.notifyStatus("connecting");

    // Build URL with fresh token each connect attempt
    const ws = new WebSocket(this.buildUrl());

    ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.notifyStatus("connected");
    };

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as WsServerEvent;
        this.handlers.forEach((h) => h(event));
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (e) => {
      this.notifyStatus("disconnected");
      // Auth failure: do not auto-reconnect, notify listeners
      if (e.code === WS_AUTH_FAILED) {
        this.shouldReconnect = false;
        this.authFailedHandlers.forEach((h) => h());
        return;
      }
      if (this.shouldReconnect) {
        this.scheduleReconnect();
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    this.ws = ws;
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.notifyStatus("disconnected");
  }

  send(event: WsClientEvent): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(event));
    }
  }

  onEvent(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  onAuthFailed(handler: () => void): () => void {
    this.authFailedHandlers.add(handler);
    return () => this.authFailedHandlers.delete(handler);
  }

  getClientId(): string {
    return this.clientId;
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
