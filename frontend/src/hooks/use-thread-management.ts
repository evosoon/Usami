"use client";

import { useState, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { api } from "@/lib/api-client";
import { useThreadStore } from "@/stores/thread-store";
import type { Phase } from "@/stores/thread-store";

export const PHASE_BADGE_VARIANT: Record<Phase, "default" | "secondary" | "destructive"> = {
  created: "secondary",
  planning: "secondary",
  planned: "secondary",
  executing: "default",
  hitl_waiting: "default",
  aggregating: "default",
  completed: "secondary",
  failed: "destructive",
};

export function timeAgo(ts: number, t: ReturnType<typeof useTranslations>): string {
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return t("chat.timeJustNow");
  if (minutes < 60) return t("chat.timeMinutesAgo", { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("chat.timeHoursAgo", { count: hours });
  return t("chat.timeDaysAgo", { count: Math.floor(hours / 24) });
}

export function useThreadManagement() {
  const threads = useThreadStore((s) => s.threads);
  const activeThreadId = useThreadStore((s) => s.activeThreadId);
  const setActiveThread = useThreadStore((s) => s.setActiveThread);
  const removeThread = useThreadStore((s) => s.removeThread);
  const restoreThread = useThreadStore((s) => s.restoreThread);
  const t = useTranslations();
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const sortedThreads = useMemo(
    () => [...threads.values()].sort((a, b) => b.createdAt - a.createdAt),
    [threads],
  );

  const requestDelete = useCallback((e: React.MouseEvent, threadId: string) => {
    e.stopPropagation();
    setPendingDeleteId(threadId);
  }, []);

  const confirmDelete = useCallback(async () => {
    if (!pendingDeleteId) return;
    const threadId = pendingDeleteId;
    setPendingDeleteId(null);
    const removed = removeThread(threadId);
    try {
      await api.deleteThread(threadId);
    } catch {
      if (removed) {
        restoreThread(removed);
        toast.error(t("chat.deleteFailed"));
      }
    }
  }, [pendingDeleteId, removeThread, restoreThread, t]);

  const cancelDelete = useCallback(() => setPendingDeleteId(null), []);

  const formatTimeAgo = useCallback(
    (ts: number) => timeAgo(ts, t),
    [t],
  );

  return {
    threads,
    sortedThreads,
    activeThreadId,
    setActiveThread,
    pendingDeleteId,
    requestDelete,
    confirmDelete,
    cancelDelete,
    formatTimeAgo,
    t,
  };
}
