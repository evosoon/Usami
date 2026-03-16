"use client";

import { useTranslations } from "next-intl";
import { useWsStore } from "@/stores/ws-store";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

export function WsStatusBadge() {
  const status = useWsStore((s) => s.status);
  const t = useTranslations("ws");

  // Don't clutter UI when connected
  if (status === "connected") return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex items-center">
          {status === "disconnected" && (
            <span className="size-2 rounded-full bg-red-500" />
          )}
          {status === "connecting" && (
            <span className="size-2 animate-pulse rounded-full bg-yellow-500" />
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {status === "disconnected" ? t("disconnected") : t("connecting")}
      </TooltipContent>
    </Tooltip>
  );
}
