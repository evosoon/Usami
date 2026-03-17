"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useThreadStore } from "@/stores/thread-store";

export function useCreateTask() {
  const queryClient = useQueryClient();
  const createThread = useThreadStore((s) => s.createThread);

  return useMutation({
    mutationFn: ({ intent, threadId }: { intent: string; threadId?: string }) =>
      api.createTask(intent, {}, threadId),
    onSuccess: (data, { intent, threadId }) => {
      if (!threadId) {
        createThread(data.thread_id, intent);
      }
      queryClient.invalidateQueries({ queryKey: ["task", data.thread_id] });
    },
  });
}
