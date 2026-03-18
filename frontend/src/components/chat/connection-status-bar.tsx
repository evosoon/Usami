"use client";

import { useEffect, useState, useRef } from "react";
import { useTranslations } from "next-intl";
import { useSseStore } from "@/stores/sse-store";
import { cn } from "@/lib/utils";

export function ConnectionStatusBar() {
  const status = useSseStore((s) => s.status);
  const t = useTranslations("connection");
  const [showText, setShowText] = useState(false);
  const prevStatus = useRef(status);

  // Show text briefly when status changes
  useEffect(() => {
    if (prevStatus.current !== status) {
      prevStatus.current = status;
      setShowText(true);
      const timer = setTimeout(() => setShowText(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [status]);

  return (
    <div className="flex items-center gap-2 px-4 py-2 bg-white/85 dark:bg-zinc-900/85 backdrop-blur-xl rounded-t-2xl">
      <span
        className={cn(
          "size-2 rounded-full transition-colors",
          status === "connected" && "bg-green-500",
          status === "connecting" && "bg-yellow-500 animate-pulse",
          status === "disconnected" && "bg-red-500"
        )}
      />
      <span
        className={cn(
          "text-xs text-muted-foreground transition-opacity duration-300",
          showText ? "opacity-100" : "opacity-0"
        )}
      >
        {status === "connected" && t("connected")}
        {status === "connecting" && t("connecting")}
        {status === "disconnected" && t("disconnected")}
      </span>
    </div>
  );
}
