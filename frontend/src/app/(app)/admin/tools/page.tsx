import { serverApi } from "@/lib/api-server";
import { ToolTable } from "@/components/admin/tool-table";

export const dynamic = "force-dynamic";

export default async function ToolsPage() {
  const tools = await serverApi.getTools();

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold">工具列表</h1>
      <ToolTable tools={tools} />
    </div>
  );
}
