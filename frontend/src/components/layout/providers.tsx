"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { useWsStore } from "@/stores/ws-store";
import { useThreadStore } from "@/stores/thread-store";
import { useAuthStore } from "@/stores/auth-store";
import { useNotificationStore } from "@/stores/notification-store";
import { HiTLDialog } from "@/components/hitl/hitl-dialog";
import type { HiTLRequest } from "@/types/api";
import type { WsServerEvent } from "@/types/ws";

function WsConnector() {
  const connect = useWsStore((s) => s.connect);
  const disconnect = useWsStore((s) => s.disconnect);
  const status = useWsStore((s) => s.status);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const queryClient = useQueryClient();
  const wasConnected = useRef(false);

  // Connect only when authenticated; disconnect on logout
  useEffect(() => {
    if (isAuthenticated) {
      connect();
    } else {
      disconnect();
    }
    return () => disconnect();
  }, [isAuthenticated, connect, disconnect]);

  // On WS reconnect, refetch active thread to catch missed events
  useEffect(() => {
    if (status === "connected") {
      if (wasConnected.current) {
        // This is a reconnect — invalidate active thread query
        const activeId = useThreadStore.getState().activeThreadId;
        if (activeId) {
          queryClient.invalidateQueries({ queryKey: ["task", activeId] });
        }
      }
      wasConnected.current = true;
    }
  }, [status, queryClient]);

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

function NotificationWatcher() {
  const ws = useWsStore((s) => s.ws);
  const handlerRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!ws) return;

    // Clean up previous handler
    handlerRef.current?.();

    const unsubscribe = ws.onEvent((event: WsServerEvent) => {
      const addNotification = useNotificationStore.getState().addNotification;

      switch (event.type) {
        case "task.completed":
          addNotification({
            type: "task_completed",
            title: "taskCompleted",
            body: event.result?.slice(0, 100) ?? "",
            threadId: event.thread_id,
          });
          break;
        case "task.failed":
          addNotification({
            type: "task_failed",
            title: "taskFailed",
            body: event.error,
            threadId: event.thread_id,
          });
          break;
        case "hitl.request":
          addNotification({
            type: "hitl_request",
            title: "hitlRequest",
            body: event.request.title ?? "",
            threadId: event.thread_id,
          });
          break;
      }
    });

    handlerRef.current = unsubscribe;
    return () => unsubscribe();
  }, [ws]);

  return null;
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
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <TooltipProvider>
          <WsConnector />
          <HiTLWatcher />
          <NotificationWatcher />
          {children}
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
