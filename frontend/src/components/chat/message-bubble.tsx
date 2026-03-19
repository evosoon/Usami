"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import { cjk } from "@streamdown/cjk";
import { Check, ChevronDown, ChevronRight, Loader2, X } from "lucide-react";
import type { ChatMessage } from "@/hooks/use-derived-messages";

interface MessageBubbleProps {
  message: ChatMessage;
}

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2 text-primary-foreground">
        <p className="whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  );
}

function ThinkingBubble({ message }: { message: ChatMessage }) {
  const t = useTranslations("chat");
  const steps = message.steps ?? [];
  const allDone = steps.length > 0 && steps.every((s) => s.status !== "active");
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (allDone) setCollapsed(true);
  }, [allDone]);

  const stepCount = steps.length;

  if (collapsed) {
    return (
      <div className="flex justify-start">
        <button
          onClick={() => setCollapsed(false)}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <ChevronRight className="size-3.5" />
          <span>{t("thinkingSteps", { count: stepCount })}</span>
        </button>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="space-y-0.5">
        {allDone && (
          <button
            onClick={() => setCollapsed(true)}
            className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground mb-1"
          >
            <ChevronDown className="size-3.5" />
            <span>{t("thinkingSteps", { count: stepCount })}</span>
          </button>
        )}
        {steps.map((step) => (
          <div
            key={step.id}
            className="flex items-center gap-2 px-2 text-sm text-muted-foreground"
          >
            {step.status === "done" && (
              <Check className="size-3.5 shrink-0 text-green-500" />
            )}
            {step.status === "active" && (
              <Loader2 className="size-3.5 shrink-0 animate-spin" />
            )}
            {step.status === "error" && (
              <X className="size-3.5 shrink-0 text-destructive" />
            )}
            <span className={step.status === "error" ? "text-destructive" : ""}>
              {step.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResultBubble({ content, isStreaming }: { content: string; isStreaming?: boolean }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] rounded-2xl bg-background border px-4 py-3 prose prose-sm dark:prose-invert prose-headings:font-semibold prose-headings:mb-2 prose-headings:mt-4 first:prose-headings:mt-0 prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 max-w-none">
        <Streamdown
          animated
          plugins={{ code, cjk }}
        >
          {content}
        </Streamdown>
        {isStreaming && (
          <span className="inline-block h-4 w-0.5 animate-pulse bg-foreground/60 ml-0.5 align-text-bottom" />
        )}
      </div>
    </div>
  );
}

function ErrorBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-2xl border border-destructive/50 bg-destructive/10 px-4 py-2 text-destructive">
        <p>{content}</p>
      </div>
    </div>
  );
}

export function MessageBubble({ message }: MessageBubbleProps) {
  if (message.role === "user") {
    return <UserBubble content={message.content} />;
  }

  switch (message.variant) {
    case "thinking":
      return <ThinkingBubble message={message} />;
    case "result":
      return <ResultBubble content={message.content} isStreaming={message.isStreaming} />;
    case "error":
      return <ErrorBubble content={message.content} />;
    default:
      return <ResultBubble content={message.content} />;
  }
}
