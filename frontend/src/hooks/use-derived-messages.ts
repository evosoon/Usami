"use client";

import { useMemo } from "react";
import type { Thread } from "@/stores/thread-store";

export interface ChatMessage {
  id: string;
  role: "user" | "system";
  variant?: "progress" | "plan" | "result" | "error" | "status";
  content: string;
  plan?: Thread["taskPlan"];
}

export function useDerivedMessages(thread: Thread | undefined): ChatMessage[] {
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
            content: "正在分析意图，规划任务...",
          });
          break;

        case "task.plan_ready":
          messages.push({
            id,
            role: "system",
            variant: "plan",
            content: `计划就绪：${event.task_count} 个子任务`,
            plan: thread.taskPlan,
          });
          break;

        case "task.executing":
          messages.push({
            id,
            role: "system",
            variant: "progress",
            content: `[${event.persona}] 正在执行...`,
          });
          break;

        case "task.progress":
          messages.push({
            id,
            role: "system",
            variant: "status",
            content: `[${event.persona}] ${event.status}`,
          });
          break;

        case "task.completed":
          messages.push({
            id,
            role: "system",
            variant: "result",
            content: thread.result ?? "任务完成",
          });
          break;

        case "task.failed":
          messages.push({
            id,
            role: "system",
            variant: "error",
            content: `任务失败: ${event.error}`,
          });
          break;
      }
    }

    return messages;
  }, [thread]);
}
