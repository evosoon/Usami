"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useThreadStore } from "@/stores/thread-store";

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
    // SSE is the sole update source — no polling needed
    staleTime: Infinity,
  });
}
