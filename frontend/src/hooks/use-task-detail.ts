"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useThreadStore } from "@/stores/thread-store";
import type { Phase } from "@/stores/thread-store";

export function useTaskDetail(threadId: string | null) {
  const updateFromRest = useThreadStore((s) => s.updateFromRest);

  return useQuery({
    queryKey: ["task", threadId],
    queryFn: async () => {
      const data = await api.getTask(threadId!);
      // Sync REST data into thread store
      updateFromRest(threadId!, {
        taskPlan: data.task_plan,
        pendingHitl: data.hitl_pending,
        result: data.result,
      });
      return data;
    },
    enabled: !!threadId,
    // Safety-net: slow poll during active phases only.
    // Primary updates still come from WS in real-time.
    // On WS reconnect, ws-store invalidates this query to catch up.
    refetchInterval: () => {
      const thread = useThreadStore.getState().threads.get(threadId ?? "");
      if (!thread) return false;
      const activePhases: Phase[] = ["planning", "planned", "executing", "hitl_waiting"];
      return activePhases.includes(thread.phase) ? 10_000 : false;
    },
  });
}
