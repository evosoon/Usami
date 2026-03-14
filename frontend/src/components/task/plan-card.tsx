"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { TaskPlan } from "@/types/api";

interface PlanCardProps {
  plan: TaskPlan;
  threadId: string;
}

export function PlanCard({ plan, threadId }: PlanCardProps) {
  return (
    <Card className="max-w-md">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          任务计划 — {plan.tasks.length} 个子任务
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="space-y-1.5">
          {plan.tasks.slice(0, 5).map((task) => (
            <li key={task.task_id} className="flex items-center gap-2 text-sm">
              <Badge variant="secondary" className="shrink-0 text-xs">
                {task.assigned_persona}
              </Badge>
              <span className="truncate">{task.title}</span>
            </li>
          ))}
          {plan.tasks.length > 5 && (
            <li className="text-xs text-muted-foreground">
              +{plan.tasks.length - 5} 个更多任务
            </li>
          )}
        </ul>
        <Button
          variant="outline"
          size="sm"
          render={<Link href={`/tasks/${threadId}`} />}
        >
          查看详情
        </Button>
      </CardContent>
    </Card>
  );
}
