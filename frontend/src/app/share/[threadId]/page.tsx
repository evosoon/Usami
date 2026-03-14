import type { Metadata } from "next";
import Link from "next/link";
import { serverApi } from "@/lib/api-server";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface Props {
  params: Promise<{ threadId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { threadId } = await params;

  try {
    const task = await serverApi.getTask(threadId);
    const title = task.task_plan?.user_intent || "Usami 任务结果";
    const description = task.result?.slice(0, 200) || "查看 Usami 生成的任务报告";

    return {
      title,
      description,
      openGraph: {
        title,
        description,
        type: "article",
        images: ["/og-default.png"],
      },
      twitter: {
        card: "summary_large_image",
        title,
        description,
      },
    };
  } catch {
    return {
      title: "Usami 任务结果",
      description: "查看 Usami 生成的任务报告",
    };
  }
}

export default async function SharePage({ params }: Props) {
  const { threadId } = await params;

  let task;
  try {
    task = await serverApi.getTask(threadId);
  } catch {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">任务未找到或无法访问</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-12 space-y-8">
      {/* Header */}
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">
          {task.task_plan?.user_intent ?? "任务结果"}
        </h1>
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{task.status}</Badge>
          {task.task_plan && (
            <span className="text-sm text-muted-foreground">
              {task.task_plan.tasks.length} 个子任务
            </span>
          )}
        </div>
      </header>

      <Separator />

      {/* Task plan summary */}
      {task.task_plan && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">任务计划</h2>
          <ul className="space-y-1">
            {task.task_plan.tasks.map((t) => (
              <li key={t.task_id} className="flex items-center gap-2 text-sm">
                <Badge variant="outline" className="text-xs">
                  {t.assigned_persona}
                </Badge>
                <span>{t.title}</span>
                <Badge
                  variant={t.status === "completed" ? "default" : "secondary"}
                  className="text-xs"
                >
                  {t.status}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Result */}
      {task.result && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">执行结果</h2>
          <div className="prose prose-sm dark:prose-invert max-w-none rounded-lg border p-6">
            {/* Static render for SSR — streamdown needs client-side for animations */}
            <div className="whitespace-pre-wrap">{task.result}</div>
          </div>
        </section>
      )}

      <Separator />

      {/* CTA */}
      <footer className="text-center">
        <Button render={<Link href="/chat" />}>
          在 Usami 中打开
        </Button>
      </footer>
    </div>
  );
}
