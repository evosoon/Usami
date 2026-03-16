"use client";

import { useRef, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { useCreateTask } from "@/hooks/use-create-task";

export function ChatInput() {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { mutate: createTask, isPending } = useCreateTask();
  const t = useTranslations("chat");

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isPending) return;
    createTask(trimmed);
    setValue("");
  }, [value, isPending, createTask]);

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
          disabled={isPending}
          className="min-h-[44px] max-h-[200px] resize-none"
          rows={1}
        />
        <Button
          onClick={handleSubmit}
          disabled={!value.trim() || isPending}
          size="lg"
        >
          {isPending ? t("sending") : t("send")}
        </Button>
      </div>
    </div>
  );
}
