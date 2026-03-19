"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { useSseStore } from "@/stores/sse-store";
import { useThreadStore } from "@/stores/thread-store";
import { timeAgo } from "@/hooks/use-thread-management";
import { cn } from "@/lib/utils";

export function ConnectionStatusBar() {
  const status = useSseStore((s) => s.status);
  const activeThread = useThreadStore((s) => s.getActiveThread());
  const tConn = useTranslations("connection");
  const tPhase = useTranslations("phase");
  const tChat = useTranslations();
  const [hovered, setHovered] = useState(false);
  const [flash, setFlash] = useState(false);
  const prevStatusRef = useRef(status);
  const isInitialMount = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Flash text briefly when status changes (skip initial mount)
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      prevStatusRef.current = status;
      return;
    }
    if (prevStatusRef.current !== status) {
      prevStatusRef.current = status;
      if (timerRef.current) clearTimeout(timerRef.current);
      setFlash(true);
      timerRef.current = setTimeout(() => setFlash(false), 3000);
    }
  }, [status]);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  const showText = hovered || flash;

  const statusLabel =
    status === "connected" ? tConn("connected") :
    status === "connecting" ? tConn("connecting") :
    tConn("disconnected");

  return (
    <div className="flex items-center gap-1.5 px-4 py-2 bg-white/85 dark:bg-zinc-900/85 backdrop-blur-xl rounded-t-2xl">
      {/* Connection dot + hover label */}
      <span
        className="relative shrink-0 p-1.5 -m-1.5 cursor-default"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <span
          className={cn(
            "block size-2 rounded-full transition-colors",
            status === "connected" && "bg-green-500",
            status === "connecting" && "bg-yellow-500 animate-pulse",
            status === "disconnected" && "bg-red-500"
          )}
        />
      </span>
      <span
        className={cn(
          "text-xs text-muted-foreground shrink-0 overflow-hidden whitespace-nowrap transition-all duration-300",
          showText ? "max-w-32 opacity-100" : "max-w-0 opacity-0"
        )}
      >
        {statusLabel}
      </span>

      {/* Thread title + phase & time */}
      {activeThread && (
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-sm font-medium truncate min-w-0">
            {activeThread.intent}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {tPhase(activeThread.phase)} · {timeAgo(activeThread.createdAt, tChat)}
          </span>
        </div>
      )}
    </div>
  );
}
