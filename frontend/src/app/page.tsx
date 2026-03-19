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
        <div className="relative flex flex-col items-center gap-4">
          {/* Background logo */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo.svg"
            alt=""
            aria-hidden="true"
            className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-40 w-auto opacity-10 sm:h-48"
          />
          <h1 className="relative text-5xl font-bold tracking-tight sm:text-6xl">
            Usami
          </h1>
          <p className="relative max-w-2xl text-xl text-muted-foreground">
            {t("subtitle")}
          </p>
        </div>
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
