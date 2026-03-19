"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Button } from "@/components/ui/button";
import { MessageBubble } from "./message-bubble";
import type { ChatMessage } from "@/hooks/use-derived-messages";

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const t = useTranslations("chat");

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 120,
    overscan: 5,
  });

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (autoScroll && messages.length > 0) {
      virtualizer.scrollToIndex(messages.length - 1, { align: "end", behavior: "smooth" });
    }
  }, [messages.length, autoScroll, virtualizer]);

  // Detect manual scroll to pause auto-scroll
  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    setAutoScroll(isAtBottom);
  }, []);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-muted-foreground">{t("emptyState")}</p>
      </div>
    );
  }

  return (
    <div className="relative flex-1 overflow-hidden bg-white/85 dark:bg-zinc-900/85 backdrop-blur-xl">
      <div ref={parentRef} className="h-full overflow-auto" onScroll={handleScroll}>
        <div
          className="relative w-full p-4"
          style={{ height: virtualizer.getTotalSize() }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const msg = messages[virtualRow.index];
            return (
              <div
                key={msg.id}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                className="absolute left-0 w-full px-4 pb-4"
                style={{ transform: `translateY(${virtualRow.start}px)` }}
              >
                <MessageBubble message={msg} />
              </div>
            );
          })}
        </div>
      </div>

      {!autoScroll && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setAutoScroll(true);
              virtualizer.scrollToIndex(messages.length - 1, { align: "end", behavior: "smooth" });
            }}
          >
            {t("scrollToBottom")}
          </Button>
        </div>
      )}
    </div>
  );
}
