"use client";

import { useRef, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { History, Plus, Send } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCreateTask } from "@/hooks/use-create-task";
import { useSseStore } from "@/stores/sse-store";
import { useThreadStore } from "@/stores/thread-store";
import { ThreadDrawer } from "@/components/chat/thread-drawer";
import { cn } from "@/lib/utils";

export function ChatInput() {
  const [value, setValue] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const t = useTranslations("chat");
  const { mutate: createTask, isPending } = useCreateTask({
    onError: () => toast.error(t("createFailed")),
  });
  const sseStatus = useSseStore((s) => s.status);
  const threads = useThreadStore((s) => s.threads);
  const activeThread = useThreadStore((s) => s.getActiveThread());
  const setActiveThread = useThreadStore((s) => s.setActiveThread);
  const prepareFollowUp = useThreadStore((s) => s.prepareFollowUp);

  const isDisabled = isPending || sseStatus !== "connected";
  const hasThreads = threads.size > 0;

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isDisabled) return;

    const canFollowUp = activeThread &&
      (activeThread.phase === "completed" || activeThread.phase === "failed");

    if (canFollowUp) {
      prepareFollowUp(activeThread.threadId, trimmed);
      createTask({ intent: trimmed, threadId: activeThread.threadId });
    } else {
      createTask({ intent: trimmed });
    }
    setValue("");
  }, [value, isDisabled, createTask, activeThread, prepareFollowUp]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleNewChat = () => {
    setActiveThread(null);
    textareaRef.current?.focus();
  };

  return (
    <>
      <div className="bg-white/50 dark:bg-zinc-800/50 backdrop-blur-xl rounded-b-2xl">
        {/* Input area - no border */}
        <div className="px-4 pt-4">
          <Textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t("placeholder")}
            disabled={isDisabled}
            className="min-h-[40px] max-h-[200px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 text-base"
            rows={1}
          />
        </div>

        {/* Action buttons */}
        <div className="flex items-center justify-between px-4 py-3">
          <div className="flex items-center gap-1">
            {/* History button */}
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    className={cn(
                      "relative flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors cursor-pointer",
                      "hover:bg-background/80",
                      "disabled:opacity-50 disabled:cursor-not-allowed"
                    )}
                    onClick={() => setDrawerOpen(true)}
                    disabled={!hasThreads}
                  />
                }
              >
                <History className="size-4" />
                {hasThreads && (
                  <span className="size-5 rounded-full bg-primary/10 text-primary text-xs flex items-center justify-center font-medium">
                    {threads.size > 9 ? "9+" : threads.size}
                  </span>
                )}
              </TooltipTrigger>
              <TooltipContent side="top">{t("historyTitle")}</TooltipContent>
            </Tooltip>

            {/* New chat button */}
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    className={cn(
                      "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors cursor-pointer",
                      "hover:bg-background/80",
                      !activeThread && "bg-background/80"
                    )}
                    onClick={handleNewChat}
                  />
                }
              >
                <Plus className="size-4" />
              </TooltipTrigger>
              <TooltipContent side="top">{t("newChat")}</TooltipContent>
            </Tooltip>
          </div>

          {/* Send button */}
          <Button
            onClick={handleSubmit}
            disabled={!value.trim() || isDisabled}
            size="icon"
            className="size-9"
          >
            <Send className="size-4" />
          </Button>
        </div>
      </div>

      <ThreadDrawer open={drawerOpen} onOpenChange={setDrawerOpen} />
    </>
  );
}
