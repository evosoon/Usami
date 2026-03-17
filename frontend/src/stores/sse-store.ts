"use client";

import { create } from "zustand";
import { UsamiSSE } from "@/lib/sse";
import { SSE_URL } from "@/lib/constants";
import { useThreadStore } from "./thread-store";

type SseStatus = "disconnected" | "connecting" | "connected";

interface SseStore {
  status: SseStatus;
  sse: UsamiSSE | null;
  connect: () => void;
  disconnect: () => void;
}

export const useSseStore = create<SseStore>((set, get) => ({
  status: "disconnected",
  sse: null,

  connect: () => {
    // Prevent duplicate connections
    if (get().sse) return;

    const sse = new UsamiSSE(SSE_URL);

    sse.onEvent((event) => {
      if ("thread_id" in event) {
        useThreadStore.getState().appendEvent(event.thread_id, event);
      }
    });

    sse.onStatus((status) => {
      set({ status });
    });

    sse.connect();
    set({ sse, status: "connecting" });
  },

  disconnect: () => {
    get().sse?.disconnect();
    set({ sse: null, status: "disconnected" });
  },
}));
