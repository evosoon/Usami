"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { useResolveHitl } from "@/hooks/use-resolve-hitl";
import type { HiTLRequest } from "@/types/api";

/**
 * Sanitize context for safe rendering: strip HTML tags and
 * truncate very long values to prevent DOM bloat.
 */
function sanitizeContext(ctx: Record<string, unknown>): string {
  const raw = JSON.stringify(ctx, null, 2);
  // Strip any HTML tags that might be present in context values
  return raw.replace(/<[^>]*>/g, "");
}

interface HiTLDialogProps {
  request: HiTLRequest;
  threadId: string;
  open: boolean;
  onClose: () => void;
}

export function HiTLDialog({ request, threadId, open, onClose }: HiTLDialogProps) {
  const [feedback, setFeedback] = useState("");
  const { mutate: resolve, isPending } = useResolveHitl(threadId);
  const t = useTranslations("hitl");

  const handleDecision = (decision: string) => {
    resolve(
      {
        request_id: request.request_id,
        decision,
        feedback: feedback.trim() || undefined,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {request.title}
            <Badge variant="secondary" className="text-xs">
              {request.hitl_type}
            </Badge>
          </DialogTitle>
          <DialogDescription>{request.description}</DialogDescription>
        </DialogHeader>

        {/* Context display — sanitized to prevent XSS */}
        {request.context && Object.keys(request.context).length > 0 && (
          <div className="rounded-md bg-muted p-3 text-sm overflow-auto max-h-60">
            <pre className="whitespace-pre-wrap text-xs">
              {sanitizeContext(request.context)}
            </pre>
          </div>
        )}

        {/* Optional feedback */}
        <Textarea
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder={t("feedbackPlaceholder")}
          className="min-h-[60px]"
        />

        {/* Decision buttons */}
        <DialogFooter className="flex-wrap gap-2">
          {(request.options ?? []).map((option) => (
            <Button
              key={option}
              onClick={() => handleDecision(option)}
              disabled={isPending}
              variant={option.toLowerCase().includes("approve") ? "default" : "outline"}
            >
              {option}
            </Button>
          ))}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
