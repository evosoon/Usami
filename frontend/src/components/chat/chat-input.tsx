"use client";

import { useRef, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { useCreateTask } from "@/hooks/use-create-task";
import { useSseStore } from "@/stores/sse-store";
import { useThreadStore } from "@/stores/thread-store";

export function ChatInput() {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const t = useTranslations("chat");
  const { mutate: createTask, isPending } = useCreateTask({
    onError: () => toast.error(t("createFailed")),
  });
  const sseStatus = useSseStore((s) => s.status);
  const activeThread = useThreadStore((s) => s.getActiveThread());
  const prepareFollowUp = useThreadStore((s) => s.prepareFollowUp);

  const isDisabled = isPending || sseStatus !== "connected";

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

  return (
    <div className="border-t p-4">
      <div className="flex gap-2 items-end">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t("placeholder")}
          disabled={isDisabled}
          className="min-h-[44px] max-h-[200px] resize-none"
          rows={1}
        />
        <Button
          onClick={handleSubmit}
          disabled={!value.trim() || isDisabled}
          size="lg"
        >
          {isPending ? t("sending") : t("send")}
        </Button>
      </div>
    </div>
  );
}
