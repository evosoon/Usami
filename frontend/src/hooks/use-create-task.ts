"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useThreadStore } from "@/stores/thread-store";

export function useCreateTask() {
  const queryClient = useQueryClient();
  const createThread = useThreadStore((s) => s.createThread);

  return useMutation({
    mutationFn: (intent: string) => api.createTask(intent),
    onSuccess: (data, intent) => {
      createThread(data.thread_id, intent);
      queryClient.invalidateQueries({ queryKey: ["task", data.thread_id] });
    },
  });
}
