"use client";

import { History, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { useThreadStore } from "@/stores/thread-store";
import { useThreadManagement, PHASE_BADGE_VARIANT } from "@/hooks/use-thread-management";
import { useTranslations } from "next-intl";

interface ThreadDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ThreadDrawer({ open, onOpenChange }: ThreadDrawerProps) {
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

  function handleSelectThread(threadId: string) {
    setActiveThread(threadId);
    onOpenChange(false);
  }

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="left" className="w-80 p-0">
          <SheetHeader className="px-4 py-3 border-b">
            <SheetTitle className="flex items-center gap-2 text-base">
              <History className="size-4" />
              {t("chat.historyTitle")}
            </SheetTitle>
          </SheetHeader>
          <ScrollArea className="h-[calc(100vh-60px)]">
            <div className="p-2 space-y-1">
              {sortedThreads.map((thread) => (
                <button
                  key={thread.threadId}
                  onClick={() => handleSelectThread(thread.threadId)}
                  className={cn(
                    "group flex w-full flex-col gap-1.5 rounded-lg px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted",
                    activeThreadId === thread.threadId && "bg-muted"
                  )}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium leading-tight">
                      {thread.intent.slice(0, 50)}
                      {thread.intent.length > 50 ? "..." : ""}
                    </span>
                    <span
                      role="button"
                      tabIndex={0}
                      aria-label={t("chat.deleteThread")}
                      onClick={(e) => requestDelete(e, thread.threadId)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") requestDelete(e as unknown as React.MouseEvent, thread.threadId);
                      }}
                      className="shrink-0 rounded p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
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
                <p className="px-3 py-12 text-center text-sm text-muted-foreground">
                  {t("chat.noThreads")}
                </p>
              )}
            </div>
          </ScrollArea>
        </SheetContent>
      </Sheet>

      <Dialog open={pendingDeleteId !== null} onOpenChange={(o) => { if (!o) cancelDelete(); }}>
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
    </>
  );
}

export function ThreadDrawerTrigger({ onClick }: { onClick: () => void }) {
  const threads = useThreadStore((s) => s.threads);
  const t = useTranslations("chat");

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-9 shrink-0"
      onClick={onClick}
      title={t("historyTitle")}
      aria-label={t("historyTitle")}
    >
      <History className="size-4" />
      {threads.size > 0 && (
        <span className="absolute -top-0.5 -right-0.5 size-4 rounded-full bg-muted text-[10px] flex items-center justify-center">
          {threads.size > 9 ? "9+" : threads.size}
        </span>
      )}
    </Button>
  );
}
