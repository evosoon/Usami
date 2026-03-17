"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { Thread } from "@/stores/thread-store";

export interface ThinkingStep {
  id: string;
  label: string;
  status: "done" | "active" | "error";
}

export interface ChatMessage {
  id: string;
  role: "user" | "system";
  variant?: "thinking" | "result" | "error";
  content: string;
  steps?: ThinkingStep[];
  isStreaming?: boolean;
}

function markPrevActive(steps: ThinkingStep[], status: "done" | "error") {
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i].status === "active") {
      steps[i].status = status;
      break;
    }
  }
}

export function useDerivedMessages(thread: Thread | undefined): ChatMessage[] {
  const t = useTranslations("chat");

  return useMemo(() => {
    if (!thread) return [];

    const messages: ChatMessage[] = [];
    const steps: ThinkingStep[] = [];

    // User intent is always first
    messages.push({
      id: `${thread.threadId}-user`,
      role: "user",
      content: thread.intent,
    });

    // Process events: aggregate process events into steps, emit result/error/follow-up separately
    for (let i = 0; i < thread.events.length; i++) {
      const event = thread.events[i];
      const id = `${thread.threadId}-${i}`;

      switch (event.type) {
        case "task.created":
          // Follow-up: render subsequent task.created events as user messages
          if (event.intent && event.intent !== thread.intent) {
            messages.push({ id, role: "user", content: event.intent });
          }
          break;

        case "task.planning":
          steps.push({ id, label: t("analyzing"), status: "active" });
          break;

        case "task.plan_ready":
          markPrevActive(steps, "done");
          steps.push({ id, label: t("planReady", { count: event.task_count }), status: "active" });
          break;

        case "task.executing":
          markPrevActive(steps, "done");
          steps.push({ id, label: t("executing", { persona: event.persona }), status: "active" });
          break;

        case "task.progress":
          markPrevActive(steps, "done");
          steps.push({ id, label: t("progress", { persona: event.persona, status: event.status }), status: "active" });
          break;

        case "task.aggregating":
          markPrevActive(steps, "done");
          steps.push({ id, label: t("aggregating"), status: "active" });
          break;

        case "task.completed":
          markPrevActive(steps, "done");
          messages.push({
            id,
            role: "system",
            variant: "result",
            content: thread.result ?? t("completed"),
          });
          break;

        case "task.failed":
          markPrevActive(steps, "done");
          steps.push({ id, label: t("failed", { error: event.error }), status: "error" });
          break;

        case "hitl.request":
          markPrevActive(steps, "done");
          steps.push({ id, label: t("hitlWaiting"), status: "active" });
          break;
      }
    }

    // Insert thinking message before result/error messages
    if (steps.length > 0) {
      // Find insertion point: after last user message, before first result
      const firstResultIdx = messages.findIndex(
        (m) => m.role === "system" && (m.variant === "result" || m.variant === "error"),
      );
      const thinkingMsg: ChatMessage = {
        id: `${thread.threadId}-thinking`,
        role: "system",
        variant: "thinking",
        content: "",
        steps: [...steps],
      };
      if (firstResultIdx >= 0) {
        messages.splice(firstResultIdx, 0, thinkingMsg);
      } else {
        messages.push(thinkingMsg);
      }
    }

    // Fallback: if thread has a result but no task.completed event in stream
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
