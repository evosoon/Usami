import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { Button } from "@/components/ui/button";

export default async function HomePage() {
  const t = await getTranslations("landing");

  const features = [
    { title: t("featureAgents"), desc: t("featureAgentsDesc") },
    { title: t("featureDag"), desc: t("featureDagDesc") },
    { title: t("featureHitl"), desc: t("featureHitlDesc") },
    { title: t("featureKnowledge"), desc: t("featureKnowledgeDesc") },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      {/* Hero */}
      <section className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-24 text-center">
        <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
          Usami
        </h1>
        <p className="max-w-2xl text-xl text-muted-foreground">
          {t("subtitle")}
        </p>
        <div className="flex gap-4 mt-4">
          <Button size="lg" render={<Link href="/chat" />}>
            {t("getStarted")}
          </Button>
          <Button variant="outline" size="lg" render={<Link href="/about" />}>
            {t("learnMore")}
          </Button>
        </div>
      </section>

      {/* Features */}
      <section className="border-t bg-muted/50 px-6 py-16">
        <div className="mx-auto grid max-w-5xl gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((item) => (
            <div key={item.title} className="space-y-2">
              <h3 className="font-semibold">{item.title}</h3>
              <p className="text-sm text-muted-foreground">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
