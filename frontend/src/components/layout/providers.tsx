"use client";

import { Component, useEffect, useRef, useState, useCallback } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { useSseStore } from "@/stores/sse-store";
import { useThreadStore } from "@/stores/thread-store";
import { useAuthStore } from "@/stores/auth-store";
import { useNotificationStore } from "@/stores/notification-store";
import { HiTLDialog } from "@/components/hitl/hitl-dialog";
import type { HiTLRequest } from "@/types/api";
import type { SseEvent } from "@/types/sse";

// ---------------------------------------------------------------------------
// Error Boundary — prevents uncaught React errors from crashing the whole app
// ---------------------------------------------------------------------------
interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[ErrorBoundary] Uncaught error:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex min-h-screen items-center justify-center p-8">
          <div className="max-w-md space-y-4 text-center">
            <h2 className="text-lg font-semibold">出现了意外错误</h2>
            <p className="text-sm text-muted-foreground">
              {this.state.error?.message ?? "未知错误"}
            </p>
            <button
              className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              重试
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export { ErrorBoundary };

function AuthHydrator() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setUser = useAuthStore((s) => s.setUser);
  const hydratedRef = useRef(false);

  useEffect(() => {
    if (isAuthenticated || hydratedRef.current) return;
    hydratedRef.current = true;

    // On page refresh, restore user profile from cookie via refresh endpoint
    fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" })
      .then((res) => {
        if (!res.ok) return null;
        return res.json();
      })
      .then((data) => {
        if (data?.user) {
          setUser(data.user);
        }
      })
      .catch(() => {
        // Not logged in — middleware will redirect if needed
      });
  }, [isAuthenticated, setUser]);

  return null;
}

function SseConnector() {
  const connect = useSseStore((s) => s.connect);
  const disconnect = useSseStore((s) => s.disconnect);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    if (isAuthenticated) {
      connect();
    } else {
      disconnect();
    }
    return () => disconnect();
  }, [isAuthenticated, connect, disconnect]);

  return null;
}

function HistoryLoader() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadedRef = useRef(false);

  useEffect(() => {
    if (!isAuthenticated || loadedRef.current) return;
    loadedRef.current = true;
    useThreadStore.getState().loadThreads();
  }, [isAuthenticated]);

  return null;
}

function HiTLWatcher() {
  const threads = useThreadStore((s) => s.threads);
  const [currentHitl, setCurrentHitl] = useState<{
    request: HiTLRequest;
    threadId: string;
  } | null>(null);

  // Watch for pending HiTL requests across all threads (v2: pendingInterrupt, Legacy: pendingHitl)
  useEffect(() => {
    for (const [threadId, thread] of threads) {
      // v2: interrupt payload
      if (thread.pendingInterrupt && !currentHitl) {
        const interrupt = thread.pendingInterrupt;
        setCurrentHitl({
          request: {
            request_id: `interrupt-${threadId}-${Date.now()}`,
            hitl_type: interrupt.type as "approval" | "clarification" | "conflict" | "error" | "plan_review",
            title: interrupt.message || "需要确认",
            description: interrupt.message,
            context: {
              raw_output: interrupt.raw_output,
              errors: interrupt.errors,
              plan: interrupt.plan,
              failed_tasks: interrupt.failed_tasks,
              failed_details: interrupt.failed_details,
            },
            options: interrupt.options,
          },
          threadId,
        });
        break;
      }
      // Legacy: pendingHitl array
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
        // v2: clear pendingInterrupt
        if (thread.pendingInterrupt) {
          useThreadStore.getState().updateFromRest(currentHitl.threadId, {
            pendingInterrupt: null,
          });
        }
        // Legacy: filter pendingHitl
        if (thread.pendingHitl.length > 0) {
          useThreadStore.getState().updateFromRest(currentHitl.threadId, {
            pendingHitl: thread.pendingHitl.filter(
              (h) => h.request_id !== currentHitl.request.request_id,
            ),
          });
        }
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
  const sse = useSseStore((s) => s.sse);
  const handlerRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!sse) return;

    // Clean up previous handler
    handlerRef.current?.();

    const unsubscribe = sse.onEvent((event: SseEvent) => {
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
            body: event.error ?? "",
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
  }, [sse]);

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
          <ErrorBoundary>
            <AuthHydrator />
            <SseConnector />
            <HistoryLoader />
            <HiTLWatcher />
            <NotificationWatcher />
            {children}
          </ErrorBoundary>
          <Toaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
