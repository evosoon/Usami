"use client";

import { create } from "zustand";
import { UsamiWebSocket } from "@/lib/ws";
import { WS_URL } from "@/lib/constants";
import { useThreadStore } from "./thread-store";
import { useAuthStore } from "./auth-store";
import type { WsClientEvent } from "@/types/ws";

type WsStatus = "disconnected" | "connecting" | "connected";

interface WsStore {
  status: WsStatus;
  ws: UsamiWebSocket | null;
  connect: () => void;
  disconnect: () => void;
  send: (event: WsClientEvent) => void;
}

export const useWsStore = create<WsStore>((set, get) => ({
  status: "disconnected",
  ws: null,

  connect: () => {
    // Prevent duplicate connections
    if (get().ws) return;

    const ws = new UsamiWebSocket(WS_URL, () => useAuthStore.getState().accessToken);

    ws.onEvent((event) => {
      if ("thread_id" in event) {
        useThreadStore.getState().appendEvent(event.thread_id, event);
      }
    });

    ws.onStatus((status) => {
      set({ status });
    });

    ws.connect();
    set({ ws, status: "connecting" });
  },

  disconnect: () => {
    get().ws?.disconnect();
    set({ ws: null, status: "disconnected" });
  },

  send: (event) => {
    get().ws?.send(event);
  },
}));
