"use client";

import { create } from "zustand";

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
  addNotification: (n: Omit<Notification, "id" | "read" | "createdAt">) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  clearAll: () => void;
}

export const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: [],
  unreadCount: 0,

  addNotification: (n) =>
    set((state) => {
      const notification: Notification = {
        ...n,
        id: `notif_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        read: false,
        createdAt: Date.now(),
      };
      const notifications = [notification, ...state.notifications].slice(0, 100);
      return {
        notifications,
        unreadCount: notifications.filter((x) => !x.read).length,
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
}));
