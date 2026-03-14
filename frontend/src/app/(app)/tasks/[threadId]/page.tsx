"use client";

import { use } from "react";
import { useTaskDetail } from "@/hooks/use-task-detail";
import { useThreadStore } from "@/stores/thread-store";
import { TaskDag } from "@/components/task/task-dag";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PHASE_LABELS } from "@/lib/constants";
import type { TaskStatus } from "@/types/api";

export default function TaskDetailPage({
  params,
}: {
  params: Promise<{ threadId: string }>;
}) {
  const { threadId } = use(params);
  const { data, isLoading } = useTaskDetail(threadId);
  const thread = useThreadStore((s) => s.threads.get(threadId));

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground">任务未找到</p>
      </div>
    );
  }

  // Build task status map from thread events
  const taskStatuses: Record<string, TaskStatus> = {};
  if (thread) {
    for (const event of thread.events) {
      if ("task_id" in event) {
        if (event.type === "task.executing") taskStatuses[event.task_id] = "running";
        if (event.type === "task.progress") taskStatuses[event.task_id] = "completed";
        if (event.type === "task.failed") taskStatuses[event.task_id] = "failed";
      }
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b px-6 py-4">
        <h1 className="text-lg font-semibold">
          {data.task_plan?.user_intent ?? "任务详情"}
        </h1>
        <div className="mt-1 flex items-center gap-2">
          <Badge variant="secondary">
            {thread ? PHASE_LABELS[thread.phase] : data.status}
          </Badge>
          <span className="text-sm text-muted-foreground">
            {threadId}
          </span>
        </div>
      </div>

      {/* DAG */}
      {data.task_plan ? (
        <div className="flex-1">
          <TaskDag
            plan={data.task_plan}
            taskStatuses={taskStatuses}
          />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <p className="text-muted-foreground">任务计划尚未生成</p>
        </div>
      )}

      {/* Result panel */}
      {data.result && (
        <div className="border-t p-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">执行结果</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground line-clamp-3">
                {data.result.slice(0, 300)}
                {data.result.length > 300 ? "..." : ""}
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
