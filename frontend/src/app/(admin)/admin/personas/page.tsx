import { getTranslations } from "next-intl/server";
import { serverApi } from "@/lib/api-server";
import { PersonaCard } from "@/components/admin/persona-card";

export const dynamic = "force-dynamic";

export default async function PersonasPage() {
  const personas = await serverApi.getPersonas();
  const t = await getTranslations("admin");

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">{t("personas")}</h1>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Object.entries(personas).map(([key, persona]) => (
          <PersonaCard key={key} name={key} persona={persona} />
        ))}
      </div>
    </div>
  );
}
