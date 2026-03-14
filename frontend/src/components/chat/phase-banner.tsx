"use client";

import { Badge } from "@/components/ui/badge";
import { PHASE_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { Phase } from "@/stores/thread-store";

interface PhaseBannerProps {
  phase: Phase;
}

const PHASE_STYLES: Record<Phase, { color: string; pulse: boolean }> = {
  created: { color: "bg-muted text-muted-foreground", pulse: false },
  planning: { color: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300", pulse: true },
  planned: { color: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300", pulse: false },
  executing: { color: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300", pulse: true },
  hitl_waiting: { color: "bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300", pulse: true },
  completed: { color: "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300", pulse: false },
  failed: { color: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300", pulse: false },
};

export function PhaseBanner({ phase }: PhaseBannerProps) {
  const style = PHASE_STYLES[phase];
  const label = PHASE_LABELS[phase] ?? phase;

  return (
    <div className="flex items-center gap-2 border-b px-4 py-2">
      <span className="text-sm text-muted-foreground">当前阶段:</span>
      <Badge
        variant="secondary"
        className={cn(style.color, style.pulse && "animate-pulse")}
      >
        {phase === "completed" && "✓ "}
        {phase === "failed" && "✗ "}
        {label}
      </Badge>
    </div>
  );
}
