import { getTranslations } from "next-intl/server";
import { serverApi } from "@/lib/api-server";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, Bot, Wrench, HeartPulse } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function AdminDashboard() {
  const [health, personas, tools] = await Promise.all([
    serverApi.getHealth(),
    serverApi.getPersonas(),
    serverApi.getTools(),
  ]);
  const t = await getTranslations("admin");

  const stats = [
    { label: t("systemStatus"), value: health.status === "ok" ? t("normal") : t("abnormal"), icon: HeartPulse },
    { label: "Personas", value: String(Object.keys(personas).length), icon: Bot },
    { label: t("toolCount"), value: String(tools.length), icon: Wrench },
  ];

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">{t("overview")}</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((s) => (
          <Card key={s.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">{s.label}</CardTitle>
              <s.icon className="size-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-bold">{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
