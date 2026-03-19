"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface Notification {
  id: string;
  type: "task_completed" | "hitl_request" | "task_failed" | "system";
  title: string;
  body: string;
  threadId?: string;
  read: boolean;
  createdAt: number;
}

interface NotificationStore {
  notifications: Notification[];
  unreadCount: number;
  /** Event keys already seen — prevents duplicates on SSE replay */
  seenEventKeys: string[];
  addNotification: (
    n: Omit<Notification, "id" | "read" | "createdAt">,
    eventKey?: string,
  ) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  clearAll: () => void;
}

export const useNotificationStore = create<NotificationStore>()(
  persist(
    (set) => ({
      notifications: [],
      unreadCount: 0,
      seenEventKeys: [],

      addNotification: (n, eventKey) =>
        set((state) => {
          // Deduplicate: skip if this event was already processed
          if (eventKey && state.seenEventKeys.includes(eventKey)) {
            return state;
          }

          const notification: Notification = {
            ...n,
            id: eventKey ?? `notif_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
            read: false,
            createdAt: Date.now(),
          };
          const notifications = [notification, ...state.notifications].slice(0, 100);
          // Keep seenEventKeys bounded (match notification limit)
          const seenEventKeys = eventKey
            ? [...state.seenEventKeys, eventKey].slice(-100)
            : state.seenEventKeys;
          return {
            notifications,
            unreadCount: notifications.filter((x) => !x.read).length,
            seenEventKeys,
          };
        }),

      markRead: (id) =>
        set((state) => {
          const notifications = state.notifications.map((n) =>
            n.id === id ? { ...n, read: true } : n,
          );
          return {
            notifications,
            unreadCount: notifications.filter((x) => !x.read).length,
          };
        }),

      markAllRead: () =>
        set((state) => ({
          notifications: state.notifications.map((n) => ({ ...n, read: true })),
          unreadCount: 0,
        })),

      clearAll: () => set({ notifications: [], unreadCount: 0 }),
    }),
    {
      name: "usami-notifications",
      // Only persist data fields, not actions
      partialize: (state) => ({
        notifications: state.notifications,
        unreadCount: state.unreadCount,
        seenEventKeys: state.seenEventKeys,
      }),
    },
  ),
);
