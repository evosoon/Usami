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

/**
 * Derives chat messages from thread events.
 *
 * Supports multi-turn conversations (follow-ups):
 * - Each task.created event starts a new conversation turn
 * - Each turn has its own thinking steps and result
 * - Events are processed in order, not by comparing intents
 */
export function useDerivedMessages(thread: Thread | undefined): ChatMessage[] {
  const t = useTranslations("chat");

  return useMemo(() => {
    if (!thread) return [];

    const messages: ChatMessage[] = [];
    let currentSteps: ThinkingStep[] = [];

    // Helper to flush accumulated thinking steps as a message
    const flushThinkingSteps = (idPrefix: string) => {
      if (currentSteps.length > 0) {
        messages.push({
          id: `${idPrefix}-thinking`,
          role: "system",
          variant: "thinking",
          content: "",
          steps: [...currentSteps],
        });
        currentSteps = [];
      }
    };

    // Fallback: if no task.created event yet (real-time before SSE arrives), use thread.intent
    const hasTaskCreated = thread.events.some((e) => e.type === "task.created");
    if (!hasTaskCreated && thread.intent) {
      messages.push({
        id: `${thread.threadId}-user-fallback`,
        role: "user",
        content: thread.intent,
      });
    }

    // Process events in order
    for (let i = 0; i < thread.events.length; i++) {
      const event = thread.events[i];
      const id = `${thread.threadId}-${i}`;

      switch (event.type) {
        case "task.created":
          // Flush any pending thinking steps from previous turn (for follow-ups)
          flushThinkingSteps(id);
          // Add user message for this turn
          messages.push({ id, role: "user", content: event.intent });
          break;

        case "task.planning":
          currentSteps.push({ id, label: t("analyzing"), status: "active" });
          break;

        case "task.plan_ready":
          markPrevActive(currentSteps, "done");
          currentSteps.push({ id, label: t("planReady", { count: event.task_count }), status: "active" });
          break;

        case "task.executing":
          markPrevActive(currentSteps, "done");
          currentSteps.push({ id, label: t("executing", { persona: event.persona }), status: "active" });
          break;

        case "task.progress":
          markPrevActive(currentSteps, "done");
          currentSteps.push({ id, label: t("progress", { persona: event.persona, status: event.status }), status: "active" });
          break;

        case "task.aggregating":
          markPrevActive(currentSteps, "done");
          currentSteps.push({ id, label: t("aggregating"), status: "active" });
          break;

        case "task.completed":
          markPrevActive(currentSteps, "done");
          // Flush thinking steps before result
          flushThinkingSteps(id);
          // Add result message - use event.result for this specific completion
          messages.push({
            id,
            role: "system",
            variant: "result",
            content: event.result ?? t("completed"),
          });
          break;

        case "task.failed":
          markPrevActive(currentSteps, "error");
          currentSteps.push({ id, label: t("failed", { error: event.error }), status: "error" });
          break;

        case "hitl.request":
          markPrevActive(currentSteps, "done");
          currentSteps.push({ id, label: t("hitlWaiting"), status: "active" });
          break;
      }
    }

    // Flush any remaining thinking steps (task still in progress)
    if (currentSteps.length > 0) {
      messages.push({
        id: `${thread.threadId}-thinking-current`,
        role: "system",
        variant: "thinking",
        content: "",
        steps: [...currentSteps],
      });
    }

    // Pending follow-up: show user message before task.created arrives
    if (thread.pendingIntent) {
      messages.push({
        id: `${thread.threadId}-pending-followup`,
        role: "user",
        content: thread.pendingIntent,
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
