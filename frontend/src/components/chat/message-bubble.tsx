"use client";

import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import { cjk } from "@streamdown/cjk";
import "streamdown/styles.css";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
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

function ProgressBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-2 rounded-2xl bg-muted px-4 py-2 text-muted-foreground">
        <span className="inline-flex gap-1">
          <span className="size-1.5 animate-pulse rounded-full bg-current" />
          <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:150ms]" />
          <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:300ms]" />
        </span>
        <span>{content}</span>
      </div>
    </div>
  );
}

function PlanBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <Card className="max-w-[80%]">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{message.content}</CardTitle>
        </CardHeader>
        {message.plan?.tasks && (
          <CardContent>
            <ul className="space-y-1">
              {message.plan.tasks.map((task) => (
                <li key={task.task_id} className="flex items-center gap-2 text-sm">
                  <Badge variant="secondary" className="text-xs">
                    {task.assigned_persona}
                  </Badge>
                  <span>{task.title}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        )}
      </Card>
    </div>
  );
}

function ResultBubble({ content, isStreaming }: { content: string; isStreaming?: boolean }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] rounded-2xl bg-background border px-4 py-3">
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

function StatusBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start">
      <div className="rounded-2xl bg-muted px-4 py-2 text-sm text-muted-foreground">
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
    case "progress":
      return <ProgressBubble content={message.content} />;
    case "plan":
      return <PlanBubble message={message} />;
    case "result":
      return <ResultBubble content={message.content} isStreaming={message.isStreaming} />;
    case "error":
      return <ErrorBubble content={message.content} />;
    case "status":
      return <StatusBubble content={message.content} />;
    default:
      return <StatusBubble content={message.content} />;
  }
}
