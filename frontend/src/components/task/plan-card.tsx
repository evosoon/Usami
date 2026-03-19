"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { TaskPlan } from "@/types/api";

interface PlanCardProps {
  plan: TaskPlan;
  threadId: string;
}

export function PlanCard({ plan, threadId }: PlanCardProps) {
  const t = useTranslations("task");

  const tasks = plan.tasks ?? [];

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          {t("planTitle", { count: tasks.length })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <ul className="space-y-1.5">
          {tasks.slice(0, 5).map((task) => (
            <li key={task.task_id} className="flex items-center gap-2 text-sm">
              <Badge variant="secondary" className="shrink-0 text-xs">
                {task.assigned_persona}
              </Badge>
              <span className="truncate">{task.title}</span>
            </li>
          ))}
          {tasks.length > 5 && (
            <li className="text-xs text-muted-foreground">
              {t("moreTasks", { count: tasks.length - 5 })}
            </li>
          )}
        </ul>
        <Button
          variant="outline"
          size="sm"
          render={<Link href={`/tasks/${threadId}`} />}
        >
          {t("viewDetail")}
        </Button>
      </CardContent>
    </Card>
  );
}
