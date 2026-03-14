import { serverApi } from "@/lib/api-server";
import { HealthPanel } from "@/components/admin/health-panel";

export const dynamic = "force-dynamic";

export default async function HealthPage() {
  const health = await serverApi.getHealth();

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">健康检查</h1>
      <HealthPanel health={health} />
    </div>
  );
}
