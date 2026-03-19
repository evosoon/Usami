"use client";

import { MessageList } from "@/components/chat/message-list";
import { ChatInput } from "@/components/chat/chat-input";
import { ConnectionStatusBar } from "@/components/chat/connection-status-bar";
import { useDerivedMessages } from "@/hooks/use-derived-messages";
import { useTaskDetail } from "@/hooks/use-task-detail";
import { useThreadStore } from "@/stores/thread-store";

export default function ChatPage() {
  const activeThreadId = useThreadStore((s) => s.activeThreadId);
  const activeThread = useThreadStore((s) =>
    s.activeThreadId ? s.threads.get(s.activeThreadId) : undefined,
  );

  // Fetch task detail on mount (SSE handles live updates)
  useTaskDetail(activeThreadId);

  // Derive messages from event stream
  const messages = useDerivedMessages(activeThread);

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="flex h-full w-full max-w-4xl flex-col rounded-2xl border border-border/50 shadow-xl overflow-hidden">
        <ConnectionStatusBar />
        <MessageList messages={messages} />
        <ChatInput />
      </div>
    </div>
  );
}
