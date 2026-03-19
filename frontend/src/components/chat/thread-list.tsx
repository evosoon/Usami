"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useThreadManagement, PHASE_BADGE_VARIANT } from "@/hooks/use-thread-management";

export function ThreadList() {
  const {
    sortedThreads,
    activeThreadId,
    setActiveThread,
    pendingDeleteId,
    requestDelete,
    confirmDelete,
    cancelDelete,
    formatTimeAgo,
    t,
  } = useThreadManagement();

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
                "group flex w-full flex-col gap-1 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                activeThreadId === thread.threadId && "bg-muted",
              )}
            >
              <span className="flex items-center justify-between gap-1">
                <span className="truncate font-medium">
                  {thread.intent.slice(0, 40)}
                  {thread.intent.length > 40 ? "..." : ""}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  aria-label={t("chat.deleteThread")}
                  onClick={(e) => requestDelete(e, thread.threadId)}
                  onKeyDown={(e) => { if (e.key === "Enter") requestDelete(e as unknown as React.MouseEvent, thread.threadId); }}
                  className="shrink-0 rounded p-0.5 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                  title={t("chat.deleteThread")}
                >
                  <Trash2 className="size-3.5" />
                </span>
              </span>
              <span className="flex items-center gap-2">
                <Badge variant={PHASE_BADGE_VARIANT[thread.phase]} className="text-xs">
                  {t(`phase.${thread.phase}`)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {formatTimeAgo(thread.createdAt)}
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

      <Dialog open={pendingDeleteId !== null} onOpenChange={(open) => { if (!open) cancelDelete(); }}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("chat.deleteThread")}</DialogTitle>
            <DialogDescription>{t("chat.deleteConfirm")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={cancelDelete}>
              {t("common.cancel")}
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              {t("common.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
