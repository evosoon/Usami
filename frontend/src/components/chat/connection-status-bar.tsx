"use client";

import { useTranslations } from "next-intl";
import { useSseStore } from "@/stores/sse-store";

export function ConnectionStatusBar() {
  const status = useSseStore((s) => s.status);
  const t = useTranslations("connection");

  if (status === "connected") return null;

  const isConnecting = status === "connecting";

  return (
    <div
      className={`flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-medium ${
        isConnecting
          ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-200"
          : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200"
      }`}
    >
      <span
        className={`size-2 rounded-full ${
          isConnecting ? "animate-pulse bg-yellow-500" : "bg-red-500"
        }`}
      />
      {isConnecting ? t("connecting") : t("disconnected")}
    </div>
  );
}
