import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { serverApi } from "@/lib/api-server";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface Props {
  params: Promise<{ threadId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { threadId } = await params;
  const t = await getTranslations("share");

  try {
    const task = await serverApi.getTask(threadId);
    const title = task.task_plan?.user_intent || t("defaultTitle");
    const description = task.result?.slice(0, 200) || t("defaultDescription");

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
      title: t("defaultTitle"),
      description: t("defaultDescription"),
    };
  }
}

export default async function SharePage({ params }: Props) {
  const { threadId } = await params;
  const t = await getTranslations();

  let task;
  try {
    task = await serverApi.getTask(threadId);
  } catch {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">{t("share.notFound")}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-12 space-y-8">
      {/* Header */}
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">
          {task.task_plan?.user_intent ?? t("share.taskResult")}
        </h1>
        <div className="flex items-center gap-2">
          <Badge variant="secondary">{task.status}</Badge>
          {task.task_plan && (
            <span className="text-sm text-muted-foreground">
              {t("task.subtaskCount", { count: task.task_plan.tasks.length })}
            </span>
          )}
        </div>
      </header>

      <Separator />

      {/* Task plan summary */}
      {task.task_plan && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">{t("task.taskPlan")}</h2>
          <ul className="space-y-1">
            {task.task_plan.tasks.map((tsk) => (
              <li key={tsk.task_id} className="flex items-center gap-2 text-sm">
                <Badge variant="outline" className="text-xs">
                  {tsk.assigned_persona}
                </Badge>
                <span>{tsk.title}</span>
                <Badge
                  variant={tsk.status === "completed" ? "default" : "secondary"}
                  className="text-xs"
                >
                  {tsk.status}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Result */}
      {task.result && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">{t("task.result")}</h2>
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
          {t("share.openInUsami")}
        </Button>
      </footer>
    </div>
  );
}
