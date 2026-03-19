"use client";

import { useEffect, useRef, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useSseStore } from "@/stores/sse-store";
import { useThreadStore } from "@/stores/thread-store";
import { cn } from "@/lib/utils";

export function ConnectionStatusBar() {
  const status = useSseStore((s) => s.status);
  const activeThread = useThreadStore((s) => s.getActiveThread());
  const t = useTranslations("connection");
  const textRef = useRef<HTMLSpanElement>(null);
  const prevStatusRef = useRef(status);
  const isInitialMount = useRef(true);

  const showTextBriefly = useCallback(() => {
    if (textRef.current) {
      textRef.current.style.opacity = "1";
      setTimeout(() => {
        if (textRef.current) {
          textRef.current.style.opacity = "0";
        }
      }, 3000);
    }
  }, []);

  // Show text briefly when status changes (skip initial mount)
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      prevStatusRef.current = status;
      return;
    }

    if (prevStatusRef.current !== status) {
      prevStatusRef.current = status;
      showTextBriefly();
    }
  }, [status, showTextBriefly]);

  return (
    <div className="relative flex items-center gap-1.5 px-4 py-2 bg-white/85 dark:bg-zinc-900/85 backdrop-blur-xl rounded-t-2xl">
      <span
        className={cn(
          "size-2 shrink-0 rounded-full transition-colors",
          status === "connected" && "bg-green-500",
          status === "connecting" && "bg-yellow-500 animate-pulse",
          status === "disconnected" && "bg-red-500"
        )}
      />
      <span
        ref={textRef}
        className="absolute left-8 text-xs text-muted-foreground transition-opacity duration-300 opacity-0"
      >
        {status === "connected" && t("connected")}
        {status === "connecting" && t("connecting")}
        {status === "disconnected" && t("disconnected")}
      </span>
      {activeThread && (
        <span className="text-sm font-medium truncate">
          {activeThread.intent}
        </span>
      )}
    </div>
  );
}
