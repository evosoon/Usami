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

        {/* Context display */}
        {request.context && Object.keys(request.context).length > 0 && (
          <div className="rounded-md bg-muted p-3 text-sm">
            <pre className="whitespace-pre-wrap text-xs">
              {JSON.stringify(request.context, null, 2)}
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
