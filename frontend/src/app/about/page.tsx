import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("about");
  return {
    title: t("title"),
    description: t("subtitle"),
  };
}

const PERSONA_ROLES = ["bossRole", "researcherRole", "writerRole", "analystRole"] as const;
const PERSONA_NAMES = [
  { name: "Boss", role: "Orchestrator", key: "bossRole" },
  { name: "Researcher", role: "Specialist", key: "researcherRole" },
  { name: "Writer", role: "Specialist", key: "writerRole" },
  { name: "Analyst", role: "Specialist", key: "analystRole" },
];

const TECH_STACK_KEYS = [
  { name: "LangGraph", key: "langraph" },
  { name: "FastAPI", key: "fastapi" },
  { name: "Next.js 16", key: "nextjs" },
  { name: "PostgreSQL + pgvector", key: "postgres" },
  { name: "Redis", key: "redis" },
  { name: "LiteLLM", key: "litellm" },
];

export default async function AboutPage() {
  const t = await getTranslations("about");

  return (
    <div className="mx-auto max-w-4xl px-6 py-16 space-y-16">
      {/* Header */}
      <section className="text-center space-y-4">
        <h1 className="text-4xl font-bold">{t("title")}</h1>
        <p className="text-lg text-muted-foreground">
          {t("subtitle")}
        </p>
      </section>

      {/* Architecture */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">{t("architecture")}</h2>
        <div className="rounded-lg border p-6 bg-muted/30">
          <pre className="text-sm text-muted-foreground whitespace-pre-wrap">
            {t("architectureDiagram")}
          </pre>
        </div>
      </section>

      {/* Personas */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">{t("personas")}</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {PERSONA_NAMES.map((p) => (
            <Card key={p.name}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  {p.name}
                  <span className="ml-2 text-xs text-muted-foreground font-normal">
                    {p.role}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{t(p.key)}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Tech Stack */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">{t("techStack")}</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TECH_STACK_KEYS.map((item) => (
            <div key={item.name} className="rounded-lg border p-4">
              <h3 className="font-medium">{item.name}</h3>
              <p className="text-sm text-muted-foreground">{t(item.key)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="text-center">
        <Button size="lg" render={<Link href="/chat" />}>
          {t("startUsing")}
        </Button>
      </section>
    </div>
  );
}
