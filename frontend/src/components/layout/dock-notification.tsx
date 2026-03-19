"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Bell, Check, Trash2, CheckCircle, AlertCircle, HelpCircle, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useNotificationStore } from "@/stores/notification-store";
import { cn } from "@/lib/utils";
import type { Notification } from "@/stores/notification-store";

const TYPE_ICON: Record<Notification["type"], typeof CheckCircle> = {
  task_completed: CheckCircle,
  task_failed: AlertCircle,
  hitl_request: HelpCircle,
  system: Info,
};

export function DockNotification() {
  const [open, setOpen] = useState(false);
  const notifications = useNotificationStore((s) => s.notifications);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const markRead = useNotificationStore((s) => s.markRead);
  const markAllRead = useNotificationStore((s) => s.markAllRead);
  const clearAll = useNotificationStore((s) => s.clearAll);
  const router = useRouter();
  const t = useTranslations("notifications");

  const handleClick = (n: Notification) => {
    markRead(n.id);
    if (n.threadId) {
      router.push(`/tasks/${n.threadId}`);
      setOpen(false);
    }
  };

  return (
    <div className="relative">
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              className={cn(
                "relative flex items-center justify-center rounded-xl p-2.5 transition-all",
                "hover:bg-muted hover:scale-110",
                "active:scale-95"
              )}
              onClick={() => setOpen(!open)}
            />
          }
        >
          <Bell className="size-5" />
          {unreadCount > 0 && (
            <Badge
              variant="destructive"
              className="absolute -top-0.5 -right-0.5 size-4 p-0 flex items-center justify-center text-[10px]"
            >
              {unreadCount > 9 ? "9+" : unreadCount}
            </Badge>
          )}
        </TooltipTrigger>
        <TooltipContent side="top">{t("title")}</TooltipContent>
      </Tooltip>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          {/* Panel opens upward from dock */}
          <div className="absolute bottom-full right-0 mb-2 z-50 w-80 rounded-lg border bg-popover shadow-lg">
            <div className="flex items-center justify-between border-b px-3 py-2">
              <span className="text-sm font-medium">{t("title")}</span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-6"
                  onClick={markAllRead}
                  title={t("markAllRead")}
                >
                  <Check className="size-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-6"
                  onClick={clearAll}
                  title={t("clearAll")}
                >
                  <Trash2 className="size-3" />
                </Button>
              </div>
            </div>

            <ScrollArea className="max-h-80">
              {notifications.length === 0 ? (
                <div className="p-6 text-center text-sm text-muted-foreground">
                  {t("empty")}
                </div>
              ) : (
                <div className="divide-y">
                  {notifications.map((n) => {
                    const Icon = TYPE_ICON[n.type];
                    return (
                      <button
                        key={n.id}
                        className={cn(
                          "w-full flex gap-3 p-3 text-left hover:bg-muted/50 transition-colors",
                          !n.read && "bg-muted/20"
                        )}
                        onClick={() => handleClick(n)}
                      >
                        <Icon className="size-4 mt-0.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <p className={cn("text-sm", !n.read && "font-medium")}>
                            {t(n.title)}
                          </p>
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {n.body || t(`${n.title}Body`)}
                          </p>
                          <p className="text-[10px] text-muted-foreground mt-1">
                            {new Date(n.createdAt).toLocaleTimeString()}
                          </p>
                        </div>
                        {!n.read && (
                          <div className="size-2 rounded-full bg-primary shrink-0 mt-1.5" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </ScrollArea>
          </div>
        </>
      )}
    </div>
  );
}
