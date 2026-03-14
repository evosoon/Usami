"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import type { HiTLResolveRequest } from "@/types/api";

export function useResolveHitl(threadId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: HiTLResolveRequest) => api.resolveHitl(threadId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["task", threadId] });
    },
  });
}
