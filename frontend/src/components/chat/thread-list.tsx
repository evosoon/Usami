"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useThreadStore } from "@/stores/thread-store";
import type { Phase } from "@/stores/thread-store";

const PHASE_BADGE_VARIANT: Record<Phase, "default" | "secondary" | "destructive"> = {
  created: "secondary",
  planning: "secondary",
  planned: "secondary",
  executing: "default",
  hitl_waiting: "default",
  completed: "secondary",
  failed: "destructive",
};

export function ThreadList() {
  const threads = useThreadStore((s) => s.threads);
  const activeThreadId = useThreadStore((s) => s.activeThreadId);
  const setActiveThread = useThreadStore((s) => s.setActiveThread);
  const t = useTranslations();

  function timeAgo(ts: number): string {
    const diff = Date.now() - ts;
    const minutes = Math.floor(diff / 60_000);
    if (minutes < 1) return t("chat.timeJustNow");
    if (minutes < 60) return t("chat.timeMinutesAgo", { count: minutes });
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return t("chat.timeHoursAgo", { count: hours });
    return t("chat.timeDaysAgo", { count: Math.floor(hours / 24) });
  }

  const sortedThreads = [...threads.values()].sort(
    (a, b) => b.createdAt - a.createdAt,
  );

  return (
    <div className="flex h-full w-64 flex-col border-r">
      <div className="p-3">
        <Button
          variant="outline"
          className="w-full"
          onClick={() => setActiveThread(null)}
        >
          + {t("nav.newThread")}
        </Button>
      </div>
      <Separator />
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {sortedThreads.map((thread) => (
            <button
              key={thread.threadId}
              onClick={() => setActiveThread(thread.threadId)}
              className={cn(
                "flex w-full flex-col gap-1 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                activeThreadId === thread.threadId && "bg-muted",
              )}
            >
              <span className="truncate font-medium">
                {thread.intent.slice(0, 40)}
                {thread.intent.length > 40 ? "..." : ""}
              </span>
              <span className="flex items-center gap-2">
                <Badge variant={PHASE_BADGE_VARIANT[thread.phase]} className="text-xs">
                  {t(`phase.${thread.phase}`)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {timeAgo(thread.createdAt)}
                </span>
              </span>
            </button>
          ))}
          {sortedThreads.length === 0 && (
            <p className="px-3 py-8 text-center text-xs text-muted-foreground">
              {t("chat.noThreads")}
            </p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
