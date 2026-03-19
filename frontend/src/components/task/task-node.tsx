"use client";

import { Handle, Position } from "@xyflow/react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TaskStatus } from "@/types/api";

export interface TaskNodeData {
  label: string;
  persona: string;
  status: TaskStatus;
  description: string;
  [key: string]: unknown;
}

const STATUS_STYLES: Record<TaskStatus, string> = {
  pending: "border-muted-foreground/30 bg-muted",
  running: "border-blue-400 bg-blue-50 dark:bg-blue-950",
  completed: "border-green-400 bg-green-50 dark:bg-green-950",
  failed: "border-red-400 bg-red-50 dark:bg-red-950",
  blocked: "border-yellow-400 bg-yellow-50 dark:bg-yellow-950",
  hitl_waiting: "border-orange-400 bg-orange-50 dark:bg-orange-950",
};

export function TaskNode({ data }: { data: TaskNodeData }) {
  const initials = (data.persona ?? "??").slice(0, 2).toUpperCase();

  return (
    <div
      className={cn(
        "rounded-lg border-2 px-4 py-3 shadow-sm min-w-[180px]",
        STATUS_STYLES[data.status] ?? STATUS_STYLES.pending,
        data.status === "running" && "animate-pulse",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-muted-foreground" />

      <div className="flex items-center gap-2">
        <div className="flex size-7 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
          {initials}
        </div>
        <div className="flex flex-col">
          <span className="text-sm font-medium leading-tight">{data.label}</span>
          <Badge variant="secondary" className="mt-0.5 w-fit text-xs">
            {data.persona}
          </Badge>
        </div>
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground" />
    </div>
  );
}
