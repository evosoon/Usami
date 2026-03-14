"use client";

import { useEffect, useState, useCallback } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { useWsStore } from "@/stores/ws-store";
import { useThreadStore } from "@/stores/thread-store";
import { HiTLDialog } from "@/components/hitl/hitl-dialog";
import type { HiTLRequest } from "@/types/api";

function WsConnector() {
  const connect = useWsStore((s) => s.connect);
  const disconnect = useWsStore((s) => s.disconnect);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return null;
}

function HiTLWatcher() {
  const threads = useThreadStore((s) => s.threads);
  const activeThreadId = useThreadStore((s) => s.activeThreadId);
  const [currentHitl, setCurrentHitl] = useState<{
    request: HiTLRequest;
    threadId: string;
  } | null>(null);

  // Watch for pending HiTL requests across all threads
  useEffect(() => {
    for (const [threadId, thread] of threads) {
      if (thread.pendingHitl.length > 0 && !currentHitl) {
        setCurrentHitl({
          request: thread.pendingHitl[0],
          threadId,
        });
        break;
      }
    }
  }, [threads, currentHitl]);

  const handleClose = useCallback(() => {
    if (currentHitl) {
      // Remove resolved HiTL from thread store
      const thread = useThreadStore.getState().threads.get(currentHitl.threadId);
      if (thread) {
        useThreadStore.getState().updateFromRest(currentHitl.threadId, {
          pendingHitl: thread.pendingHitl.filter(
            (h) => h.request_id !== currentHitl.request.request_id,
          ),
        });
      }
    }
    setCurrentHitl(null);
  }, [currentHitl]);

  if (!currentHitl) return null;

  return (
    <HiTLDialog
      request={currentHitl.request}
      threadId={currentHitl.threadId}
      open={true}
      onClose={handleClose}
    />
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WsConnector />
        <HiTLWatcher />
        {children}
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
