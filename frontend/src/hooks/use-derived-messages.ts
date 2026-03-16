"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { Thread } from "@/stores/thread-store";

export interface ChatMessage {
  id: string;
  role: "user" | "system";
  variant?: "progress" | "plan" | "result" | "error" | "status";
  content: string;
  plan?: Thread["taskPlan"];
  isStreaming?: boolean;
}

export function useDerivedMessages(thread: Thread | undefined): ChatMessage[] {
  const t = useTranslations("chat");

  return useMemo(() => {
    if (!thread) return [];

    const messages: ChatMessage[] = [];

    // User intent is always first
    messages.push({
      id: `${thread.threadId}-user`,
      role: "user",
      content: thread.intent,
    });

    // Derive system messages from event stream
    for (let i = 0; i < thread.events.length; i++) {
      const event = thread.events[i];
      const id = `${thread.threadId}-${i}`;

      switch (event.type) {
        case "task.planning":
          messages.push({
            id,
            role: "system",
            variant: "progress",
            content: t("analyzing"),
          });
          break;

        case "task.plan_ready":
          messages.push({
            id,
            role: "system",
            variant: "plan",
            content: t("planReady", { count: event.task_count }),
            plan: thread.taskPlan,
          });
          break;

        case "task.executing":
          messages.push({
            id,
            role: "system",
            variant: "progress",
            content: t("executing", { persona: event.persona }),
          });
          break;

        case "task.progress":
          messages.push({
            id,
            role: "system",
            variant: "status",
            content: t("progress", { persona: event.persona, status: event.status }),
          });
          break;

        case "task.aggregating":
          messages.push({
            id,
            role: "system",
            variant: "progress",
            content: t("aggregating"),
          });
          break;

        case "task.completed":
          messages.push({
            id,
            role: "system",
            variant: "result",
            content: thread.result ?? t("completed"),
          });
          break;

        case "task.failed":
          messages.push({
            id,
            role: "system",
            variant: "error",
            content: t("failed", { error: event.error }),
          });
          break;

        case "hitl.request":
          messages.push({
            id,
            role: "system",
            variant: "status",
            content: t("hitlWaiting"),
          });
          break;
      }
    }

    // Fallback: if thread has a result but no task.completed event in stream
    // (e.g., WS event was missed, result came via REST polling)
    const hasCompletedEvent = thread.events.some((e) => e.type === "task.completed");
    if (thread.result && !hasCompletedEvent) {
      messages.push({
        id: `${thread.threadId}-result-fallback`,
        role: "system",
        variant: "result",
        content: thread.result,
      });
    }

    // Streaming result: show accumulated chunks while aggregation is in progress
    if (thread.streamingResult && thread.phase === "aggregating") {
      messages.push({
        id: `${thread.threadId}-streaming`,
        role: "system",
        variant: "result",
        content: thread.streamingResult,
        isStreaming: true,
      });
    }

    return messages;
  }, [thread, t]);
}
